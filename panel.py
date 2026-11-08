#!/usr/bin/env python3
"""
World Games · 实况面板 (World Games Live Panel)

一个**只读**的小型 HTTP 服务：把状态文件渲染成可以长期挂着的游戏面板
（玩家血量/心流/图鉴/编年史/市场行情实时更新）。

单独用:
    python panel.py --state ww_state.json --port 8765
由 MCP 拉起: 调工具 open_panel（会自动指向当前对局的状态文件）

端点:
    GET /          面板页面（panel.html）
    GET /state     视图模型 JSON（状态 + 引擎推导 + 图鉴/判定/上下文/存档库/剧情）
    GET /series    长局态势侧写（图表数据）
    GET /history   剧情回放与归档检索（?q=关键词&scope=all|prose|archive&limit=N）
    GET /actions   行动队列（只读）
    GET /export    导出状态 JSON（只读）
    GET /health    健康检查（面板版本、状态文件大小、队列长度）
    GET /events    SSE：状态文件一变就推送（连接有最长寿命，客户端自动重连）
    POST /action   排队一条行动（写 <state>.inbox.jsonl 侧写，状态文件仍然只读）

面板严格只读状态文件：唯一的写入是行动队列侧写（带进程内锁 + 跨进程文件锁 + 原子替换）。
"""

import argparse
import hashlib
import json
import os
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
try:  # installed package
    from game_engine import bootstrap as _bootstrap
except ImportError:  # bare checkout: the package dir may not be on sys.path yet
    if _SCRIPT_DIR not in sys.path:
        sys.path.insert(0, _SCRIPT_DIR)
    import bootstrap as _bootstrap
_bootstrap.install(_SCRIPT_DIR)

from game_engine.rules import lorebook as lore_engine  # noqa: E402
from game_engine.rules import playbook as playbook_rules  # noqa: E402
from game_engine.rules import questline as quest_rules  # noqa: E402
from game_engine.rules.narrative_engine import (  # noqa: E402
    flow_channel_status, panarchy_phase_check, player_identity_vector)
from game_engine.state_schema import load_state  # noqa: E402
from game_engine import input_policy  # noqa: E402

_PANEL_VERSION = __import__("game_engine").__version__
HTML_FILE = os.path.join(_SCRIPT_DIR, "panel.html")
HTML_DIR = _SCRIPT_DIR
MORAL_DIMS = ("关怀", "公平", "忠诚", "权威", "圣洁", "自由")
EVENTS_CAP = 40
MAX_VIZ_SIDECAR_BYTES = 4 * 1024 * 1024

# 唯一的事件分级表（前端不得再维护关键词表；未知类型走 EVENT_LABELS 兜底）
EVENT_LABELS = {
    "combat": ("交锋", "战"),
    "trade": ("交易", "交"),
    "social": ("人情", "情"),
    "karma": ("因果", "债"),
    "breakthrough": ("突破", "境"),
    "travel": ("行旅", "路"),
    "use_item": ("用物", "药"),
    "emergent": ("风起", "风"),
    "system": ("世界", "启"),
    "tick": ("回合", "回"),
    "prose": ("正文", "墨"),
    "world": ("世事", "势"),
    "quest": ("事业线", "线"),
}


_SEVERITY_BY_TYPE = {
    "system": "info",
    "tick": "info",
    "travel": "info",
    "prose": "info",
    "world": "info",
    "combat": "warning",
    "trade": "success",
    "social": "info",
    "karma": "warning",
    "emergent": "warning",
    "use_item": "success",
}


def _combat_kind(desc):
    """击杀 vs 交手：只按"结果"分类，不看谁赢。"""
    if any(w in desc for w in ("击败", "击杀", "倒下")):
        return "击杀", "danger"
    return "交手", "warning"


def _trade_kind(desc):
    if "购买" in desc:
        return "购入"
    if "出售" in desc:
        return "出售"
    return "交易"


def _social_kind(desc):
    return "人情"


def _breakthrough_kind(desc):
    if any(w in desc for w in ("失败", "反噬")):
        return "突破受挫", "danger"
    return "突破", "success"


def _travel_kind(desc):
    return ("初探" if "初次" in desc else "行旅")


def _social_severity(desc):
    return "success" if any(w in desc for w in ("好感", "敬重", "结盟", "帮助")) else "info"


_KIND_RULES = {
    "combat": _combat_kind,
    "trade": lambda d: (_trade_kind(d), "success"),
    "social": lambda d: ("人情", _social_severity(d)),
    "breakthrough": _breakthrough_kind,
    "travel": lambda d: (_travel_kind(d), "info"),
}


def classify_event(ev, milestone_ticks=()):
    """把一条 event_log 映射成前端可直接渲染的条目（kind/severity/title/icon 全在此决定）。

    分类逻辑按事件类型拆成小函数（`_KIND_RULES`），一行一个类型；
    未登记的类型走默认值，不抛错也不编造严重度。
    """
    etype = str(ev.get("type") or "system")
    desc = str(ev.get("desc") or "")
    tick = int(ev.get("tick", 0) or 0)
    title, icon = EVENT_LABELS.get(etype, ("事件", "·"))
    rule = _KIND_RULES.get(etype)
    if rule:
        kind, severity = rule(desc)
    else:
        kind, severity = "事件", _SEVERITY_BY_TYPE.get(etype, "info")
    # 事件 id 只是去重键，不用于任何安全用途（bandit B324 的 High 是误报，
    # 显式声明 usedforsecurity=False 让扫描器与读者都清楚这一点）
    digest = hashlib.sha1(desc.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
    # seq 进 id 前缀：同 tick 两条描述相同、类型不同的事件曾共用同一去重键
    # （tick:type:digest 相同），前端按 id 去重时会丢掉一条。有 seq 时以它为先。
    seq = ev.get("seq")
    ident = ("%d:%s:%s" % (tick, etype, digest) if seq is None
             else "%d.%d:%s:%s" % (tick, int(seq), etype, digest))
    return {"id": ident, "seq": seq, "tick": tick, "type": etype,
            "kind": kind, "severity": severity, "title": title, "desc": desc,
            "icon": icon, "milestone": tick in milestone_ticks,
            "repeat": int(ev.get("repeat", 1) or 1)}


SCENE_TEXT_CAP = 700
_SCENE_TEXT_SOURCES = (
    ("prose", "prose"),
    ("place", "places"),
    ("summary", "summaries"),
    ("world", "world_info"),
)


def _scene_prose(state, loc):
    """最新一段正文：只有它属于当前地点才算"当下"。"""
    prose = state.get("prose") or []
    if not prose or not isinstance(prose[-1], dict):
        return "", None
    last = prose[-1]
    last_loc = last.get("location")
    if loc and last_loc and last_loc != loc:
        return "", None
    return str(last.get("text") or ""), last.get("tick")


def _scene_place(state, loc):
    if not loc:
        return ""
    return str((state.get("places") or {}).get(loc, {}).get("desc") or "")


def _scene_summary(state):
    summaries = state.get("summaries") or []
    if not summaries:
        return ""
    return str(summaries[-1].get("text", "") or "")


def _next_moves(state, player, playbook, quests, loop):
    """Concrete "what can I do now" hints, derived from state alone.

    Why this exists: a rule engine is invisible until you know what it will
    accept. New players ask "what do I type?" — the panel answered that with a
    generic placeholder, which is not an answer. These hints are computed from
    the same state the tools read, so they cannot drift from what is possible.

    Each hint is {kind, text, why}. Ordered by how likely it is to unblock the
    player: active quest objectives first, then survival, then world, then loop.
    """
    moves = []
    if not isinstance(player, dict):
        return moves

    # 1) A quest objective you have not met yet is the strongest signal.
    for row in (quests.get("rows") or [])[:2]:
        if row.get("status") in ("done", "failed"):
            continue
        for objective in (row.get("objectives") or [])[:2]:
            moves.append({"kind": "quest", "text": str(objective)[:80],
                          "why": "推进「%s」" % (row.get("title") or row.get("id", ""))})

    # 2) Survival: low HP or a heavy debt changes what a sensible next move is.
    hp = player.get("hp")
    hp_max = player.get("hp_max")
    if isinstance(hp, (int, float)) and isinstance(hp_max, (int, float)) and hp_max > 0:
        if hp / hp_max < 0.35:
            moves.append({"kind": "risk", "text": "找地方疗伤，或换条安全的路",
                          "why": "气血只剩 %d%%" % round(hp * 100 / hp_max)})

    karma = player.get("unsettled_karma")
    if isinstance(karma, (int, float)) and karma >= 30:
        moves.append({"kind": "risk", "text": "还一笔业债，或做件好事抵掉",
                      "why": "未清业债 %s，会压突破成功率" % round(karma)})

    # 3) World: a market with bargains is a concrete, checkable opportunity.
    market = state.get("market") or {}
    here = str(player.get("location") or "")
    local = (market.get(here) or {}).get("items") or {}
    bargains = 0
    for item in local.values():
        if not isinstance(item, dict):
            continue
        price = item.get("price")
        base = item.get("base_price")
        if isinstance(price, (int, float)) and isinstance(base, (int, float)) and base > 0:
            if price < base * 0.95:
                bargains += 1
    if bargains:
        moves.append({"kind": "opportunity", "text": "看看本地市价，有 %d 样低于基准" % bargains,
                      "why": "低价买入，离开后可能卖得更高"})

    # 4) Loop: if the player is circling, say so plainly.
    if loop.get("loop_suspected"):
        moves.append({"kind": "loop", "text": "换个地方，或推进一个没试过的交互",
                      "why": "同一状态已经重复出现"})

    # 5) Always offer the fallback that always works.
    if not moves:
        moves.append({"kind": "free", "text": "描述你想做的事，或先去别处看看",
                      "why": "自由推进：引擎会结算，结果由规则决定"})
    return moves[:5]


def _scene_focus(events):
    """最近一条非 info 事件优先；没有就用最后一条。"""
    for e in reversed(events or []):
        if e.get("severity") != "info":
            return e.get("desc")
    return events[-1]["desc"] if events else None


_MOOD_BY_TYPE = {"trade": "trade", "social": "social", "travel": "discovery"}
_MOOD_BY_SEVERITY = {"danger": "danger", "success": "growth"}


def _scene_mood(events):
    if not events:
        return "neutral"
    last = events[-1]
    return (_MOOD_BY_TYPE.get(last.get("type"))
            or _MOOD_BY_SEVERITY.get(last.get("severity"))
            or "neutral")


def _scene_text(state, loc, focus):
    """按优先级取正文；每一级都只读状态，不推断剧情。"""
    text, prose_tick = _scene_prose(state, loc)
    for key, _label in _SCENE_TEXT_SOURCES[1:]:
        if text:
            break
        if key == "place":
            text = _scene_place(state, loc)
        elif key == "summary":
            text = _scene_summary(state)
        elif key == "world":
            text = str((state.get("world_info") or {}).get("location_desc") or "")
    if not text and focus:
        text = focus
    return text, prose_tick


def build_scene(state, events, player):
    """叙事主舞台标题/描述/氛围：只用状态里已有的文字，不编造剧情。

    正文优先级（越靠前越"当下"）：
      1. `prose` 最新一段（宿主用 publish_prose 写的本回合正文）
      2. `places[当前地点].desc`（travel 或 publish_prose 记下的本地描写）
      3. 最新章节摘要 `summaries[-1]`
      4. `world_info.location_desc`（开场描写）
      5. 最近事件文案
    这样移动之后面板显示的是新地方的描写，而不是永远停在开场那句。
    """
    world = state.get("world_info", {}) or {}
    loc = str(player.get("location", "") or "")
    focus = _scene_focus(events)
    desc, prose_tick = _scene_text(state, loc, focus)
    # 主舞台是"一屏可读"的叙事卡，不是阅读器：超长正文截断，完整正文仍在
    # 状态文件与 /export 里（面板只读，不丢数据）。
    shown = desc if len(desc) <= SCENE_TEXT_CAP else desc[:SCENE_TEXT_CAP].rstrip() + "…"
    return {"location": loc, "title": loc or str(world.get("name", "") or ""),
            "description": shown, "mood": _scene_mood(events), "focus_event": focus,
            "prose_tick": prose_tick, "full_length": len(desc)}


MAX_INVENTORY = 60
MAX_MODIFIERS = 40
MAX_SESSIONS_SHOWN = 50
MAX_MARKET_ITEMS = 400          # /state 里最多下发的商品条目（超出按价格排序截断并标记）
MAX_CODEX_ITEMS = 200           # 图鉴每类最多下发
MAX_PROSE_ITEMS = 20            # 主舞台剧情回放保留的正文段数（完整文本）
MAX_HISTORY_PAGE = 200          # /history 单页上限


def _int_or(value, default=0):
    """宽松整数：None/字符串/浮点/NaN 都不许把面板打崩。"""
    try:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, float):
            if value != value or value in (float("inf"), float("-inf")):
                return default
            return int(value)
        return int(value)
    except (TypeError, ValueError):
        return default


