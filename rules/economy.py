"""
经济结算规则 (Economy)

成交价 = 当前价 × 与数量相关的供需乘数（买入推价 ≤1.5×，卖出压价 ≥0.5×）；
每回合 tick_market 按 OU 均值回归（models.ou_price_reverted）把价格缓慢
拉回 base_price，并缓慢补库存。

卖出须先持有（ent.items）——卖自己没有的东西等于印钱，挡在结算之前。
"""



DEFAULT_BASE_PRICES = {
    "回灵丹": 50,
    "金疮药": 30,
    "辟谷丹": 20,
    "灵石": 100,
    "凝气丸": 80,
    "辟尘符": 40,
}

def init_market(location_id, items=None):
    """初始化一个市场"""
    if items is None:
        items = ["回灵丹", "金疮药", "辟谷丹"]
    market = {}
    for item in items:
        market[item] = {
            "price": DEFAULT_BASE_PRICES.get(item, 50),
            "supply": 20,
            "base_price": DEFAULT_BASE_PRICES.get(item, 50)
        }
    return market

def _held(ent, item):
    return int((ent.get("items") or {}).get(item, 0))


def _add_items(ent, item, delta):
    inv = ent.get("items")
    if not isinstance(inv, dict):
        inv = ent["items"] = {}
    n = int(inv.get(item, 0)) + int(delta)
    if n > 0:
        inv[item] = n
    else:
        inv.pop(item, None)


def resolve_trade(state, location_id, item, quantity, is_buyer, entity_id):
    """
    结算一次交易
    
    参数:
        is_buyer: True=玩家购买, False=玩家卖出
        entity_id: 交易方 entity id
    
    返回: {
        "success": true,
        "price_per_unit": 50,
        "total_cost": 100,
        "price_after": 52,    # 交易后新价格
        "supply_after": 18,
        "events": ["玩家购买回灵丹×2，花费100灵石"]
    }
    """
    cur = state.get("currency", "灵石")   # 世界观无关：货币名由状态给出（默认「灵石」，与 use_item 一致）
    loc_market = state.get("market", {}).get(location_id)
    result = {
        "success": False,
        "price_per_unit": 0,
        "total_cost": 0,
        "price_after": 0,
        "supply_after": 0,
        "events": []
    }
    
    if quantity <= 0:
        result["events"].append("交易数量必须为正")
        return result

    if not loc_market or item not in loc_market:
        result["events"].append(f"此地没有{item}")
        return result
    
    ent = state["entities"].get(entity_id)
    if not ent:
        result["events"].append("交易方不存在")
        return result
    
    item_data = loc_market[item]
    # 负价格会让买入变成"加钱"（total 为负 → gold -= total 反而增加），
    # 属于可被设定包/手改状态放大成无限金钱的漏洞，必须在结算前拒绝。
    if int(item_data.get("price", 0) or 0) < 1:
        result["events"].append("商品价格非法（必须为正）")
        return result
    item_name = item_data.get("name") or item   # 叙事文本用显示名，item_key 只做定位
    
    # 大宗交易引起的价格波动
    supply_ratio = quantity / max(1, item_data["supply"])
    
    supply = max(0, int(item_data.get("supply", 0) or 0))
    if is_buyer:
        if supply < quantity:
            result["events"].append(f"库存不足(只剩{supply}个)")
            return result
        
        # 价格随购买量上升
        price_multiplier = 1.0 + supply_ratio * 0.2
        price = int(item_data["price"] * min(price_multiplier, 1.5))
        total = price * quantity
        
        if ent.get("gold", 0) < total:
            result["events"].append(f"{cur}不足(需要{total}，只有{ent.get('gold', 0)})")
            return result
        
        # 执行交易
        ent["gold"] -= total
        item_data["supply"] = supply - quantity
        _add_items(ent, item, quantity)
        # 价格更新基于本次成交价（用旧价会把大宗买入的涨价吞掉，出现买完立刻卖出套利）
        item_data["price"] = max(1, int(price * (1 + min(supply_ratio, 1.0) * 0.05)))
        
        result["success"] = True
        result["price_per_unit"] = price
        result["total_cost"] = total
        result["price_after"] = item_data["price"]
        result["supply_after"] = item_data["supply"]
        result["items_after"] = _held(ent, item)
        result["events"].append(
            f"{ent['name']}购买{item_name}×{quantity}，花费{total}{cur}"
        )
        
        # 大宗交易影响关系 (坊主印象)
        if quantity >= 5:
            result["events"].append(f"坊主注意到了{ent['name']}的大额购买")
            result["relation_hint"] = "merchant"
    else:
        # 卖出：必须先持有（卖自己从没有的东西 = 印钱，挡在结算前）
        held = _held(ent, item)
        if held < quantity:
            result["events"].append(f"没有足够的{item}可卖（仅持有{held}，要卖{quantity}）")
            return result

        price_multiplier = max(0.5, 1.0 - supply_ratio * 0.15)
        price = int(item_data["price"] * price_multiplier)
        total = price * quantity
        
        ent["gold"] = ent.get("gold", 0) + total
        item_data["supply"] = supply + quantity
        _add_items(ent, item, -quantity)
        # 卖出只让价格回落，不抬高 base_price：
        # 旧实现 max(base, sell_price) 是单向棘轮，长局里物价只能涨不能跌。
        sell_price = int(item_data["price"] * (1 - supply_ratio * 0.03))
        item_data["price"] = max(1, sell_price)
        
        result["success"] = True
        result["price_per_unit"] = price
        result["total_cost"] = total
        result["price_after"] = item_data["price"]
        result["supply_after"] = item_data["supply"]
        result["items_after"] = _held(ent, item)
        result["events"].append(
            f"{ent['name']}出售{item_name}×{quantity}，获得{total}{cur}"
        )
    
    return result

