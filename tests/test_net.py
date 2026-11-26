"""Network mode tests (stdlib unittest; no game is run).

    python3 -m unittest discover -s tests -v

The server tests need the bundled co-op server (build/shadnet-runtime, made by
packaging/bundle-shadnet.sh) and free UDP ports 31399 and 3478; they are skipped otherwise.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'app', 'gb3r'))
import net  # noqa: E402

SHADNET = os.path.join(ROOT, 'build', 'shadnet-runtime')


def free_tcp_base():
    for base in range(46313, 47000, 10):
        ok = True
        for p in (base, base + 2):
            s = socket.socket()
            try:
                s.bind(('0.0.0.0', p))
            except OSError:
                ok = False
            finally:
                s.close()
        if ok:
            return base
    raise RuntimeError('no free ports')


def udp_free(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(('0.0.0.0', port))
        return True
    except OSError:
        return False
    finally:
        s.close()


class Pure(unittest.TestCase):
    def test_names(self):
        for good in ('gb3deck', 'Red_X9', 'a-b', 'ABCDEFGHIJKLMNOP'):
            self.assertTrue(net.valid_name(good), good)
        for bad in ('', 'ab', 'ABCDEFGHIJKLMNOPQ', 'with space', 'émile', 'DeletedUser', 'a.b'):
            self.assertFalse(net.valid_name(bad), bad)

    def test_addr(self):
        self.assertEqual(net.split_addr('1.2.3.4'), ('1.2.3.4', 31313))
        self.assertEqual(net.split_addr(' host:4000 '), ('host', 4000))
        self.assertEqual(net.split_addr(''), ('', 31313))

    def test_pick_port_skips_taken(self):
        busy = socket.socket()
        busy.bind(('0.0.0.0', 0))
        base = busy.getsockname()[1]
        try:
            self.assertNotEqual(net.pick_port(base), base)
        finally:
            busy.close()

    def test_proto(self):
        self.assertEqual(net._varint(300), b'\xac\x02')
        self.assertEqual(net._pb({1: 'ab', 3: '', 2: 'c'}), b'\x0a\x02ab\x12\x01c')

    def test_offline_env(self):
        lines = net.launch_env('/nowhere', 0, dict(net.DEFAULTS))
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith('unset PS_ONLINE'))

    def test_no_name_stays_offline(self):
        c = dict(net.DEFAULTS, mode='online', server='127.0.0.1:1')
        self.assertEqual(len(net.launch_env('/nowhere', 0, c, log=lambda m: None)), 1)

    def test_unreachable_server_stays_offline(self):
        c = dict(net.DEFAULTS, mode='online', name='nobody1', server='127.0.0.1:1')
        msgs = []
        self.assertEqual(len(net.launch_env('/nowhere', 0, c, log=msgs.append)), 1)
        self.assertIn('playing offline', msgs[-1])


@unittest.skipUnless(udp_free(3478), 'udp 3478 busy')
class RelayTest(unittest.TestCase):
    def test_forward(self):
        net.Relay(3478).start()
        a = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        b = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for s in (a, b):
            s.settimeout(2)
        A, B, C = (n.ljust(16, b'\0') for n in (b'alice', b'bob', b'carol'))
        r = ('127.0.0.1', 3478)
        a.sendto(b'BBR1\x01' + A, r)
        b.sendto(b'BBR1\x01' + B, r)
        self.assertEqual(a.recv(64), b'BBR1\x02')
        self.assertEqual(b.recv(64), b'BBR1\x02')
        a.sendto(b'BBR1\x03' + B + A + b'frame', r)
        self.assertEqual(b.recv(64), b'BBR1\x04' + A + b'frame')
        a.sendto(b'BBR1\x03' + C + A + b'x', r)
        self.assertEqual(a.recv(64), b'BBR1\x05' + C)


@unittest.skipUnless(os.path.exists(os.path.join(SHADNET, 'shadnet')) and udp_free(net.BEACON_PORT),
                     'no bundled server or udp 31399 busy')
class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='gb3net-test-')
        cls.base = free_tcp_base()
        env = dict(os.environ, XDG_CONFIG_HOME=os.path.join(cls.tmp, 'cfg'), XDG_DATA_HOME=os.path.join(cls.tmp, 'data'))
        cls.proc = subprocess.Popen([sys.executable, os.path.join(ROOT, 'app', 'gb3r', 'net.py'), 'serve', '--shadnet', SHADNET,
                                     '--data', os.path.join(cls.tmp, 'srv'), '--port', str(cls.base), '--name', 'unittest',
                                     '--no-relay'], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        end = time.time() + 15
        while time.time() < end and not net.tcp_open('127.0.0.1', cls.base, 0.3):
            time.sleep(0.3)
        net.ACCOUNTS = os.path.join(cls.tmp, 'accounts.json')

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(15)

    def test_1_listening(self):
        self.assertTrue(net.tcp_open('127.0.0.1', self.base))
        self.assertTrue(net.tcp_open('127.0.0.1', self.base + 2))

    def test_2_discover(self):
        hosts = [h for h in net.discover(1.5) if h['port'] == self.base]
        self.assertEqual(len(hosts), 1)
        self.assertEqual(hosts[0]['name'], 'unittest')
        self.assertTrue(hosts[0]['id'])

    def test_3_accounts(self):
        ip = net.lan_ip()
        pw = net.ensure_account(ip, self.base, 'Unit_Test', server_id='t', log=lambda m: None)
        self.assertEqual(net.ensure_account(ip, self.base, 'Unit_Test', server_id='t', log=lambda m: None), pw)
        self.assertEqual(net.check_login(ip, self.base, 'Unit_Test', 'wrong'), 8)
        with self.assertRaises(RuntimeError):
            net.ensure_account(ip, self.base, 'Unit_Test', server_id='other', log=lambda m: None)
        self.assertEqual(os.stat(net.ACCOUNTS).st_mode & 0o777, 0o600)

    def test_4_join_env(self):
        c = dict(net.DEFAULTS, mode='lan-join', name='Joiner_1', lan_host='127.0.0.1:%d' % self.base)
        old = os.environ.get('XDG_RUNTIME_DIR')
        os.environ['XDG_RUNTIME_DIR'] = self.tmp
        try:
            lines = net.launch_env('/nowhere', 0, c, log=lambda m: None)
        finally:
            if old is None:
                os.environ.pop('XDG_RUNTIME_DIR')
            else:
                os.environ['XDG_RUNTIME_DIR'] = old
        env = dict(l[7:].split('=', 1) for l in lines if l.startswith('export '))
        self.assertEqual(env['PS_ONLINE'], "'1'")
        self.assertEqual(env['PS_SHADNET_NPID'], "'Joiner_1'")
        self.assertEqual(env['PS_UPNP'], "'0'")
        secrets_file = env['PS_SHADNET_SECRETS_FILE'].strip("'")
        self.assertEqual(os.stat(secrets_file).st_mode & 0o777, 0o600)
        with open(secrets_file) as f:
            self.assertTrue(f.read().startswith('password='))
        os.unlink(secrets_file)


if __name__ == '__main__':
    unittest.main()
