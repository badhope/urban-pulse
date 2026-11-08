#!/usr/bin/env python3
"""
演示存档生成器 (make_demo.py)

为 README / 文档 / 视频生成**真实**演示存档：不是手写 JSON，而是把设定包载入引擎，
按一套确定性的玩家脚本真跑 N 回合（战斗 / 交易 / 社交 / 因果 / 移动 / 突破 / 摘要），
最后由引擎状态反推叙事正文写进 `prose`，面板主舞台显示的因此是这一局真实发生的事。

为什么单独一个脚本：
  · README 与截图需要"长局真实存档"，而 stress_freeplay 用完就删临时目录；
  · 手写 demo_state.json 无法体现新系统（势力/相位/道德/术语）；
  · 演示必须可复现——同一 seed 每次生成同一份存档（逐字节一致），
    这样"截图对应哪个存档"是可核对的，而不是拍脑袋。

用法:
    python scripts/make_demo.py                 # 生成全部四套世界
    python scripts/make_demo.py --only 玄枢界 --turns 500
产出:
    docs/demo/<世界>.save.json        演示存档（随仓库分发）
    docs/demo/README.md               存档说明（自动生成）
"""

import argparse
import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if "game_engine" not in sys.modules:
    import importlib.util

    _spec = importlib.util.spec_from_file_location(
        "game_engine", os.path.join(ROOT, "__init__.py"),
        submodule_search_locations=[ROOT])
    _pkg = importlib.util.module_from_spec(_spec)
    _pkg.__path__ = [ROOT]
    sys.modules["game_engine"] = _pkg
    _spec.loader.exec_module(_pkg)

import mcp_server as MS  # noqa: E402
from game_engine.state_schema import load_state, save_state, log_event  # noqa: E402
from game_engine.rules import questline as quest_rules  # noqa: E402
from game_engine.rules.world_evolution import evolve  # noqa: E402

OUT_DIR = os.path.join(ROOT, "docs", "demo")
SETTINGS_DIR = os.path.join(ROOT, "settings")

# 每个世界一套玩家脚本：不同的"性格"，让演示存档不是同一条轨迹
PERSONAS = {
    "玄枢界": {"travel": ["听霄城", "南屏药谷", "旧枢台废墟", "渡口", "临川城"],
               "social": ["pei_wujiu", "shi_sanniang", "shen_chongshan", "liu_hanyi"],
               "prey": ["qin_xiao", "han_ya_ke"], "buy": ["ningyuan_dan", "liaoshang_san"]},
    "折剑行": {"travel": ["栖霞镇", "断碑崖", "听雨楼", "洛水帮", "洛水渡"],
               "social": ["lao_shegong", "ning_sanniang", "qi_shou"],
               "prey": ["shen_bie"], "buy": ["jinchuang_yao", "du_jiu"]},
    "霓虹深渊": {"travel": ["白鲸诊所", "网域", "灰鼠帮地盘", "上层穹顶", "第9区"],
                 "social": ["dr_bai", "echo", "mu_laoban"],
                 "prey": ["kui"], "buy": ["trauma_patch", "coolant"]},
    "雾港": {"travel": ["雾港码头", "灯塔", "雾港教堂", "沉船湾", "永昌号"],
             "social": ["captain_zhou", "miss_lin", "inspector_gu"],
             "prey": ["old_shen"], "buy": ["bandage", "film"]},
}

# 叙事正文模板：**只陈述引擎已经算出来的事实**（地点/在场者/最近事件），
# 不做新的裁定。演示存档要的是"面板上有真实正文"，不是让脚本替 Agent 编故事。
PROSE_TPL = "{loc}{company}{focus}{tail}"


def _entities_here(state, loc):
    return [e.get("name", "") for k, e in (state.get("entities") or {}).items()
            if k != "player" and e.get("location") == loc and int(e.get("hp", 1) or 0) > 0]


def _recent_events(state, n=3):
    evs = [e for e in (state.get("event_log") or []) if e.get("type") != "tick"]
    return [str(e.get("desc", "")) for e in evs[-n:]]


