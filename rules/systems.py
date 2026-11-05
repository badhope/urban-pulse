"""
通用子系统 (Systems) —— 数据驱动的可插拔规则模块

为什么需要：v1.2 的通用层解决了"任何题材都能结算一次判定"，但每种游戏真正需要的
是一整套**体系**：时间怎么走、掉落怎么算、制造怎么成、声望怎么涨、成就怎么解、
等级怎么长。把这些写死在引擎里，就永远只能做一种游戏。

这一层把六类体系做成**声明式配置 + 统一运行时**：

  time          日历/时段/季节/天气，按分钟推进
  loot          加权掉落表，按 (seed, tick, table, index) 确定性派生
  craft         配方 + 材料校验 + 技能判定 → 产出
  reputation    势力声望轨道（-100..100，分档）
  achievement   成就条件（复用 questline 谓词语言）与奖励
  progression   XP 曲线 / 等级 / 每级属性成长
  custom        自定义动作：受限效果列表（资源/属性/进度轨/标签/事实/声望）

设计约束与其他 rules 一致：
  · 纯标准库、不读写文件、不依赖墙钟与全局随机；
  · 所有运行时结构有界（历史/日志/成就条数）；
  · 定义走 `state["systems"]["defs"]`，运行态走 `state["systems"]["rt"]`，
    因此快照回退会连体系状态一起回退（INV-E4）。
"""

import hashlib
import math

MAX_DEFS = 40
MAX_HISTORY = 100
MAX_ACHIEVEMENTS = 200
MAX_LOOT_ENTRIES = 60
MAX_RECIPES = 80
MAX_FACTIONS = 40
MAX_CUSTOM_EFFECTS = 12

KIND_TIME = "time"
KIND_LOOT = "loot"
KIND_CRAFT = "craft"
KIND_REPUTATION = "reputation"
KIND_ACHIEVEMENT = "achievement"
KIND_PROGRESSION = "progression"
KIND_CUSTOM = "custom"

KINDS = (KIND_TIME, KIND_LOOT, KIND_CRAFT, KIND_REPUTATION,
         KIND_ACHIEVEMENT, KIND_PROGRESSION, KIND_CUSTOM)

KIND_LABELS = {
    KIND_TIME: "时间体系", KIND_LOOT: "掉落体系", KIND_CRAFT: "制造体系",
    KIND_REPUTATION: "声望体系", KIND_ACHIEVEMENT: "成就体系",
    KIND_PROGRESSION: "成长体系", KIND_CUSTOM: "自定义体系",
}

DEFAULT_SEASONS = ("春", "夏", "秋", "冬")
DEFAULT_WEATHERS = (
    {"name": "晴", "weight": 40},
    {"name": "阴", "weight": 25},
    {"name": "雨", "weight": 20},
    {"name": "雾", "weight": 10},
    {"name": "storm", "weight": 5},
)


# ────────────────────────────── 小工具 ──────────────────────────────

def _int(value, default=0, lo=None, hi=None):
    try:
        if isinstance(value, bool):
            out = int(value)
        elif isinstance(value, float):
            if value != value or value in (float("inf"), float("-inf")):
                return default
            out = int(value)
        else:
            out = int(value)
    except (TypeError, ValueError):
        return default
    if lo is not None:
        out = max(lo, out)
    if hi is not None:
        out = min(hi, out)
    return out


def _num(value, default=0.0):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if out != out or out in (float("inf"), float("-inf")):
        return default
    return out


def _text(value, limit=200):
    return str(value or "").strip()[:limit]


def _unit(seed, tick, *parts):
    """由 (seed, tick, parts) 派生的 [0,1) 伪随机量：确定性、不消耗 rng_counter。"""
    raw = "|".join([str(seed or 0), str(tick or 0)] + [str(p) for p in parts]).encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big") / float(1 << 64)


def _systems(state: dict) -> dict:
    box = state.setdefault("systems", {})
    if not isinstance(box, dict):
        box = {}
        state["systems"] = box
    box.setdefault("defs", {})
    box.setdefault("rt", {})
    if not isinstance(box["defs"], dict):
        box["defs"] = {}
    if not isinstance(box["rt"], dict):
        box["rt"] = {}
    return box


# ────────────────────────────── 规范化 ──────────────────────────────

