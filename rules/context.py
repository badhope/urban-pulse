"""
上下文管理 (Context) —— 互动对话里"AI 该记住什么"的确定性台账

为什么需要：互动对话游戏的长局质量，取决于宿主 AI 每回合能看到什么。原内核只有
`write_summary` / `recap` / `recall` / 世界书触发，缺三样东西：
  · **结构化事实库**：NPC 说过什么、承诺过什么、线索指向谁——可增删改查，不靠 LLM 记忆；
  · **上下文预算打包**：在字符预算内，按优先级拼出"这一回合该给 AI 看的材料"；
  · **冲突与过期**：事实有有效期与置信度，避免旧设定一直压在上下文里。

设计原则：
  · 事实是**数据**，不是指令——输出统一带 `untrusted` 与来源，与角色卡同规格；
  · 全部确定性：不随机、不读时钟、不读网络；
  · 与现有三层记忆互补：summary/milestones/archive 是"叙事历史"，这里是"结构化知识"。
"""

import hashlib
import json
import re

MAX_FACTS = 400
MAX_TEXT = 600
MAX_KEYS = 8
MAX_SUMMARY_LINES = 40

KINDS = ("fact", "clue", "promise", "npc", "place", "item", "rule", "note")
STATUSES = ("open", "done", "expired", "superseded")

# 检索打分：generative_agents 记忆流的确定性移植。原实现
# (reverie/backend_server/persona/cognitive_modules/retrieve.py) 用
# recency=0.99**age、importance=LLM 1..10、relevance=余弦相似度，
# 三分量各自 min-max 归一后按 0.5/3/2 加权。这里零依赖复刻同一形状：
# relevance 换成字符/词元重叠，importance 换成类型权重 x 置信度（可显式覆盖）。
RECENCY_DECAY = 0.99
SCORE_WEIGHTS = {"recency": 0.5, "relevance": 3.0, "importance": 2.0}
IMPORTANCE_BY_KIND = {
    "promise": 1.0, "clue": 0.9, "rule": 0.8, "npc": 0.7,
    "fact": 0.5, "place": 0.5, "item": 0.5, "note": 0.3,
}
# 事件类型权重（编年史检索用）：突破/事业线/涌现 > 战斗/世界 > 日常。
# 直接照搬"所有事件同权"会让 200 条"攻击被闪避"淹没唯一一次突破。
EVENT_IMPORTANCE = {
    "breakthrough": 1.0, "quest": 0.9, "emergent": 0.9, "karma": 0.8,
    "world": 0.7, "combat": 0.7, "travel": 0.5, "trade": 0.4,
    "social": 0.4, "system": 0.3, "context": 0.3, "check": 0.3,
    "use_item": 0.3, "sheet": 0.2, "prose": 0.2, "tick": 0.05,
}
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_CJK_RE = re.compile(r"[㐀-䶿一-鿿]+")


def _now_tick(state: dict) -> int:
    return int(state.get("tick", 0) or 0)


def _fact_id(seq: int) -> str:
    # %04d 在 seq>9999 时自然变宽（f10000），永不回绕——旧写法 % 10000 会让
    # 第 10000 条与第 1 条同 id，context_forget(id) 会误删活事实（实测碰撞）。
    return "f%d" % int(seq)


def _normalize_keys(keys):
    if isinstance(keys, str):
        keys = [keys]
    out = []
    for key in keys or []:
        text = str(key or "").strip()[:40]
        if text and text not in out:
            out.append(text)
        if len(out) >= MAX_KEYS:
            break
    return out


def _tokens(text) -> set:
    """确定性词元集合：ASCII 词 + CJK 二元组（中文无需分词器）。

    按二元组而非整句切片，「灯塔三年前熄了」与「灯塔早已不亮」能共享「灯塔」，
    这是本项目在无嵌入模型时的 relevance 近似。
    """
    raw = str(text or "").lower()
    out = set()
    for word in _TOKEN_RE.findall(raw):
        if len(word) >= 2 or word.isdigit():
            out.add(word)
    for run in _CJK_RE.findall(raw):
        if len(run) == 1:
            out.add(run)
        else:
            for i in range(len(run) - 1):
                out.add(run[i:i + 2])
    return out


