"""
游戏模板库 (Templates) —— 开箱即用的完整游戏骨架

为什么需要：`settings/` 里的四套设定包是"完整示例"，但它们体量大、绑定特定世界观。
做一个新游戏时，真正需要的是**起点**：这套模板给出世界/角色/属性/资源/进度轨/玩法循环/
事业线/世界书/地点/市场/术语/体系，全部填好，改几个词就能玩。

模板分两层：
  · `GAME_TEMPLATES`：单文件模板（纯 Python dict），覆盖主流题材，随包分发、无需读盘；
  · `load(name)`：深拷贝 + 可选覆盖（overrides），返回可直接交给 build_state 的 bundle。

每个模板都通过 `validate()` 的结构校验（`scripts/verify_systems.py` 逐项断言），
保证"模板不缺基础件"——这是本层的核心承诺。
"""

import copy

MAX_TEMPLATES = 40


def _pack(tid, name, genre, loop, **kw):
    """构造一个标准模板（统一字段顺序与默认值）。"""
    base = {
        "id": tid,
        "name": name,
        "genre": genre,
        "loop": loop,
        "world": {},
        "player": {},
        "entities": [],
        "market": [],
        "relations": [],
        "world_flags": [],
        "level_tiers": [],
        "terms": {},
        "places": {},
        "lore": [],
        "currency": "金币",
        "ui": {},
        "playbook": {},
        "questlines": [],
        "systems": [],
        "game": {},
        "notes": "",
    }
    base.update(kw)
    return base


# ────────────────────────────── 模板定义 ──────────────────────────────

_JRPG = _pack(
    "jrpg", "日式奇幻冒险", "奇幻 / 成长", "freeform",
    notes="经典少年成长线：接受委托 → 探索 → 战斗 → 升级 → 揭开更大的阴谋。",
    world={"name": "艾瑟兰", "era": "王国历 412 年",
           "location_desc": "边境小镇洛恩的清晨，铁匠铺刚升起第一缕烟。冒险者公会的告示板上钉着一张新委托。"},
    player={"name": "旅人", "faction": "无", "level": "见习",
            "attrs": {"str": 10, "dex": 11, "int": 9, "con": 10, "cha": 10},
            "hp": 30, "hp_max": 30, "mp": 10, "mp_max": 10, "gold": 40,
            "location": "洛恩镇",
            "skills": ["基础剑术"], "items": {"potion": 2}},
    entities=[
        {"id": "guildmaster", "name": "公会会长 格雷", "faction": "冒险者公会",
         "level": "退役老兵", "attrs": {"str": 12, "dex": 9, "int": 11, "con": 12, "cha": 13},
         "hp": 40, "hp_max": 40, "gold": 200, "location": "洛恩镇",
         "desc": "左脸有一道旧疤，说话像在点兵。", "personality": "寡言、护短",
         "speech": "「活着回来，比什么委托都值钱。」"},
        {"id": "smith", "name": "铁匠 玛莎", "faction": "工匠行会",
         "level": "匠师", "attrs": {"str": 14, "dex": 8, "int": 10, "con": 13, "cha": 9},
         "hp": 35, "hp_max": 35, "gold": 120, "location": "洛恩镇",
         "desc": "手臂比寻常男人还粗，围裙上全是烫痕。", "personality": "直率",
         "speech": "「东西可以赊，命不能。」"},
    ],
    market=[{"location": "洛恩镇", "items": [
        {"key": "potion", "name": "治疗药水", "price": 12, "supply": 20, "base_price": 12, "type": "药品",
         "desc": "回复 20 点生命。"},
        {"key": "bread", "name": "干粮", "price": 3, "supply": 30, "base_price": 3, "type": "食物"},
        {"key": "dagger", "name": "短剑", "price": 35, "supply": 5, "base_price": 35, "type": "武器"},
    ]}],
    relations=[{"a": "player", "b": "guildmaster", "affinity": 10, "respect": 15}],
    level_tiers=["见习", "铜级", "银级", "金级", "白金", "传说"],
    terms={"hero": "冒险者", "level": "等级", "hp": "生命", "mp": "魔力", "gold": "金币",
           "track": "公会阶", "territory": "足迹", "inventory": "行囊", "codex": "见闻录"},
    places={
        "洛恩镇": {"desc": "边境小镇，木屋沿河而建，公会旗在风里响。",
                   "market": "洛恩镇"},
        "灰狼林": {"desc": "林间有新鲜爪印，鸟声突然断了。", "market": ""},
        "废弃哨塔": {"desc": "塔顶塌了一角，风穿过箭孔发出低鸣。", "market": ""},
    },
    currency="金币",
    ui={"skin": "neutral", "accent": "#d9a441", "motif": "奇幻·边境", "brand": "艾瑟兰",
        "tagline": "委托与远方"},
    playbook={"loop": "freeform", "input": "natural",
              "progress": {"axis": "level", "label": "公会阶", "max": 5},
              "failure": {"mode": "hp", "label": "重伤撤退", "max": 0},
              "beat": {"pattern": ["日常", "接委托", "路上", "交锋", "结算"], "every": 5},
              "settlement": ["combat", "trade", "social", "karma", "roll"],
              "context": {"inject": ["lore", "cast", "chronicle"], "max_lore": 10, "scan_depth": 2}},
    questlines=[{
        "id": "wolf_forest", "title": "灰狼林的爪印", "summary": "最近三支商队都没能穿过灰狼林。",
        "visibility": {"flag": "__start__"},
        "stages": [
            {"id": "accept", "title": "接下委托", "objectives": ["去找公会会长确认细节"],
             "exit_if": {"flag": "accepted_wolf"}, "next": ["track"]},
            {"id": "track", "title": "追踪", "objectives": ["在林中找到爪印的来源"],
             "exit_if": {"visited": "灰狼林"}, "next": ["tower"]},
            {"id": "tower", "title": "哨塔", "objectives": ["查明哨塔里的东西"], "next": []},
        ],
        "reward": {"gold": 120, "flags": ["wolf_forest_cleared"]},
    }],
    systems=[
        {"id": "clock", "kind": "time", "label": "时间",
         "config": {"start": {"day": 1, "hour": 7}, "days_per_season": 30}},
        {"id": "drops_wolf", "kind": "loot", "label": "灰狼掉落",
         "config": {"tables": {"wolf": {"rolls": 2, "entries": [
             {"item": "pelt", "name": "狼皮", "weight": 60, "qty": [1, 2]},
             {"item": "fang", "name": "狼牙", "weight": 30, "qty": [1, 1]},
             {"item": "core", "name": "兽核", "weight": 8, "qty": [1, 1]},
         ]}}}},
        {"id": "alchemy", "kind": "craft", "label": "调和",
         "config": {"recipes": [
             {"id": "potion", "name": "治疗药水", "inputs": {"herb": 2},
              "output": {"item": "potion", "name": "治疗药水", "qty": 1},
              "difficulty": 8, "attribute": "int"},
         ]}},
        {"id": "guild_rep", "kind": "reputation", "label": "公会声望",
         "config": {"factions": ["冒险者公会", "工匠行会", "边境守备"]}},
        {"id": "xp", "kind": "progression", "label": "成长",
         "config": {"base_xp": 100, "growth": 1.4, "max_level": 20,
                    "per_level": {"str": 1, "con": 1}, "level_label": "冒险者等级"}},
        {"id": "achievements", "kind": "achievement", "label": "成就",
         "config": {"items": [
             {"id": "first_blood", "name": "初次交锋", "desc": "赢下第一场战斗",
              "condition": {"counter_gte": {"key": "kills", "n": 1}}, "reward": {"xp": 50, "gold": 20}},
             {"id": "explorer", "name": "踏遍边境", "desc": "探索三处地点",
              "condition": {"counter_gte": {"key": "locations", "n": 3}}, "reward": {"xp": 80}},
         ]}},
        {"id": "actions", "kind": "custom", "label": "日常动作",
         "config": {"actions": {
             "rest": {"label": "扎营休息",
                      "effects": [{"op": "advance_time", "minutes": 480},
                                  {"op": "flag", "flag": "rested"}]},
             "train": {"label": "训练",
                       "effects": [{"op": "xp", "delta": 25},
                                   {"op": "attribute", "key": "str", "delta": 1}]},
         }}},
    ],
    game={"title": "艾瑟兰", "kind": "rpg",
          "resources": [{"key": "hp", "label": "生命", "value": 30, "min": 0, "max": 30, "color": "hp"},
                        {"key": "mp", "label": "魔力", "value": 10, "min": 0, "max": 10, "color": "mp"},
                        {"key": "gold", "label": "金币", "value": 40, "min": 0, "max": 0, "color": "gold"}],
          "attributes": [{"key": "str", "label": "力量", "value": 10},
                         {"key": "dex", "label": "敏捷", "value": 11},
                         {"key": "int", "label": "智力", "value": 9},
                         {"key": "con", "label": "体质", "value": 10},
                         {"key": "cha", "label": "魅力", "value": 10}],
          "meters": [{"key": "guild", "label": "公会阶", "value": 0, "min": 0, "max": 5}],
          "tags": ["边境"], "sheet": {"职业": "见习冒险者", "住所": "洛恩镇旅店"}},
    lore=[
        {"keys": ["基调", "文风"], "constant": True, "comment": "基调",
         "content": "英雄奇幻底色：委托驱动、成长可见、代价真实。战斗有风险，钱要算着花。"},
        {"keys": ["灰狼林", "爪印"], "comment": "灰狼林",
         "content": "灰狼林的爪印比寻常狼大一圈，树皮上有灼烧痕迹——不像野兽干的。"},
        {"keys": ["哨塔", "旧哨塔"], "comment": "哨塔",
         "content": "废弃哨塔是三十年前边境战争的遗留，塔基被刻意封过一次。"},
    ],
)