def compose_prose(state, world_name, places=None):
    """用真实的当前状态写一段演示正文（只描述已发生的事）。

    places 必须传**设定包里的原始地点描写**：状态里的 `places` 会被 publish_prose
    回写成上一段正文，拿它当输入会让正文自我复制（实测 5 段之后场景卡里叠了 5 个
    "第N回合"，越写越长）。
    """
    loc = (state.get("entities", {}).get("player") or {}).get("location", "")
    here = _entities_here(state, loc)
    places = places or {}
    desc = str((places.get(loc) or {}).get("desc") or "")
    if not desc:
        desc = str((state.get("world_info") or {}).get("location_desc") or "")
    company = ("在场的是" + "、".join(here[:3]) + "。") if here else "此刻只有你一个人。"
    recent = _recent_events(state, 2)
    focus = ("刚才发生的事还压在心上：" + "；".join(recent) + "。") if recent else ""
    pan = (state.get("panarchy") or {}).get("phase")
    tail = ""
    if pan:
        tail = " 世界的相位落在「%s」——这种时候，任何小事都可能被放大。" % pan
    return PROSE_TPL.format(tick=state.get("tick", 0), loc=desc, company=company,
                            focus=focus, tail=tail)


def play_one(bundle_name, turns, seed, out_path):
    bundle_path = os.path.join(SETTINGS_DIR, bundle_name + ".setting.json")
    with open(bundle_path, encoding="utf-8") as f:
        bundle = json.load(f)
    persona = PERSONAS.get(bundle_name) or {"travel": [], "social": [], "prey": [], "buy": []}

    MS.load_setting(path=bundle_path, state_path=out_path, seed=seed)
    state = load_state(out_path)
    rng = random.Random(seed)
    player = state["entities"]["player"]
    locs = [l for l in (bundle.get("places") or {}) if l]
    if not locs:
        locs = list(state.get("market") or {})

    for t in range(1, turns + 1):
        state = load_state(out_path)
        player = state["entities"]["player"]
        loc = player.get("location", "")

        # 每 7 回合换一个地方；每 5 回合找人说句话；其余回合按"性格"做买卖或切磋
        if t % 7 == 0 and locs:
            dest = locs[(t // 7) % len(locs)]
            MS.travel(dest, note="沿途留意了路边的动静")
        elif t % 5 == 0 and persona["social"]:
            target = persona["social"][(t // 5) % len(persona["social"])]
            if target in state.get("entities", {}):
                # 真实玩家不会只做好人：善意/冒犯交替，亲密度才不会一路顶到 100 上限
                MS.social("player", target, rng.choice(
                    ["help", "gift", "praise", "cooperate", "insult", "threaten"]))
        elif t % 11 == 0 and state.get("market", {}).get(loc):
            items = list(state["market"][loc])
            if items:
                key = items[t % len(items)]
                MS.trade(loc, key, "buy", 1)
        elif t % 17 == 0 and persona["prey"]:
            target = persona["prey"][(t // 17) % len(persona["prey"])]
            ent = state.get("entities", {}).get(target)
            if ent and ent.get("location") == loc and int(ent.get("hp", 1) or 0) > 0:
                MS.combat("player", target, rng.choice(["attack", "heavy"]))

        # 回合推进：市场 + 世界演化（与 tick 工具同一套语义）
        state = load_state(out_path)
        MS._seed_rng(state)
        MS.tick_market(state)
        state["tick"] = state.get("tick", 0) + 1
        for e in evolve(state).get("events", []):
            log_event(state, "world", str(e))
        # 事业线也要推进——否则演示存档里「事业线」卡永远是"还没到浮现的时候"，
        # 截图与真实 tick 行为不一致（实测踩到）。
        for ch in quest_rules.advance(state, state.get("questlines") or [],
                                      tick=int(state["tick"])):
            if ch.get("change") == "stage":
                log_event(state, "quest", "事业线「%s」推进到：%s"
                              % (ch.get("quest"), ch.get("title")),
                              quest=ch.get("quest"), stage=ch.get("stage"))
            elif ch.get("change") == "done":
                log_event(state, "quest", "事业线「%s」完成" % ch.get("quest"),
                             quest=ch.get("quest"))
        log_event(state, "tick", "回合%d结束" % state["tick"])
        save_state(state, out_path)

        if t % 25 == 0:
            MS.write_summary("第 %d 回合：%s。%s" % (
                t, (load_state(out_path)["entities"]["player"].get("location", "")),
                "；".join(_recent_events(load_state(out_path), 3))[:180]))

        # 每 30 回合写一段正文：面板主舞台展示的即这一段
        if t % 30 == 0:
            MS.publish_prose(compose_prose(load_state(out_path), bundle_name, bundle.get("places") or {}))
        # 每 60 回合尝试一次突破（走引擎判定，失败会反噬）
        if t % 60 == 0:
            tiers = (load_state(out_path).get("config") or {}).get("level_tiers") or []
            cur = load_state(out_path)["entities"]["player"].get("level", "")
            if tiers:
                idx = next((i for i, x in enumerate(tiers) if str(cur).startswith(x)), 0)
                nxt = tiers[min(len(tiers) - 1, idx + 1)]
                try:
                    MS.advance(nxt, insight=0.55 + 0.3 * ((t // 60) % 2))
                except ValueError:
                    pass

    # 收尾：回到世界的"枢纽"（开局地点），让演示存档的最后画面里有在场人物与关系网，
    # 而不是停在一个只有主角的荒地里——README 的首图要能展示面板的完整信息密度。
    state = load_state(out_path)
    hub = ((bundle.get("player") or {}).get("location")
           or ((state.get("world_info") or {}).get("location_desc") and "")
           or locs[0] if locs else "")
    if hub:
        MS.travel(hub, note="回到城里，把这一路的事记下来")
    MS.publish_prose(compose_prose(load_state(out_path), bundle_name, bundle.get("places") or {}))
    return load_state(out_path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--turns", type=int, default=0)
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    bundles = sorted(f[:-len(".setting.json")] for f in os.listdir(SETTINGS_DIR)
                     if f.endswith(".setting.json"))
    plan = {"玄枢界": 500, "折剑行": 180, "霓虹深渊": 180, "雾港": 180}
    rows = []
    for name in bundles:
        if args.only and args.only != name:
            continue
        turns = args.turns or plan.get(name, 120)
        seed = 20261014 + sum(ord(c) for c in name) % 1000
        out_path = os.path.join(OUT_DIR, name + ".save.json")
        state = play_one(name, turns, seed, out_path)
        player = state["entities"]["player"]
        rows.append({
            "world": name, "file": os.path.basename(out_path), "turns": turns,
            "seed": seed, "player": player.get("name"), "level": player.get("level"),
            "location": player.get("location"), "gold": player.get("gold"),
            "factions": len(state.get("factions") or {}),
            "phase": (state.get("panarchy") or {}).get("phase"),
            "milestones": len(state.get("milestones") or []),
            "summaries": len(state.get("summaries") or []),
            "prose": len(state.get("prose") or []),
            "size": os.path.getsize(out_path),
        })
        print("%-8s %4d 回合 · %-4s · %-6s · %s · %d 势力 · 相位 %s · %.0f KB"
              % (name, turns, player.get("name"), player.get("level"),
                 player.get("location"), len(state.get("factions") or {}),
                 (state.get("panarchy") or {}).get("phase", "?"),
                 os.path.getsize(out_path) / 1024))

    # 说明文件（自动生成，避免手写清单与产物漂移）
    lines = ["# 演示存档（docs/demo）", "",
             "本目录的 `.save.json` 是 `scripts/make_demo.py` 生成的**真实对局存档**：",
             "设定包载入引擎后按确定性玩家脚本真跑 N 回合，包含真实的世界演化、",
             "因果台账、大事记、章节摘要与叙事正文。README 里的截图与视频都基于这些存档。", "",
             "| 世界 | 存档 | 回合 | 主角 | 等级 | 所在地 | 势力 | 相位 | 文件大小 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append("| %s | `%s` | %d | %s | %s | %s | %d | %s | %.0f KB |"
                     % (r["world"], r["file"], r["turns"], r["player"], r["level"],
                        r["location"], r["factions"], r["phase"], r["size"] / 1024))
    lines += ["", "重新生成：", "", "```bash", "python scripts/make_demo.py",
              "python scripts/audit_ui.py --state docs/demo/<世界>.save.json   # 截图", "```", "",
              "同一 seed 生成同一份存档（逐字节一致），因此截图与存档可以互相对照。", ""]
    with open(os.path.join(OUT_DIR, "README.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    # 只发布"演示需要"的文件：状态 + 侧写（图表数据源）。
    # .bak / .inbox / .log 是运行时产物，不该进仓库，也不该被当成演示素材。
    for fn in os.listdir(OUT_DIR):
        if fn.endswith((".bak", ".inbox.jsonl", ".log.jsonl")):
            try:
                os.remove(os.path.join(OUT_DIR, fn))
            except OSError:
                pass
    print("\n写出 %d 份演示存档到 %s" % (len(rows), OUT_DIR))
    return 0


if __name__ == "__main__":
    sys.exit(main())