def _importance(fact: dict) -> float:
    """事实重要性 0..1：显式值优先，否则类型权重 x 置信度。"""
    explicit = fact.get("importance")
    if explicit is not None:
        try:
            return max(0.0, min(1.0, float(explicit)))
        except (TypeError, ValueError):
            pass
    kind = str(fact.get("kind") or "")
    base = IMPORTANCE_BY_KIND.get(kind) or EVENT_IMPORTANCE.get(kind) or 0.4
    try:
        conf = max(0.0, min(1.0, float(fact.get("confidence", 1.0))))
    except (TypeError, ValueError):
        conf = 1.0
    return max(0.0, min(1.0, base * conf))


def _recency(fact: dict, tick: int) -> float:
    """0.99 ** 距今年数；tick 是离散回合，等价于 GA 的消息位置衰减。"""
    age = max(0, int(tick) - int(fact.get("tick", 0) or 0))
    return RECENCY_DECAY ** age


def _relevance(fact: dict, query_grams: set) -> float:
    """查询词元被事实覆盖的比例（封顶 1）。"""
    if not query_grams:
        return 0.0
    fact_grams = _tokens(fact.get("text")) | _tokens(" ".join(fact.get("keys") or []))
    hit = len(query_grams & fact_grams)
    if not hit:
        return 0.0
    return min(1.0, hit / float(min(len(query_grams), 8)))


def _rank(rows: list, state: dict, query: str = "") -> list:
    """GA 三分量打分；候选集内 min-max 归一，range=0 时取 0.5（同原实现）。"""
    if not rows:
        return rows
    tick = _now_tick(state)
    qgrams = _tokens(query)
    raw = [(dict(row), _recency(row, tick), _importance(row), _relevance(row, qgrams))
           for row in rows]

    def normalise(index):
        values = [row[index] for row in raw]
        low, high = min(values), max(values)
        if high - low <= 1e-12:
            return [0.5] * len(values)
        return [(value - low) / (high - low) for value in values]

    recency, importance, relevance = normalise(1), normalise(2), normalise(3)
    scored = []
    for i, (row, _rec, _imp, _rel) in enumerate(raw):
        total = (SCORE_WEIGHTS["recency"] * recency[i]
                 + SCORE_WEIGHTS["relevance"] * relevance[i]
                 + SCORE_WEIGHTS["importance"] * importance[i])
        row["score"] = round(total, 6)
        row["score_detail"] = {"recency": round(recency[i], 4),
                               "importance": round(importance[i], 4),
                               "relevance": round(relevance[i], 4)}
        scored.append(row)
    # 排序稳定性（借 open-dungeon 的 prompt-cache 教训：前缀一变就整段重算）。
    # 原始分数是候选集内相对值，新增一条事实就会让所有分数轻微漂移；若按全精度排序，
    # 每回合的 section 顺序都在抖，宿主的提示词前缀缓存全部失效。
    # 把排序键量化到 0.25 的桶、桶内按 id 稳定排序：只有真正跨桶的分数变化才改顺序。
    stable = (state.get("config") or {}).get("context_stable_order", True) is not False
    quantum = 0.25 if stable else 0.0

    def sort_key(row):
        bucket = round(row["score"] / quantum) if quantum else row["score"]
        return (-bucket, str(row.get("id", "")))

    scored.sort(key=sort_key)
    return scored


def rank_events(rows, state: dict, query: str = "", limit: int = 8) -> list:
    """编年史/归档检索打分：event_log 条目借用同一套三分量。

    recall 旧实现只按 tick 取最近 N 条——"很久以前那次突破"永远捞不回来。
    event_log 没有 confidence，因此 importance 走 EVENT_IMPORTANCE（类型权重），
    relevance 走 desc 词元重叠，recency 仍是 0.99^age；排序桶同样量化以稳住顺序。
    """
    if not rows:
        return []
    pseudo = []
    for event in rows:
        if not isinstance(event, dict):
            continue
        item = dict(event)
        item["kind"] = str(event.get("type") or event.get("kind") or "fact")
        item["text"] = str(event.get("desc") or "")
        item.setdefault("id", "t%d" % int(event.get("tick", 0) or 0))
        pseudo.append(item)
    limit = max(1, min(200, int(limit or 8)))
    return _rank(pseudo, state, query)[:limit]


def _next_seq(state: dict) -> int:
    ctx = state.setdefault("context", {})
    # seq 缺失时从现有最大 id 推导（旧存档里 facts 先于 seq 字段存在）：
    # 直接从 0 起数会与既有 f0001 撞 id（实测 remember 立刻产生第二个 f0001）。
    seq = int(ctx.get("seq", 0) or 0)
    if seq <= 0:
        for fact in ctx.get("facts") or []:
            fid = str(fact.get("id") or "")
            if fid.startswith("f") and fid[1:].isdigit():
                seq = max(seq, int(fid[1:]))
    seq += 1
    ctx["seq"] = seq
    return seq