_MYSTERY = _pack(
    "mystery", "本格推理调查", "悬疑 / 调查", "choice",
    notes="线索链 + 时间线 + 嫌疑人口供。核心是「问对问题」，不是「打赢谁」。",
    world={"name": "雾港", "era": "民国十七年 · 深秋",
           "location_desc": "雾从海面漫上来，码头的灯一盏一盏亮起。巡捕房的电话在雨里响个不停。"},
    player={"name": "调查员", "level": "外行",
            "attrs": {"str": 8, "dex": 9, "int": 13, "con": 9, "cha": 11, "per": 12},
            "hp": 20, "hp_max": 20, "mp": 0, "mp_max": 0, "gold": 60,
            "location": "雾港码头", "items": {"notebook": 1, "flashlight": 1}},
    entities=[
        {"id": "inspector", "name": "巡捕 老陈", "faction": "巡捕房", "level": "老手",
         "attrs": {"str": 11, "dex": 9, "int": 11, "con": 11, "cha": 10, "per": 12},
         "hp": 25, "hp_max": 25, "gold": 30, "location": "雾港码头",
         "desc": "大衣下摆全是泥，眼睛里有常年熬夜的红血丝。", "personality": "疲惫但固执",
         "speech": "「这城里死人不稀奇，稀奇的是有人想让我们查。」"},
        {"id": "innkeeper", "name": "旅店老板 吴婶", "faction": "市井", "level": "平民",
         "attrs": {"str": 8, "dex": 8, "int": 10, "con": 9, "cha": 12, "per": 11},
         "hp": 15, "hp_max": 15, "gold": 80, "location": "雾港码头",
         "desc": "袖口永远干净，记账的本子藏在围裙里。", "personality": "热心但嘴严",
         "speech": "「客官，昨儿夜里那动静，我可什么都没听见。」"},
    ],
    market=[{"location": "雾港码头", "items": [
        {"key": "film", "name": "胶片", "price": 18, "supply": 10, "base_price": 18, "type": "工具"},
        {"key": "whisky", "name": "威士忌", "price": 22, "supply": 8, "base_price": 22, "type": "饮品"},
        {"key": "bandage", "name": "纱布", "price": 5, "supply": 20, "base_price": 5, "type": "药品"},
    ]}],
    relations=[{"a": "player", "b": "inspector", "affinity": 5, "respect": 10}],
    level_tiers=["外行", "学徒", "熟练", "专家", "传奇"],
    terms={"hero": "调查员", "level": "资历", "hp": "体力", "mp": "理智", "gold": "法币",
           "track": "调查阶", "territory": "走访范围", "inventory": "随身",
           "codex": "案卷", "quests": "线索链", "context": "案卷台账"},
    places={
        "雾港码头": {"desc": "货箱堆到人腰高，雾里能听见水声和远处的汽笛。", "market": "雾港码头"},
        "永昌号": {"desc": "船身锈得厉害，甲板上有一道被冲洗过的暗痕。", "market": ""},
        "灯塔": {"desc": "灯塔三年没亮过，铁门上的锁是新的。", "market": ""},
    },
    currency="法币",
    ui={"skin": "neutral", "accent": "#8aa6c8", "motif": "悬疑·雾港", "brand": "雾港",
        "tagline": "别让灯塔亮起来"},
    playbook={"loop": "choice", "input": "choice",
              "progress": {"axis": "knowledge", "label": "线索", "max": 24},
              "failure": {"mode": "sanity", "label": "理智", "max": 10},
              "beat": {"pattern": ["现场", "问询", "矛盾", "逼近", "代价"], "every": 4},
              "settlement": ["social", "roll", "travel", "trade"],
              "context": {"inject": ["lore", "cast", "chronicle"], "max_lore": 14, "scan_depth": 3}},
    questlines=[{
        "id": "lighthouse", "title": "别让灯塔亮起来", "summary": "有人在等灯塔重新亮起，有人不想它亮。",
        "visibility": {"flag": "__start__"},
        "stages": [
            {"id": "letter", "title": "无署名信", "objectives": ["弄清信是谁写的"],
             "exit_if": {"visited": "雾港码头"}, "next": ["keeper"]},
            {"id": "keeper", "title": "看守", "objectives": ["找到灯塔看守"],
             "exit_if": {"visited": "灯塔"}, "next": ["ledger"]},
            {"id": "ledger", "title": "名册", "objectives": ["对上那七个名字"], "next": []},
        ],
        "reward": {"flags": ["lighthouse_truth"]},
    }],
    systems=[
        {"id": "clock", "kind": "time", "label": "时间",
         "config": {"start": {"day": 1, "hour": 20}, "days_per_season": 30,
                    "seasons": ["深秋", "初冬", "隆冬", "早春"],
                    "weathers": [{"name": "雾", "weight": 50}, {"name": "雨", "weight": 30},
                                 {"name": "阴", "weight": 20}]}},
        {"id": "clues", "kind": "loot", "label": "现场勘查",
         "config": {"tables": {"scene": {"rolls": 2, "empty_weight": 30, "entries": [
             {"item": "fiber", "name": "纤维", "weight": 40, "qty": [1, 1]},
             {"item": "ash", "name": "灰烬", "weight": 30, "qty": [1, 1]},
             {"item": "note", "name": "残页", "weight": 20, "qty": [1, 1]},
         ]}}}},
        {"id": "trust", "kind": "reputation", "label": "信任",
         "config": {"factions": ["巡捕房", "市井", "教会", "船帮"],
                    "tiers": [{"min": -1000, "label": "戒备"}, {"min": -20, "label": "冷淡"},
                              {"min": 20, "label": "合作"}, {"min": 60, "label": "信任"}]}},
        {"id": "sanity", "kind": "custom", "label": "理智消耗",
         "config": {"actions": {
             "investigate": {"label": "深挖",
                             "effects": [{"op": "advance_time", "minutes": 120},
                                         {"op": "meter", "key": "clue", "delta": 1},
                                         {"op": "resource", "key": "sanity", "delta": -1}]},
             "rest": {"label": "休息",
                      "effects": [{"op": "advance_time", "minutes": 480},
                                  {"op": "resource", "key": "sanity", "delta": 2}]},
         }}},
        {"id": "achievements", "kind": "achievement", "label": "结案",
         "config": {"items": [
             {"id": "first_clue", "name": "第一条线索", "desc": "找到任何一条线索",
              "condition": {"counter_gte": {"key": "clues", "n": 1}}, "reward": {"xp": 20}},
         ]}},
    ],
    game={"title": "雾港调查", "kind": "investigation",
          "resources": [{"key": "sanity", "label": "理智", "value": 10, "min": 0, "max": 10, "color": "hp"},
                        {"key": "gold", "label": "法币", "value": 60, "min": 0, "max": 0, "color": "gold"}],
          "attributes": [{"key": "per", "label": "感知", "value": 12},
                         {"key": "int", "label": "推理", "value": 13},
                         {"key": "cha", "label": "话术", "value": 11}],
          "meters": [{"key": "clue", "label": "线索", "value": 0, "min": 0, "max": 24}],
          "tags": ["雨季"], "sheet": {"职业": "私家调查员", "委托人": "无署名信"}},
    lore=[
        {"keys": ["基调", "文风"], "constant": True, "comment": "基调",
         "content": "冷硬派调查：证据说话，口供有偏差，真相往往比谎言更伤人。"},
        {"keys": ["灯塔", "熄"], "comment": "灯塔",
         "content": "灯塔三年前熄灭，官方记录是设备老化，但维修单上的签名是伪造的。"},
        {"keys": ["名册", "七个名字"], "comment": "名册",
         "content": "永昌号的旧名册上有七个名字，其中三个在同一年先后死亡。"},
    ],
)

