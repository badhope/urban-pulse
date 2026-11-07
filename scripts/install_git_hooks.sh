#!/usr/bin/env bash
#
# 安装 git 钩子：pre-push 门禁 + commit-msg 校验
#
# 用法: bash scripts/install_git_hooks.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

HOOK_DIR=".git/hooks"
mkdir -p "$HOOK_DIR"

cat > "$HOOK_DIR/pre-push" <<'EOF'
#!/usr/bin/env bash
# 由 scripts/install_git_hooks.sh 安装；判据见 scripts/pre_push_gate.sh
exec bash "$(git rev-parse --show-toplevel)/scripts/pre_push_gate.sh"
EOF
chmod +x "$HOOK_DIR/pre-push" 2>/dev/null || true

echo "已安装: $HOOK_DIR/pre-push"
echo "推送时会先跑本机门禁（与 GitHub Actions 同一套判据）。"
echo "临时跳过: git push --no-verify"