def remember(state: dict, text: str, kind: str = "fact", keys=None,
             source: str = "", confidence: float = 1.0, ttl: int = 0,
             subject: str = "", importance: float | None = None,
             supersede: bool = False, witnesses=None, public: bool = False) -> dict:
    """记一条结构化事实。重复文本（同 kind + 同正文）会刷新而不是重复追加。

    supersede=True：同一 kind + 同一 subject 的旧开放事实标为 superseded 并写
    superseded_by 审计链（mem0 的 UPDATE 语义，但冲突条件显式给出，不靠 LLM 猜）。
    """
    body = str(text or "").strip()
    if not body:
        raise ValueError("text 不能为空")
    body = body[:MAX_TEXT]
    kind = str(kind or "fact").strip().lower()
    if kind not in KINDS:
        raise ValueError("kind 只能是: %s" % " / ".join(KINDS))
    try:
        confidence = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        raise ValueError("confidence 必须在 0..1")
    try:
        ttl = max(0, int(ttl or 0))
    except (TypeError, ValueError):
        raise ValueError("ttl 必须是非负整数")
    if importance is not None:
        try:
            importance = max(0.0, min(1.0, float(importance)))
        except (TypeError, ValueError):
            raise ValueError("importance 必须在 0..1")
    subject_text = str(subject or "").strip()[:60]

    ctx = state.setdefault("context", {})
    facts = ctx.setdefault("facts", [])
    tick = _now_tick(state)
    for fact in facts:
        if fact.get("kind") == kind and fact.get("text") == body:
            fact["tick"] = tick
            fact["confidence"] = round(confidence, 3)
            fact["ttl"] = ttl
            fact["source"] = str(source or fact.get("source") or "")[:120]
            if importance is not None:
                fact["importance"] = round(importance, 3)
            if keys:
                merged = fact.get("keys") or []
                for key in _normalize_keys(keys):
                    if key not in merged:
                        merged.append(key)
                fact["keys"] = merged[:MAX_KEYS]
            fact["status"] = "open"
            return {"fact": dict(fact), "created": False, "total": len(facts)}

    fact_id = _fact_id(_next_seq(state))
    superseded = []
    if supersede and subject_text:
        for old in facts:
            if old.get("status") != "open" or old.get("kind") != kind:
                continue
            if str(old.get("subject") or "") != subject_text:
                continue
            old["status"] = "superseded"
            old["superseded_by"] = fact_id
            old["closed_tick"] = tick
            superseded.append(old.get("id"))
    fact = {
        "id": fact_id,
        "tick": tick,
        "kind": kind,
        "subject": subject_text,
        "text": body,
        "keys": _normalize_keys(keys),
        "source": str(source or "")[:120],
        "confidence": round(confidence, 3),
        "ttl": ttl,
        "status": "open",
    }
    if importance is not None:
        fact["importance"] = round(importance, 3)
    fact["public"] = bool(public)
    fact["witnesses"] = _normalize_witnesses(witnesses, public)
    facts.append(fact)
    # 线索计数：模板/成就常用 counter_gte:{key:"clues"} 判断"找到第一条线索"
    if kind == "clue":
        from game_engine.state_schema import bump
        bump(state, "clues")
    if len(facts) > MAX_FACTS:
        # 先淘汰已结案/过期，再淘汰最旧的低置信度条目；绝不动未结案的高置信度
        closed = [i for i, f in enumerate(facts) if f.get("status") != "open"]
        for i in reversed(closed):
            if len(facts) <= MAX_FACTS:
                break
            del facts[i]
        while len(facts) > MAX_FACTS:
            weakest = min(range(len(facts)), key=lambda i: (facts[i].get("confidence", 0),
                                                           facts[i].get("tick", 0)))
            del facts[weakest]
    return {"fact": dict(fact), "created": True, "total": len(facts),
            "superseded": superseded}


