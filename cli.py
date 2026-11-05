"""Unified command-line entry point (world-games / wg).

Why this exists
---------------
The project shipped four separate commands (engine, mcp_server, panel,
init_game) and no single place that answered "how do I start?" for a new user.
A product needs one front door.

Subcommands:
    wg init [path]                 create a starter save
    wg play [--state P]            open the live stage in the browser
    wg serve [--state P] [--port]  run the stage headless (no auto-open)
    wg mcp                         run the MCP server on stdio
    wg run <action> [args]         run one rule-engine action (see `wg run --help`)
    wg doctor                      print an environment/diagnostic report
    wg version                     print the version

`wg` is a thin dispatcher: every subcommand delegates to the existing module, so
there is exactly one implementation of each behaviour.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))


def _bootstrap():
    try:
        from game_engine import bootstrap
    except ImportError:
        sys.path.insert(0, ROOT)
        import bootstrap
    bootstrap.ensure_parent_on_path(ROOT)
    bootstrap.install(ROOT)


def _version() -> str:
    _bootstrap()
    from game_engine import __version__
    return __version__


def _free_port(preferred: int) -> int:
    """Return `preferred` when free, otherwise the next free port.

    Never kills whatever holds the port: the project rule is to pick a
    different port and say so, not to terminate someone else's process.
    """
    for candidate in range(preferred, preferred + 40):
        with socket.socket() as probe:
            try:
                probe.bind(('127.0.0.1', candidate))
            except OSError:
                continue
            return candidate
    raise SystemExit('no free port in %d-%d' % (preferred, preferred + 39))


def cmd_init(args) -> int:
    """Write a starter save.

    init_game.py is a top-level script whose path comes from sys.argv, which is
    unreliable inside a frozen exe. Instead the starter bundle is loaded through
    the normal settings path, so the exe and the source tree share one code path.
    """
    _bootstrap()
    import json
    import settings_loader

    target = os.path.abspath(args.path)
    if os.path.exists(target):
        print('refusing to overwrite existing file: %s' % target, file=sys.stderr)
        return 1

    bundle_path = os.path.join(ROOT, 'settings', '玄枢界.setting.json')
    if not os.path.isfile(bundle_path):
        print('starter bundle missing: %s' % bundle_path, file=sys.stderr)
        return 1
    with open(bundle_path, encoding='utf-8') as fh:
        bundle = json.load(fh)
    state = settings_loader.build_state(bundle)
    settings_loader.apply_runtime_fields(state, bundle)
    os.makedirs(os.path.dirname(target) or '.', exist_ok=True)
    with open(target, 'w', encoding='utf-8') as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
    print('created %s' % target)
    print('world: %s · entities: %d · markets: %d'
          % (state['world_info']['name'], len(state['entities']), len(state['market'])))
    return 0


def _serve(state: str, port: int, open_browser: bool) -> int:
    _bootstrap()
    import panel

    state = os.path.abspath(state)
    if not os.path.exists(state):
        print('state file not found: %s' % state, file=sys.stderr)
        print('hint: wg init %s' % state, file=sys.stderr)
        return 1
    chosen = _free_port(port)
    if chosen != port:
        print('port %d is busy; using %d instead' % (port, chosen))
    srv, bound = panel.start(state, chosen)
    url = 'http://127.0.0.1:%d/' % bound
    print('World Games stage: %s' % url)
    print('state: %s' % state)
    print('press Ctrl+C to stop')
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    import time
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        panel.stop(srv)
    return 0


def cmd_play(args) -> int:
    return _serve(args.state, args.port, open_browser=not args.no_browser)


def cmd_serve(args) -> int:
    return _serve(args.state, args.port, open_browser=False)


def cmd_mcp(_args) -> int:
    _bootstrap()
    import mcp_server
    mcp_server.main()
    return 0


def cmd_run(args) -> int:
    """Delegate to engine.py's argparse so there is one definition of each action."""
    _bootstrap()
    import engine
    argv = sys.argv
    try:
        sys.argv = ['engine.py'] + args.rest
        engine.main()
    finally:
        sys.argv = argv
    return 0


def cmd_doctor(_args) -> int:
    _bootstrap()
    import platform
    import shutil

    report = {
        'version': _version(),
        'python': sys.version.split()[0],
        'executable': sys.executable,
        'platform': platform.platform(),
        'cwd': os.getcwd(),
        'package_root': ROOT,
        'stdlib_only_core': True,
        'optional': {},
        'assets': {},
    }
    for name in ('mcp', 'pydantic', 'playwright', 'coverage'):
        try:
            module = __import__(name)
            report['optional'][name] = getattr(module, '__version__', 'present')
        except ImportError:
            report['optional'][name] = None
    for rel in ('panel.html', 'panel.js', 'panel.css', 'panel.i18n.js',
                'assets/echarts.min.js'):
        path = os.path.join(ROOT, rel)
        report['assets'][rel] = os.path.getsize(path) if os.path.exists(path) else None
    report['bundles'] = sorted(f for f in os.listdir(os.path.join(ROOT, 'settings'))
                               if f.endswith('.setting.json')) \
        if os.path.isdir(os.path.join(ROOT, 'settings')) else []
    report['git'] = shutil.which('git')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    healthy = all(report['assets'].values()) and bool(report['bundles'])
    return 0 if healthy else 1


def cmd_version(_args) -> int:
    print(_version())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='wg',
        description='World Games — the AI narrates, the engine decides.',
        epilog='Run `wg <command> --help` for details.')
    parser.add_argument('--version', action='version', version='%(prog)s ' + _version())
    sub = parser.add_subparsers(dest='command')

    p = sub.add_parser('init', help='create a starter save')
    p.add_argument('path', nargs='?', default='game_state.json')
    p.set_defaults(func=cmd_init)

    p = sub.add_parser('play', help='open the live stage in a browser')
    p.add_argument('--state', default='game_state.json')
    p.add_argument('--port', type=int, default=8765)
    p.add_argument('--no-browser', action='store_true')
    p.set_defaults(func=cmd_play)

    p = sub.add_parser('serve', help='run the stage headless')
    p.add_argument('--state', default='game_state.json')
    p.add_argument('--port', type=int, default=8765)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser('mcp', help='run the MCP server on stdio')
    p.set_defaults(func=cmd_mcp)

    p = sub.add_parser('run', help='run one rule-engine action')
    p.add_argument('rest', nargs=argparse.REMAINDER,
                   help='action and its flags, e.g. combat --state s.json --attacker player '
                        '--defender goblin')
    p.set_defaults(func=cmd_run)

    p = sub.add_parser('doctor', help='environment and asset diagnostics')
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser('version', help='print the version')
    p.set_defaults(func=cmd_version)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, 'func', None):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
