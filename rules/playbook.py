"""
玩法剧本 (Playbook) —— 让同一套规则内核跑出不同"游戏类型"

为什么需要：本项目的定位是「万界」——世界观无关。但只有世界观可换还不够：
修仙长线养成、武侠江湖恩怨、赛博朋克调查、克苏鲁理智消耗，它们的**玩法结构**本身不同：
  · 有的靠自由输入推进（AI Dungeon 式）
  · 有的靠选项推进（互动小说式）
  · 有的靠房间/命令推进（MUD 式）
  · 有的靠"声明→判定→后果"推进（桌面 RPG 式）

把这些差异收进一份 `playbook` 配置：循环类型、输入自由度、进度轴、失败条件、
节拍序列、结算方式、上下文注入策略。引擎据此决定 tick 里该做什么、面板该显示什么、
宿主该按什么节奏叙事。**规则函数不变，玩法剧本可换。**

设计约束：
  · 纯标准库、纯函数；不读文件、不依赖时间；
  · 缺失 playbook 时退回默认值（旧存档与旧设定包照常跑）；
  · 任何"随机"都用 `sha256(seed|tick|key)` 派生，不消耗 rng_counter。
"""

import copy
import hashlib

LOOPS = ("freeform", "choice", "mud", "ttrpg")
INPUTS = ("natural", "choice", "command")
FAILURE_MODES = ("none", "clock", "deadline", "hp", "sanity")

DEFAULT_PLAYBOOK = {
    "loop": "freeform",
    "input": "natural",
    "progress": {"axis": "level", "label": "进度", "max": 10},
    "failure": {"mode": "hp", "label": "失败", "max": 0},
    "beat": {"pattern": ["日常", "摩擦", "升级", "代价", "回收"], "every": 5},
    "settlement": ["combat", "trade", "social", "karma"],
    "context": {"inject": ["lore", "cast", "chronicle"], "max_lore": 12, "scan_depth": 2},
}

# 每种循环的默认叙事指令：宿主拿到它就知道"这一局该怎么带"
LOOP_GUIDE = {
    "freeform": "玩家自由输入任何行动；引擎只结算有数值后果的部分，其余由你描写。"
                "不写选项，不催促玩家，让世界自己回应。",
    "choice": "每个场景给出 2-4 个**有代价差异**的选项（不是同一件事的三种说法）；"
              "玩家也可以拒绝选项自由输入——引擎照常结算。选项由当前状态与任务目标生成，不预写剧情树。",
    "mud": "场景用「地点—出口—在场者—可交互对象」组织；玩家用简短命令式行动（去/看/拿/打/问）。"
           "每次移动与交互都调用对应工具，别跳过结算。",
    "ttrpg": "按「玩家声明 → 引擎判定 → 后果描述」三步走。判定必须落到工具（combat/social/trade/karma），"
             "你只描述结果与代价，不改数值。失败要有后果，不要用叙述抹掉。",
}


_SCALAR_FIELDS = (("loop", LOOPS, "freeform"), ("input", INPUTS, "natural"))


def _apply_progress(pb, block, notes):
    if not isinstance(block, dict):
        return
    for field in ("axis", "label", "max"):
        if field in block:
            pb["progress"][field] = block[field]


def _apply_failure(pb, block, notes):
    if not isinstance(block, dict):
        return
    for field in ("mode", "label", "max"):
        if field in block:
            pb["failure"][field] = block[field]
    if pb["failure"].get("mode") not in FAILURE_MODES:
        notes.append("未知 failure.mode=%r，回退 hp" % pb["failure"].get("mode"))
        pb["failure"]["mode"] = "hp"


def _apply_beat(pb, block):
    if not isinstance(block, dict):
        return
    pattern = block.get("pattern")
    if isinstance(pattern, list) and pattern:
        pb["beat"]["pattern"] = [str(x) for x in pattern][:12]
    if isinstance(block.get("every"), int) and block["every"] > 0:
        pb["beat"]["every"] = block["every"]


def _apply_context(pb, block):
    if not isinstance(block, dict):
        return
    if isinstance(block.get("inject"), list):
        pb["context"]["inject"] = [str(x) for x in block["inject"]]
    for field in ("max_lore", "scan_depth"):
        if isinstance(block.get(field), int) and block[field] >= 0:
            pb["context"][field] = block[field]


