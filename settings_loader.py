"""
设定包装载 (settings_loader) —— 纯标准库

为什么单独成模块：把"一个 JSON 设定包 → 一份可运行的游戏状态"这件事从 MCP 层里拿出来。

- MCP 的 `load_setting` / `world_init` 需要 pydantic 做入参 schema，因此必须有 mcp 依赖；
- 但**校验设定包**、**验证四套世界观**不需要 MCP，也不该因为没有 mcp 就跳过。

把这条路径抽出来后：
  · `mcp_server.world_init` 与 `settings_loader.build_state` 共用同一套规范化逻辑，
    不会出现"MCP 建局"与"测试建局"两套字段处理而悄悄漂移；
  · `scripts/verify_settings.py` 可以在零依赖环境（CI 的 core 作业）里跑。

所有函数都是纯函数（除非显式接收 state 并原地更新），不读写文件、不依赖时间。
"""

from game_engine.rules import gamesystem as game_rules
from game_engine.rules import playbook as playbook_rules
from game_engine.rules import questline as questline_rules
from game_engine.rules import systems as system_rules
from game_engine.state_schema import entity_key, log_event

ATTR_KEYS = ("str", "dex", "int", "con", "cha")
DEFAULT_SEED = 20261014
PLACE_DESC_CAP = 1200


def normalize_entity(entity_id: str, raw: dict) -> dict:
    """把设定包里的一个角色规范成引擎实体。

    规则与 MCP 的 EntityIn 保持一致：五维缺省 10 且必须是数字，hp 缺省等于 hp_max，
    items 只保留正数，描述类文字截断到 1200 字（防止一个设定包把状态撑爆）。
    """
    if not isinstance(raw, dict) or not raw.get("name"):
        raise ValueError("实体 %s 缺少 name" % entity_id)
    attrs = dict(raw.get("attrs") or {})
    for key in ATTR_KEYS:
        val = attrs.get(key, 10)
        if not isinstance(val, (int, float)):
            raise ValueError("实体 %s 的属性 %s 必须是数字" % (entity_id, key))
        attrs[key] = int(val)

    hp_max = max(1, int(raw.get("hp_max", 100)))
    mp_max = max(0, int(raw.get("mp_max", 0)))
    hp = max(0, min(int(raw.get("hp", hp_max)), hp_max))
    mp = max(0, min(int(raw.get("mp", mp_max)), mp_max))
    ent = {
        "name": str(raw["name"]),
        "faction": str(raw.get("faction", "")),
        "attrs": attrs,
        "hp": hp,
        "hp_max": hp_max,
        "mp": mp,
        "mp_max": mp_max,
        "level": str(raw.get("level", "凡人")),
        "gold": max(0, int(raw.get("gold", 0))),
        "location": str(raw.get("location", "")),
    }
    for extra in ("desc", "personality", "speech"):
        if raw.get(extra):
            ent[extra] = str(raw[extra])[:PLACE_DESC_CAP]
    if raw.get("skills"):
        ent["skills"] = list(raw["skills"])
    if raw.get("morality"):
        ent["morality"] = list(raw["morality"])[:6]
    if raw.get("roam"):
        ent["roam"] = True

    items = raw.get("items")
    if items:
        cleaned = {}
        for key, val in dict(items).items():
            try:
                n = int(val)
            except (TypeError, ValueError):
                continue
            if n > 0:
                cleaned[str(key)] = n
        if cleaned:
            ent["items"] = cleaned
    return ent


def normalize_market(market: list) -> dict:
    """[{location, items:[{key,...}]}] → {location: {key: item}}。"""
    out = {}
    for loc in market or []:
        if not isinstance(loc, dict) or not loc.get("location"):
            raise ValueError("market 每项都必须有 location")
        items = {}
        for item in loc.get("items") or []:
            if not isinstance(item, dict) or not item.get("key"):
                raise ValueError("market.items 每项都必须有 key")
            key = str(item["key"])
            # 价格必须为正：负价格会让买入反向加钱（见 economy.resolve_trade 的同类防护）。
            price = max(1, int(item.get("price", 50)))
            items[key] = {
                "name": str(item.get("name", key)),
                "price": price,
                "supply": max(0, int(item.get("supply", 20))),
                "base_price": max(1, int(item.get("base_price", price))),
                "type": str(item.get("type", "")),
                "desc": str(item.get("desc", "")),
            }
        out[str(loc["location"])] = items
    return out


def normalize_relations(relations: list, entity_ids) -> dict:
    """[{a,b,affinity,respect}] → {'a:b': {...}}；引用了不存在的实体直接报错。"""
    out = {}
    for rel in relations or []:
        if not isinstance(rel, dict):
            raise ValueError("relations 每项必须是对象")
        a, b = str(rel.get("a", "")), str(rel.get("b", ""))
        for eid in (a, b):
            if eid not in entity_ids:
                raise ValueError("关系引用了不存在的实体: %s" % eid)
        out[entity_key(a, b)] = {
            "affinity": max(-100, min(100, int(rel.get("affinity", 0)))),
            "respect": max(-100, min(100, int(rel.get("respect", 0)))),
        }
    return out