def _num_or(value, default=0.0):
    try:
        if isinstance(value, bool):
            return float(value)
        out = float(value)
        if out != out or out in (float("inf"), float("-inf")):
            return default
        return out
    except (TypeError, ValueError):
        return default


def build_inventory(state, player):
    """随身物品：以 player.items 为准，用市场元数据补显示名与类别。"""
    items = player.get("items")
    if not isinstance(items, dict):
        return []
    meta = {}
    for mk in (state.get("market") or {}).values():
        if isinstance(mk, dict):
            for k, it in mk.items():
                if isinstance(it, dict) and k not in meta:
                    meta[k] = it
    out = []
    for k in sorted(items, key=lambda x: str(x))[:MAX_INVENTORY]:
        n = _int_or(items[k], 0)
        if n <= 0:
            continue
        it = meta.get(k) or {}
        out.append({"key": str(k), "name": str(it.get("name") or k),
                    "quantity": n, "type": str(it.get("type") or "")})
    return out


def build_relations(state, player_id="player"):
    """只返回与玩家有关的关系（键为字母序 a:b），带对方名字。"""
    rels = state.get("relations") or {}
    ents = state.get("entities") or {}
    out = []
    if not isinstance(rels, dict):
        return out
    for key, val in rels.items():
        if not isinstance(val, dict):
            continue
        parts = str(key).split(":")
        if len(parts) != 2 or player_id not in parts:
            continue
        other = parts[0] if parts[1] == player_id else parts[1]
        ent = ents.get(other) or {}
        out.append({"id": other, "name": str(ent.get("name") or other),
                    "affinity": _int_or(val.get("affinity", 0), 0),
                    "respect": _int_or(val.get("respect", 0), 0)})
    out.sort(key=lambda r: r["id"])
    return out


def _merge_adjacent(events):
    """把连续相同描述的事件合并为一条，并记 repeat 次数（缺省 1）。

    长局里战斗常连续多回合都是"攻击被闪避"，逐条铺开会让时间线失去信息量。
    只合并"紧邻且描述完全一致"的条目——不跨类型聚合，不改变事件先后顺序，
    因此既不掩盖真实叙事节奏，也不会把不同对象的事件混在一起。
    """
    out = []
    for e in events:
        if not isinstance(e, dict):
            continue
        desc = str(e.get("desc", ""))
        if out and str(out[-1].get("desc", "")) == desc:
            out[-1]["repeat"] = int(out[-1].get("repeat", 1)) + 1
            continue
        item = dict(e)
        item["repeat"] = 1
        out.append(item)
    return out


def _build_market(state):
    """market: [{location, items:[{key,name,price,base_price,supply,delta,type}]}]。

    按 location / item_key 排序，保证同一状态每次渲染顺序一致（面板每次刷新不该跳）。
    """
    out = []
    market = state.get("market") if isinstance(state.get("market"), dict) else {}
    for loc, items in sorted(market.items(), key=lambda kv: str(kv[0])):
        rows = []
        if isinstance(items, dict):
            for key, it in sorted(items.items(), key=lambda kv: str(kv[0])):
                if not isinstance(it, dict):
                    continue
                price = _int_or(it.get("price", 0), 0)
                base = _int_or(it.get("base_price") or price, price)
                rows.append({
                    "key": str(key), "name": str(it.get("name") or key), "price": price,
                    "base_price": base, "supply": _int_or(it.get("supply", 0), 0),
                    "delta": price - base, "type": str(it.get("type") or ""),
                })
        out.append({"location": str(loc), "items": rows})
    total = sum(len(m["items"]) for m in out)
    if total > MAX_MARKET_ITEMS:
        # 超出上限时按"价格偏离基准最大"排序保留，其余标记截断（完整数据仍在状态文件）
        flat = [(abs(it["delta"]), m["location"], it) for m in out for it in m["items"]]
        flat.sort(key=lambda x: (-x[0], x[1], x[2]["key"]))
        keep = {(loc, it["key"]) for _d, loc, it in flat[:MAX_MARKET_ITEMS]}
        for m in out:
            m["items"] = [it for it in m["items"] if (m["location"], it["key"]) in keep]
        out = [m for m in out if m["items"]]
    return out


def _build_events(state):
    """时间线事件：滤掉 tick 心跳、合并相邻重复、再分类。

    返回 (events, milestone_ticks, merged)。`merged` 是合并后的原始事件，
    编年史直接复用，避免对同一份 event_log 再做一次 O(n) 合并。
    """
    milestones = state.get("milestones") if isinstance(state.get("milestones"), list) else []
    milestone_ticks = {_int_or(m.get("tick", 0), 0) for m in milestones if isinstance(m, dict)}
    # tick 是心跳、prose 是正文（已在主舞台整段显示）：两者都不该占时间线。
    log = state.get("event_log") if isinstance(state.get("event_log"), list) else []
    raw = [e for e in log
           if isinstance(e, dict) and e.get("type") not in ("tick", "prose")]
    merged = _merge_adjacent(raw)
    events = [classify_event(e, milestone_ticks) for e in merged[-EVENTS_CAP:]]
    return events, milestone_ticks, merged


