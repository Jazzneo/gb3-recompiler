"""Network mode: co-op without typing commands.

Standard library only, and one file on purpose: the Recompiler copies it into every install as
psport/gb3net.py, and play.sh runs it with the system's python3 before each launch (also from a
Steam shortcut), so the mode picked in the window applies however the game is started.

Modes (network.json in ~/.config/gb3-recompiler):
    offline     no network (default)
    lan-host    this device runs the co-op server for the local network and plays on it
    lan-join    play on a server another device on the local network runs (found automatically)
    online      play on an internet server (address typed once in the window)

PS4 GUNDAM BREAKER 3 has no real ad hoc mode: "Local" is a small shadNet server on one device of the
same Wi-Fi/LAN (or the Deck's own hotspot), the others join it. Game traffic stays peer to peer.
Over the internet, Tailscale (a free virtual LAN) makes friends "local": the host picks "friends join
over Tailscale", joiners find it among their Tailscale peers.

The user name is the shadNet account name, which the game shows as the Online ID in co-op. The
account is created on the chosen server the first time (random password, kept 0600 in
accounts.json), so nobody types a password either.

CLI (python3 gb3net.py ...):
    status                                 current mode, name, server
    set [--mode M] [--name N] [--server HOST[:PORT]] [--lan-host IP[:PORT]|auto] [--key K]
    discover [--wait S]                    list co-op servers on the local network
    account                                create / check the account on the current server
    server start|stop|status [--install DIR]   the local co-op server (lan-host)
    serve --shadnet DIR --data DIR [...]   run a server in the foreground (cloud install, systemd)
    launch-env --install DIR --game-pid PID    shell lines for play.sh (exports, or nothing offline)
"""
import argparse
import json
import os
import secrets
import signal
import socket
import struct
import subprocess
import sys
import threading
import time

MODES = ('offline', 'lan-host', 'lan-join', 'online')
MODE_NAMES = {'offline': 'Offline', 'lan-host': 'Host on this device (Wi-Fi/LAN or Tailscale)',
              'lan-join': 'Join a host (Wi-Fi/LAN or Tailscale)', 'online': 'Online server (advanced)'}
PORT = 31313            # shadNet TCP; +1 = matching UDP (STUN/signaling), +2 = WebAPI HTTP
RELAY_PORT = 3478       # P2P relay (UDP) for internet play behind NAT
BEACON_PORT = 31399     # LAN discovery (UDP)
BEACON_ASK = b'GB3R?1'

CONFIG_DIR = os.path.join(os.environ.get('XDG_CONFIG_HOME') or os.path.expanduser('~/.config'), 'gb3-recompiler')
NET_CONFIG = os.path.join(CONFIG_DIR, 'network.json')
ACCOUNTS = os.path.join(CONFIG_DIR, 'accounts.json')
STATE_DIR = os.path.join(os.environ.get('XDG_DATA_HOME') or os.path.expanduser('~/.local/share'), 'gb3-recompiler')
SERVER_DATA = os.path.join(STATE_DIR, 'server')
SERVER_STATE = os.path.join(SERVER_DATA, 'serve.json')

DEFAULTS = {'mode': 'offline', 'name': '', 'server': '', 'lan_host': 'auto', 'key': '', 'lan_port': PORT,
            'host_via': 'lan'}   # host_via: how friends reach a local host: 'lan' or 'tailscale'

# shadNet error codes (src/protocol.h ErrorType) the account step can meet.
ERR = {0: 'ok', 1: 'malformed', 3: 'invalid input', 5: 'login error', 6: 'already signed in',
       7: 'unknown user name', 8: 'wrong password', 10: 'account could not be created',
       11: 'name already taken', 12: 'e-mail domain banned', 13: 'e-mail already used',
       23: 'registration key needed or wrong', 24: 'server database error'}


def say(msg):
    print('gb3net: %s' % msg, file=sys.stderr, flush=True)


# ------------------------------------------------------------------ config

def _read_json(path, default):
    try:
        with open(path) as f:
            v = json.load(f)
        return v if isinstance(v, type(default)) else default
    except (OSError, ValueError):
        return default


