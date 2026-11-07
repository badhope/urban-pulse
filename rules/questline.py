"""
事业线 / 任务链 (Questline) —— 由世界状态驱动，而不是待办清单

设计原则（来自调研结论）：
  1. **任务只声明目标与压力，不声明过程**：过程由玩家自由行动产生，引擎只判定"是否达成"。
  2. **门禁与完成条件只用世界状态谓词求值**：不解析叙述文字，不依赖 LLM 判断。
  3. **stage 是有向无环图（DAG）**：允许分叉与汇合；同一 stage 可有多条进入路径。
  4. **dormant 任务不显示**：未满足浮现条件的事业线不占面板，也不催促玩家。
  5. **失败要有明确判据**：deadline_tick / fail_if 谓词，不用"剧情需要"。

数据结构（写进设定包的 `questlines` 字段）：

    {
      "id": "letter_from_the_dead",
      "title": "亡者来信",
      "summary": "一封没有署名的信，指向二十年前的灯塔。",
      "stages": [
        {"id": "start", "title": "收到信",
         "objectives": ["读信", "去码头打听"],
         "next": ["lighthouse"], "enter_if": null},
        {"id": "lighthouse", "title": "灯塔之下",
         "objectives": ["进入灯塔", "找到看守"],
         "next": ["truth"], "enter_if": {"flag": "抵达灯塔"}},
        {"id": "truth", "title": "真相",
         "objectives": ["面对它"], "next": [], "enter_if": {"visited": "沉船湾"}}
      ],
      "visibility": {"flag": "收到信"},          # 达到才显示（dormant → active）
      "fail_if": {"tick_gte": 400},
      "reward": {"gold": 200, "flags": ["真相大白"]}
    }

所有谓词求值都是纯函数、只读状态，不修改任何东西。
"""

PREDICATE_KEYS = (
    "all", "any", "not",
    "flag", "tick_gte", "gold_gte", "karma_gte", "tier_gte",
    "visited", "killed", "relation_gte", "item_gte", "counter_gte",
    "stage_done", "quest_done",
)

MAX_STAGES = 40
MAX_QUESTS = 40
HISTORY_CAP = 80


def _tier(state, entity_id="player"):
    """实体在等级阶梯上的序号（无阶梯配置时退回 stage）。"""
    try:
        from game_engine.rules.progression import level_tier
        ents = state.get("entities") or {}
        ent = ents.get(entity_id) or {}
        return int(level_tier(state, ent))
    except Exception:  # aqg: top-level boundary —— 阶梯坏了不影响任务判定
        return 0


def _unsettled_karma(state, entity_id="player"):
    return sum(int(e.get("amount", 0) or 0)
               for e in (state.get("karma_ledger") or [])
               if e.get("from") == entity_id and not e.get("settled"))


def _quest_state(state, quest_id):
    return ((state.get("quests") or {}).get(quest_id) or {})


