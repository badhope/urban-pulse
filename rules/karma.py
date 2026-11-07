"""
因果债分录规则 (Karma / Causal Debt)

底层思想: 所有行动产生"业"，业的总量必须平衡。
杀死一个筑基修士的业 > 杀死一个凡人。
欠债不还在未来某个时刻收敛——可能是天劫、心魔、或因果清算。

这是世界观无关的底层原理: 
- 修真 = 天劫降临
- 武侠 = 江湖恩怨，正道围剿
- 奇幻 = 神罚降临
- 科幻 = 社会信任崩塌
"""

from game_engine.state_schema import add_karma, get_unsettled_karma

# 叙事文本用中文标签（这些事件会进编年史与面板时间线，英文枚举会直接漏给玩家）
KARMA_LABELS = {
    "murder_innocent": "杀害无辜",
    "murder_evil": "诛杀恶人",
    "theft": "偷窃",
    "lie": "说谎",
    "betray": "背叛",
    "help_innocent": "助人",
    "help_evil": "助纣为虐",
    "repay_debt": "还债",
    "oath_broken": "誓约违背",
    "minor_insult": "轻慢失礼",
    "major_betrayal": "背信弃义",
    "save_life": "救人性命",
    "mass_murder": "大开杀戒",
}

KARMA_VALUES = {
    "murder_innocent": 50,
    "murder_evil": 5,
    "theft": 15,
    "lie": 5,
    "betray": 40,
    "help_innocent": -10,
    "help_evil": 20,
    "repay_debt": -30,
    "oath_broken": 60,
    "minor_insult": 8,
    "major_betrayal": 80,
    "save_life": -20,
    "mass_murder": 200,
}


def resolve_karma(state, actor_id, victim_id=None, action_type="normal"):
    """
    基于行动类型计业
        
    事件类型及业力量级:
        "murder_innocent":  杀害无辜  +50
        "murder_evil":      诛杀恶人  +5 (杀亦有业)
        "theft":            偷窃      +15
        "lie":              说谎      +5
        "betray":           背叛      +40
        "help_innocent":    助人      -10 (消业)
        "help_evil":        助纣为虐  +20
        "repay_debt":       还债      -30 (大幅消业)
        "oath_broken":      誓约违背  +60
    
    返回: {
        "karma_delta": 50,
        "total_unsettled": 120,
        "risk_level": "moderate",     # low/moderate/high/extreme
        "events": ["杀害无辜，背负50业"]
    }
    """
    result = {
        "karma_delta": 0,
        "total_unsettled": 0,
        "risk_level": "low",
        "events": []
    }
    
    delta = KARMA_VALUES.get(action_type, 0)
    result["karma_delta"] = delta
    
    actor = state["entities"].get(actor_id, {})
    actor_name = actor.get("name", actor_id)
    
    if delta > 0:
        # 无具体受害者（屠城/纵火等）也必须记账：victim=None 不是"没有业"，
        # 只是没有可指向的对象。用 "world" 占位，保证业债、风险等级与天劫机制不被绕过。
        add_karma(state, actor_id, victim_id or "world", action_type, delta)
        result["events"].append(f"{actor_name}因{KARMA_LABELS.get(action_type, action_type)}背负{delta}业")
    elif delta < 0:
        # 消业: 寻找未偿还的 karma 条目并部分结算
        _settle_karma(state, actor_id, abs(delta))
        result["events"].append(f"{actor_name}因{KARMA_LABELS.get(action_type, action_type)}消除{abs(delta)}业")
    
    total = get_unsettled_karma(state, actor_id)
    result["total_unsettled"] = total
    
    # 业力等级 (与 consequence 阈值统一)
    #   extreme/catastrophe:  >= 300 (天劫/大清算)
    #   high/strong_pressure: >= 150 (沉重压力)
    #   moderate/mild_pressure: >= 60 (隐约负担)
    #   low/none:             <  60
    if total >= 300:
        result["risk_level"] = "extreme"
    elif total >= 150:
        result["risk_level"] = "high"
    elif total >= 60:
        result["risk_level"] = "moderate"
    else:
        result["risk_level"] = "low"
    
    return result

def _settle_karma(state, entity_id, amount):
    """结算 karma: 从最早的条目开始消。

    部分结算不再直接改写原条目金额（那会让"这笔债最初是多少"永久不可考），
    而是把已还部分拆成一条 settled 记录，原条目保留剩余未清金额。
    """
    remaining = amount
    ledger = state.get("karma_ledger") or []
    paid_parts = []
    for entry in ledger:
        if entry["from"] == entity_id and not entry["settled"] and remaining > 0:
            if entry["amount"] <= remaining:
                remaining -= entry["amount"]
                entry["settled"] = True
            else:
                paid = remaining
                paid_parts.append({
                    "from": entry["from"],
                    "to": entry.get("to", ""),
                    "type": entry.get("type", ""),
                    "amount": paid,
                    "tick": entry.get("tick", 0),
                    "settled": True,
                    "partial_of": entry.get("tick"),
                })
                entry["amount"] = entry["amount"] - paid
                remaining = 0
    ledger.extend(paid_parts)

def get_karma_consequence(state, entity_id):
    """
    检查业力是否触发后果
    依据 risk_level 返回可能的后果类型
    """
    total = get_unsettled_karma(state, entity_id)
    
    if total >= 300:
        return {
            "triggered": True,
            "type": "catastrophe",
            "desc": "因果大清算即将降临",
            "effects": ["npc自发敌意", "突破时心魔大爆发", "随机厄运事件+"]
        }
    elif total >= 150:
        return {
            "triggered": True,
            "type": "strong_pressure",
            "desc": "因果压力沉重",
            "effects": ["突破成功率-30%", "陌生npc初识好感-10"]
        }
    elif total >= 60:
        return {
            "triggered": True,
            "type": "mild_pressure",
            "desc": "因果负担隐约",
            "effects": ["突破成功率-10%"]
        }
    
    return {"triggered": False, "type": "none", "desc": "", "effects": []}