def _write_json(path, value, private=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if private else 0o644)
    with os.fdopen(fd, 'w') as f:
        json.dump(value, f, indent=1)
    if private:
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def load():
    c = dict(DEFAULTS)
    c.update(_read_json(NET_CONFIG, {}))
    if c.get('mode') not in MODES:
        c['mode'] = 'offline'
    return c


def save(c):
    _write_json(NET_CONFIG, {k: c.get(k, v) for k, v in DEFAULTS.items()})


def valid_name(name):
    """shadNet's rule (ClientSession::IsValidNpid): 3-16 letters, digits, - or _."""
    if not 3 <= len(name) <= 16 or name == 'DeletedUser':
        return False
    return all(ch.isascii() and (ch.isalnum() or ch in '-_') for ch in name)


def split_addr(text, default_port=PORT):
    text = (text or '').strip()
    if not text:
        return '', default_port
    if text.count(':') == 1:
        host, port = text.rsplit(':', 1)
        try:
            return host.strip(), int(port)
        except ValueError:
            return host.strip(), default_port
    return text, default_port


# ------------------------------------------------------------------ network helpers

def lan_ip():
    """This device's address on the local network (the one a route to the internet would use)."""
    for probe in ('192.168.0.1', '10.0.0.1', '8.8.8.8'):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((probe, 9))
            ip = s.getsockname()[0]
            if ip and not ip.startswith('127.'):
                return ip
        except OSError:
            pass
        finally:
            s.close()
    return '127.0.0.1'


def broadcast_addrs():
    out = ['255.255.255.255']
    try:
        r = subprocess.run(['ip', '-4', '-o', 'addr', 'show'], capture_output=True, text=True, timeout=3)
        for line in r.stdout.splitlines():
            parts = line.split()
            if 'brd' in parts:
                b = parts[parts.index('brd') + 1]
                if b not in out:
                    out.append(b)
    except (OSError, subprocess.SubprocessError):
        pass
    return out


def resolve(host):
    try:
        return socket.gethostbyname(host)
    except OSError:
        return None


def tcp_open(host, port, timeout=2.0):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# ------------------------------------------------------------------ Tailscale

TS_NET = (0x64400000, 0xffc00000)       # 100.64.0.0/10, Tailscale's address range


def _ip_int(ip):
    try:
        return struct.unpack('!I', socket.inet_aton(ip))[0]
    except OSError:
        return None


def is_tailscale_ip(ip):
    n = _ip_int(ip or '')
    return n is not None and n & TS_NET[1] == TS_NET[0]


def tailscale_bin():
    for d in os.environ.get('PATH', '').split(os.pathsep) + ['/usr/bin', '/usr/local/bin', '/opt/tailscale',
                                                            os.path.expanduser('~/.local/bin')]:
        c = os.path.join(d, 'tailscale')
        if d and os.access(c, os.X_OK):
            return c
    return None


def _tailscale_status():
    ts = tailscale_bin()
    if not ts:
        return None
    try:
        r = subprocess.run([ts, 'status', '--json'], capture_output=True, text=True, timeout=5)
        return json.loads(r.stdout) if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def tailscale_ip():
    """This device's Tailscale IPv4 address, or None (not installed / not signed in)."""
    st = _tailscale_status()
    if st and st.get('BackendState') == 'Running':
        for ip in (st.get('Self') or {}).get('TailscaleIPs') or []:
            if is_tailscale_ip(ip):
                return ip
    try:   # no CLI (or not in PATH): an address on the tailscale0 interface still counts
        r = subprocess.run(['ip', '-4', '-o', 'addr', 'show'], capture_output=True, text=True, timeout=3)
        for line in r.stdout.splitlines():
            parts = line.split()
            if 'inet' in parts:
                ip = parts[parts.index('inet') + 1].split('/')[0]
                if is_tailscale_ip(ip):
                    return ip
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def tailscale_state():
    """'on' (signed in, with an address), 'off' (installed, not up), 'missing'."""
    if tailscale_ip():
        return 'on'
    return 'off' if tailscale_bin() else 'missing'


