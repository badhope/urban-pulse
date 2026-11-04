"""
世界书引擎 (Lorebook) —— 与酒馆 semantic 对齐，但**逐回合确定性**

为什么单独成模块：旧实现只有一个近似 AND 的关键词过滤器（constant + 主键 + 副键），
导入一份真正的 SillyTavern 世界书会静默丢掉大部分语义：selectiveLogic 的四种组合、
递归扫描、概率、sticky/cooldown/delay、同组互斥、scanDepth。

这个模块把那些语义按“回合（tick）”重实现：
  · **时间单位是 tick，不是消息条数**——本引擎的回合是离散且落盘的，比聊天消息更可靠；
  · **所有随机都由 sha256(seed|tick|entry) 派生**，不消耗 rng_counter（INV-E7）；
  · **触发历史写进 state["lore_runtime"]**，因此快照回退后重放一致（INV-E4）。

不实现的（明确标为不支持，见 docs/LOREBOOK.md）：
  position / depth / role / outlet（提示词布局属于宿主）、vectorized（需嵌入模型）、
  automationId / triggers / characterFilter（SillyTavern 前端脚本能力）。
"""

import hashlib

MAX_RECURSION = 3
DEFAULT_SCAN_DEPTH = 2
RUNTIME_CAP = 400
HISTORY_CAP = 200

# SillyTavern 的 selectiveLogic 枚举
LOGIC_AND_ANY = 0
LOGIC_NOT_ALL = 1
LOGIC_NOT_ANY = 2
LOGIC_AND_ALL = 3

LOGIC_NAMES = {
    LOGIC_AND_ANY: "AND_ANY",
    LOGIC_NOT_ALL: "NOT_ALL",
    LOGIC_NOT_ANY: "NOT_ANY",
    LOGIC_AND_ALL: "AND_ALL",
}


def _unit(seed, tick, key):
    raw = ("%s|%s|%s" % (seed, tick, key)).encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big") / float(1 << 64)


def _entry_id(entry, index=0):
    """条目标识：优先 comment，其次首个关键词，最后序号。用于运行时状态与随机派生。"""
    if entry.get("id") is not None:
        return str(entry["id"])
    if entry.get("comment"):
        return str(entry["comment"])
    keys = entry.get("keys") or []
    if keys:
        return str(keys[0])
    return "entry:%d" % index


def _normalize_logic(value):
    """接受 0-3 的数字，也接受字符串（AND_ANY 等）。未知值回退 AND_ANY。"""
    if isinstance(value, bool):
        return LOGIC_AND_ANY
    if isinstance(value, int) and value in LOGIC_NAMES:
        return value
    if isinstance(value, str):
        text = value.strip().upper()
        for num, name in LOGIC_NAMES.items():
            if text == name:
                return num
    return LOGIC_AND_ANY


def _hits(entry, text, low):
    """关键词命中判定（大小写与整词由条目自身决定）。"""
    case = bool(entry.get("case_sensitive"))
    whole = bool(entry.get("match_whole_words"))

    def one(key):
        if not key:
            return False
        hay = text if case else low
        needle = key if case else key.lower()
        if not whole:
            return needle in hay
        # 整词匹配：用非字母数字做边界（中英文都成立）
        def word_char(ch):
            # 只把 ASCII 字母/数字当"词内字符"：中文没有词边界，
            # 用 str.isalnum() 会把「一盏灯」的「盏」当成词内字符，导致整词匹配在中文里永远失败（实测）。
            return ch.isascii() and ch.isalnum()

        idx = 0
        while True:
            idx = hay.find(needle, idx)
            if idx < 0:
                return False
            before = hay[idx - 1] if idx > 0 else " "
            after = hay[idx + len(needle)] if idx + len(needle) < len(hay) else " "
            if not word_char(before) and not word_char(after):
                return True
            idx += len(needle)

    return one


def _match_primary(entry, text, low):
    hit = _hits(entry, text, low)
    return any(hit(k) for k in (entry.get("keys") or []))


def _match_secondary(entry, text, low):
    sec = entry.get("secondary_keys") or []
    if not sec:
        return True
    hit = _hits(entry, text, low)
    return any(hit(k) for k in sec)