def _norm_time_config(raw):
    cfg = raw if isinstance(raw, dict) else {}
    start = cfg.get("start") if isinstance(cfg.get("start"), dict) else {}
    raw_seasons = cfg.get("seasons")
    if not isinstance(raw_seasons, list):
        raw_seasons = []
    seasons = [str(s) for s in (raw_seasons or DEFAULT_SEASONS)][:12]
    weathers = []
    raw_weathers = cfg.get("weathers")
    if not isinstance(raw_weathers, list):
        raw_weathers = []
    for w in (raw_weathers or DEFAULT_WEATHERS)[:20]:
        if isinstance(w, dict) and w.get("name"):
            weathers.append({"name": _text(w["name"], 12),
                             "weight": max(1, _int(w.get("weight"), 20, 1, 1000))})
    if not weathers:
        weathers = [dict(x) for x in DEFAULT_WEATHERS]
    return {
        "start": {
            "day": _int(start.get("day"), 1, 1, 99999),
            "hour": _int(start.get("hour"), 8, 0, 23),
            "minute": _int(start.get("minute"), 0, 0, 59),
            "season": _text(start.get("season"), 12) or seasons[0],
            "weather": _text(start.get("weather"), 12) or weathers[0]["name"],
        },
        "seasons": seasons or list(DEFAULT_SEASONS),
        "days_per_season": _int(cfg.get("days_per_season"), 30, 1, 999),
        "weathers": weathers,
        "log_cap": _int(cfg.get("log_cap"), MAX_HISTORY, 10, MAX_HISTORY),
    }


def _norm_loot_config(raw):
    cfg = raw if isinstance(raw, dict) else {}
    tables = {}
    src = cfg.get("tables") if isinstance(cfg.get("tables"), dict) else {}
    for name, table in list(src.items())[:20]:
        if not isinstance(table, dict):
            continue
        entries = []
        for e in (table.get("entries") or [])[:MAX_LOOT_ENTRIES]:
            if not isinstance(e, dict) or not _text(e.get("item")):
                continue
            qty = e.get("qty") if isinstance(e.get("qty"), (list, tuple)) else [1, 1]
            entries.append({
                "item": _text(e.get("item"), 40),
                "name": _text(e.get("name"), 40) or _text(e.get("item"), 40),
                "weight": max(1, _int(e.get("weight"), 10, 1, 10000)),
                "qty_min": max(1, _int(qty[0] if qty else 1, 1, 1, 999)),
                "qty_max": max(1, _int(qty[1] if len(qty) > 1 else 1, 1, 1, 999)),
            })
        tables[_text(name, 40)] = {
            "rolls": _int(table.get("rolls"), 1, 1, 20),
            "empty_weight": _int(table.get("empty_weight"), 0, 0, 10000),
            "entries": entries,
        }
    return {"tables": tables}


def _norm_craft_config(raw):
    cfg = raw if isinstance(raw, dict) else {}
    recipes = []
    for r in (cfg.get("recipes") or [])[:MAX_RECIPES]:
        if not isinstance(r, dict) or not _text(r.get("id")):
            continue
        inputs = {}
        for k, v in (r.get("inputs") or {}).items():
            qty = _int(v, 1, 1, 999)
            if _text(k):
                inputs[_text(k, 40)] = qty
        out = r.get("output") if isinstance(r.get("output"), dict) else {}
        if not inputs or not _text(out.get("item")):
            continue
        recipes.append({
            "id": _text(r["id"], 40),
            "name": _text(r.get("name"), 40) or _text(r["id"], 40),
            "inputs": inputs,
            "output": {"item": _text(out.get("item"), 40),
                       "name": _text(out.get("name"), 40) or _text(out.get("item"), 40),
                       "qty": _int(out.get("qty"), 1, 1, 99)},
            "difficulty": _int(r.get("difficulty"), 10, 0, 100),
            "attribute": _text(r.get("attribute"), 20),
            "fail_consume": _num(r.get("fail_consume"), 0.5),
        })
    return {"recipes": recipes}


def _norm_reputation_config(raw):
    cfg = raw if isinstance(raw, dict) else {}
    tiers = []
    for t in (cfg.get("tiers") or [])[:12]:
        if isinstance(t, dict):
            tiers.append({"min": _int(t.get("min"), -100, -1000, 1000),
                          "label": _text(t.get("label"), 20) or "中立"})
    if not tiers:
        tiers = [{"min": -1000, "label": "敌对"}, {"min": -40, "label": "冷淡"},
                 {"min": 0, "label": "中立"}, {"min": 40, "label": "友好"},
                 {"min": 80, "label": "敬重"}]
    tiers.sort(key=lambda t: t["min"])
    factions = []
    for f in (cfg.get("factions") or [])[:MAX_FACTIONS]:
        if isinstance(f, str):
            factions.append({"name": _text(f, 30), "start": 0})
        elif isinstance(f, dict) and _text(f.get("name")):
            factions.append({"name": _text(f["name"], 30),
                             "start": _int(f.get("start"), 0, -100, 100)})
    return {"tiers": tiers, "factions": factions, "default": _int(cfg.get("default"), 0, -100, 100)}