_MANAGEMENT = _pack(
    "management", "店铺经营", "经营 / 模拟", "mud",
    notes="进货 → 定价 → 雇人 → 扩张。核心是现金流与供需，不是打怪。",
    world={"name": "临川老街", "era": "市井",
           "location_desc": "老街的青石板被踩得发亮，你的铺子夹在茶摊和药铺之间，卷帘门刚拉起一半。"},
    player={"name": "掌柜", "level": "小摊",
            "attrs": {"str": 8, "dex": 9, "int": 12, "con": 9, "cha": 12},
            "hp": 20, "hp_max": 20, "mp": 0, "mp_max": 0, "gold": 300,
            "location": "临川老街", "items": {"tea": 10}},
    entities=[
        {"id": "clerk", "name": "伙计 阿福", "faction": "本店", "level": "学徒",
         "attrs": {"str": 10, "dex": 10, "int": 9, "con": 10, "cha": 11},
         "hp": 20, "hp_max": 20, "gold": 5, "location": "临川老街",
         "desc": "手脚麻利，算盘打得比嘴快。", "personality": "勤快", "speech": "「掌柜的，今儿进多少？」"},
        {"id": "supplier", "name": "茶商 周老板", "faction": "商行", "level": "行商",
         "attrs": {"str": 9, "dex": 9, "int": 12, "con": 10, "cha": 13},
         "hp": 22, "hp_max": 22, "gold": 500, "location": "临川老街",
         "desc": "袖子里永远揣着两泡样品。", "personality": "精明", "speech": "「量大从优，现银结算。」"},
    ],
    market=[{"location": "临川老街", "items": [
        {"key": "tea", "name": "粗茶", "price": 6, "supply": 60, "base_price": 6, "type": "货"},
        {"key": "cake", "name": "茶点", "price": 4, "supply": 40, "base_price": 4, "type": "货"},
        {"key": "silk", "name": "绸缎", "price": 30, "supply": 12, "base_price": 30, "type": "货"},
    ]}],
    relations=[{"a": "player", "b": "clerk", "affinity": 20, "respect": 10}],
    level_tiers=["小摊", "铺面", "商号", "行会", "巨贾"],
    terms={"hero": "掌柜", "level": "字号", "hp": "体力", "mp": "精力", "gold": "银钱",
           "track": "商号阶", "territory": "铺面", "inventory": "库存",
           "codex": "行商见闻", "quests": "经营目标"},
    places={
        "临川老街": {"desc": "铺面不大，柜台擦得发亮，门口的木牌写着「新茶上市」。", "market": "临川老街"},
        "后巷仓库": {"desc": "堆着上个月的茶箱，墙角有点返潮。", "market": ""},
        "南市集": {"desc": "人声鼎沸，批发价在这里才见真章。", "market": ""},
    },
    currency="银钱",
    ui={"skin": "ink", "accent": "#c9a86b", "motif": "市井·经营", "brand": "临川老街",
        "tagline": "一分利，撑起一间铺"},
    playbook={"loop": "mud", "input": "command",
              "progress": {"axis": "gold", "label": "资产", "max": 5000},
              "failure": {"mode": "clock", "label": "周转", "max": 12},
              "beat": {"pattern": ["进货", "定价", "待客", "盘账", "扩张"], "every": 5},
              "settlement": ["trade", "social", "roll", "tick"],
              "context": {"inject": ["lore", "cast", "chronicle"], "max_lore": 8, "scan_depth": 2}},
    questlines=[{
        "id": "first_month", "title": "第一个月", "summary": "先活过这个月，再谈扩张。",
        "visibility": {"flag": "__start__"},
        "stages": [
            {"id": "stock", "title": "备货", "objectives": ["库存里有 20 份茶"],
             "exit_if": {"item_gte": {"key": "tea", "n": 20}}, "next": ["profit"]},
            {"id": "profit", "title": "见利", "objectives": ["资产超过 400"],
             "exit_if": {"gold_gte": 400}, "next": []},
        ],
        "reward": {"gold": 100, "flags": ["first_month_done"]},
    }],
    systems=[
        {"id": "clock", "kind": "time", "label": "营业时间",
         "config": {"start": {"day": 1, "hour": 6}, "days_per_season": 30}},
        {"id": "supply", "kind": "loot", "label": "到货",
         "config": {"tables": {"restock": {"rolls": 2, "empty_weight": 20, "entries": [
             {"item": "tea", "name": "粗茶", "weight": 50, "qty": [5, 15]},
             {"item": "cake", "name": "茶点", "weight": 40, "qty": [5, 10]},
             {"item": "silk", "name": "绸缎", "weight": 10, "qty": [1, 3]},
         ]}}}},
        {"id": "books", "kind": "custom", "label": "经营动作",
         "config": {"actions": {
             "open_shop": {"label": "开门营业",
                           "effects": [{"op": "advance_time", "minutes": 600},
                                       {"op": "meter", "key": "turnover", "delta": 1}]},
             "restock": {"label": "补货",
                         "effects": [{"op": "advance_time", "minutes": 180},
                                     {"op": "resource", "key": "gold", "delta": -60}]},
         }}},
        {"id": "rep", "kind": "reputation", "label": "商誉",
         "config": {"factions": ["街坊", "商行", "行会"]}},
    ],
    game={"title": "临川老街", "kind": "management",
          "resources": [{"key": "gold", "label": "银钱", "value": 300, "min": 0, "max": 0, "color": "gold"},
                        {"key": "energy", "label": "精力", "value": 10, "min": 0, "max": 10, "color": "mp"}],
          "attributes": [{"key": "cha", "label": "口才", "value": 12},
                         {"key": "int", "label": "算账", "value": 12}],
          "meters": [{"key": "turnover", "label": "周转", "value": 0, "min": 0, "max": 12}],
          "tags": ["新开张"], "sheet": {"铺面": "临川老街 3 号", "主营": "茶与茶点"}},
    lore=[
        {"keys": ["基调", "文风"], "constant": True, "comment": "基调",
         "content": "市井经营：每天算账，偶尔人情。钱不是万能的，但没钱万万不能。"},
        {"keys": ["南市集", "批发"], "comment": "批发",
         "content": "南市集的批发价比零售低三成，但一次至少要拿五十份。"},
    ],
)