def tailscale_peers():
    """Online Tailscale peers: [{'ip', 'name'}]."""
    st = _tailscale_status() or {}
    out = []
    for p in (st.get('Peer') or {}).values():
        if not p.get('Online'):
            continue
        ip = next((a for a in p.get('TailscaleIPs') or [] if is_tailscale_ip(a)), None)
        if ip:
            out.append({'ip': ip, 'name': p.get('HostName') or ip})
    return out


# ------------------------------------------------------------------ LAN discovery

def discover(wait=1.5, only=None):
    """Co-op servers that answer on the local network: [{'ip', 'port', 'name', 'id'}]."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.settimeout(0.25)
    targets = [only] if only else broadcast_addrs()
    found = {}
    end = time.time() + wait
    next_ask = 0
    while time.time() < end:
        if time.time() >= next_ask:
            for t in targets:
                try:
                    s.sendto(BEACON_ASK, (t, BEACON_PORT))
                except OSError:
                    pass
            next_ask = time.time() + 0.5
        try:
            data, addr = s.recvfrom(2048)
        except (socket.timeout, OSError):
            continue
        try:
            info = json.loads(data.decode())
        except ValueError:
            continue
        if info.get('gb3r') != 1:
            continue
        # One entry per server (a host with several interfaces, e.g. a container bridge, answers
        # on each); its own LAN address wins over the address the answer came from.
        ip = str(info.get('ip') or addr[0])
        if only and ip != only:
            ip = addr[0]
        found[str(info['id']) if info.get('id') else (ip, int(info.get('port', PORT)))] = {
            'ip': ip, 'port': int(info.get('port', PORT)),
            'name': str(info.get('name', ''))[:32], 'id': str(info.get('id', ''))[:40]}
        if only:
            break
    s.close()
    return sorted(found.values(), key=lambda h: (h['name'], h['ip']))


def discover_all(wait=1.5):
    """Hosts on the LAN (broadcast) and on Tailscale (each online peer asked directly)."""
    results = []
    lock = threading.Lock()

    def ask(ip, name):
        for h in discover(min(wait, 1.2), only=ip):
            h['via'] = 'tailscale'
            h['name'] = h['name'] or name
            with lock:
                results.append(h)
    threads = [threading.Thread(target=ask, args=(p['ip'], p['name']), daemon=True) for p in tailscale_peers()]
    for t in threads:
        t.start()
    for h in discover(wait):
        h['via'] = 'tailscale' if is_tailscale_ip(h['ip']) else 'lan'
        results.append(h)
    for t in threads:
        t.join(wait + 1)
    seen, out = set(), []
    for h in sorted(results, key=lambda h: (h['via'] != 'lan', h['name'], h['ip'])):
        key = (h['id'] or h['ip'], h['via'])
        if key not in seen:
            seen.add(key)
            out.append(h)
    return out


def host_address(cfg):
    """The address a local host's friends use (and its own game, so the server tells them that one)."""
    if cfg.get('host_via') == 'tailscale':
        ip = tailscale_ip()
        if not ip:
            raise RuntimeError('Tailscale is not running on this device (Network window: Set up Tailscale)')
        return ip
    return lan_ip()


class Beacon(threading.Thread):
    """Answers discovery queries for the server this process runs."""

    def __init__(self, info):
        super().__init__(daemon=True, name='gb3r-beacon')
        self.info = json.dumps(dict(info, gb3r=1)).encode()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('0.0.0.0', BEACON_PORT))

    def run(self):
        while True:
            try:
                data, addr = self.sock.recvfrom(256)
            except OSError:
                return
            if data.startswith(BEACON_ASK):
                try:
                    self.sock.sendto(self.info, addr)
                except OSError:
                    pass