def _norm_achievement_config(raw):
    cfg = raw if isinstance(raw, dict) else {}
    items = []
    for a in (cfg.get("items") or [])[:MAX_ACHIEVEMENTS]:
        if not isinstance(a, dict) or not _text(a.get("id")):
            continue
        cond = a.get("condition") if isinstance(a.get("condition"), dict) else {"flag": "__never__"}
        reward = a.get("reward") if isinstance(a.get("reward"), dict) else {}
        items.append({
            "id": _text(a["id"], 40),
            "name": _text(a.get("name"), 40) or _text(a["id"], 40),
            "desc": _text(a.get("desc"), 160),
            "condition": cond,
            "gold": _int(reward.get("gold"), 0, 0, 100000),
            "flags": [str(x)[:40] for x in (reward.get("flags") or [])][:8],
            "xp": _int(reward.get("xp"), 0, 0, 100000),
        })
    return {"items": items}


def _norm_progression_config(raw):
    cfg = raw if isinstance(raw, dict) else {}
    growth = _num(cfg.get("growth"), 1.25)
    return {
        "base_xp": _int(cfg.get("base_xp"), 100, 1, 1000000),
        "growth": min(3.0, max(1.0, growth)),
        "max_level": _int(cfg.get("max_level"), 20, 1, 999),
        "per_level": {k: _int(v, 0, 0, 100) for k, v in (cfg.get("per_level") or {}).items()
                      if _text(k) and isinstance(v, (int, float))},
        "level_label": _text(cfg.get("level_label"), 20) or "等级",
    }


EFFECT_OPS = ("resource", "attribute", "meter", "flag", "fact",
              "reputation", "xp", "advance_time", "loot")


def _norm_custom_config(raw):
    cfg = raw if isinstance(raw, dict) else {}
    actions = {}
    raw_actions = cfg.get("actions")
    if not isinstance(raw_actions, dict):
        raw_actions = {}
    for name, spec in list(raw_actions.items())[:20]:
        if not isinstance(spec, dict):
            continue
        effects = []
        raw_effects = spec.get("effects")
        if not isinstance(raw_effects, list):
            raw_effects = []
        for e in raw_effects[:MAX_CUSTOM_EFFECTS]:
            if not isinstance(e, dict):
                continue
            op = _text(e.get("op"), 20).lower()
            if not op:
                continue
            if op not in EFFECT_OPS:
                # 定义期就拒绝：白名单外的 op 绝不允许进入运行时
                raise ValueError("自定义体系的未知效果 op=%r（可用: %s）"
                                 % (op, " / ".join(EFFECT_OPS)))
            effects.append(dict(e))
        actions[_text(name, 30)] = {
            "label": _text(spec.get("label"), 40) or _text(name, 30),
            "effects": effects,
        }
    return {"actions": actions}


_CONFIG_NORMALIZERS = {
    KIND_TIME: _norm_time_config,
    KIND_LOOT: _norm_loot_config,
    KIND_CRAFT: _norm_craft_config,
    KIND_REPUTATION: _norm_reputation_config,
    KIND_ACHIEVEMENT: _norm_achievement_config,
    KIND_PROGRESSION: _norm_progression_config,
    KIND_CUSTOM: _norm_custom_config,
}


def normalize_system(raw: dict) -> dict:
    """规范化一个体系定义。未知 kind 直接报错（不静默降级成空壳）。"""
    if not isinstance(raw, dict):
        raise ValueError("体系定义必须是对象")
    sid = _text(raw.get("id"), 40)
    if not sid:
        raise ValueError("体系缺少 id")
    kind = _text(raw.get("kind"), 20).lower()
    if kind not in KINDS:
        raise ValueError("未知体系 kind=%r（可用: %s）" % (kind, " / ".join(KINDS)))
    config = _CONFIG_NORMALIZERS[kind](raw.get("config"))
    return {
        "id": sid,
        "kind": kind,
        "label": _text(raw.get("label"), 40) or KIND_LABELS[kind],
        "note": _text(raw.get("note"), 200),
        "config": config,
    }