def tick_market(state):
    """每回合：价格向 base_price 均值回归 + 小幅市场扰动，供给缓慢恢复。

    为什么要有扰动：纯确定性 OU（sigma=0）在价格等于基准时**永远不动**，
    于是"物价指数"图表永远是一条 1.0 的平线——玩家看不到任何市场动态，
    面板三张图里有一张等于废图。

    扰动必须仍是**确定性**的（本项目核心不变量：同种子同结果）：
    用 state 里的 rng_seed/tick/商品键 派生一个 [-1,1] 的伪随机量，
    不调用 random 模块，因此不会消耗 rng_counter，也不破坏回放一致性。
    """
    import hashlib as _hl

    seed = state.get("rng_seed") or 0
    tick = int(state.get("tick", 0) or 0)
    for loc_id, loc_market in state.get("market", {}).items():
        for item, data in loc_market.items():
            base = int(data.get("base_price", data.get("price", 0)) or 0)
            cur = int(data.get("price", 0) or 0)
            # 派生 [-1, 1]：sha256(seed|tick|loc|item) 取前 8 字节归一
            key = ("%s|%s|%s|%s" % (seed, tick, loc_id, item)).encode("utf-8")
            h = int.from_bytes(_hl.sha256(key).digest()[:8], "big")
            jitter = (h / float(1 << 64)) * 2.0 - 1.0
            # 扰动幅度：基准价的 4%。config.market_jitter=False 时关闭，
            # 供"价格必须严格等于 OU 闭式解"的预测类用例使用（见 upload_test）。
            jitter_on = (state.get("config") or {}).get("market_jitter", True)
            noise = (jitter * max(1.0, base * 0.04)) if jitter_on else 0.0
            data["price"] = max(1, int(round(cur + (-0.15 * (cur - base)) + noise)))
            # 供给向 20 回归（卖出造成的超额库存在回合里慢慢消化，而不是永久滞留）
            supply = int(data.get("supply", 0) or 0)
            if supply < 20:
                data["supply"] = supply + 1
            elif supply > 20:
                data["supply"] = supply - 1
