"""Build a single-file Windows executable for World Games.

Why PyInstaller and not a custom packer: it is the de-facto standard for Python
desktop distribution, handles the stdlib subset automatically, and produces one
file the user can double-click. Hand-rolling zipapp/startup bootstrapping would
be re-inventing this.

The build script is deliberately a Python module rather than a .spec file so the
asset list can be derived from the repository instead of maintained by hand —
a missing panel.js would otherwise only surface at runtime on a user's machine.

Usage:
    python scripts/build_exe.py            # one-file console build into dist/
    python scripts/build_exe.py --onedir   # faster startup, directory layout
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Everything the runtime opens by path. Derived from the repo, not typed twice.
DATA_FILES = [
    ('panel.html', '.'),
    ('panel.css', '.'),
    ('panel.js', '.'),
    ('panel.i18n.js', '.'),
    ('admin.html', '.'),
    ('admin.js', '.'),
    ('assets/echarts.min.js', 'assets'),
    ('settings', 'settings'),
    ('README.md', '.'),
    ('README.zh-CN.md', '.'),
    ('ARCHITECTURE.md', '.'),
    ('CHANGELOG.md', '.'),
    ('GAME_MASTER_PROTOCOL.md', '.'),
    ('LICENSE', '.'),
    ('docs/ARCHIVE_RECOVERY.md', 'docs'),
    ('docs/GAMEPLAY.md', 'docs'),
    ('docs/BENCHMARK.md', 'docs'),
    ('docs/RELEASING.md', 'docs'),
    ('docs/metrics.json', 'docs'),
    ('docs/demo', 'docs/demo'),
    ('docs/screenshots', 'docs/screenshots'),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--onedir', action='store_true', help='directory build instead of one-file')
    parser.add_argument('--clean', action='store_true', help='remove previous build output first')
    args = parser.parse_args()

    try:
        import PyInstaller
    except ImportError:
        print('PyInstaller is required: pip install pyinstaller', file=sys.stderr)
        return 2

    if args.clean:
        for path in ('build', 'dist'):
            shutil.rmtree(os.path.join(ROOT, path), ignore_errors=True)

    print('PyInstaller', PyInstaller.__version__)
    missing = [rel for rel, _dest in DATA_FILES
               if not os.path.exists(os.path.join(ROOT, rel))]
    if missing:
        print('missing data files, refusing to build an incomplete exe:', missing, file=sys.stderr)
        return 1

    # The repository root IS the `game_engine` package, but the checkout
    # directory is named something else, so `import game_engine` cannot resolve
    # at analysis time. Stage a real `game_engine/` directory containing the
    # package sources and put it on the search path; PyInstaller then treats the
    # package normally instead of shipping data files with no code.
    stage = os.path.join(ROOT, 'build', 'stage')
    shutil.rmtree(stage, ignore_errors=True)
    pkg_dir = os.path.join(stage, 'game_engine')
    os.makedirs(os.path.join(pkg_dir, 'rules'), exist_ok=True)
    for name in os.listdir(ROOT):
        if name.endswith('.py'):
            shutil.copy2(os.path.join(ROOT, name), os.path.join(pkg_dir, name))
    for name in os.listdir(os.path.join(ROOT, 'rules')):
        if name.endswith('.py'):
            shutil.copy2(os.path.join(ROOT, 'rules', name),
                         os.path.join(pkg_dir, 'rules', name))
    print('staged package at', pkg_dir)

    sep = ';' if os.name == 'nt' else ':'
    add_data = []
    for rel, dest in DATA_FILES:
        add_data += ['--add-data', '%s%s%s' % (os.path.join(ROOT, rel), sep, dest)]

    # PyInstaller cannot see modules behind dynamic imports (cli.py resolves
    # game_engine.* at runtime), so the whole package is declared explicitly.
    # Without this the exe ships data files but no code and dies at startup.
    hidden = ['game_engine', 'game_engine.rules', 'game_engine.engine',
              'game_engine.mcp_server', 'game_engine.panel', 'game_engine.sessions',
              'game_engine.state_schema', 'game_engine.settings_loader',
              'game_engine.templates', 'game_engine.input_policy',
              'game_engine.viz_series', 'game_engine.bootstrap',
              'game_engine.mcp_primitives', 'game_engine.cli',
              'game_engine.init_game']
    hidden += ['game_engine.rules.' + name[:-3]
               for name in sorted(os.listdir(os.path.join(ROOT, 'rules')))
               if name.endswith('.py') and name != '__init__.py']
    hidden_args = []
    for mod in hidden:
        hidden_args += ['--hidden-import', mod]

    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--noconfirm',
        '--name', 'world-games',
        '--onedir' if args.onedir else '--onefile',
        '--console',
        *hidden_args,
        '--paths', stage,
        '--distpath', os.path.join(ROOT, 'dist'),
        '--workpath', os.path.join(ROOT, 'build'),
        '--specpath', os.path.join(ROOT, 'build'),
        *add_data,
        os.path.join(ROOT, 'cli.py'),
    ]
    print('building:', ' '.join(cmd[:8]), '... (%d data entries)' % len(DATA_FILES))
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        return result.returncode

    exe = os.path.join(ROOT, 'dist', 'world-games.exe' if os.name == 'nt' else 'world-games')
    if args.onedir:
        exe = os.path.join(ROOT, 'dist', 'world-games', 'world-games.exe' if os.name == 'nt' else 'world-games')
    size = os.path.getsize(exe) if os.path.exists(exe) else 0
    print('built %s (%.1f MB)' % (exe, size / 1024 / 1024))
    return 0


if __name__ == '__main__':
    sys.exit(main())