# ────────────────────────────── 运行时初始化 ──────────────────────────────

def _init_runtime(state: dict, system: dict) -> dict:
    box = _systems(state)
    sid = system["id"]
    existing = box["rt"].get(sid)
    if isinstance(existing, dict):
        return existing
    kind = system["kind"]
    cfg = system["config"]
    if kind == KIND_TIME:
        start = cfg["start"]
        rt = {"day": start["day"], "hour": start["hour"], "minute": start["minute"],
              "season": start["season"], "weather": start["weather"],
              "elapsed_minutes": (start["day"] - 1) * 1440 + start["hour"] * 60 + start["minute"],
              "log": []}
    elif kind == KIND_REPUTATION:
        rt = {"factions": {f["name"]: {"value": f["start"], "tier": ""}
                           for f in cfg["factions"]}}
    elif kind == KIND_ACHIEVEMENT:
        rt = {"unlocked": {}}
    elif kind == KIND_PROGRESSION:
        rt = {"xp": 0, "level": 1, "spent": 0}
    elif kind == KIND_CUSTOM:
        rt = {"counts": {}}
    else:
        rt = {}
    box["rt"][sid] = rt
    return rt


def define(state: dict, raw: dict) -> dict:
    """新增/覆盖一个体系定义（覆盖时保留运行态中仍然有效的部分）。"""
    system = normalize_system(raw)
    box = _systems(state)
    if system["id"] not in box["defs"] and len(box["defs"]) >= MAX_DEFS:
        raise ValueError("体系数量已达上限 %d" % MAX_DEFS)
    box["defs"][system["id"]] = system
    rt = _init_runtime(state, system)
    return {"system": system, "runtime": rt, "total": len(box["defs"])}


def remove(state: dict, sid: str) -> dict:
    box = _systems(state)
    sid = _text(sid, 40)
    existed = sid in box["defs"]
    box["defs"].pop(sid, None)
    box["rt"].pop(sid, None)
    return {"removed": existed, "total": len(box["defs"])}


def status(state: dict, sid: str = "") -> dict:
    """体系清单 / 单个体系状态（面板与宿主都用这个）。"""
    box = _systems(state)
    defs = box["defs"]
    if sid:
        key = _text(sid, 40)
        if key not in defs:
            raise ValueError("体系不存在: %s（可用: %s）" % (key, ", ".join(defs) or "空"))
        system = defs[key]
        return {"id": key, "kind": system["kind"], "label": system["label"],
                "note": system["note"], "config": system["config"],
                "runtime": _runtime_summary(system, _init_runtime(state, system))}
    rows = []
    for key, system in defs.items():
        rows.append({"id": key, "kind": system["kind"], "label": system["label"],
                     "summary": _runtime_summary(system, _init_runtime(state, system))})
    return {"systems": rows, "total": len(rows),
            "kinds": [{"kind": k, "label": KIND_LABELS[k]} for k in KINDS]}


def _runtime_summary(system: dict, rt: dict) -> dict:
    kind = system["kind"]
    if kind == KIND_TIME:
        return {"day": rt.get("day"), "hour": rt.get("hour"), "minute": rt.get("minute"),
                "season": rt.get("season"), "weather": rt.get("weather"),
                "clock": "%02d:%02d" % (_int(rt.get("hour")), _int(rt.get("minute")))}
    if kind == KIND_REPUTATION:
        return {"factions": {k: dict(v) for k, v in (rt.get("factions") or {}).items()}}
    if kind == KIND_ACHIEVEMENT:
        return {"unlocked": len(rt.get("unlocked") or {}),
                "total": len((system["config"].get("items") or []))}
    if kind == KIND_PROGRESSION:
        return progression_status(state=None, system=system, rt=rt) if False else {
            "xp": rt.get("xp", 0), "level": rt.get("level", 1),
            "need": need_for_level(system, rt.get("level", 1)),
            "max_level": system["config"]["max_level"]}
    if kind == KIND_LOOT:
        return {"tables": sorted((system["config"].get("tables") or {}).keys())}
    if kind == KIND_CRAFT:
        return {"recipes": len(system["config"].get("recipes") or [])}
    if kind == KIND_CUSTOM:
        return {"actions": sorted((system["config"].get("actions") or {}).keys()),
                "counts": dict(rt.get("counts") or {})}
    return {}


# ────────────────────────────── 成长体系 ──────────────────────────────