def normalize(raw):
    """把设定包里可能残缺的 playbook 补成完整结构。

    容错策略：类型不对就退回默认值（而不是抛错）——一个写坏的 playbook 不应该让整局开不起来，
    但 `playbook_notes` 会记录哪些项被回退了，面板与 status 都能看到。
    """
    notes = []
    # 深拷贝：beat.pattern 是 list，浅拷贝会让调用方原地修改污染全局默认剧本
    # （实测 append 一次后，后续所有 normalize 都带上那个词）。
    pb = copy.deepcopy(DEFAULT_PLAYBOOK)
    if not isinstance(raw, dict):
        return pb, ["playbook 缺失或不是对象，已用默认剧本"]

    for field, allowed, default in _SCALAR_FIELDS:
        value = raw.get(field)
        if value in allowed:
            pb[field] = value
        elif value:
            notes.append("未知 %s=%r，回退 %s" % (field, value, default))

    _apply_progress(pb, raw.get("progress"), notes)
    _apply_failure(pb, raw.get("failure"), notes)
    _apply_beat(pb, raw.get("beat"))
    _apply_context(pb, raw.get("context"))
    if isinstance(raw.get("settlement"), list) and raw["settlement"]:
        pb["settlement"] = [str(x) for x in raw["settlement"]]
    return pb, notes