def _build_player(state, player, loc, karma):
    """HUD 用的玩家切片：所有数值保持为数字，格式化留给前端（千分位/百分比）。"""
    return {
        "name": str(player.get("name") or "玩家"), "level": str(player.get("level") or ""),
        "stage": _int_or(player.get("stage", 0), 0),
        "stage_max": max(1, _int_or((state.get("config") or {}).get("stage_max", 20), 20)),
        "mind_scars": _int_or(player.get("mind_scars", 0), 0),
        "near_death_count": _int_or(player.get("near_death_count", 0), 0),
        "hp": _int_or(player.get("hp", 0), 0), "hp_max": max(1, _int_or(player.get("hp_max", 1), 1)),
        "mp": _int_or(player.get("mp", 0), 0), "mp_max": max(0, _int_or(player.get("mp_max", 0), 0)),
        "gold": _int_or(player.get("gold", 0), 0), "location": str(loc or ""),
        "currency": str(state.get("currency") or "灵石"),
        "karma": karma,
        "attrs": player.get("attrs", {}),
        "inventory": build_inventory(state, player),
        "tier": _player_tier(state, player),
        "tier_max": len((state.get("config") or {}).get("level_tiers") or []) or None,
    }


def _player_tier(state, player):
    """等级阶梯序号（配置了 level_tiers 才有意义；否则返回 None 让前端回退到 stage）。"""
    try:
        from game_engine.rules.progression import level_tier
        if not (state.get("config") or {}).get("level_tiers"):
            return None
        return level_tier(state, player)
    except Exception:  # aqg: top-level boundary —— 阶梯坏了退回 stage 展示
        return None


DEFAULT_TERMS = {
    "hero": "行者",
    "level": "境界",
    "location": "所在",
    "hp": "气血",
    "mp": "内力",
    "gold": "钱财",
    "flow": "心流",
    "phase": "世界相位",
    "karma": "未清因果债",
    "inventory": "随身",
    "chronicle": "编年史",
    "present": "在场",
    "relations": "人情关系",
    "territory": "境地",
    "track": "修行轨",
    "stage": "阶段",
    "codex": "探索图鉴",
    "market": "市场行情",
    "milestones": "大事记",
    "factions": "势力",
    "rumors": "传闻",
    "culture": "风气",
    "quests": "事业线",
    "playbook": "玩法",
    "lorebook": "世界书",
}


def build_terms(state):
    """面板术语表：默认中文修真词 + 设定包 `ui.terms` 覆盖（世界观无关的最后一公里）。"""
    terms = dict(DEFAULT_TERMS)
    ui = state.get("ui") or {}
    override = ui.get("terms") if isinstance(ui.get("terms"), dict) else {}
    for k, v in (override or {}).items():
        key = str(k)
        if key in terms and str(v).strip():
            terms[key] = str(v)[:24]
    return terms


def build_world(state):
    """世界侧摘要（势力/相位/谣言/风气/物价指数）：面板右栏与顶部徽章用。"""
    try:
        from game_engine.rules.world_evolution import world_summary
        return world_summary(state)
    except Exception as e:  # aqg: top-level boundary —— 世界侧坏了不影响面板其余部分
        return {"error": str(e)[:120]}


def _build_cast(state, loc):
    """在场 / 别处两类 NPC 切片（面板右栏用）。

    `desc/personality/speech` 一并下发：点击角色卡要能看到完整的卡面文字，
    而不是只有被截断的一行简介（角色卡生态里这三段才是人物）。
    """
    present, others = [], []
    entities = state.get("entities") if isinstance(state.get("entities"), dict) else {}
    for eid, ent in entities.items():
        if str(eid) == "player" or not isinstance(ent, dict):
            continue
        if not loc or ent.get("location") == loc:
            hp = _int_or(ent.get("hp"), 0)
            hp_max = _int_or(ent.get("hp_max"), 0)
            present.append({"id": str(eid), "name": str(ent.get("name") or eid),
                            "level": str(ent.get("level") or ""),
                            "faction": str(ent.get("faction") or ""),
                            "hp": hp, "hp_max": hp_max,
                            "hp_pct": round(hp * 100.0 / hp_max, 1) if hp_max > 0 else None,
                            "desc": str(ent.get("desc") or "")[:240],
                            "personality": str(ent.get("personality") or "")[:240],
                            "speech": str(ent.get("speech") or "")[:240],
                            "mind_scars": _int_or(ent.get("mind_scars", 0), 0)})
        else:
            others.append({"id": str(eid), "name": str(ent.get("name") or eid),
                           "location": str(ent.get("location") or "")})
    present.sort(key=lambda r: (-(r["hp_pct"] if r["hp_pct"] is not None else 0), r["id"]))
    others.sort(key=lambda r: r["id"])
    return present, others


def _build_insights(state):
    """引擎推导块（心流/相位/身份）。任一计算失败只降级这一块，不让整页崩。"""
    try:
        return {
            "flow": flow_channel_status(state),
            "phase": panarchy_phase_check(state),
            "identity": player_identity_vector(state),
        }
    except Exception as e:  # aqg: top-level boundary —— 推导失败降级为错误字段，面板仍可用
        return {"error": str(e)[:120]}


def _build_codex(state):
    """探索图鉴四类（地点/人物/物品/设定词条）。

    每类都有下发上限：2000 轮存档的图鉴可能有几千条，全量塞进 /state 会让
    每次刷新都传几 MB。超出部分在面板里提示"还有 N 条"，完整数据仍在状态文件。
    """
    c = state.get("codex") if isinstance(state.get("codex"), dict) else {}
    out, truncated = {}, {}
    for key in ("locations", "people", "items", "lore"):
        rows = c.get(key) if isinstance(c.get(key), list) else []
        out[key] = [str(x) for x in rows[:MAX_CODEX_ITEMS]]
        if len(rows) > MAX_CODEX_ITEMS:
            truncated[key] = len(rows) - MAX_CODEX_ITEMS
    out["truncated"] = truncated
    return out


def _build_prose(state):
    """主舞台剧情回放：最近若干段正文的**完整文本**（不截断），供"过一遍剧情"。

    旧实现只把最新一段塞进 scene 并按 700 字截断，玩家看不到前因。
    这里额外下发最近 MAX_PROSE_ITEMS 段完整正文（含地点与回合），
    面板用可滚动列表呈现；更早的正文仍在状态文件/归档与 /history 里。
    """
    rows = state.get("prose") if isinstance(state.get("prose"), list) else []
    out = []
    for entry in rows[-MAX_PROSE_ITEMS:]:
        if not isinstance(entry, dict):
            continue
        out.append({
            "tick": _int_or(entry.get("tick", 0), 0),
            "location": str(entry.get("location") or ""),
            "text": str(entry.get("text") or ""),
            "chars": len(str(entry.get("text") or "")),
        })
    return {"items": out, "shown": len(out), "total": len(rows),
            "truncated": max(0, len(rows) - len(out))}


def _build_playbook(state):
    """玩法剧本：这一局按什么循环、进度看什么、失败怎么算、当前节拍、宿主要怎么带。"""
    try:
        return playbook_rules.summary(state, state.get("playbook") or {})
    except Exception as exc:  # aqg: top-level boundary —— 剧本坏了不影响主舞台其余部分
        return {"error": str(exc)[:120]}


def _build_quests(state):
    """事业线：只给已浮现的（dormant 不占版面，避免变成待办清单）。

    Also emits the stage graph (`graph`) so the panel can draw the whole DAG, not
    just the current stage. The data already exists in questlines[].stages[].next;
    exposing it costs nothing and turns a flat list into a map of where the story
    can go.
    """
    try:
        quests = state.get("questlines") or []
        return {
            "rows": quest_rules.status(state, quests),
            "total": len(quests),
            "visible": quest_rules.visible_count(state, quests),
            "graph": _build_quest_graph(state, quests),
        }
    except Exception as exc:  # aqg: top-level boundary
        return {"rows": [], "total": 0, "visible": 0, "graph": [], "error": str(exc)[:120]}


def _build_quest_graph(state, quests):
    """Flat node/edge list for the stage DAG, coloured by progression state.

    Nodes: {id, quest, title, state: done|current|open|dormant, objectives}
    Edges: {from, to}  — straight from the declared `next` lists.
    """
    nodes, edges = [], []
    for quest in quests:
        qid = str(quest.get("id") or "")
        progress = (state.get("quests") or {}).get(qid) or {}
        # `stage` is stored as a plain id string by questline.advance(); older
        # saves may hold the whole stage dict. Accept both instead of assuming.
        raw_stage = progress.get("stage")
        if isinstance(raw_stage, dict):
            current_stage = str(raw_stage.get("id") or "")
        else:
            current_stage = str(raw_stage or "")
        done = set(progress.get("done_stages") or [])
        failed = bool(progress.get("failed"))
        for stage in (quest.get("stages") or []):
            sid = str(stage.get("id") or "")
            if failed:
                node_state = "failed" if sid == current_stage else (
                    "done" if sid in done else "open")
            elif sid in done:
                node_state = "done"
            elif sid == current_stage:
                node_state = "current"
            else:
                node_state = "open"
            nodes.append({
                "id": "%s.%s" % (qid, sid),
                "quest": qid,
                "quest_title": str(quest.get("title") or ""),
                "stage": sid,
                "title": str(stage.get("title") or sid),
                "state": node_state,
                "objectives": [str(o) for o in (stage.get("objectives") or [])][:4],
            })
            for nxt in (stage.get("next") or []):
                edges.append({"from": "%s.%s" % (qid, sid), "to": "%s.%s" % (qid, nxt)})
    return {"nodes": nodes, "edges": edges}