_SURVIVAL = _pack(
    "survival", "末日生存", "生存 / 资源管理", "mud",
    notes="体力/饥饿/口渴/温度四条线同时压着，白天搜刮，夜里躲藏。",
    world={"name": "灰区", "era": "崩坏第 47 天",
           "location_desc": "便利店的玻璃碎了一地，货架被翻得精光。远处的天是灰的，风里有铁锈味。"},
    player={"name": "幸存者", "level": "新手",
            "attrs": {"str": 10, "dex": 11, "int": 10, "con": 12, "cha": 8},
            "hp": 40, "hp_max": 40, "mp": 0, "mp_max": 0, "gold": 0,
            "location": "废弃便利店", "items": {"water": 1, "canned": 1}},
    entities=[
        {"id": "scavenger", "name": "拾荒者 老周", "faction": "散人", "level": "老手",
         "attrs": {"str": 11, "dex": 10, "int": 11, "con": 13, "cha": 7},
         "hp": 35, "hp_max": 35, "gold": 0, "location": "废弃便利店",
         "desc": "防毒面具推到额头上，露出一双总在打量你的眼睛。", "personality": "谨慎",
         "speech": "「东西可以换，别问从哪来的。」"},
    ],
    market=[{"location": "废弃便利店", "items": [
        {"key": "water", "name": "净水", "price": 15, "supply": 6, "base_price": 15, "type": "补给"},
        {"key": "canned", "name": "罐头", "price": 12, "supply": 8, "base_price": 12, "type": "补给"},
        {"key": "bandage", "name": "绷带", "price": 10, "supply": 5, "base_price": 10, "type": "医疗"},
    ]}],
    relations=[{"a": "player", "b": "scavenger", "affinity": 0, "respect": 5}],
    level_tiers=["新手", "老练", "硬核", "传奇幸存者"],
    terms={"hero": "幸存者", "level": "状态", "hp": "体力", "mp": "精神", "gold": "物资点",
           "track": "生存天数", "territory": "据点", "inventory": "背包",
           "codex": "生存笔记", "quests": "生存目标"},
    places={
        "废弃便利店": {"desc": "货架翻倒，收银台的抽屉被撬开，后门通向小巷。", "market": "废弃便利店"},
        "地下车库": {"desc": "阴影里堆着废弃车辆，偶尔有滴水声。", "market": ""},
        "水塔": {"desc": "铁梯锈得厉害，塔顶视野开阔但风很大。", "market": ""},
    },
    currency="物资点",
    ui={"skin": "neutral", "accent": "#c76b4a", "motif": "废土·灰区", "brand": "灰区",
        "tagline": "第四十七天，还活着"},
    playbook={"loop": "mud", "input": "command",
              "progress": {"axis": "knowledge", "label": "生存天数", "max": 30},
              "failure": {"mode": "hp", "label": "倒下", "max": 0},
              "beat": {"pattern": ["清晨", "搜刮", "遭遇", "夜宿", "清点"], "every": 4},
              "settlement": ["combat", "trade", "roll", "travel", "use_item"],
              "context": {"inject": ["lore", "cast", "chronicle"], "max_lore": 8, "scan_depth": 2}},
    questlines=[{
        "id": "water_tower", "title": "水塔", "summary": " rumor 说水塔里还有干净的水。",
        "visibility": {"flag": "__start__"},
        "stages": [
            {"id": "reach", "title": "抵达", "objectives": ["走到水塔"],
             "exit_if": {"visited": "水塔"}, "next": ["climb"]},
            {"id": "climb", "title": "攀爬", "objectives": ["爬上水塔检查水箱"], "next": []},
        ],
        "reward": {"flags": ["clean_water"]},
    }],
    systems=[
        {"id": "clock", "kind": "time", "label": "昼夜",
         "config": {"start": {"day": 47, "hour": 16}, "days_per_season": 30,
                    "seasons": ["崩坏季"], "weathers": [{"name": "灰霾", "weight": 60},
                                                       {"name": "酸雨", "weight": 25},
                                                       {"name": "晴", "weight": 15}]}},
        {"id": "scavenge", "kind": "loot", "label": "搜刮",
         "config": {"tables": {"store": {"rolls": 3, "empty_weight": 40, "entries": [
             {"item": "water", "name": "净水", "weight": 30, "qty": [1, 2]},
             {"item": "canned", "name": "罐头", "weight": 35, "qty": [1, 2]},
             {"item": "scrap", "name": "零件", "weight": 25, "qty": [1, 3]},
             {"item": "chip", "name": "电子元件", "weight": 8, "qty": [1, 1]},
         ]}}}},
        {"id": "survival", "kind": "custom", "label": "生存动作",
         "config": {"actions": {
             "eat": {"label": "进食",
                     "effects": [{"op": "resource", "key": "hp", "delta": 5},
                                 {"op": "flag", "flag": "fed"}]},
             "sleep": {"label": "睡觉",
                       "effects": [{"op": "advance_time", "minutes": 480},
                                   {"op": "resource", "key": "hp", "delta": 8}]},
             "scavenge": {"label": "搜刮周围",
                          "effects": [{"op": "advance_time", "minutes": 120},
                                      {"op": "meter", "key": "day", "delta": 1}]},
         }}},
        {"id": "rep", "kind": "reputation", "label": "据点关系",
         "config": {"factions": ["散人", "哨站", "车队"]}},
    ],
    game={"title": "灰区", "kind": "survival",
          "resources": [{"key": "hp", "label": "体力", "value": 40, "min": 0, "max": 40, "color": "hp"},
                        {"key": "water", "label": "水", "value": 1, "min": 0, "max": 20, "color": "mp"},
                        {"key": "food", "label": "食物", "value": 1, "min": 0, "max": 20, "color": "success"}],
          "attributes": [{"key": "str", "label": "力量", "value": 10},
                         {"key": "con", "label": "体质", "value": 12}],
          "meters": [{"key": "day", "label": "生存天数", "value": 0, "min": 0, "max": 30}],
          "tags": ["断水断电"], "sheet": {"据点": "废弃便利店", "队伍": "无"}},
    lore=[
        {"keys": ["基调", "文风"], "constant": True, "comment": "基调",
         "content": "废土生存：资源永远不够，每个选择都有代价，希望是奢侈品。"},
        {"keys": ["水塔", "干净的水"], "comment": "水塔",
         "content": "水塔顶层的储水箱有独立过滤层，可能还有存水。"},
    ],
)

