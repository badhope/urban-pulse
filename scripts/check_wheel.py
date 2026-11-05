#!/usr/bin/env python3
"""
wheel 资源校验 (check_wheel.py)

CI 的 package 作业与本机 pre-push 门禁共用同一判据：构建出来的 wheel
必须带齐运行时按路径读取的资源，否则 pip 安装后 open_panel / load_setting
会找不到文件（这类缺陷只在"装完再跑"时暴露，源码树里永远看不出来）。

用法:  python scripts/check_wheel.py <dist 目录>
退出码: 0 = 齐全；1 = 缺文件或无 wheel
"""

import glob
import os
import sys
import zipfile

# 运行时通过 __file__ 相对路径读取的资源（见 pyproject.toml package-data）
REQUIRED = [
    'bootstrap.py',
    'panel.html',
    'panel.css',
    'panel.js',
    'panel.i18n.js',
    'admin.html',
    'admin.js',
    'cli.py',
    'mcp_primitives.py',
    'action_log.py',
    'assets/echarts.min.js',
    'settings/玄枢界.setting.json',
    'settings/折剑行.setting.json',
    'settings/霓虹深渊.setting.json',
    'settings/雾港.setting.json',
    'settings/README.md',
    'README.md',
    'README.zh-CN.md',
    'CODE_OF_CONDUCT.md',
    'docs/metrics.json',
    'ARCHITECTURE.md',
    'BRAND.md',
    'templates.py',
    'rules/systems.py',
    'GAME_MASTER_PROTOCOL.md',
    'docs/GAMEPLAY.md',
    'docs/BENCHMARK.md',
    'docs/demo/玄枢界.save.json',
    'docs/demo/折剑行.save.json',
    'docs/demo/霓虹深渊.save.json',
    'docs/demo/雾港.save.json',
    'docs/screenshots/stage-xuanshu.png',
    'docs/screenshots/walkthrough.mp4',
]


def main():
    if len(sys.argv) < 2:
        print('用法: python scripts/check_wheel.py <dist 目录>')
        return 1
    dist = sys.argv[1]
    wheels = sorted(glob.glob(os.path.join(dist, '*.whl')))
    if not wheels:
        print('在 %s 下没有找到 wheel' % dist)
        return 1
    names = zipfile.ZipFile(wheels[0]).namelist()
    missing = [r for r in REQUIRED if not any(n.endswith(r) for n in names)]
    if missing:
        print('wheel 缺少运行时资源: %s' % missing)
        return 1
    print('wheel 资源完整（%d 条目，%s）' % (len(names), os.path.basename(wheels[0])))
    return 0


if __name__ == '__main__':
    sys.exit(main())