def _build_lorebook(state):
    """世界书：每条目的触发次数、sticky/cooldown 剩余（只读展示，解释"为什么这段被触发"）。"""
    try:
        entries = state.get("lore") or []
        return {"rows": lore_engine.runtime_summary(state, entries), "total": len(entries)}
    except Exception as exc:  # aqg: top-level boundary
        return {"rows": [], "total": 0, "error": str(exc)[:120]}


def _unsettled_karma(state):
    ledger = state.get("karma_ledger") if isinstance(state.get("karma_ledger"), list) else []
    return sum(_int_or(e.get("amount", 0), 0) for e in ledger
               if isinstance(e, dict) and e.get("from") == "player" and not e.get("settled"))


def _chronicle(state, merged=None):
    """编年史：复用 `_build_events` 已合并的序列，只取最近 24 条并倒序（最新在上）。"""
    if merged is None:
        log = state.get("event_log") if isinstance(state.get("event_log"), list) else []
        raw = [e for e in log
               if isinstance(e, dict) and e.get("type") not in ("tick", "prose")]
        merged = _merge_adjacent(raw)
    return merged[-24:][::-1]


def _milestones(state):
    rows = state.get("milestones") if isinstance(state.get("milestones"), list) else []
    out = []
    for m in rows[-10:]:
        if not isinstance(m, dict):
            continue
        out.append("第%d回合·%s" % (_int_or(m.get("tick", 0), 0), str(m.get("desc") or "")))
    return out[::-1]


_DICT_FIELDS = ("entities", "relations", "market", "config", "ui", "codex", "places",
                "world_info", "playbook", "game", "context")
_LIST_FIELDS = ("event_log", "karma_ledger", "world_flags", "milestones", "summaries",
                "prose", "lore", "questlines", "checks", "factions")


def _coerce_state(state: dict) -> dict:
    """把顶层字段的类型归一：脏存档（手改/旧版本/截断恢复）也能渲染，不崩整页。

    只修**容器类型**与 tick，不动业务数值——具体数值由各 _build_* 自己宽松转换。
    """
    out = dict(state)
    for key in _DICT_FIELDS:
        if out.get(key) is not None and not isinstance(out.get(key), dict):
            out[key] = {}
    for key in _LIST_FIELDS:
        if out.get(key) is not None and not isinstance(out.get(key), list):
            out[key] = []
    out["tick"] = _int_or(out.get("tick", 0), 0)
    words = out.get("world_info") or {}
    out["world_info"] = {k: str(words.get(k) or "") for k in ("name", "era", "location_desc")}
    return out


def load_state_retry(state_path, attempts=3, delay=0.02):
    """读状态文件；MCP 正在原子替换时可能短暂读到半截/空文件，这里重试几次。

    与 MCP 的 save_state（临时文件 + os.replace）配合：正常情况下 replace 是原子的，
    但在 Windows 上杀毒/索引器短暂持有句柄时 open 会失败或读到旧 inode，
    面板不该因此把整页打成错误态。
    """
    from game_engine.state_schema import state_lock, _recover_archive
    with state_lock(state_path):
        _recover_archive(state_path)
        return _load_state_retry_locked(state_path, attempts, delay)


def _load_state_retry_locked(state_path, attempts, delay):
    last = None
    for i in range(max(1, int(attempts))):
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
            last = ValueError("状态文件顶层必须是 JSON 对象")
        except (OSError, ValueError) as exc:
            last = exc
        if i + 1 < attempts:
            time.sleep(delay * (i + 1))
    raise last if last else ValueError("状态文件不可读")


def view_model(state_path):
    """把状态文件转成面板要用的视图模型（只读，不改状态）。

    本函数只做"取数 + 组装"：每个子块由一个 `_build_*` 负责，
    因此单函数复杂度保持低位，也让每块能独立测试。
    """
    state = load_state_retry(state_path)
    if not isinstance(state, dict):
        raise ValueError("状态文件顶层必须是 JSON 对象")
    state = _coerce_state(state)
    try:
        sidecar = input_policy.validate_path(
            series_path(state_path), (".jsonl",), must_exist=False,
            root=os.path.dirname(os.path.abspath(state_path)))
        if not os.path.exists(sidecar) or os.path.getsize(sidecar) <= MAX_VIZ_SIDECAR_BYTES:
            record_sample(state_path, state)
    except (UnicodeError, ValueError, OSError):
        pass
    entities = state.get("entities") if isinstance(state.get("entities"), dict) else {}
    player = entities.get("player") if isinstance(entities.get("player"), dict) else {}
    loc = player.get("location", "")
    karma = _unsettled_karma(state)
    events, _, merged_events = _build_events(state)
    present, others = _build_cast(state, loc)

    return {
        "updated_at": time.strftime("%H:%M:%S"),
        "world": state.get("world_info", {}) or {},
        "tick": state.get("tick", 0),
        "seed": state.get("rng_seed"),
        "skin": skin_for_world(state),
        "terms": build_terms(state),
        "meta": {
            "state_path": os.path.abspath(state_path),
            "sidecar": os.path.abspath(series_path(state_path)),
            "inbox": os.path.abspath(inbox_path(state_path)),
            "read_only": True,
            "panel": "World Games 主舞台（只读）",
        },
        "scene": build_scene(state, events, player),
        "events": events,
        "relations": build_relations(state),
        "player": _build_player(state, player, loc, karma),
        "insights": _build_insights(state),
        "world_state": build_world(state),
        "moral": {
            "dims": MORAL_DIMS,
            "values": (player.get("morality") or [0, 0, 0, 0, 0, 0])[:6],
            "derived": _derived_moral(state),
        },
        "karma": karma,
        "present": present,
        "others": others,
        "codex": _build_codex(state),
        "lore_total": len(state.get("lore", [])),
        "market": _build_market(state),
        "chronicle": _chronicle(state, merged_events),
        "prose": _build_prose(state),
        "milestones": _milestones(state),
        "summaries": len(state.get("summaries") or []),
        "archived_events": int(state.get("archived_events", 0)),
        "flags": state.get("world_flags", []),
        "prose_count": len(state.get("prose") or []),
        "inbox_pending": len(inbox_pending(state_path)),
        "playbook": _build_playbook(state),
        "quests": _build_quests(state),
        "lorebook": _build_lorebook(state),
        "game": _build_game(state),
        "systems": _build_systems(state),
        "sessions": _build_sessions(state_path),
        "rules": _build_rules(state),
        "loop": _build_loop(state),
        "replay": _build_replay(state_path, state),
        "next_moves": _next_moves(
            state, player,
            state.get("playbook") or {},
            _build_quests(state),
            _build_loop(state)),
    }


def _build_rules(state):
    """Setting-declared rules: what fired, how often, in what priority order."""
    try:
        from game_engine.rules import rulebook as rulebook_rules
        return rulebook_rules.describe(state)
    except Exception as exc:  # aqg: boundary — a bad rulebook must not blank the panel
        return {"total": 0, "fired": 0, "rules": [], "error": str(exc)[:120]}


def _build_loop(state):
    """Loop signals: is the player circling, and which routes are dead ends."""
    try:
        from game_engine.rules import loopguard as loop_rules
        return loop_rules.summary(state)
    except Exception as exc:  # aqg: boundary
        return {"window": 0, "repeats": 0, "loop_suspected": False,
                "pruned_edges": [], "error": str(exc)[:120]}


def _build_replay(state_path, state):
    """Replay readiness: how many actions are logged, and the last fingerprint.

    The panel is read-only, so this reports capability and never replays; the
    actual replay runs through the MCP tools so it exercises production code.
    """
    try:
        from game_engine import action_log
        rows = action_log.read_actions(state_path, limit=5)
        total = int(state.get("actions_seq", 0) or 0)
        return {
            "logged": total,
            "log_file": os.path.basename(action_log.action_log_path(state_path)),
            "recent": [{"seq": r.get("seq"), "tick": r.get("tick"), "tool": r.get("tool")}
                       for r in rows],
            "last_state_hash": rows[-1].get("state_after") if rows else "",
        }
    except Exception as exc:  # aqg: boundary
        return {"logged": 0, "recent": [], "error": str(exc)[:120]}


def _build_game(state):
    """通用游戏档案 + 最近判定 + 上下文台账概览（任何题材都用同一块 UI）。"""
    out = {"profile": {}, "checks": [], "check_rate": {}, "context": {}}
    try:
        from game_engine.rules import gamesystem as game_rules
        out["profile"] = game_rules.profile_of(state)
    except Exception as exc:  # aqg: top-level boundary —— 档案坏了不影响其余面板
        out["profile"] = {"error": str(exc)[:120], "resources": [], "attributes": [],
                          "meters": [], "tags": [], "sheet": {}}
    try:
        from game_engine.rules import checks as check_rules
        out["checks"] = check_rules.summary(state, 10)
        out["check_rate"] = check_rules.win_rate(state)
    except Exception as exc:  # aqg: top-level boundary
        out["check_error"] = str(exc)[:120]
    try:
        from game_engine.rules import context as context_rules
        out["context"] = context_rules.summary(state)
    except Exception as exc:  # aqg: top-level boundary
        out["context"] = {"error": str(exc)[:120], "total": 0, "recent": [], "by_kind": {}}
    return out


