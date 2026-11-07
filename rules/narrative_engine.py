"""
叙事引擎 (Narrative Engine)

基于: 叙事学与游戏研究文献（Bartle 玩家类型 / 叙事传输 / 空间叙事 /
      涌现叙事），为 Agent 提供结构化叙事元数据
提供涌现故事的结构化元数据。Agent 用这些元数据生成文字描写。

关键约定（本模块的输出会被结算层消费，不只是展示）：
- 心流状态由**结构化胜负标记**判定（`event["outcome"]`），不靠中文关键词猜。
  旧实现只认"命中"，把"暴击!"当失败——这是真 bug，已由 verify_world 锁定。
- 六维道德向量按 **业债类型键**直接累加（`event["karma_type"]`），
  不解析中文文案——旧实现用英文键去 match 中文描述，真实对局永远得到全 0。
- 世界相位来自 `world_evolution.panarchy_step` 的状态机；本模块只读不推。
"""

import math
from typing import List, Dict

MORAL_DIMS = ("care", "fairness", "loyalty", "authority", "sanctity", "liberty")

# 业债类型 → 六维道德增量（Haidt MFT）。正=滋养该维，负=侵蚀该维。
KARMA_MORAL = {
    "murder_innocent": {"care": -3, "fairness": -2, "sanctity": -1},
    "murder_evil": {"fairness": -1, "loyalty": 1},
    "theft": {"fairness": -2},
    "lie": {"fairness": -1},
    "betray": {"loyalty": -3, "fairness": -2},
    "oath_broken": {"loyalty": -3, "authority": -2, "sanctity": -2},
    "minor_insult": {"authority": -1},
    "major_betrayal": {"loyalty": -4, "fairness": -3, "sanctity": -2},
    "mass_murder": {"care": -5, "fairness": -4, "sanctity": -3, "liberty": -2},
    "help_innocent": {"care": 2, "fairness": 1},
    "help_evil": {"care": -2, "loyalty": 1},
    "repay_debt": {"fairness": 2, "loyalty": 1},
    "save_life": {"care": 3, "sanctity": 1},
}

# 相位 → 涌现事件概率倍率（Ω 最烈）。与 world_evolution.PHASE_INTENSITY 同源语义。
PHASE_EVENT_MULT = {"Ω": 1.6, "α": 1.25, "r": 1.1, "K": 0.85}


def _phase_key(state: Dict) -> str:
    """当前相位字母；无演化状态时回退 K（最保守）。"""
    pan = state.get("panarchy") or {}
    ph = pan.get("phase")
    if ph:
        return str(ph)
    stored = state.get("panarchy_phase")
    if isinstance(stored, dict) and stored.get("phase"):
        return str(stored["phase"])
    return "K"


def phase_multiplier(state: Dict) -> float:
    """相位对事件/波动的烈度倍率（1.0 = 基准）。"""
    return PHASE_EVENT_MULT.get(_phase_key(state), 1.0)


def player_identity_vector(state: Dict) -> Dict:
    """玩家身份多维坐标 (Bartle 扩展 + MFT)，按结构化事件类型统计。"""
    events = state.get("event_log", [])
    counts = {"achiever": 0, "explorer": 0, "socializer": 0, "killer": 0}
    for ev in events:
        etype = str(ev.get("type") or "")
        if etype == "combat":
            counts["killer"] += 1
        elif etype == "trade":
            counts["achiever"] += 1
        elif etype == "social":
            counts["socializer"] += 1
        elif etype == "travel":
            counts["explorer"] += 1
        else:
            desc = str(ev.get("desc") or "")
            if "击败" in desc:
                counts["killer"] += 1
            elif "购买" in desc or "获得" in desc:
                counts["achiever"] += 1
            elif "帮助" in desc or "亲密" in desc:
                counts["socializer"] += 1
            elif "抵达" in desc:
                counts["explorer"] += 1
    total = max(1, len(events))
    out = {k: round(min(100.0, v * 100.0 / total), 2) for k, v in counts.items()}
    out["explorer"] = round(min(100.0, len(set(ev.get("location") for ev in events
                                                if ev.get("location"))) * 25.0
                                  + out["explorer"] * 0.5), 2)
    return out