class Relay(threading.Thread):
    """P2P relay for players who cannot reach each other directly (psport's "BBR1" protocol):
    0x01 id[16] register (every 5 s) -> 0x02; 0x03 dst[16] src[16] frame -> to dst as 0x04 src[16]
    frame; an unknown dst gets 0x05 dst back (at most every 10 s per pair)."""
    MAGIC = b'BBR1'

    def __init__(self, port):
        super().__init__(daemon=True, name='gb3r-relay')
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('0.0.0.0', port))
        self.peers = {}
        self.missing = {}

    def run(self):
        while True:
            try:
                data, addr = self.sock.recvfrom(65536)
            except OSError:
                return
            if data[:4] != self.MAGIC or len(data) < 5:
                continue
            now = time.time()
            kind = data[4]
            if kind == 0x01 and len(data) >= 21:
                self.peers[data[5:21]] = (addr, now)
                self.sock.sendto(self.MAGIC + b'\x02', addr)
            elif kind == 0x03 and len(data) >= 37:
                dst, src = data[5:21], data[21:37]
                sender = self.peers.get(src)
                if not sender or sender[0] != addr:
                    continue
                self.peers[src] = (addr, now)
                target = self.peers.get(dst)
                if target and now - target[1] < 60:
                    self.sock.sendto(self.MAGIC + b'\x04' + src + data[37:], target[0])
                elif now - self.missing.get((src, dst), 0) >= 10:
                    self.missing[(src, dst)] = now
                    self.sock.sendto(self.MAGIC + b'\x05' + dst, addr)


# ------------------------------------------------------------------ shadNet account (TCP protocol)

def _varint(n):
    out = bytearray()
    while True:
        b = n & 0x7f
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _pb(fields):
    """A protobuf message of string fields: {field_number: str}."""
    out = b''
    for num, val in sorted(fields.items()):
        if val:
            raw = val.encode()
            out += _varint(num << 3 | 2) + _varint(len(raw)) + raw
    return out


def _recv_exact(s, n):
    buf = b''
    while len(buf) < n:
        chunk = s.recv(n - len(buf))
        if not chunk:
            raise ConnectionError('server closed the connection')
        buf += chunk
    return buf


def _request(host, port, cmd, proto, timeout=6.0):
    """One shadNet command on a fresh connection; returns the reply's error code."""
    with socket.create_connection((host, port), timeout=timeout) as s:
        s.settimeout(timeout)
        hdr = _recv_exact(s, 15)
        if hdr[0] != 3:
            raise ConnectionError('not a shadNet server')
        _recv_exact(s, struct.unpack_from('<I', hdr, 3)[0] - 15)
        payload = struct.pack('<I', len(proto)) + proto
        s.sendall(struct.pack('<BHIQ', 0, cmd, 15 + len(payload), 1) + payload)
        while True:
            hdr = _recv_exact(s, 15)
            size = struct.unpack_from('<I', hdr, 3)[0]
            body = _recv_exact(s, size - 15) if size > 15 else b''
            if hdr[0] == 1 and struct.unpack_from('<H', hdr, 1)[0] == cmd:
                try:
                    s.sendall(struct.pack('<BHIQ', 0, 1, 15, 2))       # Terminate
                except OSError:
                    pass
                return body[0] if body else 1


def create_account(host, port, name, password, key=''):
    email = '%s@players.gb3-recompiler.invalid' % name.lower()
    return _request(host, port, 2, _pb({1: name, 2: password, 4: email, 5: key}))


def check_login(host, port, name, password):
    return _request(host, port, 0, _pb({1: name, 2: password, 4: 'CUSA07651'}))


def account_key(host, port, server_id=''):
    return 'id:' + server_id if server_id else '%s:%d' % (host.lower(), port)


def ensure_account(host, port, name, key='', server_id='', log=say):
    """The account `name` on this server, created on first use. Returns its password."""
    if not valid_name(name):
        raise RuntimeError('user name must be 3-16 letters, digits, - or _')
    accounts = _read_json(ACCOUNTS, {})
    k = account_key(host, port, server_id)
    entry = accounts.get(k)
    if entry and entry.get('name') == name:
        rc = check_login(host, port, name, entry['password'])
        if rc in (0, 6):
            return entry['password']
        if rc != 7:
            raise RuntimeError('sign-in as %s failed: %s' % (name, ERR.get(rc, 'error %d' % rc)))
        log('%s is not on this server any more: creating it again' % name)
    password = secrets.token_urlsafe(18)
    rc = create_account(host, port, name, password, key)
    if rc != 0:
        if rc == 11:
            raise RuntimeError('the name %s is already taken on this server: pick another' % name)
        raise RuntimeError('could not create %s: %s' % (name, ERR.get(rc, 'error %d' % rc)))
    accounts[k] = {'name': name, 'password': password, 'created': time.strftime('%Y-%m-%d %H:%M:%S')}
    _write_json(ACCOUNTS, accounts, private=True)
    log('account %s created on %s:%d' % (name, host, port))
    return password