def _build_sessions(state_path):
    """存档库只读清单（读目录与文件头，不写任何东西）。"""
    try:
        from game_engine import sessions as session_store
        root = session_store.saves_root(os.path.dirname(os.path.abspath(state_path)))
        rows = session_store.list_saves(root)
        active = os.path.abspath(state_path)
        for row in rows:
            row["active"] = os.path.abspath(row.get("path", "")) == active
        return {"root": root, "saves": rows[:50], "count": len(rows),
                "trash": len(session_store.list_trash(root))}
    except Exception as exc:  # aqg: top-level boundary —— 存档库读不到不影响主舞台
        return {"root": "", "saves": [], "count": 0, "trash": 0, "error": str(exc)[:120]}


def _build_systems(state):
    """体系概览（面板「体系」卡）：每套体系的紧凑摘要，不含完整 config。"""
    try:
        from game_engine.rules import systems as system_rules
        data = system_rules.summary(state)
        data["kinds"] = [{"kind": k, "label": system_rules.KIND_LABELS[k]}
                         for k in system_rules.KINDS]
        return data
    except Exception as exc:  # aqg: top-level boundary —— 体系坏了不影响主舞台其余部分
        return {"rows": [], "total": 0, "kinds": [], "error": str(exc)[:120]}


def _derived_moral(state):
    """引擎推导的六维道德（从业债台账/事件累加）；面板用它覆盖静态 morality。

    注意维度顺序必须与 `MORAL_DIMS`（中文展示名）一致，而引擎侧用的是英文键
    （care/fairness/loyalty/authority/sanctity/liberty）——两边顺序一一对应。
    推导失败时返回空表，前端自动回退到静态值。
    """
    try:
        from game_engine.rules.narrative_engine import MORAL_DIMS as ENGINE_DIMS
        from game_engine.rules.narrative_engine import update_player_moral_identity
        vec = update_player_moral_identity(state)
        return [int(vec.get(k, 0)) for k in ENGINE_DIMS]
    except Exception:  # aqg: top-level boundary —— 推导失败只用静态值
        return []


# ────────────────────────── 行动收件箱（双向通道，可选）──────────────────────────
# 面板仍然**只读状态文件**（INV-V1 不变）。玩家在浏览器里写的行动不进状态，
# 而是追加到 `<状态文件>.inbox.jsonl` 这个侧写文件；宿主 Agent 用 MCP 工具
# `pending_actions` 取走并照常经引擎结算。这样：
#   · 状态只有一个写入源（MCP），确定性 / 快照回退语义不被破坏；
#   · 玩家不必每回合切回对话框，浏览器就能排队行动；
#   · 宿主不在线时行动只是"排队"，不会凭空改世界。
INBOX_MAX_TEXT = 2000
INBOX_MAX_PENDING = 100
INBOX_LOCK_TIMEOUT = 5.0
INBOX_MAX_BYTES = 512 * 1024

# 进程内锁：HTTP handler 是线程池，同进程多线程也要串行化读-改-写。
_INBOX_TLOCK = threading.Lock()


def _file_lock(path, timeout=INBOX_LOCK_TIMEOUT):
    """Cross-process lock for the action inbox.

    Delegates to `state_schema._key_lock` so the panel and the state writer use
    one lock implementation. The inbox lives beside the state file, inside the
    same library scope, so the same key derivation applies.
    """
    from game_engine.state_schema import _key_lock
    return _key_lock(os.path.abspath(path), timeout)
def _atomic_write_text(path, text):
    """同目录临时文件 + os.replace：写到一半被杀也不会留下半个文件。"""
    import tempfile as _tf
    folder = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = _tf.mkstemp(prefix=".ww_inbox_", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def inbox_path(state_path):
    """收件箱侧写路径（与状态文件同目录，不参与打包）。"""
    return state_path + ".inbox.jsonl"


def inbox_read_all(state_path):
    """读全部收件记录（坏行跳过，永不抛）。"""
    if not state_path:
        return []
    from game_engine.state_schema import state_lock, _recover_archive
    with state_lock(state_path):
        _recover_archive(state_path)
        return _inbox_read_all_locked(state_path)


def _inbox_read_all_locked(state_path):
    out = []
    path = inbox_path(state_path)
    if not state_path or not os.path.exists(path):
        return out
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict) and rec.get('text'):
                    out.append(rec)
    except OSError:
        return []
    return out


def inbox_pending(state_path):
    """未处理的行动（按写入顺序，封顶 INBOX_MAX_PENDING）。"""
    return [r for r in inbox_read_all(state_path) if not r.get('done')][-INBOX_MAX_PENDING:]


def _rewrite_inbox(state_path, records):
    """整文件重写（原子 replace）。调用方必须已持有收件箱锁。"""
    body = "".join(json.dumps(rec, ensure_ascii=False) + "\n" for rec in records)
    _atomic_write_text(inbox_path(state_path), body)


def inbox_append(state_path, text, source='panel'):
    """追加一条行动；超出上限时丢弃最旧的未处理条目（有界 + 并发安全）。"""
    body = str(text or "").strip()
    if not body:
        raise ValueError("行动不能为空")
    body = body[:INBOX_MAX_TEXT]
    rec = {
        'id': hashlib.sha1(('%s|%s|%s' % (time.time_ns(), os.getpid(), body)).encode('utf-8'),
                           usedforsecurity=False).hexdigest()[:12],
        'ts': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'tick': None,
        'source': str(source)[:24],
        'text': body,
        'done': False,
    }
    from game_engine.state_schema import state_lock, _recover_archive
    with state_lock(state_path), _INBOX_TLOCK, _file_lock(inbox_path(state_path)):
        _recover_archive(state_path)
        if not os.path.isfile(state_path):
            raise FileNotFoundError(state_path)
        try:
            with open(state_path, 'r', encoding='utf-8') as f:
                rec['tick'] = _int_or(json.load(f).get('tick', 0), 0)
        except (OSError, ValueError, TypeError):
            pass
        records = inbox_read_all(state_path)
        records.append(rec)
        pending_idx = [i for i, r in enumerate(records) if not r.get('done')]
        if len(pending_idx) > INBOX_MAX_PENDING:
            drop = set(pending_idx[:len(pending_idx) - INBOX_MAX_PENDING])
            records = [r for i, r in enumerate(records) if i not in drop]
        # 字节上限兜底：已处理条目长期堆积也不能让侧写无限长
        while records and len("".join(json.dumps(r, ensure_ascii=False)
                                      for r in records)) > INBOX_MAX_BYTES:
            records.pop(0)
        _rewrite_inbox(state_path, records)
    return rec


def inbox_mark_done(state_path, ids):
    """把指定 id 标为已处理；返回实际标记条数（与 append 共用同一把锁）。"""
    wanted = {str(i) for i in ids}
    if not wanted:
        return 0
    n = 0
    from game_engine.state_schema import state_lock, _recover_archive
    with state_lock(state_path), _INBOX_TLOCK, _file_lock(inbox_path(state_path)):
        _recover_archive(state_path)
        if not os.path.isfile(state_path):
            raise FileNotFoundError(state_path)
        records = inbox_read_all(state_path)
        for r in records:
            if str(r.get('id')) in wanted and not r.get('done'):
                r['done'] = True
                r['done_ts'] = time.strftime('%Y-%m-%dT%H:%M:%S')
                n += 1
        if n:
            _rewrite_inbox(state_path, records)
    return n


STATIC_WHITELIST = {
    "/": ("panel.html", "text/html; charset=utf-8"),
    "/panel.html": ("panel.html", "text/html; charset=utf-8"),
    "/panel.css": ("panel.css", "text/css; charset=utf-8"),
    "/panel.js": ("panel.js", "text/javascript; charset=utf-8"),
    "/panel.theme.js": ("panel.theme.js", "text/javascript; charset=utf-8"),
    "/panel.i18n.js": ("panel.i18n.js", "text/javascript; charset=utf-8"),
    "/admin": ("admin.html", "text/html; charset=utf-8"),
    "/admin.html": ("admin.html", "text/html; charset=utf-8"),
    "/admin.js": ("admin.js", "text/javascript; charset=utf-8"),
    "/assets/echarts.min.js": (os.path.join("assets", "echarts.min.js"),
                               "text/javascript; charset=utf-8"),
}

from game_engine.viz_series import SERIES_CAP, load_series, record_sample, series_path  # noqa: E402