def build_state(bundle: dict, seed: int | None = None) -> dict:
    """设定包 → 初始状态（不落盘、不写文件）。

    `bundle` 形状见 settings/README.md：world / player / entities / market /
    relations / world_flags / ui / seed。所有校验错误都是 ValueError，带人能读懂的原因。
    """
    if not isinstance(bundle, dict):
        raise ValueError("设定包必须是 JSON 对象")
    world = bundle.get("world")
    player = bundle.get("player")
    if not isinstance(world, dict) or not world.get("name"):
        raise ValueError("设定包缺 world.name")
    if not isinstance(player, dict) or not player.get("name"):
        raise ValueError("设定包缺 player.name")

    entities = {"player": normalize_entity("player", player)}
    for npc in bundle.get("entities") or []:
        if not isinstance(npc, dict):
            raise ValueError("entities 每项必须是对象")
        eid = str(npc.get("id") or "").strip()
        if not eid:
            raise ValueError("entities 里每个 NPC 都必须有 id")
        if eid == "player":
            raise ValueError("entities 里不要重复定义 player")
        if eid in entities:
            raise ValueError("实体 id 重复: %s" % eid)
        entities[eid] = normalize_entity(eid, npc)

    # 玩法剧本与事业线在**建局时**就要写进状态：面板与 status 第一屏就要能显示，
    # 不能等到 apply_runtime_fields 才补（那样 UI 第一帧是空的）。
    playbook, pb_notes = playbook_rules.normalize(bundle.get("playbook"))
    quests = questline_rules.normalize_all(bundle.get("questlines"))         if bundle.get("questlines") else []

    # 游戏档案与体系定义在**建局时**就落盘：面板第一帧与 status 立刻可用。
    # 模板库（templates.py）产出的 bundle 直接带这两块；老设定包没有也不影响。
    profile = game_rules.normalize(bundle.get("game")) if bundle.get("game") else {}
    system_defs = {}
    for raw in bundle.get("systems") or []:
        try:
            normalized = system_rules.normalize_system(raw)
        except ValueError as exc:
            raise ValueError("systems 定义非法: %s" % exc)
        system_defs[normalized["id"]] = normalized

    state = {
        "tick": 0,
        "rng_seed": int(seed if seed is not None else bundle.get("seed", DEFAULT_SEED)),
        "entities": entities,
        "relations": normalize_relations(bundle.get("relations") or [], set(entities)),
        "market": normalize_market(bundle.get("market") or []),
        "karma_ledger": [],
        "world_flags": [str(f) for f in (bundle.get("world_flags") or [])],
        "ui": dict(bundle.get("ui") or {}),
        "event_log": [],
        "world_info": {
            "name": str(world["name"]),
            "era": str(world.get("era", "")),
            "location_desc": str(world.get("location_desc", "")),
        },
        "playbook": playbook,
        "playbook_notes": pb_notes,
        "questlines": quests,
        "quests": {},
    }
    if profile:
        state["game"] = profile
    if system_defs:
        state["systems"] = {"defs": system_defs, "rt": {}}
    return state


def search_place(bundle: dict, name: str) -> dict:
    """取设定包里某地点的描写（兼容 {name:{desc}} 与 {name:"文字"} 两种写法）。"""
    places = bundle.get("places") or {}
    info = places.get(name)
    if isinstance(info, dict):
        return {"desc": str(info.get("desc", ""))[:PLACE_DESC_CAP], "tick": 0}
    if isinstance(info, str):
        return {"desc": info[:PLACE_DESC_CAP], "tick": 0}
    return {}


def apply_runtime_fields(state: dict, bundle: dict) -> int:
    """把"建局之外的运行时字段"写进状态，返回导入的世界书条目数。

    字段：playbook / questlines / currency / terms / level_tiers / places / lore。
    这里**不**做落盘——调用方（MCP 的 load_setting）负责 save_state。
    """
    if bundle.get("playbook"):
        pb, notes = playbook_rules.normalize(bundle["playbook"])
        state["playbook"] = pb
        state["playbook_notes"] = notes
    if bundle.get("questlines"):
        state["questlines"] = questline_rules.normalize_all(bundle["questlines"])
        state.setdefault("quests", {})
    if bundle.get("game"):
        state["game"] = game_rules.normalize(bundle["game"])
    if bundle.get("systems"):
        defs = state.setdefault("systems", {}).setdefault("defs", {})
        for raw in bundle["systems"]:
            try:
                normalized = system_rules.normalize_system(raw)
            except ValueError as exc:
                raise ValueError("systems 定义非法: %s" % exc)
            defs[normalized["id"]] = normalized
    if bundle.get("currency"):
        state["currency"] = str(bundle["currency"])
    terms = bundle.get("terms")
    if isinstance(terms, dict) and terms:
        state.setdefault("ui", {})["terms"] = {str(k): str(v) for k, v in terms.items()}
    tiers = bundle.get("level_tiers")
    if isinstance(tiers, list) and tiers:
        state.setdefault("config", {})["level_tiers"] = [str(t) for t in tiers]
    places = bundle.get("places")
    if isinstance(places, dict):
        bucket = state.setdefault("places", {})
        for name in places:
            info = search_place(bundle, str(name))
            if info:
                info["tick"] = int(state.get("tick", 0) or 0)
                bucket[str(name)] = info

    # 去重：load_setting / 重复 apply_runtime_fields / 同包二次载入都不能让世界书翻倍
    # （实测同一包调用两次会 21→42 条，narration_context 的预算被重复条目吃掉）。
    lore = state.setdefault("lore", [])
    seen = {_lore_identity(e) for e in lore if isinstance(e, dict)}
    lore_n = 0
    for entry in bundle.get("lore") or []:
        norm = normalize_lore_entry(entry)
        if norm:
            ident = _lore_identity(norm)
            if ident in seen:
                continue
            seen.add(ident)
            lore.append(norm)
            lore_n += 1
    if lore_n:
        log_event(state, "system", "设定包「%s」载入：世界书 %d 条"
                  % (bundle.get("name", ""), lore_n))
    return lore_n


