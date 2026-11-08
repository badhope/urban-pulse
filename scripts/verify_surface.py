#!/usr/bin/env python3
"""Delivery-surface self-check (verify_cli.py and friends).

Why this exists: v1.7.0 added a unified CLI, MCP resources, a web console and a
packaged executable. None of those are covered by the rule-engine suites, and a
shipped binary that cannot start is exactly the kind of defect that only shows
up on a user's machine. This checks the surfaces themselves.

  S1  `wg` exposes every documented subcommand and `--help` works
  S2  `wg version` prints the same version as __init__.py
  S3  `wg doctor` returns the full diagnostic JSON and exits 0 on a healthy tree
  S4  `wg init` writes a loadable save and refuses to overwrite
  S5  the MCP surface declares resources and annotations in source
  S6  the admin console assets are whitelisted and served
  S7  the exe build script refuses to build with missing data files

Usage:  python scripts/verify_cli.py
Exit:   0 = consistent, 1 = defect
"""

import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = []


def _scratch(prefix='ww-surface-'):
    """Scratch dir under <repo>/.tmp/, creating .tmp when a fresh clone lacks it."""
    base = os.path.join(ROOT, '.tmp')
    os.makedirs(base, exist_ok=True)
    return tempfile.mkdtemp(prefix=prefix, dir=base)


def check(name, ok, note=''):
    RESULTS.append(bool(ok))
    print('%s  %-56s %s' % ('PASS' if ok else 'FAIL', name, str(note)[:90]))


def run(args, cwd=None):
    return subprocess.run([sys.executable] + args, cwd=cwd or ROOT,
                          capture_output=True, text=True, timeout=180)