# ------------------------------------------------------------------ the local server

def shadnet_dir(install):
    return os.path.join(install, 'shadnet')


def server_running():
    st = _read_json(SERVER_STATE, {})
    pid = st.get('pid')
    if not pid:
        return None
    try:
        os.kill(pid, 0)
    except OSError:
        return None
    return st


def _write_server_cfg(data, port, key, public):
    os.makedirs(data, exist_ok=True)
    cfg = {
        'Host': '0.0.0.0', 'UnsecuredPort': port, 'MatchingUdpPort': port + 1, 'WebApiPort': port + 2,
        'Matching2Enabled': 'true', 'Matching2MaxUsers': 0, 'TrophiesEnabled': 'true',
        'EmailValidated': 'false', 'LogFile': 'shadnet.log', 'LogMaxSizeMB': 5,
        'AdminApiEnabled': 'false', 'MemberApiEnabled': 'false', 'StatsEnabled': 'false',
        'ClientVersionRulesFile': 'clientversions.cfg', 'RegistrationSecretKey': key or '',
        'AvatarBaseUrl': 'https://shadps4.net/shad_net/assets/avatar/',
    }
    path = os.path.join(data, 'shadnet.cfg')
    with open(path + '.tmp', 'w') as f:
        f.write('[General]\n')
        for k in sorted(cfg):
            f.write('%s=%s\n' % (k, cfg[k]))
    os.chmod(path + '.tmp', 0o600)
    os.replace(path + '.tmp', path)
    sid = os.path.join(data, 'server-id')
    if not os.path.exists(sid):
        with open(sid, 'w') as f:
            f.write(secrets.token_hex(8))
    return open(sid).read().strip()


def serve(shadnet, data, port=PORT, key='', name='', beacon=True, relay=True, until_pid=0):
    """Run shadNet (+ LAN beacon, + relay) in the foreground until stopped or `until_pid` exits."""
    shadnet = os.path.abspath(shadnet)
    exe, loader = os.path.join(shadnet, 'shadnet'), os.path.join(shadnet, 'lib', 'ld-linux-x86-64.so.2')
    if not (os.path.exists(exe) and os.path.exists(loader)):
        raise RuntimeError('co-op server files missing in %s (install or update first)' % shadnet)
    sid = _write_server_cfg(data, port, key, not beacon)
    for f in ('worlds.cfg', 'scoreboards.cfg', 'clientversions.cfg'):
        src = os.path.join(shadnet, 'share', f)
        if os.path.exists(src) and not os.path.exists(os.path.join(data, f)):
            with open(src, 'rb') as a, open(os.path.join(data, f), 'wb') as b:
                b.write(a.read())
    try:
        os.unlink(os.path.join(data, 'worlds.cfg.running'))   # a lock a killed server leaves behind
    except OSError:
        pass
    env = dict(os.environ, QT_PLUGIN_PATH=os.path.join(shadnet, 'plugins'), QT_QPA_PLATFORM='offscreen')
    for k in ('LD_PRELOAD', 'LD_LIBRARY_PATH', 'PYTHONHOME', 'PYTHONPATH'):
        env.pop(k, None)
    console = open(os.path.join(data, 'console.log'), 'ab')
    # shadNet makes its own folder (QCoreApplication::applicationDirPath, i.e. the program the
    # kernel started: the loader) its working directory, so a copy of the loader lives in `data`.
    local_ld = os.path.join(data, 'shadnet-ld.so')
    if not os.path.exists(local_ld) or os.path.getsize(local_ld) != os.path.getsize(loader):
        with open(loader, 'rb') as a, open(local_ld + '.tmp', 'wb') as b:
            b.write(a.read())
        os.chmod(local_ld + '.tmp', 0o755)
        os.replace(local_ld + '.tmp', local_ld)
    loader = local_ld
    child = subprocess.Popen([loader, '--library-path', os.path.join(shadnet, 'lib'), exe], cwd=data, env=env,
                             stdin=subprocess.DEVNULL, stdout=console, stderr=subprocess.STDOUT)
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, lambda *_: stop.set())
    extras = []
    if beacon:
        try:
            b = Beacon({'name': name or socket.gethostname(), 'port': port, 'id': sid, 'ip': lan_ip()})
            b.start()
            extras.append('LAN discovery udp %d' % BEACON_PORT)
        except OSError as e:
            say('LAN discovery off: %s' % e)
    if relay:
        try:
            Relay(RELAY_PORT).start()
            extras.append('relay udp %d' % RELAY_PORT)
        except OSError as e:
            say('relay off: %s' % e)
    _write_json(SERVER_STATE if data == SERVER_DATA else os.path.join(data, 'serve.json'),
                {'pid': os.getpid(), 'shadnet_pid': child.pid, 'port': port, 'id': sid, 'name': name,
                 'started': time.strftime('%Y-%m-%d %H:%M:%S'), 'until_pid': until_pid})
    say('co-op server on tcp %d, udp %d, http %d%s (data %s)' % (
        port, port + 1, port + 2, ''.join(', ' + e for e in extras), data))
    while not stop.is_set() and child.poll() is None:
        if until_pid:
            try:
                os.kill(until_pid, 0)
            except OSError:
                say('game %d exited: stopping the co-op server' % until_pid)
                break
        stop.wait(1.0)
    if child.poll() is None:
        child.terminate()                 # shadNet ignores SIGTERM today; give it a moment anyway
        try:
            child.wait(3)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
    try:
        os.unlink(os.path.join(data, 'worlds.cfg.running'))
    except OSError:
        pass
    say('co-op server stopped (code %s)' % child.returncode)
    return 0