def _selective_ok(entry, text, low):
    """selectiveLogic 四种组合。

    AND_ANY（默认）：主键命中 + 任一副键命中
    NOT_ALL：主键命中 + 不是所有副键都命中
    NOT_ANY：主键命中 + 没有任何副键命中
    AND_ALL：主键命中 + 所有副键都命中
    """
    if not entry.get("selective"):
        return _match_secondary(entry, text, low)
    sec = entry.get("secondary_keys") or []
    if not sec:
        return True
    hit = _hits(entry, text, low)
    matched = sum(1 for k in sec if hit(k))
    logic = _normalize_logic(entry.get("selective_logic", entry.get("selectiveLogic")))
    if logic == LOGIC_AND_ALL:
        return matched == len(sec)
    if logic == LOGIC_NOT_ALL:
        return matched < len(sec)
    if logic == LOGIC_NOT_ANY:
        return matched == 0
    return matched >= 1


def _runtime(state):
    rt = state.setdefault("lore_runtime", {})
    for key in ("last_fired", "sticky_until", "cooldown_until", "fired_count", "delayed_until"):
        rt.setdefault(key, {})
    return rt


def _availability(entry, rt, tick):
    """once / max_fires / sticky / cooldown / delay 五个闸。返回 (可触发, 原因)。

    once / max_fires 借自 ink 的"选项只能用一次"（once-only choice）：
    关键剧情条目（"第一次见到灯塔守夜人"）不该因为关键词再次出现就重复注入。
    计数用已有的 fired_count，快照回退后与状态一起回退，重放一致。
    """
    eid = entry["_eid"]
    fired = int(rt["fired_count"].get(eid, 0) or 0)
    if entry.get("once") and fired > 0:
        return False, "once"
    limit = entry.get("max_fires")
    if limit is not None:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 0
        if limit > 0 and fired >= limit:
            return False, "max_fires"
    # delay=N：**第 N 回合起**才可用（N=0 表示不限）。
    # 与 SillyTavern 的"需要 N 条消息"同义，只是这里以 tick 计。
    delay = int(entry.get("delay") or 0)
    if delay > 0 and tick < delay:
        return False, "delay"
    sticky_until = int(rt["sticky_until"].get(eid, -1) or -1)
    if sticky_until >= tick:
        return True, "sticky"          # sticky 期间不重掷概率、也不受 cooldown 影响
    cooldown_until = int(rt["cooldown_until"].get(eid, -1) or -1)
    if cooldown_until > tick:
        return False, "cooldown"
    return True, ""


def _probability_ok(entry, state, tick):
    """概率闸：useProbability/probability（酒馆语义），用确定性派生。"""
    if not entry.get("use_probability", True):
        return True
    p = entry.get("probability")
    if p is None:
        return True
    try:
        p = float(p)
    except (TypeError, ValueError):
        return True
    try:
        scale = float(entry.get("probability_scale", 0) or 0)
    except (TypeError, ValueError):
        scale = 0.0
    # 酒馆语义：probability 是 0-100 的百分比。历史实现把 0<p<=1 当成"比例"，
    # 导致 probability=1（1%）变成 100% 恒触发——与酒馆语义相反。
    # normalize 会写入 probability_scale（百分比=100，旧比例=1）；手写条目没有该字段时
    # 按"1 及以上=百分比、小于 1=比例"解释，兼容旧配置。
    if scale == 1:
        ratio = p
    elif scale == 100:
        ratio = p / 100.0
    else:
        ratio = p / 100.0 if p >= 1 else p
    if ratio >= 1.0:
        return True
    if ratio <= 0.0:
        return False
    return _unit(state.get("rng_seed") or 0, tick, "lore:" + entry["_eid"]) < ratio


def _group_split(candidates):
    """把候选分成"独立条目"与"分组桶"。"""
    groups, singles = {}, []
    for entry in candidates:
        group = entry.get("group")
        if group:
            groups.setdefault(str(group), []).append(entry)
        else:
            singles.append(entry)
    return singles, groups


def _match_score(entry, text, low):
    """组内评分：命中主键数 + 命中副键数（SillyTavern WorldInfoBuffer.getScore 同义）。

    与"按 groupWeight 抽签"的区别：抽签把"关键词命中更精确的条目"和"只沾一个边"的
    条目当成同权；评分让最贴合当轮文本的那条胜出，避免长局里设定条目轮流坐庄。
    """
    hit = _hits(entry, text, low)
    primary = sum(1 for k in (entry.get("keys") or []) if hit(k))
    secondary = sum(1 for k in (entry.get("secondary_keys") or []) if hit(k))
    return primary + secondary