_NARRATIVE = _pack(
    "narrative", "情感叙事", "剧情 / 关系", "freeform",
    notes="没有战斗，只有关系与选择。核心是「你说什么、你欠谁、你最后选了谁」。",
    world={"name": "长夏", "era": "毕业那年的夏天",
           "location_desc": "教室的风扇吱呀转着，桌上的试卷被风掀起一角。窗外的蝉叫得让人心慌。"},
    player={"name": "你", "level": "高三",
            "attrs": {"str": 8, "dex": 9, "int": 11, "con": 9, "cha": 13},
            "hp": 20, "hp_max": 20, "mp": 0, "mp_max": 0, "gold": 50,
            "location": "教室", "items": {"letters": 1}},
    entities=[
        {"id": "lin", "name": "林夏", "faction": "同班", "level": "同桌",
         "attrs": {"str": 7, "dex": 9, "int": 12, "con": 8, "cha": 14},
         "hp": 20, "hp_max": 20, "gold": 20, "location": "教室",
         "desc": "总把袖子挽到手肘，笑起来会眯眼。", "personality": "开朗但藏事",
         "speech": "「你要是敢忘了我，我就把你的卷子撕了。」"},
        {"id": "chen", "name": "陈老师", "faction": "教师", "level": "班主任",
         "attrs": {"str": 8, "dex": 8, "int": 14, "con": 10, "cha": 11},
         "hp": 20, "hp_max": 20, "gold": 60, "location": "办公室",
         "desc": "衬衫永远扣到最上面一颗。", "personality": "严厉但心软",
         "speech": "「你们以后会明白的。」"},
    ],
    market=[{"location": "校门口", "items": [
        {"key": "ice", "name": "冰棍", "price": 2, "supply": 30, "base_price": 2, "type": "零食"},
        {"key": "letter_paper", "name": "信纸", "price": 5, "supply": 20, "base_price": 5, "type": "文具"},
    ]}],
    relations=[{"a": "player", "b": "lin", "affinity": 40, "respect": 10}],
    level_tiers=["高一", "高二", "高三", "毕业"],
    terms={"hero": "你", "level": "学年", "hp": "心力", "mp": "勇气", "gold": "零花钱",
           "track": "时间线", "territory": "校园", "inventory": "口袋",
           "codex": "回忆", "quests": "未说出口的话", "context": "心事"},
    places={
        "教室": {"desc": "午后的光落在课桌上，粉笔灰在光里浮。", "market": ""},
        "天台": {"desc": "铁丝网外是整个县城，风把校服吹得鼓起来。", "market": ""},
        "校门口": {"desc": "小卖部的冰柜嗡嗡响，放学的自行车流从这里涌出去。", "market": "校门口"},
    },
    currency="零花钱",
    ui={"skin": "ink", "accent": "#d98f8f", "motif": "青春·长夏", "brand": "长夏",
        "tagline": "那个夏天没有说完的话"},
    playbook={"loop": "freeform", "input": "natural",
              "progress": {"axis": "level", "label": "学年", "max": 3},
              "failure": {"mode": "none", "label": "无失败", "max": 0},
              "beat": {"pattern": ["日常", "接近", "迟疑", "冲突", "坦白"], "every": 5},
              "settlement": ["social", "roll", "travel"],
              "context": {"inject": ["lore", "cast", "chronicle"], "max_lore": 8, "scan_depth": 2}},
    questlines=[{
        "id": "letter", "title": "那封信", "summary": "有封信一直没送出去。",
        "visibility": {"flag": "__start__"},
        "stages": [
            {"id": "hesitate", "title": "犹豫", "objectives": ["决定要不要写"],
             "exit_if": {"flag": "letter_written"}, "next": ["give"]},
            {"id": "give", "title": "交出", "objectives": ["把信交出去"], "next": []},
        ],
        "reward": {"flags": ["letter_delivered"]},
    }],
    systems=[
        {"id": "clock", "kind": "time", "label": "学期",
         "config": {"start": {"day": 1, "hour": 8}, "days_per_season": 60,
                    "seasons": ["初夏", "盛夏", "夏末", "秋初"]}},
        {"id": "bond", "kind": "reputation", "label": "羁绊",
         "config": {"factions": ["林夏", "陈老师", "家人", "同学"],
                    "tiers": [{"min": -1000, "label": "疏远"}, {"min": 0, "label": "普通"},
                              {"min": 30, "label": "亲近"}, {"min": 70, "label": "心意相通"}]}},
        {"id": "mood", "kind": "custom", "label": "心事动作",
         "config": {"actions": {
             "write": {"label": "写信",
                       "effects": [{"op": "flag", "flag": "letter_written"},
                                   {"op": "resource", "key": "courage", "delta": -2}]},
             "talk": {"label": "找她说话",
                      "effects": [{"op": "reputation", "system": "bond",
                                   "faction": "林夏", "delta": 5},
                                  {"op": "advance_time", "minutes": 60}]},
         }}},
        {"id": "memories", "kind": "achievement", "label": "回忆",
         "config": {"items": [
             {"id": "first_talk", "name": "第一次搭话", "desc": "主动和她说话",
              "condition": {"flag": "talked"}, "reward": {"xp": 10}},
         ]}},
    ],
    game={"title": "长夏", "kind": "story",
          "resources": [{"key": "courage", "label": "勇气", "value": 10, "min": 0, "max": 10, "color": "mp"},
                        {"key": "gold", "label": "零花钱", "value": 50, "min": 0, "max": 0, "color": "gold"}],
          "attributes": [{"key": "cha", "label": "表达", "value": 13},
                         {"key": "int", "label": "成绩", "value": 11}],
          "meters": [{"key": "days", "label": "夏天还剩", "value": 0, "min": 0, "max": 60}],
          "tags": ["毕业季"], "sheet": {"班级": "高三 2 班", "心事": "那封信"}},
    lore=[
        {"keys": ["基调", "文风"], "constant": True, "comment": "基调",
         "content": "克制的青春叙事：不煽情，用细节说话。每个选择都在减少某些可能性。"},
    ],
)