def evaluate(state, pred):
    """求值一个谓词。未知键返回 False（fail-closed，不静默放行）。"""
    if pred is None:
        return True
    if pred is True:
        return True
    if pred is False:
        return False
    if not isinstance(pred, dict):
        return False
    if "all" in pred:
        return all(evaluate(state, p) for p in (pred.get("all") or []))
    if "any" in pred:
        return any(evaluate(state, p) for p in (pred.get("any") or []))
    if "not" in pred:
        return not evaluate(state, pred.get("not"))
    if "flag" in pred:
        return str(pred["flag"]) in (state.get("world_flags") or [])
    if "tick_gte" in pred:
        return int(state.get("tick", 0) or 0) >= int(pred["tick_gte"])
    if "gold_gte" in pred:
        player = (state.get("entities") or {}).get("player") or {}
        return int(player.get("gold", 0) or 0) >= int(pred["gold_gte"])
    if "karma_gte" in pred:
        return _unsettled_karma(state) >= int(pred["karma_gte"])
    if "tier_gte" in pred:
        return _tier(state) >= int(pred["tier_gte"])
    if "visited" in pred:
        return str(pred["visited"]) in ((state.get("codex") or {}).get("locations") or [])
    if "killed" in pred:
        target = str(pred["killed"])
        for m in (state.get("milestones") or []):
            if m.get("kind") == "击杀" and target in str(m.get("desc", "")):
                return True
        return target in (state.get("killed") or [])
    if "relation_gte" in pred:
        target = pred["relation_gte"] or {}
        who = str(target.get("with", ""))
        from game_engine.state_schema import entity_key
        key = entity_key("player", who) if who else ""
        rel = (state.get("relations") or {}).get(key) or {}
        field = "respect" if target.get("respect") is not None else "affinity"
        want = int(target.get(field, 0))
        return int(rel.get(field, 0) or 0) >= want
    if "item_gte" in pred:
        target = pred["item_gte"] or {}
        player = (state.get("entities") or {}).get("player") or {}
        return int((player.get("items") or {}).get(str(target.get("key", "")), 0)) >= int(target.get("n", 1))
    if "counter_gte" in pred:
        target = pred["counter_gte"] or {}
        counters = state.get("counters") or {}
        return int(counters.get(str(target.get("key", "")), 0) or 0) >= int(target.get("n", 1))
    if "stage_done" in pred:
        target = pred["stage_done"] or {}
        st = _quest_state(state, str(target.get("quest", "")))
        done = st.get("done_stages") or []
        return str(target.get("stage", "")) in done
    # ink 的 knot 访问计数（`{ visit_paris }` / `TURNS_SINCE(-> knot)`）。
    # 数值从已有 history 派生，不新增平行状态：同一份数据既能画图也能做条件。
    if "visits" in pred:
        target = pred["visits"] or {}
        return _visits(state, str(target.get("quest", "")),
                       str(target.get("stage", ""))) >= int(target.get("gte", 1))
    if "turns_since" in pred:
        target = pred["turns_since"] or {}
        since = _turns_since(state, str(target.get("quest", "")),
                             str(target.get("stage", "")))
        # 从未到过没有"多少回合前"可算，条件不成立（fail-closed，不因缺失而放行）
        return since is not None and since >= int(target.get("gte", 0))
    if "quest_done" in pred:
        st = _quest_state(state, str(pred["quest_done"]))
        return bool(st.get("status") == "done")
    return False


def _visits(state, quest_id, stage_id):
    """某幕进入过几次（来自 history 的 enter 记录；随快照回退，可重放）。"""
    row = _quest_state(state, quest_id)
    return sum(1 for h in (row.get("history") or [])
               if h.get("stage") == stage_id and h.get("event") == "enter")


def _turns_since(state, quest_id, stage_id):
    """距上次进入该幕过了多少回合；从未进入返回 None。"""
    row = _quest_state(state, quest_id)
    last = None
    for h in (row.get("history") or []):
        if h.get("stage") == stage_id and h.get("event") == "enter":
            tick = int(h.get("tick", 0) or 0)
            if last is None or tick > last:
                last = tick
    if last is None:
        return None
    return max(0, int(state.get("tick", 0) or 0) - last)


def _normalize_stage(qid, raw, index):
    if not isinstance(raw, dict):
        raise ValueError("questline %s 的 stage #%d 不是对象" % (qid, index))
    sid = str(raw.get("id") or "").strip()
    if not sid:
        raise ValueError("questline %s 的 stage id 缺失（#%d）" % (qid, index))
    nxt = raw.get("next") or []
    if not isinstance(nxt, list):
        raise ValueError("questline %s/%s 的 next 必须是数组" % (qid, sid))
    return {
        "id": sid,
        "title": str(raw.get("title") or sid)[:80],
        "objectives": [str(x)[:120] for x in (raw.get("objectives") or [])][:12],
        "enter_if": raw.get("enter_if"),
        "exit_if": raw.get("exit_if"),
        "next": [str(x) for x in nxt][:12],
        "on_enter": [str(x)[:120] for x in (raw.get("on_enter") or [])][:8],
    }