def system_python():
    """The machine's own python3 (it outlives this window; the AppImage's mount does not), with
    an environment free of the AppImage's Python/Tk settings. Falls back to this interpreter."""
    env = dict(os.environ)
    appdir = env.get('APPDIR', '')
    for k in ('LD_PRELOAD', 'LD_LIBRARY_PATH', 'PYTHONHOME', 'PYTHONPATH', 'PYTHONNOUSERSITE',
              'TCL_LIBRARY', 'TK_LIBRARY', 'GB3R_ROOT', 'GB3R_PYCMD'):
        env.pop(k, None)
    if appdir:
        env['PATH'] = os.pathsep.join(p for p in env.get('PATH', '').split(os.pathsep) if not p.startswith(appdir))
    for d in env.get('PATH', '/usr/bin:/bin').split(os.pathsep) + ['/usr/bin', '/bin']:
        c = os.path.join(d, 'python3')
        if d and os.access(c, os.X_OK) and not (appdir and c.startswith(appdir)):
            return [c], env
    cmd = os.environ.get('GB3R_PYCMD')
    return (cmd.split('\x1f') if cmd else [sys.executable]), dict(os.environ)


def server_start(install, cfg=None, until_pid=0, wait=8.0):
    """Start the local server in the background (no-op when it already runs). Returns its state."""
    st = server_running()
    if st:
        return st
    cfg = cfg or load()
    os.makedirs(SERVER_DATA, exist_ok=True)
    log = open(os.path.join(SERVER_DATA, 'serve.log'), 'ab')
    py, env = system_python()
    script = os.path.join(install, 'psport', 'gb3net.py')
    if not os.path.exists(script):
        script = os.path.abspath(__file__)
    argv = py + [script, 'serve', '--shadnet', shadnet_dir(install), '--data', SERVER_DATA,
                 '--port', str(int(cfg.get('lan_port') or PORT)), '--name', cfg.get('name') or socket.gethostname()]
    # No registration key on a device host: Wi-Fi/LAN or Tailscale already limits who can reach it
    # (the "Server key" box belongs to an Online server and must not lock friends out here).
    if until_pid:
        argv += ['--until-pid', str(until_pid)]
    subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True,
                     close_fds=True, env=env)
    port = int(cfg.get('lan_port') or PORT)
    end = time.time() + wait
    while time.time() < end:
        st = server_running()
        if st and tcp_open('127.0.0.1', port, 0.5):
            return st
        time.sleep(0.3)
    raise RuntimeError('the co-op server did not start (see %s)' % os.path.join(SERVER_DATA, 'console.log'))


