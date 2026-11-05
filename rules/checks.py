"""
通用判定引擎 (Checks) —— 任何游戏系统的骰子与难度判定

为什么需要：原内核只有一套修真/武侠式的"攻击-防御-伤害"结算。World Games 要
通用于所有游戏（跑团、调查、经营、生存、文字冒险），就必须有一层**与系统无关**
的判定：骰型、属性修正、难度、对抗、成功等级。

支持四种判定模式：
  · add       骰面之和 + 属性 + 修正，与难度比较（d20 / 2d6 / 3d6 通用）
  · roll_under 骰面之和 <= 目标值（百分比系统 / 属性检定）
  · pool      数成功骰（每个 >= success_on 记 1），与难度比较（骰池系统）
  · fate      4dF + 属性，与难度比较（Fate/Fudge）

随机源与 `resolve_combat` 一致：调用方先 `seed_rng(state)`，本模块只用 `random`，
因此同一状态 + 同一行动序列必然复现。判定结果会写进 `state["checks"]`（有界）。
"""

import random

DICE_SPECS = ("d20", "2d6", "3d6", "d100", "4dF", "pool")

MODE_ADD = "add"
MODE_ROLL_UNDER = "roll_under"
MODE_POOL = "pool"
MODE_FATE = "fate"
MODES = (MODE_ADD, MODE_ROLL_UNDER, MODE_POOL, MODE_FATE)

# 默认成功等级：按 margin（总值 - 难度）从高到低匹配第一档
DEFAULT_BANDS = [
    {"min": 10, "key": "critical_success", "label": "大成功"},
    {"min": 0, "key": "success", "label": "成功"},
    {"min": -4, "key": "partial", "label": "部分成功"},
    {"min": -999, "key": "failure", "label": "失败"},
]

CHECKS_KEEP = 200


def parse_dice(spec: str):
    """解析骰型：`2d6+1` / `d20` / `4dF` / `d100` / `pool`。

    返回 (count, sides, modifier)。`sides` 为 "F" 表示 Fudge 骰；
    `pool` 返回 (0, 6, 0)，由调用方用 pool_size 决定骰数。
    """
    text = str(spec or "d20").strip().lower()
    if text == "pool":
        return 0, 6, 0
    if "d" not in text:
        raise ValueError("骰型必须是 NdM 形式（如 2d6 / d20 / 4dF）: %r" % spec)
    left, right = text.split("d", 1)
    count = int(left) if left else 1
    mod = 0
    for sign in ("+", "-"):
        if sign in right:
            right, tail = right.split(sign, 1)
            mod = int(tail) * (1 if sign == "+" else -1)
            break
    if right == "f":
        sides = "F"
    else:
        sides = int(right)
    if count <= 0 or count > 100:
        raise ValueError("骰子数量必须在 1..100: %r" % spec)
    if sides != "F" and not (2 <= sides <= 1000):
        raise ValueError("骰面必须在 2..1000: %r" % spec)
    return count, sides, mod


def roll_dice(spec: str, pool_size: int = 0):
    """掷一次骰，返回 (骰面列表, 合计, 骰型说明)。不写状态。"""
    count, sides, mod = parse_dice(spec)
    if sides == "F":
        rolls = [random.randint(-1, 1) for _ in range(count)]
        return rolls, sum(rolls) + mod, spec
    if count == 0 and str(spec).lower() == "pool":
        n = max(1, min(100, int(pool_size or 1)))
        rolls = [random.randint(1, 6) for _ in range(n)]
        return rolls, sum(rolls), "pool(%d d6)" % n
    rolls = [random.randint(1, sides) for _ in range(count)]
    return rolls, sum(rolls) + mod, spec


def level_for(margin: int, bands=None, natural_max=False, natural_min=False):
    """按 margin 取成功等级；单骰自然极值可上/下调一档（由调用方决定是否启用）。"""
    table = bands or DEFAULT_BANDS
    ordered = sorted(table, key=lambda b: int(b.get("min", 0)), reverse=True)
    idx = len(ordered) - 1
    for i, band in enumerate(ordered):
        if margin >= int(band.get("min", 0)):
            idx = i
            break
    if natural_max and idx > 0:
        idx -= 1
    if natural_min and idx < len(ordered) - 1:
        idx += 1
    band = ordered[idx]
    return {"key": band.get("key", "success"), "label": band.get("label", band.get("key", ""))}