def _combat_outcome(ev: Dict) -> str:
    """单条战斗事件的结果：win / loss / draw。

    优先读结构化字段 `outcome`（combat.resolve_combat 写入）；
    旧存档没有该字段时才退回文案判断，且把"暴击!"也算成命中。
    """
    oc = ev.get("outcome")
    if oc in ("win", "loss", "draw"):
        return str(oc)
    desc = str(ev.get("desc") or "")
    if "被击败" in desc or "闪避" in desc or "逃跑失败" in desc or "已经没有还手之力" in desc:
        return "loss"
    if "命中" in desc or "暴击" in desc or "击败" in desc or "逃跑成功" in desc:
        return "win"
    return "draw"


def flow_channel_status(state: Dict) -> Dict:
    """基于最近战斗胜率判定心流/焦虑/无聊（结构化结果，不猜词）。"""
    events = state.get("event_log", [])
    combat_events = [e for e in events if e.get("type") == "combat"]
    if len(combat_events) < 3:
        return {"state": "flow", "adjustment": 0.0, "confidence": "low"}

    recent = combat_events[-8:]
    outcomes = [_combat_outcome(e) for e in recent]
    decided = [o for o in outcomes if o != "draw"]
    if not decided:
        return {"state": "flow", "adjustment": 0.0, "confidence": "low", "win_rate": 0.5}
    wins = sum(1 for o in decided if o == "win")
    win_rate = wins / len(decided)

    target = 0.65
    if abs(win_rate - target) < 0.15:
        return {"state": "flow", "adjustment": 0.0, "win_rate": round(win_rate, 2),
                "target": target}
    if win_rate > target + 0.15:
        delta = min(0.3, (win_rate - target) * 0.5)
        return {"state": "boredom", "adjustment": round(delta, 3),
                "win_rate": round(win_rate, 2), "target": target}
    delta = max(-0.3, (win_rate - target) * 0.5)
    return {"state": "anxiety", "adjustment": round(delta, 3),
            "trigger_luck": win_rate < 0.3, "win_rate": round(win_rate, 2),
            "target": target}


def narrative_event_weight(event_probability: float, base_importance: float = 1.0) -> float:
    """事件叙事权重 = 自信息量 I(E) = -log P(E)"""
    if event_probability <= 0:
        return float('inf')
    return -math.log(event_probability) * base_importance


def check_world_emergent_events(state: Dict) -> List[Dict]:
    """基于世界状态阈值检查涌现事件（概率按世界相位缩放）。

    只返回**本回合尚未记录过**的事件：`state["_emergent_seen"]` 由调用方
    （narrative 工具）维护为 {type: tick}，同一 tick 同一类型不重复触发。
    """
    events = []
    tick = state.get("tick", 0)
    event_count = len(state.get("event_log", []))
    mult = phase_multiplier(state)
    seen = state.get("_emergent_seen") or {}

    def fresh(kind: str) -> bool:
        return int(seen.get(kind, -1)) != int(tick)

    if event_count > 10 and tick > 20 and fresh("calamity_omen"):
        p = min(0.9, event_count / 50.0 * mult)
        events.append({"type": "calamity_omen", "kind": "calamity_omen",
                       "desc": "天地灵气出现异常波动，天机紊乱",
                       "probability": round(p, 3)})

    unique_relations = set()
    for k in state.get("relations", {}).keys():
        for p in str(k).split(":"):
            if p != "player" and p:
                unique_relations.add(p)

    if len(unique_relations) > 3 and fresh("reputation_spread"):
        p = min(0.95, len(unique_relations) / 8.0 * mult)
        events.append({"type": "reputation_spread", "kind": "reputation_spread",
                       "desc": "你的名声已在%d个圈子传开" % len(unique_relations),
                       "probability": round(p, 3)})

    total = sum(int(e.get("amount", 0) or 0) for e in state.get("karma_ledger", [])
                if not e.get("settled"))
    if total >= 300 and fresh("karma_collapse"):
        p = min(0.95, total / 300.0 * mult / 1.2)
        events.append({"type": "karma_collapse", "kind": "karma_collapse",
                       "desc": "因果大清算即将降临...", "probability": round(p, 3)})

    return events


