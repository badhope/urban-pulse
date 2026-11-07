#!/bin/bash
# 万界 · 行者 — 快速启动脚本
# ./play.sh           运行所有命令演示
# ./play.sh --state F  指定状态文件 (默认 game_state.json)

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE="$ROOT/engine.py"
INIT="$ROOT/init_game.py"
STATE="game_state.json"
STATE_EXPLICIT=0
ARGS=()

# 参数解析：支持 `./play.sh combat`、`./play.sh combat --state F`、
# `./play.sh --state F combat` 三种写法。
while [ $# -gt 0 ]; do
  case "$1" in
    --state)
      if [ $# -lt 2 ]; then
        echo "--state 需要文件路径" >&2
        exit 2
      fi
      STATE="$2"
      STATE_EXPLICIT=1
      shift 2
      ;;
    --state=*)
      STATE="${1#--state=}"
      STATE_EXPLICIT=1
      shift
      ;;
    *)
      ARGS+=("$1")
      shift
      ;;
  esac
done

CMD="${ARGS[0]:-}"
CMD_ARGS=("${ARGS[@]:1}")
PY=python3
command -v python3 >/dev/null 2>&1 || PY=python

if [ "$CMD" = "init" ]; then
  if [ "$STATE_EXPLICIT" -eq 1 ]; then
    exec "$PY" "$INIT" "$STATE"
  fi
  exec "$PY" "$INIT"
fi

if [ ! -f "$STATE" ]; then
  echo "状态文件不存在: $STATE（先跑 ./play.sh init 生成）" >&2
  exit 1
fi

TICK=$("$PY" - "$STATE" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as state_file:
    print(json.load(state_file).get("tick", 0))
PY
)
if [ "$?" -ne 0 ]; then
  echo "状态文件无法读取: $STATE" >&2
  exit 1
fi

echo "=== 万界 · 行者 | 第 $TICK 回合 ==="
echo ""

case "$CMD" in
  combat)
    "$PY" "$ENGINE" combat --state "$STATE" --attacker "${CMD_ARGS[0]:-player}" --defender "${CMD_ARGS[1]:-goblin}"
    ;;
  trade)
    "$PY" "$ENGINE" trade --state "$STATE" --location "${CMD_ARGS[0]:-bamboo_tea_booth}" --item "${CMD_ARGS[1]:-an_zhen_san}" --quantity "${CMD_ARGS[2]:-1}" --direction "${CMD_ARGS[3]:-buy}" --entity "${CMD_ARGS[4]:-player}"
    ;;
  social)
    "$PY" "$ENGINE" social --state "$STATE" --actor "${CMD_ARGS[0]:-player}" --target "${CMD_ARGS[1]:-old_chen}" --event "${CMD_ARGS[2]:-help}"
    ;;
  karma)
    "$PY" "$ENGINE" karma --state "$STATE" --actor "${CMD_ARGS[0]:-player}" --karma_type "${CMD_ARGS[1]:-help_innocent}"
    ;;
  tick)
    "$PY" "$ENGINE" tick --state "$STATE"
    ;;
  world)
    "$PY" "$ENGINE" world_state --state "$STATE"
    ;;
  narrative)
    "$PY" "$ENGINE" narrative --state "$STATE"
    ;;
  flow)
    "$PY" "$ENGINE" flow --state "$STATE"
    ;;
  panarchy)
    "$PY" "$ENGINE" panarchy --state "$STATE"
    ;;
  identity)
    "$PY" "$ENGINE" identity --state "$STATE"
    ;;
  moral)
    "$PY" "$ENGINE" moral_update --state "$STATE"
    ;;
  cognition)
    "$PY" "$ENGINE" cognition --state "$STATE" --entity "${CMD_ARGS[0]:-player}"
    ;;
  merit)
    "$PY" "$ENGINE" merit --state "$STATE" --aid "${CMD_ARGS[0]:-1.0}" --sincerity "${CMD_ARGS[1]:-1.0}"
    ;;
  info)
    "$PY" "$ENGINE" info_weight --state "$STATE" --probability "${CMD_ARGS[0]:-0.1}"
    ;;
  *)
    echo "用法: ./play.sh <command> [--state FILE] [args]"
    echo ""
    echo "可用命令:"
    echo "  combat    trade    social    karma     tick"
    echo "  world     narrative  flow    panarchy  identity"
    echo "  moral     cognition  merit   info      init"
    ;;
esac
