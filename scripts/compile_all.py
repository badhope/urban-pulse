#!/usr/bin/env python3
"""
全仓编译检查 (compile_all.py)

替代 `python -m compileall -x <正则>`：compileall 的 `-x` 在 Windows 上因为
路径分隔符是反斜杠、且 shell 会对正则做二次转义，实测排除规则经常失效
（build/ 下仍会生成 .pyc）。这里直接用 Python 遍历，跨平台一致。

排除：.git / __pycache__ / dist / build / .aqg / node_modules
用法:  python scripts/compile_all.py
退出码: 0 = 全部可编译；1 = 有语法错误
"""

import os
import py_compile
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {'.git', '__pycache__', 'dist', 'build', '.aqg', 'node_modules',
             '.gate-dist', '.venv', 'venv', '.idea', '.vscode'}


def main():
    failed, checked = [], 0
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if not fn.endswith('.py'):
                continue
            path = os.path.join(dirpath, fn)
            checked += 1
            try:
                py_compile.compile(path, doraise=True)
            except py_compile.PyCompileError as e:
                failed.append((os.path.relpath(path, ROOT), str(e)[:200]))
    if failed:
        print('编译失败 %d / %d 个文件：' % (len(failed), checked))
        for p, err in failed:
            print('  %s\n    %s' % (p, err))
        return 1
    print('全部 %d 个 Python 文件编译通过（已排除 build/dist/.git 等目录）' % checked)
    return 0


if __name__ == '__main__':
    sys.exit(main())
