"""Install logic: PKG -> game folder, psport runtime copy, mods, play script, undo.

Install folder layout (default ~/Games/GB3-Recompiler):
    CUSA07651/        the game, unpacked from the player's own PKG (mods are applied here)
    psport-bundle/    psport runtime copy (saves live in psport-bundle/user/savedata)
    psport/           launch scripts (play-gb3.sh, common.sh, fix-interp.py, ...)
    play.sh           start the game (add this as a non-Steam game)
    gb3r.json         what this tool installed and the chosen options
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

from . import gdat

APP_NAME = 'Recompiler Gundam Breaker 3 Break Edition'
APP_VERSION = '1.0.0'
TITLE = 'CUSA07651'
SAVE_TITLE = 'CUSA03489'

# The CUSA07651 v01.00 eboot the 720p patch was made for (sha256 of the unpacked eboot.bin).
EBOOT_SHA256 = '76994b8d150f53e03ef9c3569f7f3c49ac530fcd1aa39a50953dab144c1b73be'
PATCH_XML = 'GB3-render-720p.xml'

HERE = os.path.dirname(os.path.abspath(__file__))
# Inside the AppImage: $APPDIR/app/gb3r -> resources at $APPDIR/{data,runtime,bin}.
ROOT = os.environ.get('GB3R_ROOT') or os.path.abspath(os.path.join(HERE, '..', '..'))
DATA = os.path.join(ROOT, 'data')
RUNTIME = os.path.join(ROOT, 'runtime')          # psport-bundle/ + psport/ (scripts)
BIN = os.path.join(ROOT, 'bin')

CONFIG_DIR = os.path.join(os.environ.get('XDG_CONFIG_HOME') or os.path.expanduser('~/.config'), 'gb3-recompiler')
CONFIG = os.path.join(CONFIG_DIR, 'config.json')

DEFAULT_OPTIONS = {'xbox': True, 'render720': True, 'fps': '30', 'async': False}


def default_install_dir():
    return os.path.expanduser('~/Games/GB3-Recompiler')


def is_steamos():
    try:
        with open('/etc/os-release') as f:
            t = f.read().lower()
        if 'steamos' in t:
            return True
    except OSError:
        pass
    try:
        with open('/sys/devices/virtual/dmi/id/board_vendor') as f:
            vendor = f.read().strip().lower()
        with open('/sys/devices/virtual/dmi/id/product_name') as f:
            product = f.read().strip().lower()
        return vendor == 'valve' and product in ('jupiter', 'galileo')
    except OSError:
        return False


# ------------------------------------------------------------------ config

def load_config():
    try:
        with open(CONFIG) as f:
            c = json.load(f)
    except (OSError, ValueError):
        c = {}
    c.setdefault('install_dir', default_install_dir())
    c.setdefault('pkg', '')
    return c


def save_config(c):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = CONFIG + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(c, f, indent=1)
    os.replace(tmp, CONFIG)


class Install:
    def __init__(self, folder):
        self.dir = os.path.abspath(os.path.expanduser(folder))
        self.game = os.path.join(self.dir, TITLE)
        self.bundle = os.path.join(self.dir, 'psport-bundle')
        self.scripts = os.path.join(self.dir, 'psport')
        self.play = os.path.join(self.dir, 'play.sh')
        self.statefile = os.path.join(self.dir, 'gb3r.json')

    def state(self):
        try:
            with open(self.statefile) as f:
                s = json.load(f)
        except (OSError, ValueError):
            s = {}
        opts = dict(DEFAULT_OPTIONS)
        opts.update(s.get('options', {}))
        s['options'] = opts
        return s

    def save_state(self, s):
        os.makedirs(self.dir, exist_ok=True)
        s['tool_version'] = APP_VERSION
        tmp = self.statefile + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(s, f, indent=1)
        os.replace(tmp, self.statefile)

    def has_game(self):
        return os.path.isfile(os.path.join(self.game, 'eboot.bin'))

    def has_runtime(self):
        return os.access(os.path.join(self.bundle, 'out', 'psport'), os.X_OK)

    def save_dir(self):
        return os.path.join(self.bundle, 'user', 'savedata', '1', SAVE_TITLE)


# ------------------------------------------------------------------ helpers

def human(n):
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if n < 1024 or unit == 'TiB':
            return ('%d %s' % (n, unit)) if unit == 'B' else ('%.1f %s' % (n, unit))
        n /= 1024.0


def file_sha256(path, progress=None):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            b = f.read(8 << 20)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def run_logged(argv, log, env=None, cwd=None):
    """Run a process, stream its output to log(); returns the exit code."""
    p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, cwd=cwd,
                         universal_newlines=True, errors='replace', bufsize=1)
    last = 0.0
    pending = None
    for line in p.stdout:
        line = line.rstrip('\n')
        # The unpacker prints a line per file: keep the log readable by thinning bursts.
        now = time.time()
        if now - last >= 0.25:
            if pending:
                log(pending)
                pending = None
            log(line)
            last = now
        else:
            pending = line
    if pending:
        log(pending)
    return p.wait()


def pkg_tool():
    for c in (os.environ.get('GB3_PKG_TOOL'), os.path.join(BIN, 'ps4-pkg-tool')):
        if c and os.access(c, os.X_OK):
            return c
    return shutil.which('ps4-pkg-tool')


def check_pkg(path):
    """-> (ok, message)."""
    try:
        with open(path, 'rb') as f:
            head = f.read(0x1000)
    except OSError as e:
        return False, 'cannot read: %s' % e
    if head[:4] != b'\x7fCNT':
        return False, 'not a PS4 PKG (wrong magic)'
    cid = head[0x40:0x64].split(b'\0')[0].decode('ascii', 'replace')
    msg = 'content id %s, %s' % (cid or '?', human(os.path.getsize(path)))
    if TITLE not in cid:
        return False, msg + ' - this is not %s (GUNDAM BREAKER 3 BREAK EDITION)' % TITLE
    return True, msg


def find_pkgs(limit=40):
    roots = [os.path.expanduser(p) for p in ('~/Downloads', '~/Games', '~/Desktop', '~')]
    for base in ('/run/media', '/media', '/mnt'):
        if os.path.isdir(base):
            roots.append(base)
    found, seen = [], set()
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            depth = dirpath[len(root):].count(os.sep)
            dirnames[:] = [d for d in dirnames if not d.startswith('.') and d not in ('proc', 'sys')]
            if depth >= 4:
                dirnames[:] = []
            for fn in filenames:
                if fn.lower().endswith('.pkg'):
                    p = os.path.realpath(os.path.join(dirpath, fn))
                    if p in seen:
                        continue
                    seen.add(p)
                    ok, _ = check_pkg(p)
                    if ok:
                        found.append(p)
                        if len(found) >= limit:
                            return found
    return found


# ------------------------------------------------------------------ steps

def step_unpack(inst, pkg, log):
    ok, msg = check_pkg(pkg)
    log('PKG: %s (%s)' % (pkg, msg))
    if not ok:
        raise RuntimeError(msg)
    if inst.has_game():
        log('Game folder already unpacked: %s (skipping the unpack)' % inst.game)
        return
    tool = pkg_tool()
    if not tool:
        raise RuntimeError('ps4-pkg-tool is missing from this package')
    size = os.path.getsize(pkg)
    os.makedirs(inst.dir, exist_ok=True)
    st = os.statvfs(inst.dir)
    free = st.f_bavail * st.f_frsize
    need = size + size // 10
    if free < need:
        raise RuntimeError('Not enough space in %s: %s free, about %s needed.'
                           % (inst.dir, human(free), human(need)))
    tmp = inst.game + '.unpacking'
    if os.path.exists(tmp):
        log('Removing an unfinished unpack from a previous run')
        shutil.rmtree(tmp)
    os.makedirs(tmp)
    log('Unpacking %s into %s (a few minutes)...' % (human(size), inst.game))
    code = run_logged([tool, pkg, tmp], log)
    if code != 0:
        raise RuntimeError('The unpacker stopped with exit code %d' % code)
    root = tmp
    if not os.path.isfile(os.path.join(root, 'eboot.bin')):
        # some unpacker versions write <out>/<TITLE>/...
        for sub in os.listdir(tmp):
            if os.path.isfile(os.path.join(tmp, sub, 'eboot.bin')):
                root = os.path.join(tmp, sub)
                break
    if not os.path.isfile(os.path.join(root, 'eboot.bin')):
        raise RuntimeError('The unpack finished without eboot.bin. Is this the base game PKG (not an update)?')
    os.replace(root, inst.game)
    if root != tmp:
        shutil.rmtree(tmp, ignore_errors=True)
    log('Unpacked: %s' % inst.game)


def check_game(inst, log):
    eboot = os.path.join(inst.game, 'eboot.bin')
    h = file_sha256(eboot)
    known = h == EBOOT_SHA256
    log('eboot.bin: %s' % ('CUSA07651 v01.00 (known)' if known else 'unknown build %s...' % h[:16]))
    for a in ('masterPS4/GxArchivedFile000.dat', 'masterPS4/GxArchivedFile001.dat'):
        if not os.path.isfile(os.path.join(inst.game, a)):
            raise RuntimeError('%s is missing from the game folder' % a)
    return known


def _copytree(src, dst, ignore=None):
    shutil.copytree(src, dst, symlinks=True, ignore=ignore)


def step_runtime(inst, log):
    """Copy (or update) the psport runtime and launch scripts; saves and settings are kept."""
    src_bundle = os.path.join(RUNTIME, 'psport-bundle')
    src_scripts = os.path.join(RUNTIME, 'psport')
    if not os.path.isdir(src_bundle):
        raise RuntimeError('runtime missing from this package: %s' % src_bundle)
    os.makedirs(inst.dir, exist_ok=True)
    marker = os.path.join(src_bundle, 'RUNTIME-VERSION')
    want = open(marker).read().strip() if os.path.exists(marker) else APP_VERSION
    have_path = os.path.join(inst.bundle, 'RUNTIME-VERSION')
    have = open(have_path).read().strip() if os.path.exists(have_path) else None
    if have == want and inst.has_runtime():
        log('psport runtime up to date (%s)' % want)
    else:
        log('Installing psport runtime %s...' % want)
        # Replace everything except user/ (saves, shader cache), psport.ini and patches/.
        os.makedirs(inst.bundle, exist_ok=True)
        keep = {'user', 'psport.ini', 'patches'}
        for name in os.listdir(src_bundle):
            if name in keep and os.path.exists(os.path.join(inst.bundle, name)):
                continue
            s, d = os.path.join(src_bundle, name), os.path.join(inst.bundle, name)
            if os.path.isdir(d) and not os.path.islink(d):
                shutil.rmtree(d)
            elif os.path.lexists(d):
                os.unlink(d)
            if os.path.isdir(s):
                _copytree(s, d)
            else:
                shutil.copy2(s, d)
        for sub in ('savedata', 'cache', 'log', 'temp'):
            os.makedirs(os.path.join(inst.bundle, 'user', sub), exist_ok=True)
        os.makedirs(os.path.join(inst.bundle, 'patches'), exist_ok=True)
        if have and have != want:
            # A new GPU translator: the old shader cache would be ignored or wrong; keep it aside.
            cache = os.path.join(inst.bundle, 'user', 'cache', TITLE)
            if os.path.isdir(cache):
                os.replace(cache, cache + '.old-%d' % int(time.time()))
                log('Old shader cache kept aside (first run will compile shaders)')
    if os.path.isdir(inst.scripts):
        shutil.rmtree(inst.scripts)
    _copytree(src_scripts, inst.scripts)
    for root, _, files in os.walk(inst.scripts):
        for fn in files:
            if fn.endswith('.sh') or fn.endswith('.py'):
                os.chmod(os.path.join(root, fn), 0o755)
    for p in ('out/psport', 'out/psport-gpu-capabilities', 'lib/ld-linux-x86-64.so.2', 'run.sh', 'relocate.sh'):
        fp = os.path.join(inst.bundle, p)
        if os.path.exists(fp):
            os.chmod(fp, 0o755)
    fix_interp(inst, log)


def python_cmd():
    """How to start this Python again (the AppImage runs it through the bundle's own loader)."""
    cmd = os.environ.get('GB3R_PYCMD')
    return cmd.split('\x1f') if cmd else [sys.executable]


def fix_interp(inst, log):
    fix = os.path.join(inst.scripts, 'fix-interp.py')
    code = run_logged(python_cmd() + [fix, inst.bundle], log)
    if code != 0:
        raise RuntimeError('could not point psport at its loader (fix-interp.py exit %d)' % code)
    try:
        out = subprocess.run([os.path.join(inst.bundle, 'out', 'psport')], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, universal_newlines=True, timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired) as e:
        out = str(e)
    if 'Usage' not in out:
        raise RuntimeError('psport does not start on this system:\n%s' % out[:400])
    log('psport binary starts')


def patchset():
    return gdat.PatchSet(DATA)


def step_mods(inst, opts, log, known_eboot=True):
    """Bring the game's archives and the patch folder to the selected options."""
    ps = patchset()
    want = [g for g in ('xbox', 'render720') if opts.get(g)]
    if opts.get('render720') and not known_eboot:
        log('720p patch skipped: this eboot.bin is not the v01.00 build it was made for')
        want.remove('render720')
        opts['render720'] = False
    live = gdat.installed_groups(inst.game, ps)
    log('Mods now: %s' % ', '.join('%s=%s' % kv for kv in sorted(live.items())))
    target = {g: ('on' if g in want else 'off') for g in ps.groups()}
    if live != target:
        if any(v != 'off' for v in live.values()):
            log('Restoring original records before re-applying...')
            gdat.restore(inst.game, ps, log)
        if want:
            gdat.apply(inst.game, ps, want, log)
    xml_dst = os.path.join(inst.bundle, 'patches', PATCH_XML)
    if 'render720' in want:
        os.makedirs(os.path.dirname(xml_dst), exist_ok=True)
        shutil.copy2(os.path.join(DATA, 'patches', PATCH_XML), xml_dst)
        log('720p eboot patch installed: %s' % xml_dst)
    elif os.path.exists(xml_dst):
        os.replace(xml_dst, xml_dst + '.off')
        log('720p eboot patch switched off (renamed to .off)')
    return want


PLAY_SH = r'''#!/usr/bin/env bash
# GUNDAM BREAKER 3 BREAK EDITION - written by Recompiler Gundam Breaker 3 Break Edition.
# Add this file to Steam as a non-Steam game (bash "%(dir)s/play.sh") or run it from a terminal.
# Extra arguments go to psport/play-gb3.sh (e.g. --check, --async, --fps 30).
here=$(dirname -- "$(readlink -f -- "$0")")
export BUNDLE="$here/psport-bundle" GAME="$here/%(title)s"
# psport's run.sh keeps saves, shader cache and settings in the bundle: psport-bundle/user, psport.ini.
export DATA="$here/psport-bundle" USERDIR="$here/psport-bundle/user"
# The shop box fix GPU library carries an experimental GB3 profile; keep it off (it breaks the 720p path).
export PS_GAME_PROFILE=${PS_GAME_PROFILE:-none}
export PS_NO_TERMINAL=${PS_NO_TERMINAL:-1}
%(extra)sexec bash "$here/psport/play-gb3.sh" %(args)s"$@"
'''


def write_play(inst, opts, log):
    args = []
    extra = ''
    fps = opts.get('fps', '30')
    if fps == '60':
        args.append('--60')
    elif fps == 'uncapped':
        args.append('--uncap')
    if opts.get('async'):
        args.append('--async')
    text = PLAY_SH % {'dir': inst.dir, 'title': TITLE, 'extra': extra,
                      'args': ''.join(a + ' ' for a in args)}
    with open(inst.play, 'w') as f:
        f.write(text)
    os.chmod(inst.play, 0o755)
    # A menu entry: Steam's "Add a Non-Steam Game" lists these, so the game is one tick away.
    apps = os.path.join(os.environ.get('XDG_DATA_HOME') or os.path.expanduser('~/.local/share'), 'applications')
    try:
        os.makedirs(apps, exist_ok=True)
        with open(os.path.join(apps, 'gb3-recompiler-play.desktop'), 'w') as f:
            f.write('[Desktop Entry]\nType=Application\nName=GUNDAM BREAKER 3 (psport)\n'
                    'Comment=Play GUNDAM BREAKER 3 BREAK EDITION through psport\n'
                    'Exec=bash "%s"\nPath=%s\nTerminal=false\nCategories=Game;\n' % (inst.play, inst.dir))
        log('Play script: %s (also in the app menu as "GUNDAM BREAKER 3 (psport)")' % inst.play)
    except OSError as e:
        log('Play script: %s (menu entry not written: %s)' % (inst.play, e))


def import_saves(inst, log, sources=None):
    """Copy saves from an older psport bundle into this install (never overwrites)."""
    dst = inst.save_dir()
    if os.path.isdir(dst) and os.listdir(dst):
        log('This install already has saves; nothing imported')
        return False
    cands = sources or [
        '~/Applications/Psport/psport-bundle', '~/Applications/psport/psport-v0.2.0-x86_64',
        '~/Applications/psport/psport-bundle',
    ]
    for c in cands:
        src = os.path.join(os.path.expanduser(c), 'user', 'savedata', '1', SAVE_TITLE)
        if os.path.isdir(src) and os.listdir(src):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copytree(src, dst)
            log('Saves copied from %s' % src)
            return True
    log('No older psport saves found to import')
    return False


def backup_saves(inst, log):
    src = inst.save_dir()
    if not os.path.isdir(src):
        log('No saves to back up yet')
        return None
    dst = os.path.join(inst.dir, 'save-backups', time.strftime('%Y%m%d-%H%M%S'))
    shutil.copytree(src, dst)
    log('Saves backed up to %s' % dst)
    return dst


# ------------------------------------------------------------------ top level

def install(folder, pkg, opts, log):
    inst = Install(folder)
    t0 = time.time()
    log('== %s %s' % (APP_NAME, APP_VERSION))
    log('Install folder: %s' % inst.dir)
    if not inst.has_game():
        if not pkg:
            raise RuntimeError('Pick your GUNDAM BREAKER 3 PKG first')
        step_unpack(inst, pkg, log)
    known = check_game(inst, log)
    step_runtime(inst, log)
    want = step_mods(inst, opts, log, known)
    write_play(inst, opts, log)
    s = inst.state()
    s['options'] = dict(opts)
    s['installed_groups'] = want
    s['eboot_known'] = known
    s['installed_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
    inst.save_state(s)
    log('== Done in %d s. Press Play, or add play.sh to Steam.' % (time.time() - t0))
    return inst


def apply_options(folder, opts, log):
    inst = Install(folder)
    if not inst.has_game():
        raise RuntimeError('No game installed in %s' % inst.dir)
    known = check_game(inst, log)
    want = step_mods(inst, opts, log, known)
    write_play(inst, opts, log)
    s = inst.state()
    s['options'] = dict(opts)
    s['installed_groups'] = want
    inst.save_state(s)
    log('== Options applied.')


def restore_all(folder, log):
    inst = Install(folder)
    ps = patchset()
    gdat.restore(inst.game, ps, log)
    xml = os.path.join(inst.bundle, 'patches', PATCH_XML)
    if os.path.exists(xml):
        os.replace(xml, xml + '.off')
        log('720p eboot patch switched off')
    live = gdat.installed_groups(inst.game, ps)
    log('Mods now: %s' % ', '.join('%s=%s' % kv for kv in sorted(live.items())))
    s = inst.state()
    s['options']['xbox'] = s['options']['render720'] = False
    s['installed_groups'] = []
    inst.save_state(s)
    write_play(inst, s['options'], log)
    log('== Game files are back to the original PS4 data (saves untouched).')


def status(folder):
    inst = Install(folder)
    lines = ['Install folder: %s' % inst.dir]
    lines.append('Game: %s' % ('unpacked' if inst.has_game() else 'not installed'))
    lines.append('psport runtime: %s' % ('installed' if inst.has_runtime() else 'not installed'))
    if inst.has_game():
        try:
            live = gdat.installed_groups(inst.game, patchset())
            names = {'xbox': 'Xbox buttons', 'render720': '720p shaders'}
            lines.append('Mods: ' + ', '.join('%s %s' % (names.get(k, k), v) for k, v in sorted(live.items())))
        except Exception as e:  # noqa: BLE001 - shown to the player
            lines.append('Mods: cannot read (%s)' % e)
        xml = os.path.join(inst.bundle, 'patches', PATCH_XML)
        lines.append('720p eboot patch: %s' % ('on' if os.path.exists(xml) else 'off'))
    sd = inst.save_dir()
    lines.append('Saves: %s' % (sd if os.path.isdir(sd) and os.listdir(sd) else 'none yet'))
    return lines


def play(folder, log=None):
    inst = Install(folder)
    if not os.path.exists(inst.play):
        raise RuntimeError('Install first')
    env = dict(os.environ)
    # Do not leak the AppImage's own environment into the game.
    for k in ('PYTHONHOME', 'PYTHONPATH', 'TCL_LIBRARY', 'TK_LIBRARY', 'GB3R_ROOT', 'LD_LIBRARY_PATH'):
        env.pop(k, None)
    appdir = os.environ.get('APPDIR')
    if appdir:
        env['PATH'] = os.pathsep.join(p for p in env.get('PATH', '').split(os.pathsep) if not p.startswith(appdir))
    return subprocess.Popen(['bash', inst.play], env=env, cwd=inst.dir,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            universal_newlines=True, errors='replace', bufsize=1)