def _pick_group(pool, state, tick, name, text="", low="", scoring=False):
    """同组互斥：groupOverride 优先；开了 group scoring 取命中分最高；
    否则按 groupWeight 做确定性加权随机。"""
    override = next((e for e in pool if e.get("group_override")), None)
    if override:
        return override
    if scoring and (text or low):
        scored = [(_match_score(e, text, low), e) for e in pool]
        best = max(score for score, _e in scored)
        finalists = [e for score, e in scored if score == best]
        if len(finalists) == 1:
            return finalists[0]
        pool = finalists
    weights = [max(0.01, float(e.get("group_weight") or 100.0)) for e in pool]
    total = sum(weights)
    roll = _unit(state.get("rng_seed") or 0, tick, "lore_group:" + name) * total
    acc = 0.0
    for entry, weight in zip(pool, weights):
        acc += weight
        if roll <= acc:
            return entry
    return pool[-1]


def mark_fired(state, entry, tick):
    """记录一次触发：更新 last_fired / sticky / cooldown / 计数。"""
    rt = _runtime(state)
    eid = entry["_eid"]
    rt["last_fired"][eid] = int(tick)
    rt["fired_count"][eid] = int(rt["fired_count"].get(eid, 0) or 0) + 1
    sticky = int(entry.get("sticky") or 0)
    cooldown = int(entry.get("cooldown") or 0)
    if sticky > 0:
        rt["sticky_until"][eid] = int(tick) + sticky
    if cooldown > 0:
        # 酒馆语义：cooldown 从 sticky 结束后起算
        rt["cooldown_until"][eid] = int(tick) + max(0, sticky) + cooldown
    for store in ("last_fired", "sticky_until", "cooldown_until", "fired_count", "delayed_until"):
        if len(rt[store]) > RUNTIME_CAP:
            for key in list(rt[store])[:len(rt[store]) - RUNTIME_CAP]:
                rt[store].pop(key, None)
    history = state.setdefault("lore_history", [])
    history.append({"tick": int(tick), "entry": eid, "comment": entry.get("comment", "")})
    if len(history) > HISTORY_CAP:
        del history[:len(history) - HISTORY_CAP]


def _decorate(entries):
    out = []
    for i, entry in enumerate(entries or []):
        if not entry or not entry.get("enabled", True):
            continue
        item = dict(entry)
        item["_eid"] = _entry_id(entry, i)
        out.append(item)
    return out


def _collect(batch, sticky_only, state, tick, depth, reason, chosen, skipped, group_won,
             text="", low=""):
    """从候选里做分组裁决 + 概率闸，写入 chosen。"""
    singles, groups = _group_split(batch)
    winners = list(singles)
    global_scoring = bool((state.get("config") or {}).get("lore_group_scoring", False))
    for name in sorted(groups):
        if name in group_won:
            skipped.append({"entry": groups[name][0]["_eid"], "why": "group"})
            continue
        pool = [e for e in groups[name] if e.get("group_override")] or groups[name]
        scoring = global_scoring or any(e.get("use_group_scoring") for e in groups[name])
        winner = _pick_group(pool, state, tick, name, text=text, low=low, scoring=scoring)
        group_won[name] = winner["_eid"]
        winners.append(winner)
    for entry in winners:
        eid = entry["_eid"]
        if eid in chosen:
            continue
        if eid not in sticky_only and not entry.get("constant")                 and not _probability_ok(entry, state, tick):
            skipped.append({"entry": eid, "why": "probability"})
            continue
        entry["_depth"] = depth
        entry["_reason"] = "sticky" if eid in sticky_only else reason
        chosen[eid] = entry


def _scan(pool, text, low, depth, reason, state, rt, tick, chosen, skipped, group_won):
    """扫描一批条目：时间闸 → 命中 → 分组/概率 → 记录。"""
    batch, sticky_only = [], set()
    for entry in pool:
        eid = entry["_eid"]
        if eid in chosen:
            continue
        ok, why = _availability(entry, rt, tick)
        if not ok:
            if why:
                skipped.append({"entry": eid, "why": why})
            continue
        if why == "sticky":
            # sticky 是把条目"保持在上下文中"，不是重新触发：
            # 重掷概率会破坏确定性，重记 mark_fired 会让 sticky 无限续期（实测永不结束）。
            batch.append(entry)
            sticky_only.add(eid)
            continue
        if entry.get("constant") and depth == 0:
            batch.append(entry)
        elif _match_primary(entry, text, low) and _selective_ok(entry, text, low):
            batch.append(entry)
    _collect(batch, sticky_only, state, tick, depth, reason, chosen, skipped, group_won,
             text=text, low=low)


