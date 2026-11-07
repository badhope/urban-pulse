"""
通用游戏层 (Game System) —— 让同一内核跑任何类型的游戏

为什么需要：原内核把"气血 / 内力 / 境界 / 灵石"写进了面板与状态。World Games 要
通用于跑团、调查、经营、生存、文字冒险、桌游，就不能假设玩家一定有"血条"。

这一层提供三样东西：
  · **游戏档案** `state["game"]`：自定义属性、资源、进度轨、标签、自由表格；
  · **回退推导**：没有显式档案时，从既有的 hp/mp/gold/attrs/playbook 推导出一份，
    旧存档与四套设定包的面板因此照常可用（不迁移、不破坏）；
  · **有界更新**：所有数值都有 min/max，写入前 clamp；条目数有上限。

设计约束与其他 rules 一致：纯标准库、纯函数、不读写文件、不依赖时间/全局随机。
"""

MAX_ENTRIES = 32
MAX_LABEL = 24
MAX_KEY = 32
MAX_TAGS = 24
MAX_TAG_LEN = 24
MAX_SHEET_FIELDS = 40
MAX_SHEET_VALUE = 240

KINDS = ("rpg", "investigation", "management", "survival", "story", "board", "custom")

ATTR_LABELS = {
    "str": "力量", "dex": "敏捷", "int": "智力", "con": "体质", "cha": "魅力",
    "per": "感知", "wil": "意志", "luck": "幸运", "san": "理智", "edu": "学识",
}


def _num(value, default=0):
    try:
        if isinstance(value, bool):
            return default
        out = float(value) if isinstance(value, float) else int(value)
    except (TypeError, ValueError):
        return default
    # NaN/Infinity 一律回退 default：json.dump 会把它们写成 NaN/Infinity，
    # 浏览器 JSON.parse 遇到直接抛错，面板整页挂掉（实测 game_adjust(inf) 后 /state 500）。
    if isinstance(out, float) and (out != out or out in (float("inf"), float("-inf"))):
        return default
    return out


def _label(value, fallback=""):
    text = str(value or "").strip()
    return (text or fallback)[:MAX_LABEL]


def _key(value):
    text = str(value or "").strip()
    if not text:
        raise ValueError("游戏条目的 key 不能为空")
    return text[:MAX_KEY]


def _normalize_entry(raw, kind, index=0):
    """规范化一个属性 / 资源 / 进度轨条目。"""
    if not isinstance(raw, dict):
        raise ValueError("%s[%d] 必须是对象" % (kind, index))
    key = _key(raw.get("key"))
    lo = _num(raw.get("min", 0), 0)
    hi = _num(raw.get("max", 0), 0)
    if hi and hi < lo:
        lo, hi = hi, lo
    value = _num(raw.get("value", raw.get("current", lo)), lo)
    if hi and hi > lo:
        value = max(lo, min(hi, value))
    entry = {
        "key": key,
        "label": _label(raw.get("label"), key),
        "value": round(value, 3) if isinstance(value, float) else int(value),
        "min": round(lo, 3) if isinstance(lo, float) else int(lo),
        "max": round(hi, 3) if isinstance(hi, float) else int(hi),
    }
    if raw.get("color") in ("hp", "mp", "gold", "accent", "danger", "success"):
        entry["color"] = str(raw["color"])
    if raw.get("note"):
        entry["note"] = str(raw["note"])[:MAX_SHEET_VALUE]
    return entry


def _normalize_list(raw, kind):
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("%s 必须是数组" % kind)
    out, seen = [], set()
    for i, item in enumerate(raw[:MAX_ENTRIES]):
        entry = _normalize_entry(item, kind, i)
        if entry["key"] in seen:
            continue
        seen.add(entry["key"])
        out.append(entry)
    return out