# 皮肤注册表：id → 视觉与图表调色板（前端只消费，不在 JS 里写配色表）
# 皮肤注册表：id → 视觉与图表调色板。
#
# 每个皮肤给两套主色：亮色主题下必须足够深才能在纸色底上达到 4.5:1，
# 暗色主题下才是原来的亮金/霓虹色。面板按 <html data-theme> 选用其一，
# 前端不再自己算主色（v1.8 让 JS 用 accent + "88" 拼半透明，结果文字色
# 在亮底上只有 1.8:1 —— 这是本轮实测抓到的真缺陷）。
SKINS = {
    "xuanshu": {
        "id": "xuanshu", "motif": "玄门·墨金",
        "accent": {"light": "#8a5a12", "dark": "#e8b04b"},
        "accent_fill": {"light": "#6d4610", "dark": "#b08a38"},
        "palette": {"line": "#e8b04b", "area": "rgba(232,176,75,.18)", "bar": "#c07a3a",
                    "hp": "#d9534f", "mp": "#4a90d9", "grid": "#2b3341", "text": "#a3abb9"},
    },
    "neutral": {
        "id": "neutral", "motif": "通用·石墨",
        "accent": {"light": "#33546f", "dark": "#8aa6c8"},
        "accent_fill": {"light": "#2c4a63", "dark": "#7d9cc0"},
        "palette": {"line": "#8aa6c8", "area": "rgba(138,166,200,.16)", "bar": "#6f8cab",
                    "hp": "#d9534f", "mp": "#4a90d9", "grid": "#2b3341", "text": "#a3abb9"},
    },
    "ink": {
        "id": "ink", "motif": "水墨·宣纸",
        "accent": {"light": "#3d4c59", "dark": "#a8b6c1"},
        "accent_fill": {"light": "#33404b", "dark": "#8d9aa6"},
        "palette": {"line": "#8fb0c9", "area": "rgba(143,176,201,.14)", "bar": "#7d8b96",
                    "hp": "#b4553f", "mp": "#5d7fa3", "grid": "#333a44", "text": "#9aa4b0"},
    },
    "neon": {
        "id": "neon", "motif": "霓虹·夜城",
        "accent": {"light": "#0b5f52", "dark": "#4fe0c0"},
        "accent_fill": {"light": "#0a5449", "dark": "#2f9a87"},
        "palette": {"line": "#4fe0c0", "area": "rgba(79,224,192,.16)", "bar": "#c74fe0",
                    "hp": "#ff5d7d", "mp": "#4fa8ff", "grid": "#243044", "text": "#93a4bd"},
    },
}


# 品牌默认值（单一信源，BRAND.md 与 README 引用此处；ui.brand/tagline 可整局覆盖）
DEFAULT_BRAND = "World Games"
DEFAULT_TAGLINE = "万物皆可为一局 · 规则为证"


def skin_for_world(state):
    """世界皮肤：优先取状态里的 ui 配置（设定包可写），否则按世界名启发式，未知一律回退 neutral。
    ui.brand / ui.tagline 让基于本引擎的其他游戏带上自己的品牌。"""
    world = state.get("world_info", {}) or {}
    ui = state.get("ui") if isinstance(state.get("ui"), dict) else {}
    sid = str(ui.get("skin") or "").strip().lower()
    if sid not in SKINS:
        text = ("%s %s" % (world.get("name", ""), " ".join(str(f) for f in (state.get("world_flags") or [])))).lower()
        sid = "xuanshu" if ("xuanshu" in text or "玄枢" in text) else "neutral"
    skin = dict(SKINS[sid])
    skin["palette"] = dict(SKINS[sid]["palette"])
    skin["accent"] = dict(SKINS[sid]["accent"])
    skin["accent_fill"] = dict(SKINS[sid]["accent_fill"])
    if ui.get("accent"):
        # 单值覆盖同时作用于两套主题：自定义主色多为深色墨金，亮底可读；
        # 若作者给了 {light, dark} 字典则分别生效。
        raw = ui["accent"]
        if isinstance(raw, dict):
            for mode in ("light", "dark"):
                if raw.get(mode):
                    skin["accent"][mode] = str(raw[mode])
                    skin["accent_fill"][mode] = str(raw[mode])
        else:
            skin["accent"] = {"light": str(raw), "dark": str(raw)}
            skin["accent_fill"] = {"light": str(raw), "dark": str(raw)}
    if ui.get("motif"):
        skin["motif"] = str(ui["motif"])
    skin["brand"] = str(ui.get("brand") or DEFAULT_BRAND)[:24]
    skin["tagline"] = str(ui.get("tagline") or DEFAULT_TAGLINE)[:48]
    return skin