def update_player_moral_identity(state: Dict) -> Dict:
    """六维道德向量：按业债类型键累加，并合并实体自身的 morality。

    数据源优先级（后两条是旧存档兼容）：
      1. **`karma_ledger`**（权威总账：有类型、有金额、按 keep 封顶，不随 event_log 归档丢失）
      2. 事件里的 `karma_type` 字段
      3. 事件文案里出现 KARMA_LABELS 的中文标签
      4. 实体 `morality` 基础值（建局时设定）
    """
    from game_engine.rules.karma import KARMA_LABELS
    vec = {d: 0 for d in MORAL_DIMS}
    base = ((state.get("entities") or {}).get("player") or {}).get("morality") or []
    for i, d in enumerate(MORAL_DIMS):
        try:
            vec[d] += int(base[i])
        except (IndexError, TypeError, ValueError):
            pass

    applied = 0
    for entry in (state.get("karma_ledger") or []):
        ktype = str(entry.get("type") or "")
        if ktype in KARMA_MORAL:
            # 道德画像是"做过什么"，与是否已还清无关 → 已结算条目同样计入。
            # 合并条目（type=merged）已失去具体类型，不参与画像。
            for d, delta in KARMA_MORAL[ktype].items():
                vec[d] += delta
            applied += 1
    if applied:
        return {d: max(-100, min(100, vec[d])) for d in MORAL_DIMS}

    label_to_type = {v: k for k, v in KARMA_LABELS.items()}
    for ev in state.get("event_log", []):
        ktype = ev.get("karma_type")
        if not ktype:
            desc = str(ev.get("desc") or "")
            for label, t in label_to_type.items():
                if label and label in desc:
                    ktype = t
                    break
        if not ktype or ktype not in KARMA_MORAL:
            continue
        for d, delta in KARMA_MORAL[ktype].items():
            vec[d] += delta

    return {d: max(-100, min(100, vec[d])) for d in MORAL_DIMS}


def moral_affinity_multiplier(state: Dict) -> float:
    """**当前恶名**对社交结算的乘数：只看未清业债，不看已经还清的历史。

    为什么按未清业债而不是六维向量：六维是"一生的道德画像"（面板要看），
    而"别人现在怎么对你"取决于你还欠着什么——还清之后名声应该能恢复。
    返回 0.6 ~ 1.6；无未清业债时恰为 1.0，保持旧行为不变。
    """
    from game_engine.rules.karma import KARMA_VALUES
    total = 0
    for e in (state.get("karma_ledger") or []):
        if e.get("settled") or e.get("from") != "player":
            continue
        amount = int(e.get("amount", 0) or 0)
        weight = KARMA_VALUES.get(str(e.get("type") or ""), 20)
        total += amount * (abs(weight) / 20.0)
    return round(max(0.6, min(1.6, 1.0 - total / 400.0)), 3)


def moral_score(state: Dict) -> int:
    """六维道德画像的合成分（面板与 status 用；与上面那个"当前恶名"不是一回事）。"""
    vec = update_player_moral_identity(state)
    return int(sum(vec.values()))


def panarchy_phase_check(state: Dict) -> Dict:
    """世界相位（读 `state["panarchy"]`，由 world_evolution 推进；旧存档按真实量推导）。"""
    pan = state.get("panarchy") or {}
    if pan.get("phase"):
        from game_engine.rules.world_evolution import PHASE_INFO
        info = dict(PHASE_INFO.get(str(pan["phase"]), PHASE_INFO["K"]))
        info["capital"] = pan.get("capital")
        info["connectedness"] = pan.get("connectedness")
        info["stress"] = pan.get("stress")
        info["collapses"] = int(pan.get("collapses", 0) or 0)
        return info

    # 旧存档 / 未演化状态：用现有资产推导，而不是硬编码常数
    from game_engine.rules.world_dynamics import panarchy_phase
    from game_engine.rules.world_evolution import _factions, _market_index

    fac = _factions(state)
    avg_power = (sum(float(v.get("power", 50.0)) for v in fac.values()) / len(fac)) if fac else 50.0
    entities = state.get("entities") or {}
    capital = min(1.0, 0.30 + avg_power / 120.0 + max(0.0, _market_index(state) - 1.0))
    connectedness = min(1.0, len(state.get("relations") or {}) / max(1, len(entities))
                        + len(state.get("world_flags") or []) / 20.0)
    return panarchy_phase(capital, connectedness, 0.5)