_COZY = _pack(
    "cozy", "田园生活", "休闲 / 建造", "freeform",
    notes="种地、钓鱼、送礼、修房子。没有失败条件，只有慢慢变好的生活。",
    world={"name": "雾溪村", "era": "初春",
           "location_desc": "溪水从屋后绕过，院里的桃树刚冒芽。镇上寄来的地契还压在门缝里。"},
    player={"name": "新村民", "level": "暂住",
            "attrs": {"str": 10, "dex": 10, "int": 10, "con": 11, "cha": 11},
            "hp": 30, "hp_max": 30, "mp": 0, "mp_max": 0, "gold": 200,
            "location": "自家小院", "items": {"seeds": 5, "hoe": 1}},
    entities=[
        {"id": "mayor", "name": "村长 温伯", "faction": "村民", "level": "长者",
         "attrs": {"str": 9, "dex": 8, "int": 11, "con": 10, "cha": 13},
         "hp": 25, "hp_max": 25, "gold": 150, "location": "雾溪村",
         "desc": "总在门口晒太阳，见谁都笑。", "personality": "和善", "speech": "「慢慢来，地跑不了。」"},
        {"id": "angler", "name": "钓鱼佬 阿海", "faction": "村民", "level": "闲人",
         "attrs": {"str": 10, "dex": 12, "int": 9, "con": 11, "cha": 9},
         "hp": 25, "hp_max": 25, "gold": 90, "location": "溪边",
         "desc": "一坐一整天，桶里常常是空的。", "personality": "悠哉", "speech": "「鱼不咬钩，人也不急。」"},
    ],
    market=[{"location": "雾溪村", "items": [
        {"key": "seeds", "name": "种子", "price": 8, "supply": 40, "base_price": 8, "type": "农资"},
        {"key": "bait", "name": "鱼饵", "price": 3, "supply": 30, "base_price": 3, "type": "杂货"},
        {"key": "wood", "name": "木料", "price": 12, "supply": 20, "base_price": 12, "type": "建材"},
    ]}],
    relations=[{"a": "player", "b": "mayor", "affinity": 15, "respect": 5}],
    level_tiers=["暂住", "落户", "村民", "乡贤"],
    terms={"hero": "村民", "level": "身份", "hp": "体力", "mp": "心气", "gold": "铜钱",
           "track": "村庄好感", "territory": "田地", "inventory": "储物",
           "codex": "村志", "quests": "小目标", "context": "村中杂记"},
    places={
        "自家小院": {"desc": "院墙有点歪，桃树下面堆着旧木箱。", "market": ""},
        "溪边": {"desc": "水清得能看见石头，柳枝垂到水面上。", "market": ""},
        "雾溪村": {"desc": "十几户人家沿溪而建，晒着被子和萝卜干。", "market": "雾溪村"},
    },
    currency="铜钱",
    ui={"skin": "ink", "accent": "#8fb87a", "motif": "田园·雾溪", "brand": "雾溪村",
        "tagline": "慢慢来，地跑不了"},
    playbook={"loop": "freeform", "input": "natural",
              "progress": {"axis": "knowledge", "label": "村庄好感", "max": 20},
              "failure": {"mode": "none", "label": "无失败", "max": 0},
              "beat": {"pattern": ["清晨", "劳作", "午后", "闲谈", "夜里"], "every": 4},
              "settlement": ["trade", "social", "roll", "use_item"],
              "context": {"inject": ["lore", "cast", "chronicle"], "max_lore": 8, "scan_depth": 2}},
    questlines=[{
        "id": "first_harvest", "title": "第一收", "summary": "把种子种下去，等它长出来。",
        "visibility": {"flag": "__start__"},
        "stages": [
            {"id": "plant", "title": "播种", "objectives": ["在院里种下种子"],
             "exit_if": {"flag": "planted"}, "next": ["harvest"]},
            {"id": "harvest", "title": "收获", "objectives": ["等作物成熟并收下"], "next": []},
        ],
        "reward": {"gold": 50, "flags": ["first_harvest"]},
    }],
    systems=[
        {"id": "clock", "kind": "time", "label": "农时",
         "config": {"start": {"day": 1, "hour": 6}, "days_per_season": 15,
                    "seasons": ["初春", "仲春", "暮春", "初夏"]}},
        {"id": "forage", "kind": "loot", "label": "采集",
         "config": {"tables": {"wild": {"rolls": 2, "empty_weight": 25, "entries": [
             {"item": "berries", "name": "野果", "weight": 50, "qty": [1, 4]},
             {"item": "mushroom", "name": "菌子", "weight": 30, "qty": [1, 2]},
             {"item": "flower", "name": "野花", "weight": 20, "qty": [1, 3]},
         ]}}}},
        {"id": "village", "kind": "reputation", "label": "村民好感",
         "config": {"factions": ["村民", "商队", "邻村"]}},
        {"id": "chores", "kind": "custom", "label": "日常",
         "config": {"actions": {
             "farm": {"label": "下地干活",
                      "effects": [{"op": "advance_time", "minutes": 240},
                                  {"op": "flag", "flag": "planted"}]},
             "fish": {"label": "钓鱼",
                      "effects": [{"op": "advance_time", "minutes": 180},
                                  {"op": "resource", "key": "energy", "delta": -1}]},
         }}},
    ],
    game={"title": "雾溪村", "kind": "management",
          "resources": [{"key": "energy", "label": "体力", "value": 10, "min": 0, "max": 10, "color": "hp"},
                        {"key": "gold", "label": "铜钱", "value": 200, "min": 0, "max": 0, "color": "gold"}],
          "attributes": [{"key": "str", "label": "干劲", "value": 10},
                         {"key": "cha", "label": "人缘", "value": 11}],
          "meters": [{"key": "harvest", "label": "收成", "value": 0, "min": 0, "max": 20}],
          "tags": ["初春"], "sheet": {"住处": "院墙有点歪的小院", "目标": "把日子过好"}},
    lore=[
        {"keys": ["基调", "文风"], "constant": True, "comment": "基调",
         "content": "温柔的田园日常：没有威胁，只有季节和人情。允许玩家什么都不做。"},
    ],
)

_TABLETOP = _pack(
    "tabletop", "桌面跑团", "跑团 / 战术", "ttrpg",
    notes="d20 + 属性 + 技能 + 难度。战斗有战术位，探索有技能检定，社交有对抗。",
    world={"name": "灰岩堡", "era": "第三纪元",
           "location_desc": "城堡的吊桥在夜里升起，酒馆的灯还亮着。门口贴着一张悬赏：地下墓穴有东西在动。"},
    player={"name": "冒险者", "level": "1 级",
            "attrs": {"str": 14, "dex": 12, "int": 10, "con": 13, "cha": 8},
            "hp": 28, "hp_max": 28, "mp": 0, "mp_max": 0, "gold": 25,
            "location": "灰岩堡", "items": {"rope": 1, "torch": 2}},
    entities=[
        {"id": "captain", "name": "守备队长 罗兰", "faction": "灰岩堡", "level": "5 级",
         "attrs": {"str": 15, "dex": 11, "int": 10, "con": 14, "cha": 12},
         "hp": 45, "hp_max": 45, "gold": 80, "location": "灰岩堡",
         "desc": "铠甲上有新添的凹痕，说话像在下命令。", "personality": "严肃", "speech": "「墓穴里的东西，不该出来。」"},
    ],
    market=[{"location": "灰岩堡", "items": [
        {"key": "torch", "name": "火把", "price": 2, "supply": 40, "base_price": 2, "type": "消耗品"},
        {"key": "rope", "name": "麻绳", "price": 5, "supply": 20, "base_price": 5, "type": "工具"},
        {"key": "heal_potion", "name": "治疗药剂", "price": 20, "supply": 8, "base_price": 20, "type": "药水"},
    ]}],
    relations=[{"a": "player", "b": "captain", "affinity": 5, "respect": 15}],
    level_tiers=["1 级", "2 级", "3 级", "4 级", "5 级", "6 级", "7 级", "8 级"],
    terms={"hero": "冒险者", "level": "等级", "hp": "生命", "mp": "法术位", "gold": "金币",
           "track": "等级", "territory": "地图", "inventory": "装备",
           "codex": "日志", "quests": "任务"},
    places={
        "灰岩堡": {"desc": "石墙厚重，火把在风里晃，酒馆门口有人在赌骰子。", "market": "灰岩堡"},
        "地下墓穴": {"desc": "石阶往下，空气里有股铁锈味，火把照不到尽头。", "market": ""},
        "旧礼拜堂": {"desc": "彩窗碎了，长椅上落满灰，祭坛后面有道暗门。", "market": ""},
    },
    currency="金币",
    ui={"skin": "xuanshu", "accent": "#b08968", "motif": "跑团·石堡", "brand": "灰岩堡",
        "tagline": "掷骰决定命运"},
    playbook={"loop": "ttrpg", "input": "command",
              "progress": {"axis": "level", "label": "等级", "max": 8},
              "failure": {"mode": "hp", "label": "倒下", "max": 0},
              "beat": {"pattern": ["探索", "遭遇", "战斗", "休整", "推进"], "every": 4},
              "settlement": ["combat", "roll", "social", "trade", "use_item"],
              "context": {"inject": ["lore", "cast", "chronicle"], "max_lore": 10, "scan_depth": 2}},
    questlines=[{
        "id": "crypt", "title": "墓穴里的动静", "summary": "守备队长想知道下面到底是什么。",
        "visibility": {"flag": "__start__"},
        "stages": [
            {"id": "brief", "title": "说明", "objectives": ["向队长了解情况"],
             "exit_if": {"flag": "briefed"}, "next": ["descend"]},
            {"id": "descend", "title": "下墓", "objectives": ["进入地下墓穴"],
             "exit_if": {"visited": "地下墓穴"}, "next": ["chapel"]},
            {"id": "chapel", "title": "礼拜堂", "objectives": ["找到祭坛后的暗门"], "next": []},
        ],
        "reward": {"gold": 150, "flags": ["crypt_cleared"]},
    }],
    systems=[
        {"id": "clock", "kind": "time", "label": "火炬计时",
         "config": {"start": {"day": 1, "hour": 19}, "days_per_season": 30}},
        {"id": "encounter", "kind": "loot", "label": "战利品",
         "config": {"tables": {"crypt": {"rolls": 2, "empty_weight": 20, "entries": [
             {"item": "bone_dust", "name": "骨粉", "weight": 50, "qty": [1, 3]},
             {"item": "old_coin", "name": "古币", "weight": 35, "qty": [1, 6]},
             {"item": "rune", "name": "符文石", "weight": 10, "qty": [1, 1]},
         ]}}}},
        {"id": "xp", "kind": "progression", "label": "经验",
         "config": {"base_xp": 300, "growth": 1.8, "max_level": 8,
                    "per_level": {"str": 1, "con": 1}, "level_label": "冒险者等级"}},
        {"id": "factions", "kind": "reputation", "label": "阵营",
         "config": {"factions": ["灰岩堡", "盗贼公会", "教会"]}},
        {"id": "skills", "kind": "custom", "label": "技能动作",
         "config": {"actions": {
             "search": {"label": "搜索",
                        "effects": [{"op": "loot", "system": "encounter", "table": "crypt", "grant": True},
                                    {"op": "advance_time", "minutes": 30}]},
             "short_rest": {"label": "短休",
                            "effects": [{"op": "resource", "key": "hp", "delta": 6},
                                        {"op": "advance_time", "minutes": 60}]},
         }}},
    ],
    game={"title": "灰岩堡", "kind": "rpg",
          "resources": [{"key": "hp", "label": "生命", "value": 28, "min": 0, "max": 28, "color": "hp"},
                        {"key": "gold", "label": "金币", "value": 25, "min": 0, "max": 0, "color": "gold"}],
          "attributes": [{"key": "str", "label": "力量", "value": 14},
                         {"key": "dex", "label": "敏捷", "value": 12},
                         {"key": "int", "label": "智力", "value": 10},
                         {"key": "con", "label": "体质", "value": 13},
                         {"key": "cha", "label": "魅力", "value": 8}],
          "meters": [{"key": "level", "label": "等级", "value": 1, "min": 1, "max": 8}],
          "tags": ["地下墓穴"], "sheet": {"职业": "战士", "背景": "雇佣兵"}},
    lore=[
        {"keys": ["基调", "文风"], "constant": True, "comment": "基调",
         "content": "经典跑团：掷骰即规则，失败要有代价，也要给出替代路径（失败前进）。"},
        {"keys": ["墓穴", "地下"], "comment": "墓穴",
         "content": "地下墓穴在城堡建成前就存在，墙壁上的符号比王国更古老。"},
    ],
)

