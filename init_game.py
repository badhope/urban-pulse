"""初始化游戏状态"""
import json, sys

# 默认写当前目录的 game_state.json；可用 `python init_game.py [路径]` 指定（CI 与多局并存用）
STATE_FILE = sys.argv[1] if len(sys.argv) > 1 else "game_state.json"

state = {
    "tick": 0,
    "entities": {
        "player": {
            "name": "陆恒",
            "faction": "散修",
            "attrs": {"str": 12, "dex": 14, "int": 10, "con": 11, "cha": 9},
            "hp": 80, "hp_max": 80,
            "mp": 30, "mp_max": 30,
            "level": "练气三层",
            "gold": 500,
            "location": "bamboo_tea_booth",
            "skills": ["基础剑术"],
            "morality": [0, 0, 0, 0, 0, 0]
        },
        "old_chen": {
            "name": "陈老头",
            "faction": "商人",
            "attrs": {"str": 6, "dex": 8, "int": 13, "con": 7, "cha": 10},
            "hp": 40, "hp_max": 40,
            "mp": 0, "mp_max": 0,
            "level": "凡人",
            "gold": 200,
            "location": "bamboo_tea_booth"
        },
        "city_guard": {
            "name": "巡城甲士",
            "faction": "官府",
            "attrs": {"str": 15, "dex": 12, "int": 8, "con": 14, "cha": 7},
            "hp": 100, "hp_max": 100,
            "mp": 20, "mp_max": 20,
            "level": "筑基一层",
            "gold": 100,
            "location": "城中"
        },
        "goblin": {
            "name": "山妖",
            "faction": "妖兽",
            "attrs": {"str": 10, "dex": 8, "int": 4, "con": 9, "cha": 3},
            "hp": 45, "hp_max": 45,
            "mp": 0, "mp_max": 0,
            "level": "一阶妖兽",
            "gold": 20,
            "location": "西山竹林"
        },
        "merchant_li": {
            "name": "李掌柜",
            "faction": "商会",
            "attrs": {"str": 8, "dex": 10, "int": 15, "con": 8, "cha": 12},
            "hp": 60, "hp_max": 60,
            "mp": 0, "mp_max": 0,
            "level": "凡人",
            "gold": 2000,
            "location": "城中"
        }
    },
    "relations": {
        "old_chen:player": {"affinity": 15, "respect": 3},
        "city_guard:player": {"affinity": -5, "respect": 10},
        "merchant_li:player": {"affinity": 0, "respect": 5}
    },
    "market": {
        "bamboo_tea_booth": {
            "an_zhen_san": {"name": "安神丹", "price": 30, "supply": 50, "base_price": 30, "type": "丹药", "desc": "恢复少量灵力"},
            "coarse_tea": {"name": "粗茶", "price": 5, "supply": 100, "base_price": 5, "type": "饮品", "desc": "寻常茶水，解渴"},
            "information": {"name": "消息", "price": 20, "supply": 5, "base_price": 20, "type": "情报", "desc": "各种江湖传闻"}
        },
        "城中": {
            "qi_gathering_pill": {"name": "聚气丹", "price": 80, "supply": 30, "base_price": 80, "type": "丹药", "desc": "练气期常用，助增灵力"},
            "low_grade_sword": {"name": "铁剑", "price": 200, "supply": 10, "base_price": 200, "type": "武器", "desc": "凡铁所制，可用"},
            "antidote": {"name": "解毒散", "price": 50, "supply": 20, "base_price": 50, "type": "丹药", "desc": "解常见毒素"},
            "spirit_sword_manual": {"name": "《剑气入门》", "price": 1000, "supply": 1, "base_price": 1000, "type": "功法", "desc": "剑修入门法诀"}
        }
    },
    "karma_ledger": [],
    "world_flags": ["peaceful", "mortal_realm"],
    "rng_seed": 20261014,
    "event_log": [
        {"tick": 0, "type": "system", "desc": "陆恒睁开眼睛，发现自己身处竹隐茶棚之中..."}
    ],
    "world_info": {
        "name": "青云界",
        "era": "修真历 234 年",
        "location_desc": "竹隐茶棚外三十里，竹林围绕。茶棚不大，几张木桌，几把竹椅。煮茶的声音和竹叶的沙沙声混在一起。"
    }
}

json.dump(state, open(STATE_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"Game state saved to {STATE_FILE}")
print(f"Entities: {len(state['entities'])}")
print(f"Market locations: {len(state['market'])}")