def _validate_graph(qid, stages):
    """引用完整性 + 无环。stage 图有环就等于"永远推进不完"，必须在载入时报错。"""
    known = {st["id"] for st in stages}
    for st in stages:
        for nxt in st["next"]:
            if nxt not in known:
                raise ValueError("questline %s 的 stage %s 指向不存在的 next=%s" % (qid, st["id"], nxt))
    graph = {st["id"]: st["next"] for st in stages}
    visiting, done = set(), set()

    def dfs(node):
        if node in done:
            return False
        if node in visiting:
            return True
        visiting.add(node)
        for nxt in graph.get(node, []):
            if dfs(nxt):
                return True
        visiting.discard(node)
        done.add(node)
        return False

    for node in graph:
        if dfs(node):
            raise ValueError("questline %s 的 stage 图有环（%s）" % (qid, node))


def normalize(raw):
    """规范化一条事业线定义（供设定包与 MCP 共用）；非法则 ValueError。"""
    if not isinstance(raw, dict):
        raise ValueError("questline 必须是对象")
    qid = str(raw.get("id") or "").strip()
    if not qid:
        raise ValueError("questline 缺 id")
    raw_stages = raw.get("stages")
    if not isinstance(raw_stages, list) or not raw_stages:
        raise ValueError("questline %s 缺 stages" % qid)
    if len(raw_stages) > MAX_STAGES:
        raise ValueError("questline %s 的 stages 超过 %d" % (qid, MAX_STAGES))
    stages = [_normalize_stage(qid, st, i) for i, st in enumerate(raw_stages)]
    ids = [st["id"] for st in stages]
    if len(ids) != len(set(ids)):
        raise ValueError("questline %s 的 stage id 有重复" % qid)
    _validate_graph(qid, stages)
    return {
        "id": qid,
        "title": str(raw.get("title") or qid)[:80],
        "summary": str(raw.get("summary") or "")[:400],
        "stages": stages,
        "visibility": raw.get("visibility"),
        "fail_if": raw.get("fail_if"),
        "deadline_tick": int(raw.get("deadline_tick") or 0) or None,
        "reward": raw.get("reward") or {},
        "tags": [str(t)[:24] for t in (raw.get("tags") or [])][:8],
    }


def normalize_all(raw_list):
    """规范化一整个 `questlines` 数组；重复 id 报错。"""
    out, seen = [], set()
    for raw in (raw_list or []):
        q = normalize(raw)
        if q["id"] in seen:
            raise ValueError("questline id 重复: %s" % q["id"])
        seen.add(q["id"])
        out.append(q)
    if len(out) > MAX_QUESTS:
        raise ValueError("questlines 超过 %d 条" % MAX_QUESTS)
    return out


def _stage_of(quest, stage_id):
    for st in quest.get("stages") or []:
        if st["id"] == stage_id:
            return st
    return None


def _reveal(state, quest, row):
    if row["status"] != "dormant":
        return False
    if quest.get("visibility") is None or evaluate(state, quest["visibility"]):
        row["status"] = "active"
        return True
    return False


def _fail_reason(state, quest, tick):
    deadline = quest.get("deadline_tick")
    if quest.get("fail_if") is not None and evaluate(state, quest["fail_if"]):
        return "fail_if"
    if deadline and tick >= int(deadline):
        return "deadline"
    return ""