class Handler(BaseHTTPRequestHandler):
    # 状态路径由 server 实例持有（见 _PanelServer.state_path）。
    # 旧实现把 state_path 写成**类属性**，于是同一进程里起第二个面板（换一局/换存档）
    # 会把第一个面板也指向新文件——实测两个面板同时开着时都显示后启动那一局。
    # 这里改成从 self.server 读取，每个面板互不干扰；类属性只作为兜底默认值。
    state_path = None

    def _state(self):
        return getattr(self.server, "state_path", None) or Handler.state_path

    def log_message(self, *args):  # 静音访问日志
        pass

    def handle_one_request(self):
        """浏览器/SSE 客户端随时可能掐断连接（刷新、关页签）——这是常态，不是错误。
        默认实现会把 ConnectionAbortedError 抛给 socketserver 打一整篇栈，这里吞掉。"""
        try:
            super().handle_one_request()
        except (ConnectionError, TimeoutError):
            self.close_connection = True

    # 基础安全响应头。面板是只读本地页，但"本地"不等于"可以裸奔"：
    # 任何页面都可能被别的本地进程/恶意扩展当作跳板，最小化攻击面是零成本的。
    _SECURITY_HEADERS = (
        ("X-Content-Type-Options", "nosniff"),          # 禁止 MIME 嗅探
        ("X-Frame-Options", "DENY"),                    # 禁止被 iframe 嵌入（防点击劫持）
        ("Referrer-Policy", "no-referrer"),             # 不外泄来源地址
        ("Content-Security-Policy",
         "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
         "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"),
    )

    def _drain_rejected_body(self):
        if self.command != 'POST' or getattr(self, '_body_consumed', False):
            return
        self._body_consumed = True
        lengths = self.headers.get_all('Content-Length', [])
        if self.headers.get('Transfer-Encoding') or len(lengths) != 1:
            return
        raw = lengths[0]
        if not raw.isascii() or not raw.isdigit() or len(raw) > 5:
            return
        length = int(raw)
        if length > self.MAX_BODY:
            return
        deadline = time.monotonic() + 0.25
        previous_timeout = self.connection.gettimeout()
        try:
            while length:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.connection.settimeout(remaining)
                chunk = self.rfile.read1(min(length, 4096))
                if not chunk:
                    break
                length -= len(chunk)
        except (OSError, ValueError):
            pass
        finally:
            self.connection.settimeout(previous_timeout)

    def _send(self, code, ctype, body):
        if self.command == 'POST':
            self.close_connection = True
            self._drain_rejected_body()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        if self.command == 'POST':
            self.send_header("Connection", "close")
        for name, val in self._SECURITY_HEADERS:
            self.send_header(name, val)
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path):
        """只发白名单里的固定文件；其余路径一律 404（不拼用户输入进文件系统）。"""
        entry = STATIC_WHITELIST.get(path)
        if not entry:
            self._send(404, "text/plain; charset=utf-8", b"not found")
            return
        fname, ctype = entry
        try:
            with open(os.path.join(HTML_DIR, fname), "rb") as f:
                body = f.read()
        except OSError:
            self._send(404, "text/plain; charset=utf-8", b"not found")
            return
        # 静态资源带 ETag：浏览器刷新时命中 304，省掉 1MB 的 ECharts 重传
        etag = '"%s"' % hashlib.sha1(body, usedforsecurity=False).hexdigest()[:16]
        if (self.headers.get("If-None-Match") or "").strip() == etag:
            self.send_response(304)
            for name, val in self._SECURITY_HEADERS:
                self.send_header(name, val)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("ETag", etag)
        for name, val in self._SECURITY_HEADERS:
            self.send_header(name, val)
        self.end_headers()
        self.wfile.write(body)

    MAX_BODY = 8192

    def _json_body(self, limit=None):
        """读请求体并解析 JSON。返回 (data, error)。error 为 None 表示成功。

        显式区分"超限/缺长度/编码错/JSON 错"四种失败，供调用方回 413/411/415/400；
        旧实现一律返回 None，客户端只能猜自己错在哪。
        """
        limit = self.MAX_BODY if limit is None else int(limit)
        raw_len = self.headers.get('Content-Length')
        if raw_len is None:
            return None, ('411', '缺少 Content-Length')
        try:
            n = int(raw_len)
        except (TypeError, ValueError):
            return None, ('400', 'Content-Length 不是数字')
        if n <= 0:
            return None, ('400', '请求体为空')
        if n > limit:
            return None, ('413', '请求体过大（上限 %d 字节）' % limit)
        self._body_consumed = True
        try:
            body = self.rfile.read(n)
        except OSError:
            return None, ('400', '读取请求体失败')
        if len(body) < n:
            return None, ('400', '请求体不完整（声明 %d，实收 %d）' % (n, len(body)))
        try:
            return json.loads(body.decode('utf-8')), None
        except UnicodeDecodeError:
            return None, ('415', '请求体必须是 UTF-8')
        except ValueError:
            return None, ('400', '请求体不是合法 JSON')

    _LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]", "::1")

    def _host_ok(self):
        """Host 头必须是本机回环名（防 DNS rebinding：恶意域名解析到 127.0.0.1 后读面板）。"""
        raw = (self.headers.get("Host") or "").strip()
        if not raw:
            return True                      # HTTP/1.0 客户端可能不带 Host，不因此拒绝
        host = raw.rsplit(":", 1)[0] if not raw.endswith("]") else raw
        if host.startswith("[") and "]" not in host:
            host = raw.rsplit(":", 1)[0]
        allow = getattr(self.server, "host_allow", None) or self._LOOPBACK_HOSTS
        return host.lower() in {h.lower() for h in allow}

    def do_POST(self):
        """唯一写入口：行动收件箱（状态文件仍然只读，INV-V1 不变）。

        本机服务不等于没有攻击面，因此：
          · Host 必须是回环名（防 DNS rebinding）；
          · 带 Origin 时必须与 Host 同源（跨站表单伪造会被拒）；
          · 只收 application/json（简单请求无法跨站伪造该 Content-Type）；
          · 请求体 ≤ 8KB、正文 ≤ 2000 字；
          · 未知路径一律 404，不回显任何内容。
        """
        path = self.path.split("?")[0]
        if path != '/action':
            self._send(404, 'text/plain; charset=utf-8', b'not found')
            return
        if not self._host_ok():
            self._send(403, 'application/json; charset=utf-8',
                       json.dumps({'ok': False, 'error': 'Host 不被允许'},
                                  ensure_ascii=False).encode('utf-8'))
            return
        origin = self.headers.get('Origin') or ''
        host = self.headers.get('Host') or ''
        if origin and origin.split('//')[-1] != host:
            self._send(403, 'application/json; charset=utf-8',
                       json.dumps({'ok': False, 'error': '跨站请求被拒绝'},
                                  ensure_ascii=False).encode('utf-8'))
            return
        ctype = (self.headers.get('Content-Type') or '').split(';')[0].strip().lower()
        if ctype != 'application/json':
            self._send(415, 'application/json; charset=utf-8',
                       json.dumps({'ok': False, 'error': '只接受 application/json'},
                                  ensure_ascii=False).encode('utf-8'))
            return
        body, body_err = self._json_body()
        if body_err is not None:
            code, msg = body_err
            self._send(int(code), 'application/json; charset=utf-8',
                       json.dumps({'ok': False, 'error': msg},
                                  ensure_ascii=False).encode('utf-8'))
            return
        if not isinstance(body, dict):
            self._send(400, 'application/json; charset=utf-8',
                       json.dumps({'ok': False, 'error': '请求体必须是 JSON 对象'},
                                  ensure_ascii=False).encode('utf-8'))
            return
        text = str(body.get('text') or '').strip()
        if not text:
            self._send(400, 'application/json; charset=utf-8',
                       json.dumps({'ok': False, 'error': '行动不能为空'},
                                  ensure_ascii=False).encode('utf-8'))
            return
        if len(text) > INBOX_MAX_TEXT:
            self._send(400, 'application/json; charset=utf-8',
                       json.dumps({'ok': False,
                                   'error': '行动太长（上限 %d 字）' % INBOX_MAX_TEXT},
                                  ensure_ascii=False).encode('utf-8'))
            return
        try:
            rec = inbox_append(self._state(), text)
        except OSError as exc:
            self._send(500, 'application/json; charset=utf-8',
                       json.dumps({'ok': False,
                                   'error': '写入收件箱失败：%s' % str(exc)[:120]},
                                  ensure_ascii=False).encode('utf-8'))
            return
        self._send(200, 'application/json; charset=utf-8',
                   json.dumps({'ok': True, 'queued': rec,
                               'pending': len(inbox_pending(self._state()))},
                              ensure_ascii=False).encode('utf-8'))

    def do_GET(self):
        if not self._host_ok():
            self._send(403, 'text/plain; charset=utf-8', b'host not allowed')
            return
        path = urllib.parse.urlsplit(self.path).path
        if path in ('/actions', '/series', '/health'):
            try:
                from game_engine.state_schema import state_lock, _recover_archive
                with state_lock(self._state()):
                    _recover_archive(self._state())
            except RuntimeError as exc:
                body = json.dumps({'error': str(exc), 'pending_review': True}, ensure_ascii=False).encode('utf-8')
                self._send(409, 'application/json; charset=utf-8', body)
                return
        if path == "/state":
            try:
                vm = json.dumps(view_model(self._state()), ensure_ascii=False).encode("utf-8")
            except FileNotFoundError:
                vm = json.dumps({
                    "error": "对局状态文件不存在：%s" % self._state(),
                    "hint": "先在对话里开一局（world_init / load_setting），本页会自动接上。",
                }, ensure_ascii=False).encode("utf-8")
            except Exception as e:  # aqg: top-level boundary —— HTTP 端点：任何读取失败都转成页面可读错误，不抛栈
                vm = json.dumps({
                    "error": "状态文件读取失败：%s" % str(e)[:180],
                    "hint": "文件可能正在写入或格式不合法；稍候重试，或先用 snapshot 校验存档。",
                }, ensure_ascii=False).encode("utf-8")
            self._send(200, "application/json; charset=utf-8", vm)
        elif path == "/actions":
            body = json.dumps({'pending': inbox_pending(self._state())},
                              ensure_ascii=False).encode('utf-8')
            self._send(200, 'application/json; charset=utf-8', body)
        elif path == "/export":
            try:
                from game_engine.state_schema import state_lock, _recover_archive
                with state_lock(self._state()):
                    _recover_archive(self._state())
                    with open(self._state(), 'rb') as f:
                        raw = f.read()
            except RuntimeError as exc:
                self._send(409, 'application/json; charset=utf-8',
                           json.dumps({'error': str(exc), 'pending_review': True}, ensure_ascii=False).encode('utf-8'))
                return
            except OSError as exc:
                self._send(404, 'application/json; charset=utf-8',
                           json.dumps({'error': '状态文件不可读：%s' % str(exc)[:120]},
                                      ensure_ascii=False).encode('utf-8'))
                return
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Content-Disposition',
                             'attachment; filename="%s"' % os.path.basename(self._state()))
            for name, val in self._SECURITY_HEADERS:
                self.send_header(name, val)
            self.end_headers()
            self.wfile.write(raw)
        elif path == "/series":
            body = json.dumps(self._series_payload(), ensure_ascii=False).encode("utf-8")
            self._send(200, "application/json; charset=utf-8", body)
        elif path == "/health":
            state_ok, state_note = True, ""
            try:
                st = os.stat(self._state())
                state_note = "%d bytes" % st.st_size
            except OSError as exc:
                state_ok, state_note = False, str(exc)[:80]
            body = json.dumps({
                "ok": state_ok, "state": os.path.abspath(self._state()),
                "state_note": state_note,
                "sse_max_seconds": self.SSE_MAX_SECONDS,
                "inbox_pending": len(inbox_pending(self._state())),
                "version": _PANEL_VERSION,
            }, ensure_ascii=False).encode("utf-8")
            self._send(200, "application/json; charset=utf-8", body)
        elif path == "/history":
            try:
                body = json.dumps(self._history_payload(), ensure_ascii=False).encode("utf-8")
            except RuntimeError as exc:
                body = json.dumps({'error': str(exc), 'pending_review': True}, ensure_ascii=False).encode('utf-8')
                self._send(409, 'application/json; charset=utf-8', body)
                return
            self._send(200, "application/json; charset=utf-8", body)
        elif path == "/admin/sessions":
            body = json.dumps(self._sessions_payload(), ensure_ascii=False).encode('utf-8')
            self._send(200, "application/json; charset=utf-8", body)
        elif path == "/events":
            self._sse()
        else:
            self._static(path)

    def _sessions_payload(self):
        """Read-only save-library listing for the console.

        Goes through sessions.py (the same library the MCP tools use) so the
        console cannot disagree with session_list. Never mutates anything.
        """
        try:
            from game_engine import sessions as session_store
        except ImportError:
            return {'error': 'save library unavailable', 'count': 0, 'sessions': []}

        current = os.path.abspath(self._state()) if self._state() else ''
        root = session_store.saves_root(os.path.dirname(current) if current else '')
        try:
            entries = session_store.list_saves(root)
        except Exception as exc:  # aqg: boundary — console must never 500 on a listing
            return {'error': str(exc)[:160], 'count': 0, 'sessions': []}

        rows = []
        for item in entries:
            path = item.get('path') or ''
            rows.append({
                'name': item.get('name', ''),
                'tick': item.get('tick'),
                'world': item.get('world', ''),
                'size_kb': round(float(item.get('bytes') or 0) / 1024.0, 1),
                'modified': item.get('updated', ''),
                'pending_review': bool(item.get('pending_review')),
                'current': bool(path) and os.path.abspath(path) == current,
                'root': root,
            })
        return {'sessions': rows, 'count': len(rows), 'root': root}

    def _history_payload(self, query=""):
        from game_engine.state_schema import state_lock, _recover_archive
        with state_lock(self._state()):
            _recover_archive(self._state())
            return self._history_payload_locked(query)

    def _history_payload_locked(self, query=""):
        """剧情回放 / 归档检索（只读，分页）。

        数据源三层：
          1. `state["prose"]`  —— 当前在内存里的最近正文（完整文本）
          2. `<state>.log*.jsonl` —— 归档事件与旧正文（只读扫描，按 query 过滤）
        返回结构固定、有上限，避免长局把响应打爆。
        查询参数：q（关键词）、limit（默认 50，上限 200）、scope（prose|archive|all）
        """
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        q = str((params.get("q") or [query or ""])[0]).strip().lower()
        try:
            limit = int((params.get("limit") or ["50"])[0])
        except (TypeError, ValueError):
            limit = 50
        limit = max(1, min(MAX_HISTORY_PAGE, limit))
        scope = str((params.get("scope") or ["all"])[0]).lower()
        if scope not in ("prose", "archive", "all"):
            scope = "all"

        state = {}
        state_error = ""
        try:
            state = load_state(self._state())
        except (OSError, ValueError, TypeError) as exc:
            state_error = str(exc)[:160]

        prose_rows, prose_total = [], 0
        if state and scope in ("prose", "all"):
            rows = state.get("prose") if isinstance(state.get("prose"), list) else []
            prose_total = len(rows)
            for entry in rows:
                if not isinstance(entry, dict):
                    continue
                text = str(entry.get("text") or "")
                if q and q not in text.lower():
                    continue
                prose_rows.append({"tick": _int_or(entry.get("tick", 0), 0),
                                   "location": str(entry.get("location") or ""),
                                   "text": text, "chars": len(text)})
            prose_rows = prose_rows[-limit:][::-1]

        archive_rows, archive_scanned, archive_total = [], 0, 0
        if scope in ("archive", "all"):
            base = self._state()
            folder = os.path.dirname(os.path.abspath(base)) or "."
            prefix = os.path.basename(base) + ".log"
            files = []
            try:
                files = sorted(f for f in os.listdir(folder)
                               if f.startswith(prefix) and f.endswith(".jsonl"))
            except OSError:
                files = []
            # 从最新世代往前扫；命中 limit 条即停，避免长局扫穿几个 GB
            for fname in reversed(files):
                path = os.path.join(folder, fname)
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        for line in fh:
                            archive_scanned += 1
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                rec = json.loads(line)
                            except ValueError:
                                continue
                            if not isinstance(rec, dict):
                                continue
                            if rec.get("type") not in (None, "prose", "combat", "social",
                                                       "trade", "karma", "travel", "world",
                                                       "quest", "context", "sheet", "check"):
                                continue
                            text = str(rec.get("text") or rec.get("desc") or "")
                            if not text:
                                continue
                            if q and q not in text.lower():
                                continue
                            archive_total += 1
                            if len(archive_rows) < limit:
                                archive_rows.append({
                                    "tick": _int_or(rec.get("tick", 0), 0),
                                    "type": str(rec.get("type") or ""),
                                    "text": text,
                                })
                            if len(archive_rows) >= limit and q:
                                break
                except OSError:
                    continue
                if len(archive_rows) >= limit and q:
                    break
            archive_rows.reverse()
            archive_rows = archive_rows[:limit]

        return {
            "query": q, "limit": limit, "scope": scope,
            "prose": {"items": prose_rows, "total": prose_total,
                      "returned": len(prose_rows)},
            "archive": {"items": archive_rows, "scanned": archive_scanned,
                        "matched": archive_total, "returned": len(archive_rows)},
            "state_error": state_error,
            "read_only": True,
        }

    def _series_payload(self):
        """长局态势序列：直接读侧写文件（不读也不写状态文件）。"""
        try:
            sidecar = series_path(self._state())
            if os.path.lexists(sidecar) and os.path.getsize(sidecar) > MAX_VIZ_SIDECAR_BYTES:
                samples = []
            else:
                samples = load_series(self._state())
        except (OSError, UnicodeError, ValueError, TypeError):
            samples = []          # 侧写坏行/缺文件 → 图表空态，接口照常 200
        skin = SKINS["neutral"]
        try:
            skin = skin_for_world(load_state_retry(self._state(), attempts=2))
        except (OSError, ValueError, TypeError):
            pass                  # 状态不可读时调色板退回 neutral；错误态由 /state 负责展示
        return {"samples": samples, "cap": SERIES_CAP, "palette": skin.get("palette", {})}

    def _state_payload(self):
        """SSE 每帧的 JSON：状态不可读时不是断流，而是把原因推给页面显示。"""
        try:
            return json.dumps(view_model(self._state()), ensure_ascii=False)
        except FileNotFoundError:
            return json.dumps({
                "error": "对局状态文件不存在：%s" % self._state(),
                "hint": "先在对话里开一局（world_init / load_setting），本页会自动接上。",
            }, ensure_ascii=False)
        except Exception as e:  # aqg: top-level boundary —— SSE 端点：状态不可读时推错误帧而不是断流
            return json.dumps({
                "error": "状态文件读取失败：%s" % str(e)[:180],
                "hint": "文件可能正在写入或格式不合法；稍候重试，或先用 snapshot 校验存档。",
            }, ensure_ascii=False)

    SSE_TICK = 0.5
    SSE_MAX_SECONDS = 1800        # 单条连接最长 30 分钟；浏览器 EventSource 会自动重连
    SSE_MAX_FRAMES = 3600

    def _sse(self):
        """SSE 推送：状态文件一变就发一帧 state；无变化时只发心跳注释。

        资源护栏：
          · 连接有最长寿命与最大帧数，不会永久占用线程；
          · 状态没变时不重复序列化整个视图模型（长局里 /state 可能几百 KB）；
          · 任何写失败立刻返回，交给 socketserver 回收线程。
        """
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        last = object()
        started = time.time()
        frames = 0
        try:
            while frames < self.SSE_MAX_FRAMES:
                if time.time() - started > self.SSE_MAX_SECONDS:
                    self.wfile.write(b"event: bye\ndata: {}\n\n")
                    self.wfile.flush()
                    return
                try:
                    st = os.stat(self._state())
                    sig = (st.st_mtime_ns, st.st_size)
                except OSError:
                    sig = None
                if sig != last:
                    last = sig
                    body = self._state_payload()
                    self.wfile.write(("event: state\ndata: %s\n\n" % body).encode("utf-8"))
                    frames += 1
                else:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
                time.sleep(self.SSE_TICK)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError,
                OSError, ValueError):
            return