def need_for_level(system: dict, level: int) -> int:
    cfg = system["config"]
    lvl = max(1, _int(level, 1, 1, cfg["max_level"]))
    return int(round(cfg["base_xp"] * (cfg["growth"] ** (lvl - 1))))


def progression_status(state, system, rt):
    cfg = system["config"]
    level = _int(rt.get("level"), 1, 1, cfg["max_level"])
    return {"xp": _int(rt.get("xp"), 0, 0, 10 ** 9), "level": level,
            "need": need_for_level(system, level), "max_level": cfg["max_level"],
            "level_label": cfg["level_label"], "per_level": dict(cfg["per_level"])}


def _grant_xp(state: dict, system: dict, rt: dict, amount: int) -> dict:
    cfg = system["config"]
    amount = _int(amount, 0, 0, 10 ** 6)
    rt["xp"] = _int(rt.get("xp"), 0, 0, 10 ** 9) + amount
    level = _int(rt.get("level"), 1, 1, cfg["max_level"])
    gained = []
    while level < cfg["max_level"] and rt["xp"] >= need_for_level(system, level):
        rt["xp"] -= need_for_level(system, level)
        level += 1
        gained.append(level)
        player = (state.get("entities") or {}).get("player")
        if isinstance(player, dict):
            attrs = player.setdefault("attrs", {})
            if isinstance(attrs, dict):
                for key, delta in (cfg["per_level"] or {}).items():
                    if delta:
                        attrs[key] = _int(attrs.get(key), 0) + delta
    rt["level"] = level
    if gained and isinstance((state.get("entities") or {}).get("player"), dict):
        player = state["entities"]["player"]
        player["stage"] = _int(player.get("stage"), 0, 0, 9999) + len(gained)
    return {"granted": amount, "level": level, "levels_gained": gained,
            "xp": rt["xp"], "need": need_for_level(system, level)}


# ────────────────────────────── 各体系动作 ──────────────────────────────