def server_stop():
    st = server_running()
    if not st:
        return False
    os.kill(st['pid'], signal.SIGTERM)
    for _ in range(50):
        if not server_running():
            return True
        time.sleep(0.1)
    return True


# ------------------------------------------------------------------ resolving the mode to a server

def target(cfg, install=None, until_pid=0, log=say):
    """(host, port, server_id, label) of the server to play on, or None for offline."""
    mode = cfg['mode']
    if mode == 'offline':
        return None
    if mode == 'lan-host':
        if not install:
            raise RuntimeError('no install folder for the local server')
        ip = host_address(cfg)
        st = server_start(install, cfg, until_pid=until_pid)
        # Our own game must use the address friends reach us at, not 127.0.0.1: the server hands
        # the address it sees to the other players as ours (LAN or Tailscale).
        return ip, int(st.get('port', PORT)), st.get('id', ''), 'this device'
    if mode == 'lan-join':
        want = (cfg.get('lan_host') or 'auto').strip()
        if want and want != 'auto':
            host, port = split_addr(want)
            ip = resolve(host)
            if not ip:
                raise RuntimeError('cannot find host %s' % host)
            hit = discover(1.0, only=ip)
            return ip, (hit[0]['port'] if hit else port), (hit[0]['id'] if hit else ''), host
        hosts = discover_all(2.0)
        if not hosts:
            raise RuntimeError('no co-op host found on this network or on Tailscale '
                               '(is "Local: host on this device" on there?)')
        h = hosts[0]
        if len(hosts) > 1:
            log('%d hosts found, using %s (%s); pick one in the Network window to change' % (len(hosts), h['name'], h['ip']))
        return h['ip'], h['port'], h['id'], h['name']
    host, port = split_addr(cfg.get('server'))
    if not host:
        raise RuntimeError('no online server address set')
    ip = resolve(host)
    if not ip:
        raise RuntimeError('cannot resolve %s' % host)
    return ip, port, '', host


def launch_env(install, game_pid, cfg=None, log=say):
    """Lines for bash `eval`: the online environment for this launch, or none (offline)."""
    cfg = cfg or load()
    lines = ['unset PS_ONLINE PS_SHADNET_SERVER PS_SHADNET_WEBAPI PS_SHADNET_NPID PS_SHADNET_SECRETS_FILE '
             'PS_SHADNET_PASSWORD PS_SHADNET_TOKEN SHADPS4_P2P_RELAY PS_GPU_LOG']
    if cfg['mode'] == 'offline':
        return lines
    name = cfg.get('name', '')
    if not valid_name(name):
        log('co-op: no valid user name set (Network window): playing offline')
        return lines
    try:
        host, port, sid, label = target(cfg, install, until_pid=game_pid, log=log)
        key = cfg.get('key', '') if cfg['mode'] == 'online' else ''
        password = ensure_account(host, port, name, key, sid, log=log)
    except (RuntimeError, OSError) as e:
        log('co-op: %s: playing offline' % e)
        return lines
    run = os.environ.get('XDG_RUNTIME_DIR') or '/tmp'
    path = os.path.join(run, 'gb3r-secrets.%d' % os.getpid())
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write('password=%s\n' % password)
    env = {
        'PS_ONLINE': '1', 'PS_SHADNET_SERVER': '%s:%d' % (host, port),
        'PS_SHADNET_WEBAPI': 'http://%s:%d' % (host, port + 2), 'PS_SHADNET_NPID': name,
        'PS_SHADNET_SECRETS_FILE': path, 'PS_ONLINE_ALLOW_PLAINTEXT_LOGIN': '1',
        'PS_UPNP': '1' if cfg['mode'] == 'online' else '0',
    }
    if cfg['mode'] == 'online':
        env['SHADPS4_P2P_RELAY'] = 'auto'      # direct first, the server's relay when NAT blocks it
    lines += ['export %s=%s' % (k, _sh(v)) for k, v in sorted(env.items())]
    log('co-op: %s as %s on %s (%s:%d)' % (MODE_NAMES[cfg['mode']], name, label, host, port))
    return lines