class _PanelServer(ThreadingHTTPServer):
    """面板 HTTP 服务。

    allow_reuse_address 必须是 False：Python 的 HTTPServer 默认把它设为 1
    （SO_REUSEADDR）。在 Windows 上这允许**两个进程同时绑定同一端口**，
    结果是请求被别的进程抢走、面板返回 404 而自己毫无察觉
    （实测被一个无关的 `python -m http.server 8791` 抢过）。
    关掉它，端口冲突就会正常抛 OSError，从而走下面的顺延逻辑。

    `state_path` 挂在 server 实例上（不是 Handler 类属性）：同进程可以同时开
    多个面板看不同存档，互不串台。
    """

    allow_reuse_address = False
    daemon_threads = True
    state_path = None

    def __init__(self, address, handler_cls, state_path=None):
        super().__init__(address, handler_cls)
        self.state_path = os.path.abspath(state_path) if state_path else None


def start(state_path, port=8765, host="127.0.0.1", host_allow=None,
          bind_attempts=10, port_fallback="scan"):
    """启动面板服务（后台线程），返回 (server, 实际端口)。端口被占则自动顺延。

    `host_allow`：允许访问的 Host 头白名单（默认只允许本机回环名）。
    `state_path` 绑定在 server 实例上，多个面板互不干扰。

    `port_fallback` 决定首选端口不可用时的策略：
      · "scan"（默认）：先顺延 `bind_attempts` 个端口，仍失败就向系统要一个
        空闲端口。CI 上同一次作业会连开多个面板（面板契约、MCP e2e、界面巡检），
        固定窗口扫完 10 个就被判"全被占用"，而其实只是前面的实例还没释放。
      · "strict"：只在窗口内顺延，失败即抛。用于需要可预测端口的调用方。
    """
    resolved = os.path.abspath(state_path)
    srv = None
    for p in range(int(port), int(port) + max(1, int(bind_attempts))):
        try:
            srv = _PanelServer((host, p), Handler, state_path=resolved)
            break
        except OSError:
            continue
    if srv is None and port_fallback == "scan":
        try:
            srv = _PanelServer((host, 0), Handler, state_path=resolved)
        except OSError:
            srv = None
        if srv is not None:
            # 记录一下：调用方拿到的端口与请求的不同，排障时需要知道原因。
            # 只在显式要求时报（WG_PANEL_PORT_VERBOSE=1）：这行本身带端口号，
            # 而测试套件用 stderr 是否为空来判定"运行是否干净"，端口每次不同
            # 会让同一份代码的两次运行看起来不一样。
            if os.environ.get("WG_PANEL_PORT_VERBOSE") == "1":
                print("面板端口 %s 不可用，已改用系统分配端口 %d"
                      % (port, srv.server_address[1]), file=sys.stderr)
    if srv is None:
        raise RuntimeError("端口 %s~%s 都被占用"
                           % (port, int(port) + max(1, int(bind_attempts)) - 1))
    srv.host_allow = host_allow
    threading.Thread(target=srv.serve_forever, daemon=True, name="panel-%d" % srv.server_address[1]).start()
    return srv, srv.server_address[1]


def stop(srv, timeout=5.0):
    """优雅停止：shutdown() 停 accept 循环，server_close() 释放端口。

    只调用 shutdown() 时 socket 仍处于监听状态，紧接着在同一端口重启会失败
    （Windows 上尤其明显）。反复 stop 是幂等的。
    """
    if srv is None:
        return
    try:
        srv.shutdown()
    except Exception:  # aqg: top-level boundary —— 已停止的 server 再 shutdown 会抛，忽略
        pass
    try:
        srv.server_close()
    except Exception:  # aqg: top-level boundary —— 同上
        pass


def main():
    ap = argparse.ArgumentParser(description="World Games 实况面板")
    ap.add_argument("--state", default="ww_state.json", help="状态文件路径")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    if not os.path.exists(args.state):
        print("状态文件不存在: %s" % args.state)
        return 1
    srv, port = start(args.state, args.port, args.host)
    print("面板已启动: http://%s:%d/   （盯住 %s，Ctrl+C 退出）" % (args.host, port, args.state))
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        stop(srv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