def forget(state: dict, fact_id: str = "", keys=None, kind: str = "") -> dict:
    """删除事实：按 id、按关键词或按类型。返回删除条数。"""
    ctx = state.get("context") or {}
    facts = ctx.get("facts") or []
    target_keys = set(_normalize_keys(keys))
    removed = []
    keep = []
    for fact in facts:
        hit = False
        if fact_id and fact.get("id") == str(fact_id):
            hit = True
        elif target_keys and target_keys & set(fact.get("keys") or []):
            hit = True
        elif kind and fact.get("kind") == str(kind):
            hit = True
        if hit:
            removed.append(fact.get("id"))
        else:
            keep.append(fact)
    if not (fact_id or target_keys or kind):
        raise ValueError("forget 需要 fact_id / keys / kind 至少一个条件")
    ctx["facts"] = keep
    state["context"] = ctx
    return {"removed": removed, "count": len(removed), "remaining": len(keep)}


def set_status(state: dict, fact_id: str, status: str = "done") -> dict:
    """把一条事实标为已结案/过期（承诺兑现、线索用掉）。"""
    status = str(status or "done").strip().lower()
    if status not in STATUSES:
        raise ValueError("status 只能是: %s" % " / ".join(STATUSES))
    ctx = state.get("context") or {}
    for fact in ctx.get("facts") or []:
        if fact.get("id") == str(fact_id):
            fact["status"] = status
            fact["closed_tick"] = _now_tick(state)
            state["context"] = ctx
            return {"fact": dict(fact), "status": status}
    raise ValueError("事实不存在: %s" % fact_id)


def _expire(state: dict) -> list:
    """把 ttl 到期的事实标为 expired（纯读语义：只在查询时计算，不反复写盘）。"""
    ctx = state.get("context") or {}
    tick = _now_tick(state)
    expired = []
    for fact in ctx.get("facts") or []:
        ttl = int(fact.get("ttl", 0) or 0)
        if ttl and fact.get("status") == "open" and tick - int(fact.get("tick", 0) or 0) > ttl:
            expired.append(fact)
    return expired


def search(state: dict, query: str = "", keys=None, kind: str = "", status: str = "open",
           limit: int = 12, ranked: bool = False) -> list:
    """检索事实：query 匹配正文/主题，keys 精确匹配，kind 过滤，status 过滤（"" = 全部）。

    ranked=True 用 GA 三分量打分（recency/importance/relevance）；默认 False 保持
    旧排序（confidence, tick），既有调用方与面板顺序不变。
    """
    q = str(query or "").strip().lower()
    wanted = set(_normalize_keys(keys))
    limit = max(1, min(100, int(limit or 12)))
    expired_ids = {f.get("id") for f in _expire(state)}
    hits = []
    for fact in (state.get("context") or {}).get("facts") or []:
        fstatus = fact.get("status", "open")
        if fact.get("id") in expired_ids and fstatus == "open":
            fstatus = "expired"
        if status and fstatus != status:
            continue
        if kind and fact.get("kind") != str(kind):
            continue
        if wanted and not (wanted & set(fact.get("keys") or [])):
            continue
        if q:
            blob = " ".join([str(fact.get("subject") or ""), str(fact.get("text") or ""),
                             " ".join(fact.get("keys") or [])]).lower()
            if ranked:
                # 打分检索按词元重叠召回（「灯塔 门房」能同时命中只含其中一个的事实），
                # 精确子串匹配只保留给旧接口的兼容语义。
                if not (_tokens(q) & _tokens(blob)):
                    continue
            elif q not in blob:
                continue
        row = dict(fact)
        row["status"] = fstatus
        if fstatus == "expired":
            row["expired"] = True
        hits.append(row)
    if ranked:
        return _rank(hits, state, q)[:limit]
    hits.sort(key=lambda f: (f.get("confidence", 0), f.get("tick", 0)), reverse=True)
    return hits[:limit]


def _context_budget(state: dict) -> int:
    cfg = state.get("config") or {}
    try:
        return max(200, int(cfg.get("context_budget_chars", 4000) or 4000))
    except (TypeError, ValueError):
        return 4000