def main():
    cli = os.path.join(ROOT, 'cli.py')

    # ── S1 subcommands ──────────────────────────────────────────────────────
    help_out = run([cli, '--help'])
    text = help_out.stdout
    documented = ['init', 'play', 'serve', 'mcp', 'run', 'doctor', 'version']
    missing = [cmd for cmd in documented if cmd not in text]
    check('S1a wg --help lists every documented subcommand', not missing, str(missing))
    check('S1b wg --help exits 0', help_out.returncode == 0, help_out.returncode)

    # ── S2 version ──────────────────────────────────────────────────────────
    with open(os.path.join(ROOT, '__init__.py'), encoding='utf-8') as fh:
        declared = re.search(r'__version__\s*=\s*"([^"]+)"', fh.read()).group(1)
    ver = run([cli, 'version'])
    check('S2 wg version matches __init__.py',
          ver.stdout.strip() == declared, '%r vs %r' % (ver.stdout.strip(), declared))

    # ── S3 doctor ───────────────────────────────────────────────────────────
    doc = run([cli, 'doctor'])
    payload = {}
    try:
        payload = json.loads(doc.stdout)
    except ValueError:
        pass
    check('S3 wg doctor returns JSON and exits 0',
          doc.returncode == 0 and isinstance(payload, dict)
          and payload.get('version') == declared,
          'rc=%s keys=%s' % (doc.returncode, sorted(payload)[:5]))
    check('S3b doctor reports every runtime asset present',
          all(payload.get('assets', {}).values()) and bool(payload.get('bundles')),
          str(payload.get('assets', {})))

    # ── S4 init ─────────────────────────────────────────────────────────────
    tmp = _scratch()
    target = os.path.join(tmp, 'probe.json')
    made = run([cli, 'init', target])
    loaded = None
    if os.path.isfile(target):
        with open(target, encoding='utf-8') as fh:
            loaded = json.load(fh)
    check('S4a wg init writes a loadable save',
          made.returncode == 0 and loaded is not None
          and bool(loaded.get('entities')) and bool(loaded.get('world_info')),
          'rc=%s' % made.returncode)
    again = run([cli, 'init', target])
    check('S4b wg init refuses to overwrite an existing save',
          again.returncode != 0, 'rc=%s' % again.returncode)

    # ── S5 MCP surface declared ─────────────────────────────────────────────
    with open(os.path.join(ROOT, 'mcp_server.py'), encoding='utf-8') as fh:
        server_src = fh.read()
    check('S5a MCP server registers resources', 'register_resources' in server_src)
    with open(os.path.join(ROOT, 'mcp_primitives.py'), encoding='utf-8') as fh:
        prim = fh.read()
    check('S5b tool annotations are defined for read-only and destructive sets',
          'read_only_hint' in prim and 'destructive_hint' in prim)
    check('S5c resource URIs are world:// scoped',
          len(re.findall(r"world://[a-z/]+", prim)) >= 4)

    # ── S6 admin console ────────────────────────────────────────────────────
    with open(os.path.join(ROOT, 'panel.py'), encoding='utf-8') as fh:
        panel_src = fh.read()
    check('S6a admin console assets are whitelisted',
          '"/admin"' in panel_src and '"/admin.js"' in panel_src)
    check('S9 主题引导脚本在面板白名单内（否则 404 → 首帧闪错色）',
          '"/panel.theme.js"' in panel_src)
    # Release notes must quote the ledger, never a hand-typed number: the v1.9.0
    # release shipped "32 steps / 50 mutants" for weeks after the gate grew.
    release_src = open(os.path.join(ROOT, 'scripts', 'publish_release.py'),
                       encoding='utf-8').read()
    check('S10 发布说明的数字来自 docs/metrics.json（不硬编码）',
          '_ledger()' in release_src and "m['gate_steps']" in release_src
          and "m['mutants']" in release_src)
    check('S6b admin console has no inline script (CSP script-src self)',
          '"/admin.js"' in open(os.path.join(ROOT, 'admin.html'), encoding='utf-8').read()
          and '<script>' not in open(os.path.join(ROOT, 'admin.html'), encoding='utf-8').read())

    # ── S11 依赖锁定必须与 requires-python 相容 ───────────────────────────
    # 2026-11-08 的 CI 红就是这个：pyproject 声明 >=3.10，而 lockfile 钉的
    # httpx2 / starlette / pydantic-settings 已要求 3.11，py3.10 作业直接装不上。
    # 这里做静态检查（不联网）：锁文件里每个包名/版本都要有记录，且不得出现
    # 已知的 3.11-only 版本号。真正的可安装性由 CI 矩阵两端验证。
    lock_path = os.path.join(ROOT, 'requirements-mcp.lock.txt')
    lock_text = open(lock_path, encoding='utf-8').read()
    pins = {}
    for line in lock_text.splitlines():
        line = line.strip()
        if '==' in line and not line.startswith('#'):
            name, _, ver = line.partition('==')
            pins[name.strip()] = ver.strip()
    # 这些版本是被实测确认要求 >=3.11 的（见 CHANGELOG v1.10.1）
    known_blockers = {
        'pydantic-settings': ('2.16.0', '2.16.1', '2.16.2'),
        'starlette': ('1.8.0', '1.9.0', '1.10.0'),
        'sse-starlette': ('3.6.0', '3.7.0'),
        'httpx2': ('2.15.0', '2.15.1', '2.16.0'),
    }
    offenders = [f'{k}=={v}' for k, v in pins.items()
                 if v in known_blockers.get(k, ())]
    check('S11a lockfile pins deps that still install on Python 3.10',
          not offenders, str(offenders))
    check('S11b lockfile pins the transitive chain mcp actually pulls',
          {'mcp', 'httpx2', 'starlette', 'pydantic-settings', 'uvicorn'} <= set(pins),
          str(sorted(set(pins))[:8]))
    pyproject = open(os.path.join(ROOT, 'pyproject.toml'), encoding='utf-8').read()
    check('S11c project still declares >=3.10 and the lockfile agrees',
          'requires-python = ">=3.10"' in pyproject)
    # Static version checks can drift from what pip actually resolves (transitive
    # deps). Ask pip to resolve the lockfile *as if* it were Python 3.10 — no
    # install, no network beyond the index. This is the check that would have
    # caught the 2026-11-08 CI failure before it shipped.
    resolve = subprocess.run(
        [sys.executable, '-m', 'pip', 'install', '--dry-run', '--ignore-installed',
         '--python-version', '3.10', '--only-binary=:all:', '-q',
         '-r', lock_path],
        capture_output=True, text=True, timeout=300,
        env=dict(os.environ, PYTHONIOENCODING='utf-8'))
    offline = ('network' in (resolve.stderr or '').lower()
               or 'connection' in (resolve.stderr or '').lower()
               or 'new connection' in (resolve.stderr or '').lower())
    check('S11d pip can resolve the lockfile for Python 3.10',
          resolve.returncode == 0 or offline,
          'SKIPPED (offline: no index reachable)' if offline
          else (resolve.stderr or resolve.stdout or '')[-160:])

    # ── S12 验证脚本不得假设 .tmp/ 已存在 ─────────────────────────────────
    # `.tmp/` 在 .gitignore 里，全新 clone 没有它；直接用 mkdtemp(dir=.tmp)
    # 会在 CI 上抛 FileNotFoundError，且错误信息完全看不出该怎么修。
    offenders = []
    for name in sorted(os.listdir(os.path.join(ROOT, 'scripts'))):
        if not name.endswith('.py'):
            continue
        # The helper itself and this check legitimately contain the pattern
        # (one implements the fix, the other searches for it).
        if name == '_tmpdir.py':
            continue
        src = open(os.path.join(ROOT, 'scripts', name), encoding='utf-8').read()
        # Match every spelling that hard-codes .tmp as a mkdtemp target:
        #   dir=os.path.join(ROOT, '.tmp')   dir=<repo>/.tmp   dir=".tmp"
        # The first version of this check only matched the first spelling and
        # therefore missed verify_surface.py itself, which kept CI red.
        for line in src.splitlines():
            if line.lstrip().startswith('#'):
                continue
            if re.search(r'mkdtemp\([^)]*dir\s*=\s*[^)]*\.tmp', line):
                offenders.append(name)
                break
    check('S12 no verification script assumes .tmp/ already exists',
          not offenders, str(offenders))
    tmpdir_helper = os.path.join(ROOT, 'scripts', '_tmpdir.py')
    check('S12b the scratch helper creates .tmp on demand',
          os.path.isfile(tmpdir_helper)
          and 'makedirs' in open(tmpdir_helper, encoding='utf-8').read())

    # ── S7 build script guards ──────────────────────────────────────────────
    with open(os.path.join(ROOT, 'scripts', 'build_exe.py'), encoding='utf-8') as fh:
        build_src = fh.read()
    check('S7 exe build refuses to ship with missing data files',
          'refusing to build an incomplete exe' in build_src)
    check('S7b exe build declares hidden imports for dynamic modules',
          '--hidden-import' in build_src and 'game_engine.mcp_server' in build_src)

    # ── S8 release tooling is versioned, not scratch ───────────────────────
    import os as _os
    tools = ['publish_github.py', 'publish_release.py']
    present = [t for t in tools if _os.path.isfile(_os.path.join(ROOT, 'scripts', t))]
    check('S8 release tooling is committed under scripts/', len(present) == len(tools),
          str(present))
    with open(_os.path.join(ROOT, 'scripts', 'publish_release.py'), encoding='utf-8') as fh:
        rel_src = fh.read()
    check('S8b release tool attaches a binary asset',
          'upload_asset' in rel_src and 'releases' in rel_src)

    passed = sum(RESULTS)
    print('\n%d/%d passed' % (passed, len(RESULTS)))
    return 0 if passed == len(RESULTS) else 1


if __name__ == '__main__':
    sys.exit(main())