def _step_quest(state, quest, row, tick):
    """推进单条事业线一步，返回变化列表。规则见 advance 的 docstring。"""
    qid = quest["id"]
    changes = []
    why = _fail_reason(state, quest, tick)
    if why:
        row["status"] = "failed"
        return [{"quest": qid, "change": "failed", "reason": why}]
    if _reveal(state, quest, row):
        changes.append({"quest": qid, "change": "revealed"})
    if row["status"] != "active":
        return changes

    if row["stage"] is None:
        for stage in quest.get("stages") or []:
            if stage["id"] in row["done_stages"]:
                continue
            if stage.get("enter_if") is None or evaluate(state, stage["enter_if"]):
                _enter_stage(state, quest, row, stage, tick)
                changes.append({"quest": qid, "change": "stage",
                                "stage": stage["id"], "title": stage.get("title")})
                break
        return changes

    cur = _stage_of(quest, row["stage"]) or {}
    if cur.get("exit_if") is None or not evaluate(state, cur["exit_if"]):
        return changes
    if cur["id"] in row["done_stages"]:
        # 已完成但 next 的 enter_if 一直不满足：不能每回合重记 stage_done（实测连续 3 回合都报），
        # 但仍要每回合重试 _next_stage —— 条件满足时自动进入下一幕。
        nxt = _next_stage(state, quest, row)
        if nxt is not None:
            _enter_stage(state, quest, row, nxt, tick)
            changes.append({"quest": qid, "change": "stage",
                            "stage": nxt["id"], "title": nxt.get("title")})
        elif not (cur.get("next") or []):
            _finish_quest(state, quest, row, tick)
            changes.append({"quest": qid, "change": "done"})
        return changes
    row["done_stages"].append(cur["id"])
    row["history"].append({"tick": tick, "stage": cur["id"], "event": "complete"})
    changes.append({"quest": qid, "change": "stage_done",
                    "stage": cur["id"], "title": cur.get("title")})
    nxt = _next_stage(state, quest, row)
    if nxt is not None:
        _enter_stage(state, quest, row, nxt, tick)
        changes.append({"quest": qid, "change": "stage",
                        "stage": nxt["id"], "title": nxt.get("title")})
    elif not (cur.get("next") or []):
        _finish_quest(state, quest, row, tick)
        changes.append({"quest": qid, "change": "done"})
    # 有 next 但 enter_if 都还不满足：保持在当前幕（done_stages 已记录），
    # 下一个 tick 走上面的"已完成 → 重试 _next_stage"分支，不重复记 stage_done。
    return changes


def advance(state, quests, tick=None):
    """按当前世界状态推进所有事业线；返回本次发生的变化列表。

    调用点：每次 tick（以及关键结算后）。**幂等**：
      · 没有当前 stage → 进入第一个 enter_if 满足的 stage；
      · 有当前 stage → 只有 exit_if 满足（或宿主手动 complete_stage）才离开；
      · 离开时在 next 里找第一个 enter_if 满足的 stage；没有 next → 整条完成；
      · 没有 exit_if 的 stage 永不自动推进 —— 它等宿主显式判定。
    重复调用同一状态不会重复推进，因为推进后 stage 已经变了。
    """
    tick = int(state.get("tick", 0) or 0) if tick is None else int(tick)
    qs = state.setdefault("quests", {})
    changes = []
    for quest in quests or []:
        row = qs.setdefault(quest["id"], {
            "status": "dormant", "stage": None, "done_stages": [],
            "entered_at": {}, "history": [],
        })
        if row["status"] in ("done", "failed"):
            continue
        changes.extend(_step_quest(state, quest, row, tick))
        if len(row["history"]) > HISTORY_CAP:
            del row["history"][:len(row["history"]) - HISTORY_CAP]
    return changes


def _ensure_row(state, quest, quest_id, stage_id=None):
    rows = state.setdefault("quests", {})
    row = rows.setdefault(quest_id, {
        "status": "active", "stage": stage_id, "done_stages": [],
        "entered_at": {}, "history": [],
    })
    # 旧存档/旧设定包的行可能缺字段：逐字段补齐，避免 KeyError
    row.setdefault("stage", stage_id)
    row.setdefault("done_stages", [])
    row.setdefault("entered_at", {})
    row.setdefault("history", [])
    if row.get("status") == "dormant":
        row["status"] = "active"
    return row


def _enter_stage(state, quest, row, stage, tick):
    row["stage"] = stage["id"]
    row["entered_at"][stage["id"]] = tick
    for line in stage.get("on_enter") or []:
        flags = state.setdefault("world_flags", [])
        if line not in flags:
            flags.append(line)
    row["history"].append({"tick": tick, "stage": stage["id"], "event": "enter"})