def _recursion_feed(chosen, depth):
    return "\n".join(str(e.get("content") or "") for e in chosen.values()
                     if int(e.get("_depth", 0)) == depth - 1)


def trigger(state, entries, scan_texts, tick=None, apply_runtime=True):
    """按当前局面选出应注入的世界书条目（已按 insertion_order 排序）。

    参数：
      entries      规范化后的条目列表（见 settings_loader.normalize_lore_entry）
      scan_texts   本轮参与扫描的文本（通常 = 场景文字 + 在场人物名 + 最近事件）
    返回 dict：
      entries      本轮命中的条目（含 _eid / _depth / _reason）
      by_depth     每层递归的条目数
      skipped      因时间闸/概率/分组被跳过的条目 id（面板"为什么没触发"用）
    """
    tick = int(state.get("tick", 0) or 0) if tick is None else int(tick)
    if isinstance(scan_texts, str):
        scan_texts = [scan_texts]
    scan_texts = [str(t) for t in (scan_texts or []) if str(t).strip()]

    decorated = _decorate(entries)
    # 递归扫描默认**关闭**（与 SillyTavern 的 "Recursive scanning" 默认一致）：
    # 条目正文互相含关键词时，递归会把整本书都拉进来（实测 21 条触发 20 条），
    # 叙事上下文被塞满、真正的当轮设定反而被挤掉。需要时用 configure(lore_recursion=N) 打开。
    depth_cap = max(0, min(MAX_RECURSION, int((state.get("config") or {}).get("lore_recursion", 0) or 0)))
    scan_depth = int((state.get("config") or {}).get("lore_scan_depth", DEFAULT_SCAN_DEPTH) or 0)
    tail = scan_texts[-scan_depth:] if scan_depth > 0 else scan_texts
    base_text = "\n".join(tail)

    rt = _runtime(state)
    chosen, skipped, group_won = {}, [], {}
    _scan(decorated, base_text, base_text.lower(), 0, "keyword",
          state, rt, tick, chosen, skipped, group_won)

    for depth in range(1, depth_cap + 1):  # depth_cap=0 时不进循环
        feed = _recursion_feed(chosen, depth)
        if not feed.strip():
            break
        pool = [e for e in decorated if not e.get("exclude_recursion")]
        _scan(pool, feed, feed.lower(), depth, "recursion",
              state, rt, tick, chosen, skipped, group_won)

    if apply_runtime:
        for entry in chosen.values():
            if entry.get("_reason") != "sticky":
                mark_fired(state, entry, tick)

    # 排序：常驻条目先插（SillyTavern 语义），其余按 insertion_order；同 order 用 id 稳定排序。
    out = sorted(chosen.values(),
                 key=lambda e: (0 if e.get("constant") else 1,
                                int(e.get("order", 100) or 100), e["_eid"]))
    by_depth = {}
    for entry in out:
        by_depth[str(entry["_depth"])] = by_depth.get(str(entry["_depth"]), 0) + 1
    return {"entries": out, "by_depth": by_depth, "skipped": skipped[-40:],
            "recursion_cap": depth_cap, "scan_depth": scan_depth,
            "scanned": len(scan_texts)}


def runtime_summary(state, entries):
    """面板"世界书"抽屉用：每条目的触发次数、剩余 sticky/cooldown、下次可触发时间。"""
    rt = _runtime(state)
    tick = int(state.get("tick", 0) or 0)
    rows = []
    for i, entry in enumerate(entries or []):
        eid = _entry_id(entry, i)
        sticky_until = int(rt["sticky_until"].get(eid, -1) or -1)
        cooldown_until = int(rt["cooldown_until"].get(eid, -1) or -1)
        rows.append({
            "id": eid,
            "comment": entry.get("comment") or eid,
            "keys": list(entry.get("keys") or [])[:6],
            "constant": bool(entry.get("constant")),
            "enabled": bool(entry.get("enabled", True)),
            "fired": int(rt["fired_count"].get(eid, 0) or 0),
            "last_tick": rt["last_fired"].get(eid),
            "sticky_left": max(0, sticky_until - tick) if sticky_until >= tick else 0,
            "cooldown_left": max(0, cooldown_until - tick) if cooldown_until > tick else 0,
            "order": int(entry.get("order", 100) or 100),
        })
    rows.sort(key=lambda r: (-r["fired"], r["order"]))
    return rows