def pack(state: dict, scene_text: str = "", recent: int = 8, budget_chars: int = 0) -> dict:
    """按字符预算打包这一回合给宿主的上下文材料。

    顺序（也是裁剪优先级，从高到低）：
      1. 任务/玩法（playbook + 事业线）
      2. 未结案的承诺与线索（按置信度）
      3. 与场景/最近事件相关的事实
      4. 最近事件与摘要
      5. 其余开放事实（低置信度先砍）
    """
    budget = max(200, int(budget_chars or _context_budget(state)))
    out = {"budget_chars": budget, "sections": [], "used_chars": 0, "truncated": []}

    def push(title, lines, priority):
        out["sections"].append({"title": title, "lines": lines, "priority": priority})

    playbook = state.get("playbook") or {}
    pb_lines = []
    if playbook:
        progress = playbook.get("progress") or {}
        pb_lines.append("玩法：%s · 进度 %s %s/%s" % (
            playbook.get("loop", "freeform"), progress.get("label", "进度"),
            progress.get("value", 0), progress.get("max", 0)))
    quests = state.get("questlines") or []
    if quests:
        active = [q for q in quests if (q.get("status") or "") != "done"]
        pb_lines.append("事业线：%d 条（%s）" % (len(active), "、".join(
            str(q.get("title") or q.get("id")) for q in active[:4]) or "无"))
    if pb_lines:
        push("本局玩法", pb_lines, 1)

    open_facts = search(state, status="open", limit=MAX_FACTS, ranked=True)
    promises = [f for f in open_facts if f.get("kind") in ("promise", "clue")]
    if promises:
        push("未结案", ["[%s] %s" % (f.get("kind"), f.get("text")) for f in promises[:8]], 2)

    scene_hits = []
    if scene_text:
        scene_hits = search(state, query=scene_text, status="open", limit=6, ranked=True)
    if scene_hits:
        push("与场景相关", ["%s" % f.get("text") for f in scene_hits], 3)

    recent_events = [e for e in (state.get("event_log") or [])[-max(1, int(recent)):] if e.get("desc")]
    if recent_events:
        push("最近事件", ["第%s回合·%s" % (e.get("tick", 0), e.get("desc")) for e in recent_events], 4)

    # 按 id 去重：搜索结果是各自的副本，带 score 字段后 dict 相等比较不再成立
    # （实测同一事实会在「未结案」和「其他事实」各出现一次）。
    seen_ids = {f.get("id") for f in promises} | {f.get("id") for f in scene_hits}
    rest = [f for f in open_facts if f.get("id") not in seen_ids]
    if rest:
        push("其他事实", [f.get("text") for f in rest[:10]], 5)

    kept, used = [], 0
    for section in sorted(out["sections"], key=lambda s: s["priority"]):
        lines = []
        for line in section["lines"]:
            text = str(line)
            if used + len(text) > budget:
                out["truncated"].append({"section": section["title"], "line": text[:60]})
                continue
            lines.append(text)
            used += len(text)
        if lines:
            kept.append({"title": section["title"], "lines": lines, "priority": section["priority"]})
    out["sections"] = kept
    out["used_chars"] = used
    out["reflection"] = reflection_due(state)
    out["prompt_prefix_hash"] = _prefix_hash(kept)
    return out


def _prefix_hash(sections):
    """本轮上下文的稳定前缀指纹（Open Dungeon 的 prompt 缓存教训）。

    为什么不直接用 used_chars 或条数：宿主关心的是"这段前缀还能不能复用 KV 缓存"，
    决定它的是**内容与顺序**，不是长度。同一批内容即使条数变了，只要前缀逐字相同，
    缓存依然有效——所以哈希必须覆盖 section 顺序 + 每行原文。

    排序固定（sort_keys + 固定分隔符 + ensure_ascii=False），否则中文在不同
    Python/平台上的转义差异会让同一内容算出不同哈希。
    """
    payload = [[s.get("title", ""), list(s.get("lines") or [])] for s in sections]
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def reflection_due(state: dict, threshold: float = 0.0) -> dict:
    """反思触发（generative_agents 的 importance 累积阈值，改成确定性版本）。

    GA 的做法：新记忆的 poignancy 不断累加，超过 importance_trigger_max（150）
    就触发一次 reflect，把零散记忆压成更高层的洞察。这里保持同一触发形状：
      · 累加量 = 自上次反思以来新增事实的 importance（0..1）
      · 阈值默认 10（约 15~20 条中等重要事实），可用 config.context_reflect_threshold 覆盖
      · 引擎只回答"该反思了"并给出候选，真正写摘要仍由宿主调用 write_summary
    这样"何时压缩"是可复算的引擎判断，"压缩成什么"仍留给叙事模型。
    """
    ctx = state.get("context") or {}
    try:
        threshold = float(threshold or (state.get("config") or {}).get(
            "context_reflect_threshold", 10) or 10)
    except (TypeError, ValueError):
        threshold = 10.0
    threshold = max(0.1, threshold)
    since = int(ctx.get("reflected_upto", -1) or -1)
    fresh = [f for f in (ctx.get("facts") or [])
             if f.get("status") == "open" and int(f.get("tick", 0) or 0) > since]
    accumulated = round(sum(_importance(f) for f in fresh), 3)
    ranked = _rank(fresh, state, "")[:5]
    return {
        "due": accumulated >= threshold,
        "accumulated": accumulated,
        "threshold": threshold,
        "since_tick": since,
        "fresh_facts": len(fresh),
        "candidates": [{"id": f.get("id"), "kind": f.get("kind"),
                        "text": str(f.get("text") or "")[:120]} for f in ranked],
    }