_IMMERSIVE = _pack(
    "immersive", "沉浸模拟", "沉浸 / 自由", "ttrpg",
    notes="强调「有代价的解决方式」：潜行、说服、破坏、贿赂都能过，但都留痕迹。",
    world={"name": "科尔沃城", "era": "雾季",
           "location_desc": "运河上的雾气混着煤烟。钟楼敲了七下，街角的告示牌上贴着新的禁令。"},
    player={"name": "无名者", "level": "素人",
            "attrs": {"str": 9, "dex": 13, "int": 11, "con": 9, "cha": 10},
            "hp": 24, "hp_max": 24, "mp": 0, "mp_max": 0, "gold": 35,
            "location": "运河区", "items": {"lockpick": 1}},
    entities=[
        {"id": "fence", "name": "黑市商人 薇拉", "faction": "黑市", "level": "掮客",
         "attrs": {"str": 8, "dex": 11, "int": 13, "con": 9, "cha": 13},
         "hp": 20, "hp_max": 20, "gold": 400, "location": "运河区",
         "desc": "围巾遮到鼻梁，只露出眼睛。", "personality": "精于算计", "speech": "「价钱好说，痕迹难洗。」"},
        {"id": "guard", "name": "巡夜人 布伦", "faction": "城卫", "level": "哨兵",
         "attrs": {"str": 13, "dex": 10, "int": 9, "con": 12, "cha": 9},
         "hp": 30, "hp_max": 30, "gold": 25, "location": "钟楼",
         "desc": "靴子踩在湿石板上，声音传得很远。", "personality": "刻板", "speech": "「宵禁了，回去吧。」"},
    ],
    market=[{"location": "运河区", "items": [
        {"key": "lockpick", "name": "撬锁器", "price": 25, "supply": 6, "base_price": 25, "type": "工具"},
        {"key": "cloak", "name": "暗色斗篷", "price": 18, "supply": 10, "base_price": 18, "type": "装备"},
        {"key": "bribe", "name": "封口费", "price": 40, "supply": 5, "base_price": 40, "type": "道具"},
    ]}],
    relations=[{"a": "player", "b": "fence", "affinity": 5, "respect": 0}],
    level_tiers=["素人", "熟手", "行家", "传奇"],
    terms={"hero": "潜入者", "level": "名声", "hp": "伤势", "mp": "专注", "gold": "金币",
           "track": "名声阶", "territory": "势力范围", "inventory": "随身",
           "codex": "情报", "quests": "目标"},
    places={
        "运河区": {"desc": "水声盖住了脚步，雾里能看见对岸的灯。", "market": "运河区"},
        "钟楼": {"desc": "齿轮在头顶咬合，栏杆上的锈一碰就掉。", "market": ""},
        "档案馆": {"desc": "高窗投下的光柱里全是灰，架子上按年份排到三百年前。", "market": ""},
    },
    currency="金币",
    ui={"skin": "neutral", "accent": "#6f8cab", "motif": "潜入·雾城", "brand": "科尔沃",
        "tagline": "每条路都留痕迹"},
    playbook={"loop": "ttrpg", "input": "command",
              "progress": {"axis": "knowledge", "label": "情报", "max": 20},
              "failure": {"mode": "clock", "label": "警觉", "max": 8},
              "beat": {"pattern": ["踩点", "接近", "行动", "善后", "代价"], "every": 4},
              "settlement": ["roll", "social", "trade", "combat", "travel"],
              "context": {"inject": ["lore", "cast", "chronicle"], "max_lore": 10, "scan_depth": 2}},
    questlines=[{
        "id": "archive", "title": "档案馆的名单", "summary": "有人愿意出钱买一份名单。",
        "visibility": {"flag": "__start__"},
        "stages": [
            {"id": "contact", "title": "接头", "objectives": ["找到黑市商人薇拉"],
             "exit_if": {"flag": "met_vira"}, "next": ["plan"]},
            {"id": "plan", "title": "踩点", "objectives": ["摸清档案馆的巡逻"],
             "exit_if": {"visited": "档案馆"}, "next": ["take"]},
            {"id": "take", "title": "取件", "objectives": ["拿到名单"], "next": []},
        ],
        "reward": {"gold": 200, "flags": ["list_taken"]},
    }],
    systems=[
        {"id": "clock", "kind": "time", "label": "宵禁时钟",
         "config": {"start": {"day": 1, "hour": 19}, "days_per_season": 30}},
        {"id": "loot", "kind": "loot", "label": "搜身",
         "config": {"tables": {"pocket": {"rolls": 2, "empty_weight": 50, "entries": [
             {"item": "coin", "name": "零钱", "weight": 60, "qty": [1, 8]},
             {"item": "key", "name": "钥匙", "weight": 25, "qty": [1, 1]},
             {"item": "note", "name": "字条", "weight": 15, "qty": [1, 1]},
         ]}}}},
        {"id": "alert", "kind": "reputation", "label": "警觉度",
         "config": {"factions": ["城卫", "黑市", "平民"],
                    "tiers": [{"min": -1000, "label": "无视"}, {"min": 20, "label": "留意"},
                              {"min": 50, "label": "追查"}, {"min": 80, "label": "通缉"}]}},
        {"id": "tactics", "kind": "custom", "label": "潜入动作",
         "config": {"actions": {
             "sneak": {"label": "潜行",
                       "effects": [{"op": "advance_time", "minutes": 20},
                                   {"op": "reputation", "system": "alert", "faction": "城卫", "delta": 5}]},
             "bribe": {"label": "行贿",
                       "effects": [{"op": "resource", "key": "gold", "delta": -40},
                                   {"op": "reputation", "system": "alert", "faction": "城卫", "delta": -10}]},
         }}},
    ],
    game={"title": "科尔沃", "kind": "rpg",
          "resources": [{"key": "hp", "label": "伤势", "value": 24, "min": 0, "max": 24, "color": "hp"},
                        {"key": "gold", "label": "金币", "value": 35, "min": 0, "max": 0, "color": "gold"}],
          "attributes": [{"key": "dex", "label": "敏捷", "value": 13},
                         {"key": "int", "label": "洞察", "value": 11}],
          "meters": [{"key": "alert", "label": "警觉", "value": 0, "min": 0, "max": 8}],
          "tags": ["宵禁"], "sheet": {"身份": "无名者", "目标": "名单"}},
    lore=[
        {"keys": ["基调", "文风"], "constant": True, "comment": "基调",
         "content": "沉浸模拟：每个目标至少有三种解法（潜行/说服/暴力），越省事留的痕迹越多。"},
    ],
)

