"""
等级阶梯 (Progression)

把「境界/等级」从纯展示字段变成**有机制作用的数值**：
设定包可在 `config.level_tiers` 给出本世界的等级阶梯（如
["淬体", "练气", "筑基", ...] 或 ["F-class", "E-class", ...]），
实体的 `level` 与阶梯做前缀匹配得到 tier 序号，战斗/社交据此加权重。

未配置阶梯时的行为：
- 有 `attrs.level_num` 就用它（旧数据兼容）
- 否则用 `stage`（突破次数）
- 都没有则 tier=0 —— 等于旧行为，不会因缺配置而报错。
"""

from typing import List


def level_tiers(state: dict) -> List[str]:
    """本世界的等级阶梯（配置里没有就返回空表）。"""
    cfg = state.get("config") or {}
    tiers = cfg.get("level_tiers")
    if isinstance(tiers, list):
        return [str(t) for t in tiers if str(t).strip()]
    return []


def level_tier(state: dict, entity: dict) -> int:
    """实体在本世界阶梯中的序号（0 起）；无法判定时回退 level_num / stage。"""
    ent = entity or {}
    tiers = level_tiers(state)
    level = str(ent.get("level") or "")
    if tiers and level:
        # 最长匹配优先：阶梯里同时有「练气」和「练气三层」时，
        # "练气三层" 必须命中更具体的项，否则层级被低估（实测返回 0）。
        best = None
        for i, name in enumerate(tiers):
            if level.startswith(name) or name in level:
                if best is None or len(name) > len(tiers[best]):
                    best = i
        if best is not None:
            return best
    attrs = ent.get("attrs") or {}
    for key in ("level_num", "tier", "rank"):
        val = attrs.get(key)
        if isinstance(val, (int, float)):
            return max(0, int(val))
    return max(0, int(ent.get("stage", 0) or 0))


def tier_bonus(state: dict, entity: dict) -> float:
    """等级带来的实力加成（每阶 +2 战力，与五维属性同量纲）。"""
    return level_tier(state, entity) * 2.0


def validate_next_level(state: dict, next_level: str, current_level: str = "") -> str:
    """校验突破目标是否是阶梯上的下一层（未配置阶梯时放行，保持旧行为）。

    返回规范化后的等级名；配置了阶梯却跳级/未知时抛 ValueError，
    让宿主能从报错里读到自己该传什么——而不是把任意字符串写进等级。
    允许带层数后缀（「练气三层」匹配阶梯项「练气」），因为设定包里的等级
    通常是「阶名 + 层数」的组合写法。
    """
    name = str(next_level or "").strip()
    if not name:
        raise ValueError("next_level 不能为空")
    tiers = level_tiers(state)
    if not tiers:
        return name

    def match(value: str):
        if not value:
            return None
        best = None
        for i, t in enumerate(tiers):
            if value == t or value.startswith(t) or t in value:
                if best is None or len(t) > len(tiers[best]):
                    best = i
        return best

    idx = match(name)
    if idx is None:
        raise ValueError("next_level 只能是本世界阶梯里的名字：%s（收到 %r）"
                         % (" / ".join(tiers), name))
    cur_idx = match(str(current_level or ""))
    if cur_idx is not None:
        # 同阶内的段位递进（淬体七段 → 淬体八段）合法；跨阶只能 +1；倒退与跳阶都拒
        if idx == cur_idx and name == current_level:
            raise ValueError("next_level 与当前等级相同（%r），没有可突破的目标" % name)
        if idx == cur_idx:
            # 同阶里比较段位序号（"七段"的七）：拿得到序号时倒退要拒
            # （实测"淬体七段 -> 淬体一段"旧实现直接放行）；拿不到序号维持放行，
            # 因为段位写法（三层/三重/三层天）没有跨世界通用的解析规则。
            a, b = _stage_ordinal(current_level), _stage_ordinal(name)
            if a is not None and b is not None and b < a:
                raise ValueError("突破不能倒退：当前 %r，收到 %r" % (current_level, name))
        if idx < cur_idx:
            raise ValueError("突破不能倒退：当前 %r，收到 %r" % (current_level, name))
        if idx > cur_idx + 1:
            expect = tiers[cur_idx + 1]
            raise ValueError("突破必须逐阶递进：当前 %r，下一层应是 %s（收到 %r）"
                             % (current_level, expect, name))
    elif idx > 0:
        raise ValueError("当前等级 %r 不在本世界阶梯上，无法判断是否递进；"
                         "阶梯为：%s" % (current_level, " / ".join(tiers)))
    return name


def _stage_ordinal(level: str):
    """取等级里的段位序号：中文（一~十/一段~九段）或阿拉伯数字；取不到返回 None。"""
    text = str(level or "")
    import re as _re
    m = _re.search(r"[一二三四五六七八九十]+(?=段|层|重|阶|品|星)", text)
    if m:
        token = m.group(0)
        # 组合写法（"十一"→11、"二十"→20）先算；单字直接查表。
        if len(token) > 1:
            units = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
                     "六": 6, "七": 7, "八": 8, "九": 9}
            if "十" in token:
                head, _, tail = token.partition("十")
                return (units.get(head, 1) if head else 1) * 10 + units.get(tail, 0)
        table = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
                 "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
        return table.get(token)
    m2 = _re.search(r"(\d+)(?=段|层|重|阶|品|星)", text)
    if m2:
        return int(m2.group(1))
    return None
