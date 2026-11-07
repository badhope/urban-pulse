#!/usr/bin/env python3
"""
MCP 覆盖率测量 (coverage_mcp.py)

为什么需要：`verify_mcp_stdio.py` 通过 MCP SDK 启动 `mcp_server.py` 子进程，
父进程 coverage 收不到子进程数据 —— 这是审查报告 U-001「[未确认]」的根因。

为什么不用 `coverage run` 包一层：`coverage run` 把告警写到 **stdout**，
而 MCP stdio 协议用 stdout 传 JSON-RPC，任何杂音都会让连接断开
（实测 `MCPError: Connection closed`）。

正确做法：**不改启动命令**，用 `sitecustomize` 在解释器启动时静默挂上 coverage：
  - 生成 `<tmp>/sitecov/sitecustomize.py`（`coverage.process_startup()`）
  - 子进程 env 注入 `PYTHONPATH=<tmp>/sitecov` + `COVERAGE_PROCESS_START=<rc>`
  - rc 里必须写**绝对路径的 data_file** + `parallel = True`，否则数据不落盘
  - stdout 保持纯净（已实测 `{"jsonrpc"...` 首字节正常）

用法:  python scripts/coverage_mcp.py
退出码: 0 = 测量完成
"""

import glob
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, '.cov-mcp')

SITECUSTOMIZE = '''import os
if os.environ.get("COVERAGE_PROCESS_START"):
    try:
        import coverage
        coverage.process_startup()
    except Exception:
        pass
'''

ORIGINAL = "params = StdioServerParameters(command=sys.executable, args=[SERVER], cwd=ROOT)"
REPLACEMENT = (
    "params = StdioServerParameters(command=sys.executable, args=[SERVER], cwd=ROOT, "
    "env={**os.environ, 'PYTHONPATH': REPLACED_SITE, "
    "'COVERAGE_PROCESS_START': REPLACED_RC, 'PYTHONIOENCODING': 'utf-8'})"
)


def main():
    try:
        __import__('coverage')
    except ImportError:
        print('缺少 coverage：pip install coverage')
        return 2

    tmp = tempfile.mkdtemp(prefix='ww-cov-')
    site_dir = os.path.join(tmp, 'sitecov')
    os.makedirs(site_dir)
    with open(os.path.join(site_dir, 'sitecustomize.py'), 'w', encoding='utf-8') as f:
        f.write(SITECUSTOMIZE)

    # 每个子进程独立数据文件：多个 MCP 进程并发时共享同一文件会锁冲突
    data_file = os.path.join(tmp, 'covdata')
    rc = os.path.join(tmp, '.covrc')
    with open(rc, 'w', encoding='utf-8') as f:
        f.write('[run]\n')
        f.write('data_file = ' + data_file.replace('\\', '/') + '\n')
        f.write('parallel = True\n')
        f.write('branch = True\n')
        # source 用绝对路径：子进程 cwd 与父进程可能不同，相对路径会匹配不到源文件
        srcs = [os.path.join(ROOT, 'mcp_server.py'), os.path.join(ROOT, 'rules'),
                os.path.join(ROOT, 'panel.py'), os.path.join(ROOT, 'state_schema.py')]
        f.write('source = ' + ','.join(s.replace('\\', '/') for s in srcs) + '\n')
        f.write('[report]\n')
        f.write('omit = */__pycache__/*,*/site-packages/*\n')

    shutil.rmtree(DATA, ignore_errors=True)
    os.makedirs(DATA, exist_ok=True)

    src = open(os.path.join(ROOT, 'scripts', 'verify_mcp_stdio.py'), encoding='utf-8').read()
    if ORIGINAL not in src:
        print('未找到预期启动语句，测试脚本可能已改动：\n  ' + ORIGINAL)
        return 1
    repl = (REPLACEMENT
            .replace('REPLACED_SITE', repr(site_dir))
            .replace('REPLACED_RC', repr(rc)))
    # 注意：patched 脚本必须放在 scripts/ 下，因为原脚本用
    # ROOT = dirname(dirname(__file__)) 推导项目根；放 tmp 里会算到错误目录，
    # SERVER 路径失效 → 子进程启动失败 → "Connection closed"。
    patched = os.path.join(ROOT, 'scripts', '_verify_mcp_cov_tmp.py')
    body = src.replace(ORIGINAL, repl)
    # 插桩后子进程启动与每次工具调用都会变慢（coverage 逐行记录）；
    # SDK 默认读超时偏紧，这里放宽到 120s，避免误判为连接断开。
    body = body.replace('async with ClientSession(read, write) as session:',
                        'async with ClientSession(read, write, read_timeout_seconds=120) as session:')
    with open(patched, 'w', encoding='utf-8') as f:
        f.write(body)

    env = dict(os.environ, COVERAGE_PROCESS_START=rc,
               PYTHONPATH=site_dir, PYTHONIOENCODING='utf-8')
    print('跑 MCP 端到端（子进程经 sitecustomize 插桩）…')
    run = subprocess.run([sys.executable, patched], cwd=ROOT, env=env,
                         capture_output=True, text=True, encoding='utf-8')
    print((run.stdout or '')[-1400:])
    if run.returncode != 0:
        print('测试失败（覆盖率数据可能不完整）：')
        print((run.stderr or '')[-600:])

    files = glob.glob(data_file + '*')
    print('覆盖数据文件：%d 个' % len(files))
    if not files:
        print('没有产出覆盖率数据')
        return 1
    # 子进程的数据文件在临时目录里，combine 前先搬到项目内（否则清理 tmp 时会丢）
    moved = []
    for i, f in enumerate(files):
        dst = os.path.join(DATA, 'part%d' % i)
        shutil.copyfile(f, dst)
        moved.append(dst)
    subprocess.run([sys.executable, '-m', 'coverage', 'combine',
                    '--data-file=' + os.path.join(DATA, 'cov')] + moved,
                   cwd=ROOT, capture_output=True)
    report = subprocess.run(
        [sys.executable, '-m', 'coverage', 'report',
         '--data-file=' + os.path.join(DATA, 'cov')],
        cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
    print(report.stdout or '(无数据)')
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        os.remove(patched)
    except OSError:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
