"""
社交关系更新规则 (Social)

关系=二维向量 (affinity, respect)，各自取值 -100 ~ 100
affinity: 亲密度 (喜欢/厌恶)
respect: 敬重/畏惧

不同世界观共用同一社交公式，只是事件描写不同。
"""

import math
from game_engine.state_schema import set_relation, get_relation

def resolve_social_event(state, actor_id, target_id, event_type, intensity=1):
    """
    基于事件类型更新关系
    
    事件类型:
        "help":      帮助 → affinity +5, respect +3
        "harm":      伤害 → affinity -20, respect ±0
        "threaten":  威胁 → affinity -10, respect -5 (弱者恐惧)
        "intimidate":恐吓 → affinity -10, respect +5 (强者敬畏)
        "gift":      送礼 → affinity +8, respect +0
        "betray":    背叛 → affinity -50, respect -30
        "cooperate": 合作 → affinity +6, respect +6
        "insult":    侮辱 → affinity -15, respect -10
        "praise":    赞美 → affinity +4, respect +2
        "murder":    杀人 → affinity -40, respect ±(对等)
    
    intensity: 强度倍率 (1=普通, 2=严重, 3=灭门级)
    
    返回: {
        "affinity_before": 10,
        "affinity_after": -10,
        "respect_before": 0,
        "respect_after": -5,
        "events": ["伤害导致关系恶化"]
    }
    """
    BEFORE = {
        "help":       (5, 3),
        "harm":       (-20, 0),
        "threaten":   (-10, -5),
        "intimidate": (-10, 5),
        "gift":       (8, 0),
        "betray":     (-50, -30),
        "cooperate":  (6, 6),
        "insult":     (-15, -10),
        "praise":     (4, 2),
        "murder":     (-40, 0),
    }
    
    try:
        intensity = float(intensity)
    except (TypeError, ValueError):
        raise ValueError("intensity 必须是数字")
    if not math.isfinite(intensity) or intensity <= 0:
        raise ValueError("intensity 必须是有限正数（收到 %r）" % intensity)
    if event_type not in BEFORE:
        raise ValueError("未知社交事件: %s（可用: %s）"
                         % (event_type, " / ".join(sorted(BEFORE))))

    affinity_delta, respect_delta = BEFORE.get(event_type, (0, 0))
    affinity_delta *= intensity
    respect_delta *= intensity

    # 道德向量修正：恶名会放大他人对你的负面反应，仁厚会放大正面反应。
    # 全零向量（中立）时乘数恰为 1.0，旧行为不变。
    moral_mult = 1.0
    try:
        from game_engine.rules.narrative_engine import moral_affinity_multiplier
        moral_mult = float(moral_affinity_multiplier(state))
        if affinity_delta < 0:
            affinity_delta *= (2.0 - moral_mult)
        else:
            affinity_delta *= moral_mult
        affinity_delta = int(round(affinity_delta))
        respect_delta = int(round(respect_delta))
    except Exception:  # aqg: top-level boundary —— 道德是辅助输入，坏了退回原始增量
        moral_mult = 1.0

    before = get_relation(state, actor_id, target_id)
    set_relation(state, actor_id, target_id, affinity_delta, respect_delta)
    after = get_relation(state, actor_id, target_id)
    
    result = {
        "affinity_before": before["affinity"],
        "affinity_after": after["affinity"],
        "respect_before": before["respect"],
        "respect_after": after["respect"],
        "moral_multiplier": round(moral_mult, 3),
        "events": []
    }
    
    target_ent = state["entities"].get(target_id, {})
    target_name = target_ent.get("name", target_id)
    
    if affinity_delta != 0:
        direction = "上升" if affinity_delta > 0 else "下降"
        result["events"].append(
            f"{target_name}对{state['entities'].get(actor_id, {}).get('name', actor_id)}的亲密{affinity_delta}"
        )
    
    if respect_delta != 0:
        direction = "上升" if respect_delta > 0 else "下降"
        result["events"].append(
            f"{target_name}对{state['entities'].get(actor_id, {}).get('name', actor_id)}的敬重{direction}{abs(respect_delta)}"
        )
    
    return result

def compute_influence(state, actor_id, target_id):
    """
    计算 actor 对 target 的影响力 (用于说服/威胁判定)
    基础: actor 的实力 × respect差 + affinity加成
    
    返回: 0.0~1.0 之间的影响力系数
    """
    actor = state["entities"].get(actor_id, {})
    target = state["entities"].get(target_id, {})
    
    # 战力强度 (简化的装备+属性总和)
    actor_power = sum(actor.get("attrs", {}).values()) + (actor.get("attrs", {}).get("level_num", 1)) * 5
    target_power = sum(target.get("attrs", {}).values()) + (target.get("attrs", {}).get("level_num", 1)) * 5
    
    power_ratio = actor_power / max(1, actor_power + target_power)
    
    rel = get_relation(state, actor_id, target_id)
    # respect 加成 (敬重使人顺从)
    respect_bonus = rel["respect"] / 200  # -0.5 ~ +0.5
    # affinity 加成 (亲近使人信任)
    affinity_bonus = rel["affinity"] / 300  # -0.33 ~ +0.33
    
    influence = power_ratio + respect_bonus + affinity_bonus
    return max(0.0, min(1.0, influence))