def _finish_quest(state, quest, row, tick):
    if row.get("status") == "done":
        return          # 幂等：重复 complete_stage / 重复 tick 不许重复发奖励
    row["status"] = "done"
    row["history"].append({"tick": tick, "stage": row.get("stage"), "event": "done"})
    reward = quest.get("reward") or {}
    player = (state.get("entities") or {}).get("player") or {}
    gold = reward.get("gold")
    # 数字一律发：int 直接加，float 取整后加。旧实现 isinstance(gold, int) 会把
    # "gold": 200.0（设定包里很常见的写法）静默丢掉——任务完成却一无所得。
    if isinstance(gold, (int, float)) and not isinstance(gold, bool) and player:
        player["gold"] = int(player.get("gold", 0) or 0) + int(gold)
    for flag in reward.get("flags") or []:
        # world_flags 全仓按"字符串集合"消费（谓词 flag: / 面板 chip / 叙事），
        # 数字或对象混进去只会产生永远匹配不上的死旗标——宁可拒绝。
        if isinstance(flag, str) and flag.strip():
            flags = state.setdefault("world_flags", [])
            if flag not in flags:
                flags.append(flag)


def _next_stage(state, quest, row):
    """当前 stage 的 next 里，第一个 enter_if 满足的；都不满足返回 None。"""
    cur = _stage_of(quest, row.get("stage") or "") or {}
    for sid in cur.get("next") or []:
        if sid in row["done_stages"]:
            continue
        st = _stage_of(quest, sid)
        if st and (st.get("enter_if") is None or evaluate(state, st["enter_if"])):
            return st
    return None


def complete_stage(state, quests, quest_id, stage_id, tick=None):
    """手动标记 stage 完成（宿主在玩家实际做到某事时调用）。

    为什么需要手动入口：有些目标（"把信交给林小姐"）引擎无法从数值推断，
    但它确实发生了——宿主是唯一知情方。这个入口只改 stage 状态，不编造世界状态。

    行为：标记完成 → 若它是当前 stage，则尝试进入下一个 stage；没有 next 则整条完成。
    """
    tick = int(state.get("tick", 0) or 0) if tick is None else int(tick)
    quest = next((q for q in (quests or []) if q["id"] == quest_id), None)
    if not quest:
        raise ValueError("未知事业线: %s" % quest_id)
    stage = _stage_of(quest, stage_id)
    if not stage:
        raise ValueError("事业线 %s 没有 stage: %s" % (quest_id, stage_id))

    row = _ensure_row(state, quest, quest_id, stage_id)
    if row.get("status") == "done":
        return row
    if stage_id not in row["done_stages"]:
        row["done_stages"].append(stage_id)
        row["history"].append({"tick": tick, "stage": stage_id, "event": "complete"})

    # 手动完成一个"未来"的 stage：把它当作当前 stage 已达成，直接从这里续
    if row.get("stage") in (None, stage_id):
        row["stage"] = stage_id
        nxt = _next_stage(state, quest, row)
        if nxt is not None:
            _enter_stage(state, quest, row, nxt, tick)
        elif not (stage.get("next") or []):
            _finish_quest(state, quest, row, tick)
    return row


def status(state, quests, only_active=True):
    """面板与 status 用：当前可见的事业线 + 进度 + 可执行目标。"""
    rows = state.get("quests") or {}
    out = []
    for quest in quests or []:
        row = rows.get(quest["id"]) or {"status": "dormant", "stage": None, "done_stages": []}
        if only_active and row["status"] == "dormant":
            continue
        cur = _stage_of(quest, row.get("stage") or "") or {}
        out.append({
            "id": quest["id"],
            "title": quest.get("title"),
            "summary": quest.get("summary"),
            "status": row["status"],
            "stage": row.get("stage"),
            "stage_title": cur.get("title"),
            "objectives": list(cur.get("objectives") or []),
            "next": list(cur.get("next") or []),
            "deadline_tick": quest.get("deadline_tick"),
            "tags": list(quest.get("tags") or []),
            "history": (row.get("history") or [])[-6:],
        })
    return out


def visible_count(state, quests):
    rows = state.get("quests") or {}
    return sum(1 for q in (quests or [])
               if (rows.get(q["id"]) or {}).get("status") in ("active", "done", "failed"))