TEMPLATES = {
    t["id"]: t for t in (_JRPG, _MYSTERY, _MANAGEMENT, _SURVIVAL,
                         _NARRATIVE, _COZY, _TABLETOP, _IMMERSIVE)
}

CORE_TEMPLATE_IDS = tuple(TEMPLATES.keys())


# ────────────────────────────── 公共 API ──────────────────────────────

def list_templates() -> list:
    """模板目录（面板与宿主都用）：id/名称/题材/循环/体系数/事业线数。"""
    out = []
    for tid, t in TEMPLATES.items():
        out.append({
            "id": tid, "name": t["name"], "genre": t["genre"], "loop": t["loop"],
            "notes": t["notes"], "systems": len(t.get("systems") or []),
            "questlines": len(t.get("questlines") or []),
            "entities": len(t.get("entities") or []),
            "places": len(t.get("places") or {}),
            "lore": len(t.get("lore") or []),
        })
    return out


def get(tid: str) -> dict:
    """取模板的深拷贝（调用方可随意修改，不会污染库）。"""
    key = str(tid or "").strip()
    if key not in TEMPLATES:
        raise ValueError("模板不存在: %r（可用: %s）" % (tid, ", ".join(TEMPLATES)))
    return copy.deepcopy(TEMPLATES[key])


def apply_overrides(template: dict, overrides: dict | None = None) -> dict:
    """把 overrides 合并进模板（深合并 dict，列表整体替换）。返回新对象。"""
    if not overrides:
        return template
    if not isinstance(overrides, dict):
        raise ValueError("overrides 必须是对象")
    merged = copy.deepcopy(template)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _deep_merge(base: dict, patch: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def to_bundle(tid: str, overrides: dict | None = None, name: str = "",
              player_name: str = "") -> dict:
    """模板 → 设定包（settings/*.setting.json 同构，可直接 load_setting / build_state）。"""
    tpl = apply_overrides(get(tid), overrides)
    bundle = {
        "name": name or tpl["name"],
        "note": tpl["notes"],
        "seed": 20261014,
        "world": tpl["world"],
        "player": tpl["player"],
        "entities": tpl["entities"],
        "market": tpl["market"],
        "relations": tpl["relations"],
        "world_flags": tpl["world_flags"],
        "level_tiers": tpl["level_tiers"],
        "terms": tpl["terms"],
        "places": {k: (v if isinstance(v, dict) else {"desc": str(v)})
                   for k, v in (tpl.get("places") or {}).items()},
        "lore": tpl["lore"],
        "currency": tpl["currency"],
        "ui": tpl["ui"],
        "playbook": tpl["playbook"],
        "questlines": tpl["questlines"],
        "systems": tpl.get("systems") or [],
        "game": tpl.get("game") or {},
    }
    if player_name:
        bundle["player"]["name"] = str(player_name)[:40]
    return bundle


def validate(tpl: dict) -> list:
    """结构校验：返回问题列表（空列表 = 通过）。模板必须"基础件齐全"。"""
    problems = []
    if not isinstance(tpl, dict):
        return ["模板不是对象"]
    for key in ("id", "name", "genre", "loop"):
        if not str(tpl.get(key) or "").strip():
            problems.append("缺少 %s" % key)
    world = tpl.get("world") or {}
    if not world.get("name"):
        problems.append("world.name 缺失")
    player = tpl.get("player") or {}
    if not player.get("name"):
        problems.append("player.name 缺失")
    if not isinstance(player.get("attrs"), dict):
        problems.append("player.attrs 缺失")
    for key in ("hp", "hp_max", "gold"):
        if key not in player:
            problems.append("player.%s 缺失" % key)
    if not tpl.get("level_tiers"):
        problems.append("level_tiers 为空")
    if not tpl.get("places"):
        problems.append("places 为空")
    if not tpl.get("market"):
        problems.append("market 为空")
    if not tpl.get("entities"):
        problems.append("entities 为空")
    playbook = tpl.get("playbook") or {}
    if not playbook.get("loop"):
        problems.append("playbook.loop 缺失")
    if not isinstance(playbook.get("progress"), dict):
        problems.append("playbook.progress 缺失")
    if not isinstance(playbook.get("failure"), dict):
        problems.append("playbook.failure 缺失")
    if not playbook.get("beat"):
        problems.append("playbook.beat 缺失")
    if not tpl.get("terms"):
        problems.append("terms 为空")
    if not tpl.get("lore"):
        problems.append("lore 为空")
    if not tpl.get("questlines"):
        problems.append("questlines 为空")
    if not tpl.get("systems"):
        problems.append("systems 为空")
    game = tpl.get("game") or {}
    if not game.get("resources"):
        problems.append("game.resources 为空")
    if not game.get("attributes"):
        problems.append("game.attributes 为空")
    if not game.get("kind"):
        problems.append("game.kind 缺失")
    # 引用完整性：place.market 必须指向 market 里存在的地点
    market_locs = {m.get("location") for m in (tpl.get("market") or []) if isinstance(m, dict)}
    for pname, pinfo in (tpl.get("places") or {}).items():
        if isinstance(pinfo, dict) and pinfo.get("market") and pinfo["market"] not in market_locs:
            problems.append("places[%s].market 指向不存在的市场 %r" % (pname, pinfo["market"]))
    # 事业线谓词的 visited 目标必须在 places 里
    place_names = set((tpl.get("places") or {}).keys())
    for quest in tpl.get("questlines") or []:
        for stage in (quest.get("stages") or []):
            cond = stage.get("exit_if")
            if isinstance(cond, dict) and cond.get("visited") and cond["visited"] not in place_names:
                problems.append("quest %s stage %s 的 visited=%r 不在 places 里"
                                % (quest.get("id"), stage.get("id"), cond["visited"]))
    return problems