def mark_reflected(state: dict, tick: int | None = None) -> dict:
    """记录一次反思完成：推进 reflected_upto 并累加计数（write_summary 调用）。"""
    ctx = state.setdefault("context", {})
    ctx["reflected_upto"] = int(_now_tick(state) if tick is None else tick)
    ctx["reflect_count"] = int(ctx.get("reflect_count", 0) or 0) + 1
    return {"reflected_upto": ctx["reflected_upto"], "reflect_count": ctx["reflect_count"]}


def summary(state: dict) -> dict:
    """面板用的上下文概览：事实统计与最近几条。"""
    ctx = state.get("context") or {}
    facts = ctx.get("facts") or []
    stats = {kind: 0 for kind in KINDS}
    for fact in facts:
        kind = fact.get("kind", "fact")
        if kind in stats:
            stats[kind] += 1
    open_rows = search(state, status="open", limit=10)
    return {
        "total": len(facts),
        "by_kind": stats,
        "open": sum(1 for f in facts if f.get("status") == "open"),
        "superseded": sum(1 for f in facts if f.get("status") == "superseded"),
        "recent": [{"id": f.get("id"), "kind": f.get("kind"), "text": f.get("text", "")[:120],
                    "keys": f.get("keys") or [], "tick": f.get("tick", 0)}
                   for f in open_rows],
        "budget_chars": _context_budget(state),
        "reflection": reflection_due(state),
    }


# ── 知识边界（A6）：谁有权知道这条事实 ──────────────────────────
def _normalize_witnesses(witnesses, public: bool) -> list:
    """Who may know this fact. Defaults to the player alone."""
    if public:
        return ["*"]
    out = ["player"]
    for raw in (witnesses or []):
        name = str(raw or "").strip()[:40]
        if name and name not in out:
            out.append(name)
    return out


def knows(fact: dict, knower: str) -> bool:
    """True when `knower` is allowed to know this fact.

    Facts written before this field existed default to player-only: the
    conservative reading, so an old save never leaks a secret it never tracked.
    """
    if not isinstance(fact, dict):
        return False
    if fact.get("public"):
        return True
    who = str(knower or "").strip()
    if not who:
        return False
    witnesses = fact.get("witnesses")
    if not isinstance(witnesses, list) or not witnesses:
        return who == "player"
    return "*" in witnesses or who in witnesses


def tell(state: dict, fact_id: str, to: str, propagation: str = "told") -> dict:
    """Propagate a fact to another knower, recording how they learned it."""
    who = str(to or "").strip()[:40]
    if not who:
        raise ValueError("to 不能为空")
    ctx = state.get("context") or {}
    for fact in (ctx.get("facts") or []):
        if fact.get("id") != fact_id:
            continue
        witnesses = fact.get("witnesses")
        if not isinstance(witnesses, list):
            witnesses = ["player"]
        if who not in witnesses:
            witnesses.append(who)
        fact["witnesses"] = witnesses
        trail = fact.get("propagation")
        if not isinstance(trail, list):
            trail = []
        trail.append({"to": who, "how": str(propagation or "told")[:20],
                      "tick": _now_tick(state)})
        fact["propagation"] = trail[-20:]
        return {"fact": dict(fact), "told": who}
    raise KeyError("没有这条事实: %s" % fact_id)


def known_to(state: dict, knower: str, limit: int = 12) -> list:
    """Facts a specific character may reference. Check before writing dialogue."""
    ctx = state.get("context") or {}
    facts = [f for f in (ctx.get("facts") or [])
             if f.get("status") == "open" and knows(f, knower)]
    facts.sort(key=lambda f: (-float(f.get("importance") or 0.5), -int(f.get("tick") or 0)))
    return [{"id": f.get("id"), "kind": f.get("kind"), "text": f.get("text"),
             "tick": f.get("tick")} for f in facts[:limit]]