def _lore_identity(entry: dict) -> tuple:
    """世界书条目的稳定身份：优先 id，其次 (comment, keys, content) 三元组。"""
    eid = entry.get("id")
    if eid is not None and str(eid).strip():
        return ("id", str(eid).strip())
    return ("body", str(entry.get("comment") or ""),
            tuple(entry.get("keys") or []), str(entry.get("content") or ""))


def normalize_lore_entry(entry: dict):
    """规范化世界书条目；同时吃角色卡 character_book 与 SillyTavern world-info 两套字段名。"""
    if not isinstance(entry, dict):
        return None
    keys = entry.get("keys", entry.get("key")) or []
    if isinstance(keys, str):
        keys = [keys]
    secondary = entry.get("secondary_keys", entry.get("keysecondary")) or []
    if isinstance(secondary, str):
        secondary = [secondary]
    content = str(entry.get("content") or "").strip()
    keys = [str(k).strip() for k in keys if str(k).strip()]
    if not keys or not content:
        return None
    if "enabled" in entry:
        enabled = bool(entry["enabled"])
    else:
        enabled = not bool(entry.get("disable", False))
    # 扩展字段（与 SillyTavern world-info 同名，缺省保持旧行为）：
    #   selective_logic / probability / use_probability / group / group_weight / group_override
    #   sticky / cooldown / delay / scan_depth / match_whole_words / exclude_recursion
    # 这些是"逐回合确定性"实现里真正会改变结果的字段，因此必须落进状态文件，
    # 否则快照回退重放会得到不同的上下文（INV-E4）。
    logic = entry.get("selective_logic", entry.get("selectiveLogic"))
    row = {
        "keys": keys,
        "secondary_keys": [str(k).strip() for k in secondary if str(k).strip()],
        "content": content,
        "comment": str(entry.get("comment") or entry.get("name") or ""),
        "selective": bool(entry.get("selective", False)),
        "constant": bool(entry.get("constant", False)),
        "case_sensitive": bool(entry.get("case_sensitive", False)),
        "order": int(entry.get("insertion_order", entry.get("order", 100)) or 0),
        "enabled": enabled,
        "match_whole_words": bool(entry.get("match_whole_words", False)),
        "exclude_recursion": bool(entry.get("exclude_recursion", False)),
        "use_probability": bool(entry.get("use_probability", True)),
        "use_group_scoring": bool(entry.get("use_group_scoring", False)),
    }
    if logic is not None:
        row["selective_logic"] = logic
    # probability 是 0-100 的百分比（酒馆语义），必须保留小数：
    # 旧实现用 int() 把 0.9 截成 0（永不触发）、把 1 当比例 100%（恒触发）。
    for key in ("sticky", "cooldown", "delay", "scan_depth"):
        val = entry.get(key)
        if val is not None:
            try:
                row[key] = int(val)
            except (TypeError, ValueError):
                pass
    if entry.get("probability") is not None:
        try:
            row["probability"] = float(entry["probability"])
            # 酒馆语义：>=1 是百分比（1 = 1%）；(0,1) 是旧配置的比例写法（0.9 = 90%）。
            row["probability_scale"] = 1 if 0 < row["probability"] < 1 else 100
        except (TypeError, ValueError):
            pass
    if entry.get("once"):
        row["once"] = True
    if entry.get("max_fires") is not None:
        try:
            row["max_fires"] = int(entry["max_fires"])
        except (TypeError, ValueError):
            pass
    if entry.get("group"):
        row["group"] = str(entry["group"])
    for key in ("group_weight",):
        val = entry.get(key)
        if val is not None:
            try:
                row[key] = float(val)
            except (TypeError, ValueError):
                pass
    if entry.get("group_override"):
        row["group_override"] = True
    # 条目 id / uid 必须保留：_entry_id 优先用它做运行时键；
    # 丢掉后同 comment 的两条会在 chosen[eid] 里互相覆盖（实测只触发第一条）。
    eid = entry.get("id") if entry.get("id") is not None else entry.get("uid")
    if eid is not None and str(eid).strip():
        row["id"] = str(eid).strip()
    return row

