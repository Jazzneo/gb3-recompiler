"""Entry point.

    gb3r                     open the window
    gb3r --play              start the installed game (for a Steam shortcut)
    gb3r install --pkg FILE [--dir DIR] [--no-xbox] [--no-720p] [--fps 30|60|uncapped]
    gb3r apply  [--dir DIR] [--[no-]xbox] [--[no-]720p]  change mods on an installed game
    gb3r restore [--dir DIR]                             put the original game files back
    gb3r status [--dir DIR]
    gb3r import-saves [--dir DIR] [--from BUNDLE]
"""
import argparse
import sys

from . import core


def cli(argv):
    ap = argparse.ArgumentParser(prog='gb3r', description=core.APP_NAME)
    ap.add_argument('--play', action='store_true', help='start the installed game')
    ap.add_argument('--version', action='store_true')
    sub = ap.add_subparsers(dest='cmd')
    for name in ('install', 'apply', 'restore', 'status', 'import-saves', 'gui'):
        p = sub.add_parser(name)
        p.add_argument('--dir', help='install folder (default: last used, else ~/Games/GB3-Recompiler)')
        if name == 'install':
            p.add_argument('--pkg', help='your GUNDAM BREAKER 3 BREAK EDITION (CUSA07651) PKG')
        if name in ('install', 'apply'):
            p.add_argument('--xbox', action=argparse.BooleanOptionalAction, default=None,
                           help='Xbox button art (install default: on; --no-xbox keeps PlayStation art)')
            p.add_argument('--720p', dest='r720', action=argparse.BooleanOptionalAction, default=None,
                           help='720p render patch (install default: on; --no-720p renders 1080p)')
            p.add_argument('--fps', choices=('30', '60', 'uncapped'), default=None)
        if name == 'import-saves':
            p.add_argument('--from', dest='src', help='an older psport bundle folder')
    a = ap.parse_args(argv)
    cfg = core.load_config()
    if a.version:
        print(core.APP_NAME, core.APP_VERSION)
        return 0
    if a.play:
        p = core.play(cfg['install_dir'])
        for line in p.stdout:
            sys.stdout.write(line)
        return p.wait()
    if a.cmd in (None, 'gui'):
        from . import gui
        return gui.main()
    folder = a.dir or cfg['install_dir']
    log = print
    try:
        if a.cmd == 'status':
            print('\n'.join(core.status(folder)))
            return 0
        if a.cmd == 'restore':
            core.restore_all(folder, log)
            return 0
        if a.cmd == 'import-saves':
            core.import_saves(core.Install(folder), log, [a.src] if a.src else None)
            return 0
        inst = core.Install(folder)
        opts = inst.state()['options']
        if a.cmd == 'install' and not inst.has_game():
            opts.update(xbox=True, render720=True)
        if a.xbox is not None:
            opts['xbox'] = a.xbox
        if a.r720 is not None:
            opts['render720'] = a.r720
        if a.fps:
            opts['fps'] = a.fps
        if a.cmd == 'install':
            if a.pkg:
                cfg['pkg'] = a.pkg
            core.install(folder, a.pkg or cfg.get('pkg'), opts, log)
        else:
            core.apply_options(folder, opts, log)
        cfg['install_dir'] = folder
        core.save_config(cfg)
        return 0
    except Exception as e:  # noqa: BLE001
        print('ERROR: %s' % e, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(cli(sys.argv[1:]))
