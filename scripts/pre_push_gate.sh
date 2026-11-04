#!/usr/bin/env bash
#
# 推送前门禁（pre-push gate）
#
# 为什么需要：GitHub Actions 是主 CI（core / mcp / package / showcase / gate 五个作业）。
# Gitee 走 .workflow/ci.yml（同一批检查的 stage/step 声明），GitCode 无 CI 服务。
# 为保证三平台代码质量一致，所有推送前在本机跑同一套判据——推上去的代码
# 必然已经通过 GitHub Actions 会跑的那些检查。
#
# 安装： bash scripts/install_git_hooks.sh
# 跳过： git push --no-verify（不推荐）

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

PY="${PYTHON:-python}"
FAILED=0
umask 077
mkdir -p "$ROOT/.tmp" || exit 1
LOG_DIR=$(mktemp -d "$ROOT/.tmp/ww-gate-XXXXXXXX") || exit 1
STEP_NUMBER=0

say() { printf '%s\n' "$*"; }
step() {
  printf '\n=== %s ===\n' "$1"
  shift
  STEP_NUMBER=$((STEP_NUMBER + 1))
  local log_file
  printf -v log_file '%s/step-%03d.log' "$LOG_DIR" "$STEP_NUMBER"
  if "$@" > "$log_file" 2>&1; then
    say "  PASS（日志：$log_file）"
  else
    say "  FAIL（完整日志：$log_file）"
    FAILED=1
  fi
}

module_status() {
  "$PY" - "$1" <<'PYMODULE'
import importlib
import sys

name = sys.argv[1]
try:
    importlib.import_module(name)
except ModuleNotFoundError as exc:
    if exc.name == name or (exc.name or '').startswith(name + '.'):
        print('MODULE_MISSING %s: %s' % (name, exc), file=sys.stderr)
        raise SystemExit(10)
    print('MODULE_IMPORT_ERROR %s: missing transitive module %s: %s' %
          (name, exc.name, exc), file=sys.stderr)
    raise SystemExit(11)
except Exception as exc:
    print('MODULE_IMPORT_ERROR %s: %s: %s' %
          (name, type(exc).__name__, exc), file=sys.stderr)
    raise SystemExit(11)
else:
    print('MODULE_PRESENT %s' % name)
PYMODULE
}

say "推送前门禁：判据与 GitHub Actions 一致（含 500 轮压测 + 打包校验）"
say "仓库：$ROOT"

step "编译全部 Python 源" "$PY" scripts/compile_all.py
step "断言审计（拒绝恒真/恒假/弱断言）" "$PY" scripts/verify_tests.py
step "行为回归（含 MCP stub，非真实 SDK 验证）" "$PY" scripts/run_behavior_regressions.py
step "CLI 通道自检" "$PY" scripts/verify_cli.py
step "面板契约自检" "$PY" scripts/verify_panel.py
step "濒死保护自检" "$PY" scripts/verify_near_death.py
step "规则内核公式对拍（77 个函数的闭式复算）" "$PY" scripts/verify_formulas.py
step "模块分支补测（systems/narrative/cognition/economy）" "$PY" scripts/verify_branches.py
step "长局内存稳定性（三段对照，查泄漏）" "$PY" scripts/verify_memory.py 300
step "世界演化与结算耦合（自演化/相位/心流/道德/术语/正文/台账）" "$PY" scripts/verify_world.py
step "多世界观设定包（四种世界各跑一遍载入与演化）" "$PY" scripts/verify_settings.py
step "数字信源（docs/metrics.json 必须与源码实测一致）" "$PY" scripts/metrics.py --check
step "面板国际化（键唯一/模板无歧义/双语接线）" "$PY" scripts/verify_i18n.py
step "交付面（wg 子命令/doctor/init/资源/控制台/打包守卫）" "$PY" scripts/verify_surface.py
step "文档一致性（版本/工具数/截图引用/演示存档/CHANGELOG）" "$PY" scripts/verify_docs.py
step "玩法层（剧本/事业线/世界书语义）" "$PY" scripts/verify_gameplay.py
step "通用游戏层（判定/档案/上下文/存档库）" "$PY" scripts/verify_generic.py
step "体系与模板（七类体系/八套模板）" "$PY" scripts/verify_systems.py

# 覆盖率门禁：核心域 ≥70%。覆盖率是 CI 的硬判据，本机缺工具时不能算绿。
if "$PY" -c "import coverage" >/dev/null 2>&1; then
  say $'
=== 覆盖率门禁（核心域 ≥70%）==='
  rm -rf "$ROOT/.cov-gate"
  COV_FAIL=0
  for suite in verify_formulas verify_branches verify_cli verify_panel verify_near_death verify_world verify_gameplay verify_generic verify_systems; do
    "$PY" -m coverage run --data-file="$ROOT/.cov-gate" --append       --source=rules,panel,state_schema,settings_loader,sessions "$ROOT/scripts/$suite.py" >"$LOG_DIR/coverage-$suite.log" 2>&1 || { say "  FAIL（日志：$LOG_DIR/coverage-$suite.log）"; COV_FAIL=1; }
  done
  PCT=$("$PY" -m coverage report --data-file="$ROOT/.cov-gate" 2>/dev/null         | awk '/^TOTAL/ {gsub("%","",$NF); print $NF}')
  rm -rf "$ROOT/.cov-gate"
  # 用 Python 比较（bc 在 Git Bash 里通常不存在）
  if [ -n "$PCT" ] && "$PY" -c "import sys; sys.exit(0 if float('$PCT') >= 70 else 1)"; then
    say "  PASS（${PCT}%）"
    # 覆盖率写入唯一数字信源；文档只能引用 docs/metrics.json，不能手写
    "$PY" scripts/metrics.py --write --coverage "$PCT" >"$LOG_DIR/metrics.log" 2>&1 \
      || { say "  FAIL（无法写入 docs/metrics.json，日志：$LOG_DIR/metrics.log）"; FAILED=1; }
  else
    say "  FAIL（覆盖率 ${PCT:-未知}% < 70%）"
    FAILED=1
  fi
  if [ "$COV_FAIL" -ne 0 ]; then
    say "  FAIL（至少一个覆盖率采样套件运行失败，覆盖率数字不完整）"
    FAILED=1
  fi