def beat_at(playbook, tick):
    """当前节拍（第几拍、叫什么）。循环播放，不依赖墙钟。"""
    source = playbook or DEFAULT_PLAYBOOK
    pattern = source.get("beat", {}).get("pattern") or DEFAULT_PLAYBOOK["beat"]["pattern"]
    every = max(1, int(source.get("beat", {}).get("every") or 5))
    idx = (max(0, int(tick)) // every) % len(pattern)
    return {"index": idx, "name": pattern[idx], "every": every,
            "next_in": every - (max(0, int(tick)) % every)}


def _player(state):
    return ((state.get("entities") or {}).get("player") or {})


def _axis_value(state, axis):
    """每个进度轴就是"看哪个已有字段"，不引入新数据。"""
    player = _player(state)
    if axis == "gold":
        return int(player.get("gold", 0) or 0)
    if axis == "reputation":
        rels = state.get("relations") or {}
        return sum(int(v.get("respect", 0)) for k, v in rels.items()
                   if isinstance(v, dict) and "player" in str(k))
    if axis == "knowledge":
        codex = state.get("codex") or {}
        return sum(len(codex.get(k) or []) for k in ("locations", "people", "items", "lore"))
    if axis == "clock":
        return int((state.get("failure_clock") or {}).get("filled", 0) or 0)
    # level（默认）：取阶梯序号与突破次数的较大者
    tier = int(player.get("tier", 0) or 0)
    stage = int(player.get("stage", 0) or 0)
    return max(stage, tier)


def progress_of(state, playbook):
    """进度轴的当前值与上限。轴是"看哪个字段"，不是新数据。"""
    pb = playbook or DEFAULT_PLAYBOOK
    axis = pb["progress"].get("axis", "level")
    cur = _axis_value(state, axis)
    cap = int(pb["progress"].get("max") or 0)
    return {"axis": axis, "label": pb["progress"].get("label", "进度"),
            "value": cur, "max": cap,
            "ratio": round(min(1.0, cur / cap), 3) if cap > 0 else None}


def _failure_clock(state, pb):
    clock = state.get("failure_clock") or {}
    filled = int(clock.get("filled", 0) or 0)
    cap = int(clock.get("max") or pb["failure"].get("max") or 8)
    return {"mode": "clock", "label": pb["failure"].get("label", "败局"),
            "value": filled, "max": cap,
            "ratio": round(min(1.0, filled / max(1, cap)), 3),
            "failed": filled >= cap,
            "reasons": list(clock.get("reasons") or [])[-5:]}


def _failure_deadline(state, pb):
    cap = int(pb["failure"].get("max") or 0)
    tick = int(state.get("tick", 0) or 0)
    left = max(0, cap - tick) if cap else None
    return {"mode": "deadline", "label": pb["failure"].get("label", "期限"),
            "value": tick, "max": cap,
            "ratio": round(1 - left / max(1, cap), 3) if cap else None,
            "failed": bool(cap and left == 0), "reasons": []}


def _failure_sanity(state, pb):
    player = _player(state)
    mp = int(player.get("mp", 0) or 0)
    mp_max = max(1, int(player.get("mp_max", 1) or 1))
    return {"mode": "sanity", "label": pb["failure"].get("label", "理智"),
            "value": mp, "max": mp_max, "ratio": round(mp / mp_max, 3),
            "failed": mp <= 0, "reasons": []}


def _failure_hp(state, pb):
    player = _player(state)
    # 没有 player 的 state（旧存档 / 只读探针）不能算"已失败"——否则 playbook.summary
    # 在空状态上会报 failed=True，面板第一帧就是红条（实测踩到）。
    if not player:
        return {"mode": "none", "label": pb["failure"].get("label", "失败"),
                "value": 0, "max": 0, "ratio": None, "failed": False, "reasons": []}
    hp = int(player.get("hp", 0) or 0)
    return {"mode": "hp" if pb["failure"].get("mode") != "none" else "none",
            "label": pb["failure"].get("label", "失败"),
            "value": hp, "max": int(player.get("hp_max", 1) or 1),
            "ratio": round(hp / max(1, int(player.get("hp_max", 1) or 1)), 3),
            "failed": pb["failure"].get("mode") != "none" and hp <= 0, "reasons": []}


_FAILURE_BUILDERS = {"clock": _failure_clock, "deadline": _failure_deadline,
                     "sanity": _failure_sanity}


def failure_state(state, playbook):
    """失败条件的当前状态。`clock` / `deadline` 有值，其余只看 hp / 理智。"""
    pb = playbook or DEFAULT_PLAYBOOK
    mode = pb["failure"].get("mode", "hp")
    builder = _FAILURE_BUILDERS.get(mode, _failure_hp)
    return builder(state, pb)


def tick_failure(state, playbook, amount=1, reason=""):
    """推进失败钟（只在 failure.mode == clock 时生效）。确定性、幂等（同一 tick 同 reason 只记一次）。"""
    pb = playbook or DEFAULT_PLAYBOOK
    if pb["failure"].get("mode") != "clock" or amount <= 0:
        return failure_state(state, pb)
    clock = state.setdefault("failure_clock", {})
    clock.setdefault("max", int(pb["failure"].get("max") or 8))
    seen = clock.setdefault("seen", [])
    key = "%s|%s" % (int(state.get("tick", 0) or 0), reason)
    if key in seen:
        return failure_state(state, pb)
    seen.append(key)
    if len(seen) > 200:
        del seen[:len(seen) - 200]
    clock["filled"] = int(clock.get("filled", 0) or 0) + int(amount)
    reasons = clock.setdefault("reasons", [])
    if reason:
        reasons.append("第%d回合·%s" % (int(state.get("tick", 0) or 0), reason))
        if len(reasons) > 20:
            del reasons[:len(reasons) - 20]
    return failure_state(state, pb)


def summary(state, playbook, tick=None):
    """给面板与 status 的一整块：剧本 + 节拍 + 进度 + 失败 + 宿主指南。"""
    pb = playbook or DEFAULT_PLAYBOOK
    tick = int(state.get("tick", 0) or 0) if tick is None else int(tick)
    return {
        "loop": pb["loop"],
        "input": pb["input"],
        "loop_guide": LOOP_GUIDE.get(pb["loop"], ""),
        "progress": progress_of(state, pb),
        "failure": failure_state(state, pb),
        "beat": beat_at(pb, tick),
        "settlement": list(pb["settlement"]),
        "context": dict(pb["context"]),
        "notes": list(state.get("playbook_notes") or []),
    }


def configurable_axes():
    """给面板"怎么玩"说明与文档用的枚举（单一信源）。"""
    return {"loops": list(LOOPS), "inputs": list(INPUTS),
            "failure_modes": list(FAILURE_MODES),
            "guides": dict(LOOP_GUIDE)}


def deterministic_unit(seed, tick, key):
    """[0,1) 确定性随机（与 world_evolution._unit 同手法，独立实现避免循环依赖）。"""
    raw = ("%s|%s|%s" % (seed, tick, key)).encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big") / float(1 << 64)