def normalize(raw: dict) -> dict:
    """把外部传入的游戏档案规范成可落盘的结构（容错：坏条目跳过而不是整局失败）。"""
    if not isinstance(raw, dict):
        raw = {}
    kind = str(raw.get("kind") or "custom").strip().lower()
    profile = {
        "title": _label(raw.get("title"), ""),
        "kind": kind if kind in KINDS else "custom",
        "attributes": _normalize_list(raw.get("attributes"), "attributes"),
        "resources": _normalize_list(raw.get("resources"), "resources"),
        "meters": _normalize_list(raw.get("meters"), "meters"),
        "tags": [],
        "sheet": {},
    }
    tags = raw.get("tags")
    if isinstance(tags, list):
        for tag in tags[:MAX_TAGS]:
            text = str(tag or "").strip()[:MAX_TAG_LEN]
            if text and text not in profile["tags"]:
                profile["tags"].append(text)
    sheet = raw.get("sheet")
    if isinstance(sheet, dict):
        for i, (k, v) in enumerate(sheet.items()):
            if i >= MAX_SHEET_FIELDS:
                break
            key = str(k or "").strip()[:MAX_LABEL]
            if not key:
                continue
            if isinstance(v, (str, int, float, bool)):
                profile["sheet"][key] = str(v)[:MAX_SHEET_VALUE] if not isinstance(v, bool) else v
    return profile


def _derived(state: dict) -> dict:
    """没有显式档案时的回退：从既有 hp/mp/gold/attrs/playbook 推导（旧存档零迁移）。"""
    player = (state.get("entities") or {}).get("player") or {}
    terms = ((state.get("ui") or {}).get("terms") or {}) if isinstance(state.get("ui"), dict) else {}
    resources = []
    hp_max = _num(player.get("hp_max", 0))
    mp_max = _num(player.get("mp_max", 0))
    resources.append({"key": "hp", "label": _label(terms.get("hp"), "生命"), "value": _num(player.get("hp", 0)),
                      "min": 0, "max": hp_max or 0, "color": "hp"})
    if mp_max or _num(player.get("mp", 0)):
        resources.append({"key": "mp", "label": _label(terms.get("mp"), "法力"), "value": _num(player.get("mp", 0)),
                          "min": 0, "max": mp_max or 0, "color": "mp"})
    resources.append({"key": "gold", "label": _label(terms.get("gold"), "钱财"),
                      "value": _num(player.get("gold", 0)), "min": 0, "max": 0, "color": "gold"})

    attributes = []
    for key, val in (player.get("attrs") or {}).items():
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            continue
        attributes.append({"key": str(key), "label": ATTR_LABELS.get(str(key), str(key)),
                           "value": int(val), "min": 0, "max": 0})

    meters = []
    playbook = state.get("playbook") or {}
    progress = playbook.get("progress") or {}
    if progress:
        meters.append({"key": "progress", "label": _label(progress.get("label"), "进度"),
                       "value": _num(progress.get("value", 0)), "min": 0,
                       "max": _num(progress.get("max", 0))})
    return {
        "title": str((state.get("world_info") or {}).get("name") or ""),
        "kind": "rpg",
        "attributes": attributes,
        "resources": resources,
        "meters": meters,
        "tags": [],
        "sheet": {},
    }


def profile_of(state: dict) -> dict:
    """当前游戏档案：显式 `state["game"]` 优先，否则从旧字段推导。始终返回完整结构。"""
    raw = state.get("game")
    if isinstance(raw, dict) and (raw.get("resources") or raw.get("attributes") or raw.get("meters") or raw.get("title")):
        return normalize(raw)
    return _derived(state)


def set_profile(state: dict, raw: dict) -> dict:
    """覆盖式设置游戏档案（会规范化并 clamp）。"""
    state["game"] = normalize(raw)
    return state["game"]


def _bucket(profile: dict, kind: str):
    if kind not in ("attributes", "resources", "meters"):
        raise ValueError("kind 只能是 attributes / resources / meters")
    return profile[kind]