def _attr_modifier(actor: dict, attribute: str, default: int = 0, profile=None) -> int:
    """属性修正：实体 attrs → 实体 sheet → 游戏档案 attributes（按 key 或 label 匹配）。

    游戏档案里定义的自定义属性（如 `{key:"per", label:"感知"}`）必须能直接用于判定，
    否则 `game_profile` 只是面板装饰——这是通用层最容易犯的"配了但不生效"错误。
    """
    if attribute in ("", None):
        return 0
    actor = actor or {}
    attrs = actor.get("attrs") or {}
    if attribute in attrs:
        value = attrs[attribute]
    elif attribute in (actor.get("sheet") or {}):
        value = actor["sheet"][attribute]
    else:
        value = default
        for item in (profile or {}).get("attributes") or []:
            if attribute in (item.get("key"), item.get("label")):
                value = item.get("value", default)
                break
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def resolve_check(state: dict, actor_id: str, attribute: str = "", difficulty: int = 10,
                  dice: str = "d20", mode: str = MODE_ADD, modifiers: list | None = None,
                  opposed_by: str = "", pool_size: int = 0, reason: str = "",
                  bands=None, record: bool = True) -> dict:
    """执行一次通用判定并（可选）写入 state["checks"]。

    modifiers 可传 `[{"value": 2, "label": "地形优势"}, ...]` 或直接 `[2, -1]`。
    对抗判定时 `opposed_by` 为对方 entity id，用同一骰型与属性再掷一次。
    """
    mode = mode if mode in MODES else MODE_ADD
    actor = (state.get("entities") or {}).get(actor_id) or {}
    if not actor and actor_id not in ("", None):
        raise ValueError("实体不存在: %s" % actor_id)

    mod_list = []
    for item in modifiers or []:
        if isinstance(item, dict):
            try:
                mod_list.append({"value": int(item.get("value", 0)),
                                 "label": str(item.get("label", ""))})
            except (TypeError, ValueError):
                continue
        else:
            try:
                mod_list.append({"value": int(item), "label": ""})
            except (TypeError, ValueError):
                continue
    mod_total = sum(m["value"] for m in mod_list
                    if mode != MODE_POOL or m.get("label") != "success_on")
    profile = state.get("game") if isinstance(state.get("game"), dict) else None
    attr_mod = _attr_modifier(actor, attribute, profile=profile)
    try:
        difficulty = int(difficulty)
    except (TypeError, ValueError):
        raise ValueError("difficulty 必须是整数")

    rolls, rolled, spec = roll_dice(dice, pool_size=pool_size)
    count, sides, _mod = parse_dice(dice)

    if mode == MODE_POOL:
        success_on = 5
        for m in mod_list:
            if m.get("label") == "success_on":
                success_on = max(2, min(6, m["value"]))
        successes = sum(1 for r in rolls if r >= success_on)
        total = successes + attr_mod + mod_total
        margin = total - difficulty
        natural_max = bool(rolls) and all(r == 6 for r in rolls)
        natural_min = bool(rolls) and all(r == 1 for r in rolls)
    elif mode == MODE_ROLL_UNDER:
        total = rolled + attr_mod + mod_total
        margin = difficulty - total
        natural_max = sides != "F" and bool(rolls) and len(rolls) == 1 and rolls[0] == 1
        natural_min = sides != "F" and bool(rolls) and len(rolls) == 1 and rolls[0] == sides
    elif mode == MODE_FATE:
        total = rolled + attr_mod + mod_total
        margin = total - difficulty
        natural_max = bool(rolls) and all(r == 1 for r in rolls)
        natural_min = bool(rolls) and all(r == -1 for r in rolls)
    else:
        total = rolled + attr_mod + mod_total
        margin = total - difficulty
        natural_max = sides != "F" and bool(rolls) and len(rolls) == 1 and rolls[0] == sides
        natural_min = sides != "F" and bool(rolls) and len(rolls) == 1 and rolls[0] == 1

    level = level_for(margin, bands, natural_max=natural_max, natural_min=natural_min)

    result = {
        "actor": actor_id,
        "attribute": attribute,
        "dice": spec,
        "rolls": rolls,
        "raw": rolled,
        "attr_mod": attr_mod,
        "modifiers": mod_list,
        "mod_total": mod_total,
        "total": total,
        "difficulty": difficulty,
        "margin": margin,
        "mode": mode,
        "level": level["key"],
        "level_label": level["label"],
        "natural_max": natural_max,
        "natural_min": natural_min,
        "reason": str(reason or ""),
        "tick": int(state.get("tick", 0) or 0),
    }

    if opposed_by:
        opponent = (state.get("entities") or {}).get(opposed_by) or {}
        if not opponent:
            raise ValueError("对抗方不存在: %s" % opposed_by)
        o_rolls, o_rolled, o_spec = roll_dice(dice, pool_size=pool_size)
        o_attr = _attr_modifier(opponent, attribute, profile=profile)
        if mode == MODE_POOL:
            o_total = sum(1 for r in o_rolls if r >= success_on) + o_attr
        else:
            o_total = o_rolled + o_attr
        result["opposed"] = {
            "actor": opposed_by, "rolls": o_rolls, "raw": o_rolled,
            "attr_mod": o_attr, "total": o_total,
        }
        result["margin"] = total - o_total
        result["difficulty"] = o_total
        result["level"] = level_for(result["margin"], bands)["key"]
        result["level_label"] = level_for(result["margin"], bands)["label"]

    if record:
        log = state.setdefault("checks", [])
        log.append(result)
        cap = int((state.get("config") or {}).get("checks_keep", CHECKS_KEEP) or CHECKS_KEEP)
        cap = max(10, cap)
        if len(log) > cap:
            del log[:len(log) - cap]
    return result


def summary(state: dict, limit: int = 12) -> list:
    """最近判定（面板用）：只保留展示需要的字段，倒序。"""
    rows = state.get("checks") or []
    out = []
    for r in rows[-max(1, int(limit)):][::-1]:
        out.append({
            "tick": int(r.get("tick", 0) or 0),
            "actor": r.get("actor", ""),
            "attribute": r.get("attribute", ""),
            "dice": r.get("dice", ""),
            "total": r.get("total", 0),
            "difficulty": r.get("difficulty", 0),
            "margin": r.get("margin", 0),
            "level": r.get("level", ""),
            "level_label": r.get("level_label", ""),
            "reason": str(r.get("reason", ""))[:80],
        })
    return out


def win_rate(state: dict, limit: int = 20) -> dict:
    """最近判定的成功率（面板与宿主判断节奏用）。"""
    rows = (state.get("checks") or [])[-max(1, int(limit)):]
    if not rows:
        return {"total": 0, "success": 0, "rate": 0.0}
    success = sum(1 for r in rows if r.get("level") in ("success", "critical_success"))
    return {"total": len(rows), "success": success, "rate": round(success / len(rows), 3)}