def _sh(v):
    return "'" + str(v).replace("'", "'\\''") + "'"


# ------------------------------------------------------------------ CLI

def main(argv=None):
    ap = argparse.ArgumentParser(prog='gb3net', description='GB3 Recompiler network mode')
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('status')
    p = sub.add_parser('set')
    p.add_argument('--mode', choices=MODES)
    p.add_argument('--name')
    p.add_argument('--server')
    p.add_argument('--lan-host')
    p.add_argument('--key')
    p.add_argument('--via', choices=('lan', 'tailscale'), help='how friends reach a local host')
    p = sub.add_parser('discover')
    p.add_argument('--wait', type=float, default=1.5)
    p = sub.add_parser('account')
    p.add_argument('--install')
    p = sub.add_parser('server')
    p.add_argument('action', choices=('start', 'stop', 'status'))
    p.add_argument('--install', default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    p = sub.add_parser('serve')
    p.add_argument('--shadnet', required=True)
    p.add_argument('--data', required=True)
    p.add_argument('--port', type=int, default=PORT)
    p.add_argument('--key', default='')
    p.add_argument('--key-file', default='', help='registration key from this file (if it exists)')
    p.add_argument('--name', default='')
    p.add_argument('--no-beacon', action='store_true')
    p.add_argument('--no-relay', action='store_true')
    p.add_argument('--until-pid', type=int, default=0)
    p = sub.add_parser('launch-env')
    p.add_argument('--install', required=True)
    p.add_argument('--game-pid', type=int, default=0)
    a = ap.parse_args(argv)
    cfg = load()
    try:
        if a.cmd == 'status':
            st = server_running()
            print('mode: %s\nname: %s\nonline server: %s\nlocal host: %s\nfriends join over: %s\n'
                  'local server here: %s\nthis device: LAN %s, Tailscale %s' % (
                      MODE_NAMES[cfg['mode']], cfg['name'] or '(none)', cfg['server'] or '(none)', cfg['lan_host'],
                      cfg.get('host_via', 'lan'), 'running on port %d' % st['port'] if st else 'off',
                      lan_ip(), tailscale_ip() or tailscale_state()))
        elif a.cmd == 'set':
            if a.name is not None and a.name and not valid_name(a.name):
                raise RuntimeError('user name must be 3-16 letters, digits, - or _')
            if a.via:
                cfg['host_via'] = a.via
            for k in ('mode', 'name', 'server', 'lan_host', 'key'):
                v = getattr(a, k)
                if v is not None:
                    cfg[k] = v
            save(cfg)
            print('saved: %s' % MODE_NAMES[cfg['mode']])
        elif a.cmd == 'discover':
            hosts = discover_all(a.wait)
            for h in hosts:
                print('%s\t%s:%d\t%s' % (h['name'], h['ip'], h['port'], h['via']))
            if not hosts:
                print('no co-op host found')
        elif a.cmd == 'account':
            t = target(cfg, a.install)
            if not t:
                print('offline: no account needed')
            else:
                ensure_account(t[0], t[1], cfg['name'], cfg.get('key', '') if cfg['mode'] == 'online' else '', t[2])
                print('account %s ok on %s:%d' % (cfg['name'], t[0], t[1]))
        elif a.cmd == 'server':
            if a.action == 'start':
                st = server_start(a.install, cfg)
                print('running on port %d' % st['port'])
            elif a.action == 'stop':
                print('stopped' if server_stop() else 'not running')
            else:
                st = server_running()
                print('running on port %d since %s' % (st['port'], st['started']) if st else 'off')
        elif a.cmd == 'serve':
            if a.key_file and os.path.isfile(a.key_file):
                with open(a.key_file) as f:
                    a.key = f.read().strip()
            return serve(a.shadnet, a.data, a.port, a.key, a.name, not a.no_beacon, not a.no_relay, a.until_pid)
        elif a.cmd == 'launch-env':
            print('\n'.join(launch_env(a.install, a.game_pid, cfg)))
        return 0
    except (RuntimeError, OSError) as e:
        say(str(e))
        return 1


if __name__ == '__main__':
    sys.exit(main())