def adjust(state: dict, key: str, kind: str = "resources", delta=None, value=None) -> dict:
    """调整一个资源/属性/进度轨；有 min/max 时 clamp。返回 before/after 与是否触顶。

    kind 缺省是 resources；若该 key 不在 resources 而在另一类里，自动定位到实际类别
    （避免"线索明明存在却报 resources 里没有"）。多类同名时要求显式指定 kind。
    """
    profile = profile_of(state)
    items = _bucket(profile, kind)
    target = next((x for x in items if x["key"] == str(key)), None)
    if target is None:
        candidates = [(k, x) for k in ("resources", "attributes", "meters")
                      for x in profile[k] if x["key"] == str(key)]
        if len(candidates) == 1:
            kind, target = candidates[0]
            items = profile[kind]
        else:
            listing = "；".join("%s: %s" % (k, ", ".join(x["key"] for x in profile[k]) or "空")
                               for k in ("resources", "attributes", "meters"))
            if len(candidates) > 1:
                raise ValueError("%r 同时存在于 %s，请显式传 kind"
                                 % (key, " / ".join(k for k, _ in candidates)))
            raise ValueError("找不到 %r（%s）" % (key, listing))
    before = target["value"]
    if value is not None:
        after = _num(value, before)
    elif delta is not None:
        after = _num(before) + _num(delta)
    else:
        raise ValueError("delta 与 value 至少要给一个")
    lo, hi = target.get("min", 0), target.get("max", 0)
    if hi and hi > lo:
        after = max(lo, min(hi, after))
    # 无界条目（max=0）没有 clamp 兜底：inf/nan 混进 delta 会原样写入档案。
    if isinstance(after, float) and (after != after or after in (float("inf"), float("-inf"))):
        after = before
    if isinstance(before, int) and isinstance(after, float) and after.is_integer():
        after = int(after)
    target["value"] = round(after, 3) if isinstance(after, float) else after
    state["game"] = profile
    return {
        "key": target["key"], "label": target["label"], "kind": kind,
        "before": before, "after": target["value"], "delta": _num(target["value"]) - _num(before),
        "min": lo, "max": hi,
        "at_max": bool(hi and target["value"] >= hi),
        "at_min": bool(target["value"] <= lo),
    }


def add_tag(state: dict, tag: str, remove: bool = False) -> dict:
    """增删游戏标签（世界内的持久状态，如「戒严」「雨季」「通缉」）。"""
    profile = profile_of(state)
    text = str(tag or "").strip()[:MAX_TAG_LEN]
    if not text:
        raise ValueError("tag 不能为空")
    tags = profile["tags"]
    if remove:
        tags[:] = [t for t in tags if t != text]
    elif text not in tags:
        tags.append(text)
        if len(tags) > MAX_TAGS:
            del tags[:len(tags) - MAX_TAGS]
    state["game"] = profile
    return {"tag": text, "tags": list(tags), "removed": bool(remove)}


def set_sheet(state: dict, fields: dict, remove: bool = False) -> dict:
    """设置自由表格字段（职业、住所、目标、关系摘要……任何游戏都能用）。"""
    if not isinstance(fields, dict) or not fields:
        raise ValueError("fields 必须是非空对象")
    profile = profile_of(state)
    sheet = profile["sheet"]
    if remove:
        for key in fields:
            sheet.pop(str(key), None)
    else:
        for key, val in fields.items():
            key = str(key or "").strip()[:MAX_LABEL]
            if not key:
                continue
            if isinstance(val, bool):
                sheet[key] = val
            elif isinstance(val, (int, float)):
                sheet[key] = val
            else:
                sheet[key] = str(val)[:MAX_SHEET_VALUE]
        if len(sheet) > MAX_SHEET_FIELDS:
            for key in list(sheet)[:len(sheet) - MAX_SHEET_FIELDS]:
                sheet.pop(key, None)
    state["game"] = profile
    return {"sheet": dict(sheet), "count": len(sheet)}