def _advance_time(state, system, rt, minutes):
    cfg = system["config"]
    minutes = _int(minutes, 0, 0, 60 * 24 * 30)
    if minutes <= 0:
        raise ValueError("minutes 必须为正")
    start_day = _int(rt.get("day"), 1)
    total = (_int(rt.get("elapsed_minutes"), 0) + minutes)
    rt["elapsed_minutes"] = total
    rt["day"] = total // 1440 + 1
    rt["hour"] = (total % 1440) // 60
    rt["minute"] = total % 60
    seasons = cfg["seasons"]
    per = cfg["days_per_season"]
    idx = ((rt["day"] - 1) // per) % len(seasons)
    old_season = rt.get("season")
    rt["season"] = seasons[idx]

    weather_changed = False
    if rt["day"] != start_day:
        table = cfg["weathers"]
        total_w = sum(w["weight"] for w in table)
        roll = _unit(state.get("rng_seed"), state.get("tick"), "weather", rt["day"]) * total_w
        acc = 0.0
        pick = table[-1]["name"]
        for w in table:
            acc += w["weight"]
            if roll <= acc:
                pick = w["name"]
                break
        if pick != rt.get("weather"):
            rt["weather"] = pick
            weather_changed = True

    log = rt.setdefault("log", [])
    log.append({"day": rt["day"], "hour": rt["hour"], "minute": rt["minute"],
                "season": rt["season"], "weather": rt.get("weather")})
    if len(log) > cfg["log_cap"]:
        del log[:len(log) - cfg["log_cap"]]
    return {"day": rt["day"], "hour": rt["hour"], "minute": rt["minute"],
            "season": rt["season"], "weather": rt.get("weather"),
            "season_changed": rt["season"] != old_season,
            "weather_changed": weather_changed,
            "clock": "%02d:%02d" % (rt["hour"], rt["minute"]),
            "advanced_minutes": minutes}


def _roll_loot(state, system, rt, table_name, times=1, grant=False):
    tables = system["config"]["tables"]
    name = _text(table_name, 40)
    if name not in tables:
        raise ValueError("掉落表不存在: %s（可用: %s）" % (name, ", ".join(sorted(tables)) or "空"))
    table = tables[name]
    times = _int(times, 1, 1, 20)
    tick = state.get("tick", 0)
    seed = state.get("rng_seed")
    drops = []
    for i in range(times):
        for slot in range(table["rolls"]):
            entries = list(table["entries"])
            if table["empty_weight"]:
                entries = entries + [{"item": "", "name": "", "weight": table["empty_weight"],
                                      "qty_min": 0, "qty_max": 0}]
            if not entries:
                continue
            total = sum(e["weight"] for e in entries)
            roll = _unit(seed, tick, "loot", name, i, slot) * total
            acc = 0.0
            pick = entries[-1]
            for e in entries:
                acc += e["weight"]
                if roll <= acc:
                    pick = e
                    break
            if not pick["item"]:
                continue
            qty_roll = _unit(seed, tick, "lootqty", name, i, slot)
            qty = pick["qty_min"] + int(qty_roll * (pick["qty_max"] - pick["qty_min"] + 1))
            qty = max(pick["qty_min"], min(pick["qty_max"], qty))
            drops.append({"item": pick["item"], "name": pick["name"], "qty": qty})
    merged = {}
    for d in drops:
        merged.setdefault(d["item"], {"item": d["item"], "name": d["name"], "qty": 0})
        merged[d["item"]]["qty"] += d["qty"]
    out = sorted(merged.values(), key=lambda x: x["item"])
    if grant and out:
        player = (state.get("entities") or {}).get("player")
        if not isinstance(player, dict):
            raise ValueError("没有 player，无法发放掉落")
        items = player.setdefault("items", {})
        if not isinstance(items, dict):
            items = {}
            player["items"] = items
        for d in out:
            items[d["item"]] = _int(items.get(d["item"]), 0) + d["qty"]
    return {"table": name, "drops": out, "granted": bool(grant),
            "total_qty": sum(d["qty"] for d in out)}


def _craft(state, system, rt, recipe_id):
    recipes = {r["id"]: r for r in (system["config"].get("recipes") or [])}
    rid = _text(recipe_id, 40)
    if rid not in recipes:
        raise ValueError("配方不存在: %s（可用: %s）" % (rid, ", ".join(sorted(recipes)) or "空"))
    recipe = recipes[rid]
    player = (state.get("entities") or {}).get("player")
    if not isinstance(player, dict):
        raise ValueError("没有 player，无法制造")
    items = player.get("items") if isinstance(player.get("items"), dict) else {}
    missing = {k: v for k, v in recipe["inputs"].items() if _int(items.get(k), 0) < v}
    if missing:
        return {"recipe": rid, "success": False, "reason": "材料不足",
                "missing": missing, "output": None}
    for k, v in recipe["inputs"].items():
        left = _int(items.get(k), 0) - v
        if left > 0:
            items[k] = left
        else:
            items.pop(k, None)
    player["items"] = items

    attr = recipe["attribute"]
    skill = 0
    if attr:
        skill = _int((player.get("attrs") or {}).get(attr), 0)
    difficulty = recipe["difficulty"]
    chance = 1.0 / (1.0 + math.exp(-(skill - difficulty) / 4.0)) if difficulty else 1.0
    roll = _unit(state.get("rng_seed"), state.get("tick"), "craft", rid)
    success = roll < max(0.05, min(0.98, chance))
    result = {"recipe": rid, "name": recipe["name"], "success": success,
              "chance": round(chance, 3), "roll": round(roll, 3), "output": None}
    if success:
        item = recipe["output"]["item"]
        items[item] = _int(items.get(item), 0) + recipe["output"]["qty"]
        player["items"] = items
        result["output"] = dict(recipe["output"])
    else:
        # 失败按 fail_consume 比例返还剩余材料（保底不再扣，避免双输）
        refund = {}
        for k, v in recipe["inputs"].items():
            back = int(v * (1.0 - recipe["fail_consume"]))
            if back > 0:
                items[k] = _int(items.get(k), 0) + back
                refund[k] = back
        player["items"] = items
        result["refunded"] = refund
    return result


def _reputation(state, system, rt, action, params):
    cfg = system["config"]
    factions = rt.setdefault("factions", {})
    tiers = cfg["tiers"]

    def tier_for(value):
        label = tiers[0]["label"]
        for t in tiers:
            if value >= t["min"]:
                label = t["label"]
        return label

    if action in ("get", "status", ""):
        rows = {}
        for name, row in factions.items():
            value = _int(row.get("value"), 0, -100, 100)
            tier = row.get("tier") or tier_for(value)
            row["tier"] = tier
            rows[name] = {"value": value, "tier": tier}
        return {"factions": rows, "tiers": tiers}

    if action != "adjust":
        raise ValueError("声望体系支持 get / adjust")
    name = _text(params.get("faction"), 30)
    if not name:
        raise ValueError("需要 faction")
    if name not in factions:
        if len(factions) >= MAX_FACTIONS:
            raise ValueError("势力数量已达上限 %d" % MAX_FACTIONS)
        factions[name] = {"value": cfg["default"], "tier": ""}
    # delta 本身允许大幅值：真正的边界由 after 的 [-100, 100] clamp 决定，
    # 否则 request(-500) 会被截成 -100，从 100 只能掉到 0（打不到下限）。
    delta = _int(params.get("delta"), 0, -10000, 10000)
    before = _int(factions[name].get("value"), 0, -100, 100)
    after = max(-100, min(100, before + delta))
    factions[name]["value"] = after
    factions[name]["tier"] = tier_for(after)
    return {"faction": name, "before": before, "after": after, "delta": after - before,
            "tier": factions[name]["tier"], "reason": _text(params.get("reason"), 120)}


def _achievement(state, system, rt, action, params):
    from game_engine.rules import questline as quest_rules

    cfg = system["config"]
    items = cfg.get("items") or []
    unlocked = rt.setdefault("unlocked", {})
    if action in ("list", "status", ""):
        rows = []
        for a in items:
            rows.append({"id": a["id"], "name": a["name"], "desc": a["desc"],
                         "unlocked": a["id"] in unlocked,
                         "tick": unlocked.get(a["id"])})
        return {"achievements": rows, "unlocked": len(unlocked), "total": len(items)}

    if action != "check":
        raise ValueError("成就体系支持 list / check")
    newly = []
    for a in items:
        if a["id"] in unlocked:
            continue
        try:
            ok = bool(quest_rules.evaluate(state, a["condition"]))
        except Exception:  # aqg: top-level boundary —— 坏条件视为未达成，不影响其他成就
            ok = False
        if not ok:
            continue
        unlocked[a["id"]] = _int(state.get("tick"), 0, 0)
        newly.append({"id": a["id"], "name": a["name"], "desc": a["desc"]})
        player = (state.get("entities") or {}).get("player")
        if isinstance(player, dict):
            if a["gold"]:
                player["gold"] = _int(player.get("gold"), 0) + a["gold"]
            req_flags = state.setdefault("world_flags", [])
            for flag in a["flags"]:
                if flag not in req_flags:
                    req_flags.append(flag)
        if a["xp"]:
            prog = _find_system(state, KIND_PROGRESSION)
            if prog:
                _grant_xp(state, prog, _init_runtime(state, prog), a["xp"])
    return {"newly_unlocked": newly, "unlocked": len(unlocked), "total": len(items)}


def _find_system(state, kind):
    for system in (_systems(state)["defs"]).values():
        if system["kind"] == kind:
            return system
    return None


def _apply_effect(state, effect):
    """自定义体系的受限效果。只允许白名单操作，路径一律走已知容器。"""
    op = _text(effect.get("op"), 20).lower()
    from game_engine.rules import gamesystem as game_rules

    if op in ("resource", "attribute", "meter"):
        kind = {"resource": "resources", "attribute": "attributes", "meter": "meters"}[op]
        key = _text(effect.get("key"), 40)
        if not key:
            raise ValueError("%s 效果需要 key" % op)
        delta = _int(effect.get("delta"), 0, -100000, 100000)
        return game_rules.adjust(state, key, kind=kind, delta=delta)
    if op == "flag":
        flag = _text(effect.get("flag"), 40)
        if not flag:
            raise ValueError("flag 效果需要 flag")
        flags = state.setdefault("world_flags", [])
        if effect.get("remove"):
            if flag in flags:
                flags.remove(flag)
            return {"flag": flag, "removed": True}
        if flag not in flags:
            flags.append(flag)
        return {"flag": flag, "removed": False}
    if op == "fact":
        from game_engine.rules import context as context_rules
        return context_rules.remember(
            state, _text(effect.get("text"), 600), kind=_text(effect.get("fact_kind"), 20) or "fact",
            keys=effect.get("keys") or [], source="system")
    if op == "reputation":
        system_id = _text(effect.get("system"), 40)
        box = _systems(state)
        target = box["defs"].get(system_id)
        if not target or target["kind"] != KIND_REPUTATION:
            raise ValueError("reputation 效果需要指向一个声望体系: %r" % system_id)
        return _reputation(state, target, _init_runtime(state, target), "adjust", {
            "faction": effect.get("faction"), "delta": effect.get("delta"),
            "reason": effect.get("reason", "system"),
        })
    if op == "xp":
        prog = _find_system(state, KIND_PROGRESSION)
        if not prog:
            raise ValueError("xp 效果需要先定义一个 progression 体系")
        return _grant_xp(state, prog, _init_runtime(state, prog), effect.get("delta"))
    if op == "advance_time":
        t = _find_system(state, KIND_TIME)
        if not t:
            raise ValueError("advance_time 效果需要先定义一个 time 体系")
        return _advance_time(state, t, _init_runtime(state, t), effect.get("minutes"))
    if op == "loot":
        system_id = _text(effect.get("system"), 40)
        box = _systems(state)
        target = box["defs"].get(system_id)
        if not target or target["kind"] != KIND_LOOT:
            raise ValueError("loot 效果需要指向一个掉落体系: %r" % system_id)
        return _roll_loot(state, target, _init_runtime(state, target),
                          effect.get("table", ""), effect.get("times", 1),
                          bool(effect.get("grant", False)))
    raise ValueError("未知效果 op=%r（%s）" % (op, " / ".join(EFFECT_OPS)))


def _custom(state, system, rt, action, params):
    actions = system["config"].get("actions") or {}
    if action in ("list", "status", ""):
        return {"actions": [{"name": k, "label": v["label"],
                             "effects": len(v["effects"])} for k, v in actions.items()],
                "counts": dict(rt.get("counts") or {})}
    if action not in actions:
        raise ValueError("自定义体系没有动作 %r（可用: %s）"
                         % (action, ", ".join(sorted(actions)) or "空"))
    applied = []
    for effect in actions[action]["effects"]:
        applied.append(_apply_effect(state, effect))
    counts = rt.setdefault("counts", {})
    counts[action] = _int(counts.get(action), 0) + 1
    return {"action": action, "label": actions[action]["label"], "effects": applied,
            "count": counts[action]}


# ────────────────────────────── 统一入口 ──────────────────────────────

def run(state: dict, sid: str, action: str = "", params: dict | None = None) -> dict:
    """执行一次体系动作。所有 kind 共用这一入口，宿主不必记每种的函数名。"""
    box = _systems(state)
    key = _text(sid, 40)
    if key not in box["defs"]:
        raise ValueError("体系不存在: %s（可用: %s）" % (key, ", ".join(sorted(box["defs"])) or "空"))
    system = box["defs"][key]
    rt = _init_runtime(state, system)
    params = params if isinstance(params, dict) else {}
    action = _text(action, 20).lower()
    kind = system["kind"]

    if kind == KIND_TIME:
        if action in ("status", ""):
            return _runtime_summary(system, rt)
        if action != "advance":
            raise ValueError("时间体系支持 status / advance")
        return _advance_time(state, system, rt, params.get("minutes", 60))
    if kind == KIND_LOOT:
        if action in ("list", "status", ""):
            return {"tables": {k: {"entries": len(v["entries"]), "rolls": v["rolls"]}
                               for k, v in (system["config"].get("tables") or {}).items()}}
        if action != "roll":
            raise ValueError("掉落体系支持 list / roll")
        return _roll_loot(state, system, rt, params.get("table", ""),
                          params.get("times", 1), bool(params.get("grant")))
    if kind == KIND_CRAFT:
        if action in ("list", "status", ""):
            return {"recipes": [{"id": r["id"], "name": r["name"], "inputs": r["inputs"],
                                 "output": r["output"], "difficulty": r["difficulty"]}
                                for r in (system["config"].get("recipes") or [])]}
        if action != "craft":
            raise ValueError("制造体系支持 list / craft")
        return _craft(state, system, rt, params.get("recipe", ""))
    if kind == KIND_REPUTATION:
        return _reputation(state, system, rt, action, params)
    if kind == KIND_ACHIEVEMENT:
        return _achievement(state, system, rt, action, params)
    if kind == KIND_PROGRESSION:
        if action in ("status", ""):
            return progression_status(state, system, rt)
        if action != "grant":
            raise ValueError("成长体系支持 status / grant")
        return _grant_xp(state, system, rt, params.get("amount", params.get("xp", 0)))
    if kind == KIND_CUSTOM:
        return _custom(state, system, rt, action, params)
    raise ValueError("体系的 kind 不可执行: %s" % kind)


def summary(state: dict) -> dict:
    """面板用：所有体系的紧凑摘要（不返回完整 config，避免 /state 膨胀）。"""
    box = _systems(state)
    rows = []
    for sid, system in box["defs"].items():
        rt = _init_runtime(state, system)
        rows.append({"id": sid, "kind": system["kind"], "label": system["label"],
                     "summary": _runtime_summary(system, rt)})
    return {"rows": rows, "total": len(rows)}