else
  say $'
=== 覆盖率门禁 ===
  FAIL（未安装 coverage：CI 会跑这项，本机不能跳过）'
  FAILED=1
fi

# MCP 相关：必须先确认 SDK 可导入；缺失或真实导入错误都不能算绿。
MCP_STATUS=0
MCP_OUTPUT=$(module_status mcp 2>&1) || MCP_STATUS=$?
if [ "$MCP_STATUS" -eq 0 ]; then
  say "  $MCP_OUTPUT"
  step "真实 MCP SDK 严格世界回归" env WORLD_GAMES_STRICT=1 "$PY" scripts/verify_world.py
  step "真实 MCP SDK 严格通用游戏回归" env WORLD_GAMES_STRICT=1 "$PY" scripts/verify_generic.py
  step "真实 MCP SDK 严格体系回归" env WORLD_GAMES_STRICT=1 "$PY" scripts/verify_systems.py
  step "审计修复回归" "$PY" scripts/verify_audit_fix.py
  step "MCP 端到端自检" "$PY" scripts/verify_mcp_stdio.py
  step "提示词注入防护（角色卡/世界书 untrusted 标记）" "$PY" scripts/verify_injection.py
  step "玩家视角试玩" "$PY" scripts/user_playtest.py
  step "长局压力测试（500 轮，对齐 CI 的 mcp 作业）" "$PY" scripts/stress_freeplay.py 500
elif [ "$MCP_STATUS" -eq 10 ]; then
  say $'\n=== MCP 作业 ===\n  FAIL（未安装 mcp SDK，相关检查未执行）'
  say '  安装后重跑：python -m pip install -r requirements-mcp.lock.txt && python -m pip install --no-deps -e ".[mcp]"'
  FAILED=1
else
  say $'\n=== MCP 作业 ===\n  FAIL（mcp SDK 导入时发生真实环境错误，相关检查未执行）'
  say "  $MCP_OUTPUT"
  FAILED=1
fi

# 界面巡检：需要 Playwright + 浏览器；装了才跑（未装时跳过但明确提示，不算绿）
if "$PY" -c "import playwright" >/dev/null 2>&1; then
  say $'
=== 界面巡检 ==='
  step "界面巡检执行" "$PY" scripts/smoke_ui.py
else
  say $'
=== 界面巡检 ===
  FAIL（未安装 playwright，界面巡检未执行）'
  FAILED=1
fi

# 真变异测试：把实现改坏，确认测试会红（静态审计之外的唯一硬证据）
step "变异测试（已知错误必须被测试杀死）" "$PY" scripts/verify_mutation.py

# 展示素材：README/Pages 依赖的截图、录屏、演示存档必须存在且可载入
say $'\n=== 展示素材（截图/录屏/演示存档/展示站）==='
if "$PY" - <<'PYGATE'
import json, os, sys
need = ["docs/index.html", "docs/BENCHMARK.md",
        "docs/screenshots/stage-xuanshu.png", "docs/screenshots/stage-ink.png",
        "docs/screenshots/stage-neon.png", "docs/screenshots/stage-neutral.png",
        "docs/screenshots/command-palette.png", "docs/screenshots/character-card.png",
        "docs/screenshots/action-queue.png", "docs/screenshots/walkthrough.mp4",
        "docs/demo/玄枢界.save.json"]
missing = [p for p in need if not os.path.exists(p) or os.path.getsize(p) == 0]
if missing:
    print("缺少展示素材:", missing)
    sys.exit(1)
for w in ("玄枢界", "折剑行", "霓虹深渊", "雾港"):
    d = json.load(open("docs/demo/%s.save.json" % w, encoding="utf-8"))
    assert d["tick"] > 0 and d["entities"]["player"], w
print("展示素材齐全，演示存档可载入")
PYGATE
then
  say "  PASS"
else
  say "  FAIL"
  FAILED=1
fi

# 打包完整性：对齐 CI 的 package 作业（构建 + wheel 资源校验）
# 本机可能无外网 PyPI，构建时不做隔离环境（CI 上有网，用默认隔离即可）
step "构建 sdist + wheel" "$PY" -m build --no-isolation --outdir "$ROOT/.gate-dist"
step "校验 wheel 运行时资源齐全" "$PY" scripts/check_wheel.py "$ROOT/.gate-dist"
rm -rf "$ROOT/.gate-dist"

if [ "$FAILED" -ne 0 ]; then
  say $'\n推送被门禁拦下：请先修复上面的失败项。'
  exit 1
fi
say $'\n门禁全绿，允许推送。'
exit 0
