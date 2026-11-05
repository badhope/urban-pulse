"""
世界演化 (World Evolution)

每回合由 tick 驱动的**世界侧**演化：势力消长、谣言传播、文化漂移、NPC 走动、
世界标记沉淀、Panarchy 适应性循环推进。

设计约束：
- 只标准库；随机一律由 `sha256(seed|tick|key)` 派生（不碰 random / rng_counter），
  因此不破坏「同状态 + 同行动 = 同结果」（INV-E4），也不消耗回放随机序。
- 所有写入都是 `state[...]` 上的幂等结构，读不到就按默认值建，旧存档可直接续跑。
- 演化强度由世界相位调制：Ω（崩溃）最烈，K（守恒）最缓。
"""

import hashlib
from typing import Dict, List

from game_engine.rules.models import (
    deffuant_update,
    logistic_growth,
    lotka_volterra,
    sir_step,
    thermal_relaxation,
)

PHASE_INTENSITY = {"Ω": 1.5, "α": 1.25, "r": 1.1, "K": 0.9}

PHASE_INFO = {
    "r": {"phase": "r", "desc": "开发/增长", "color": "green",
          "trigger": "快速扩张期，机会涌现"},
    "K": {"phase": "K", "desc": "保护/守恒", "color": "blue",
          "trigger": "稳定但也僵化，创新受抑"},
    "Ω": {"phase": "Ω", "desc": "崩溃/释放", "color": "red",
          "trigger": "积重难返，旧秩序在这一刻解体"},
    "α": {"phase": "α", "desc": "重组/革新", "color": "yellow",
          "trigger": "新秩序也在废墟中萌芽"},
}

MAX_FACTIONS = 24
MAX_FLAGS = 200
MAX_RUMORS = 12


def _unit(seed, tick, key: str) -> float:
    """确定性 [0,1)：sha256(seed|tick|key) 前 8 字节归一并截断。

    与 economy.tick_market 同一手法：不调用 random，因此不推进 rng_counter。
    """
    raw = ("%s|%s|%s" % (seed, tick, key)).encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big") / float(1 << 64)


def phase_intensity(state: dict) -> float:
    """当前相位的事件/波动烈度倍数；无相位信息时按 K（最缓）。"""
    phase = (state.get("panarchy") or {}).get("phase")
    return PHASE_INTENSITY.get(str(phase), 1.0)


def _factions(state: dict) -> Dict[str, dict]:
    """势力存量表。缺省从实体的 faction 字段建（每个势力初始 power=在场人数×12）。"""
    fac = state.setdefault("factions", {})
    if fac:
        return fac
    seen = {}
    for eid, ent in (state.get("entities") or {}).items():
        name = str(ent.get("faction") or "").strip()
        if not name or eid == "player":
            continue
        seen[name] = seen.get(name, 0) + 1
    for name, n in list(seen.items())[:MAX_FACTIONS]:
        fac[name] = {"power": min(100.0, 20.0 + n * 12.0), "reach": 0.2}
    return fac


def _market_index(state: dict) -> float:
    """全市场「现价 ÷ 基准价」的均值；无市场时返回 1.0。"""
    ratios = []
    for loc in (state.get("market") or {}).values():
        for item in loc.values():
            base = int(item.get("base_price", item.get("price", 0)) or 0)
            if base > 0:
                ratios.append(float(item.get("price", base)) / base)
    if not ratios:
        return 1.0
    return sum(ratios) / len(ratios)


def evolve_factions(state: dict) -> List[str]:
    """势力消长：每个势力有自己的**禀赋**与承载上限，头部两家再做温和的相互压制。

    为什么不是"所有势力都朝 100 长"：那样几十回合后全体贴顶，排行榜变成平线，
    "谁在崛起"就看不出来了（实测 180 回合即饱和）。为什么也不是"共享一个总容量"：
    那会把所有势力拉平到同一个数（实测 8 家全部 35.5），同样没有信息量。

    正确做法是让**每个势力带着自己的禀赋**参与竞争：
      · 禀赋由势力名确定性派生（`sha256(name)` → 0.55~1.45），决定它的承载上限；
      · logistic 增长把自己的存量推向该上限；
      · 头部两家再用 Lotka-Volterra 做温和压制，制造此消彼长的摆荡；
      · 强者承担治理成本，弱者享受"挑战者回流"，避免赢家通吃。
    结果是：长期有稳定的强弱格局（排行榜可读），短期有换手（世界是活的）。

    返回本回合产生的事件文案（供 tick 写进编年史）。
    """
    fac = _factions(state)
    if not fac:
        return []
    seed = state.get("rng_seed") or 0
    tick = int(state.get("tick", 0) or 0)
    intensity = phase_intensity(state)
    events = []

    names = sorted(fac)
    previous_leader = state.get("_faction_leader")
    ranks = sorted(names, key=lambda n: -float(fac[n].get("power", 50.0)))
    for name in names:
        row = fac.setdefault(name, {"power": 50.0, "reach": 0.2})
        power = float(row.get("power", 50.0))
        trait = 0.55 + _unit(seed, 0, "trait:" + name) * 0.90
        cap = 24.0 + 40.0 * trait                      # 46 ~ 82，各自的"天花板"
        drift = (_unit(seed, tick, "fac:" + name) - 0.5) * 0.10 * intensity
        r = 0.055 * (1.0 - min(1.0, power / max(1.0, cap))) + drift
        grown = logistic_growth(power, r, cap + 6.0)
        fac[name]["power"] = max(3.0, min(96.0, grown))

    top = ranks[:2]
    if len(top) == 2:
        a, b = top
        pa = float(fac[a].get("power", 50.0))
        pb = float(fac[b].get("power", 50.0))
        prey, pred = min(pa, pb), max(pa, pb)
        if pred > 0:
            prey2, pred2 = lotka_volterra(prey / 100.0, pred / 100.0,
                                          a=0.004 * intensity, b=0.014,
                                          c=0.012, d=0.006)
            weaker = a if pa <= pb else b
            stronger = b if weaker == a else a
            fac[weaker]["power"] = max(3.0, min(96.0, prey2 * 100.0))
            fac[stronger]["power"] = max(3.0, min(96.0, pred2 * 100.0))

    # 挑战者回流 + 强者治理成本：没有这两项，任何正反馈竞争都会在长局里一家独大。
    avg = sum(float(fac[n].get("power", 50.0)) for n in names) / len(names)
    for name in names:
        cur = float(fac[name].get("power", 50.0))
        pull = 0.02 * (avg - cur) * min(1.5, intensity)
        if cur > 68.0:
            pull -= 0.008 * (cur - 68.0)
        fac[name]["power"] = max(3.0, min(96.0, cur + pull))

    leader = max(names, key=lambda n: float(fac[n].get("power", 0)))
    leader_power = float(fac[leader].get("power", 0))
    avg_power = sum(float(fac[n].get("power", 0)) for n in names) / len(names)
    flags = state.setdefault("world_flags", [])
    state["_faction_leader"] = leader
    # "势盛"用相对优势判定：绝对阈值在容量受限的世界里永远到不了。
    # 判据用"绝对差距"而不是比值：两家时平均=中位，比值阈值要么永远触发（≥1.1）
    # 要么永远不触发（≥1.3），而差距 >6 点在有 4~8 家的世界里恒定代表"压过一头"。
    if avg_power > 0 and leader_power >= 38.0 and (leader_power - avg_power) >= 4.0:
        flag = "势力:%s 势盛" % leader
        if flag not in flags:
            flags.append(flag)
            events.append("「%s」声势渐盛，开始主导地方格局" % leader)
    if previous_leader and previous_leader != leader:
        events.append("「%s」压过「%s」，地方格局换了个主" % (leader, previous_leader))
    if len(flags) > MAX_FLAGS:
        del flags[:len(flags) - MAX_FLAGS]
    return events


def evolve_rumors(state: dict) -> List[str]:
    """谣言传播：SIR 一步。谣言由业债/市场异动/高烈度相位播种。"""
    tick = int(state.get("tick", 0) or 0)
    intensity = phase_intensity(state)
    rumors = state.setdefault("rumors", {})
    events = []

    karma = sum(e.get("amount", 0) for e in (state.get("karma_ledger") or [])
                if e.get("from") == "player" and not e.get("settled"))
    mkt = _market_index(state)
    if tick % 7 == 0 and len(rumors) < MAX_RUMORS:
        topic = None
        if karma >= 60:
            topic = "血债传闻"
        elif abs(mkt - 1.0) >= 0.12:
            topic = "物价异动"
        elif intensity >= 1.25:
            topic = "天地异象"
        if topic and topic not in rumors:
            rumors[topic] = {"s": 0.95, "i": 0.05, "r": 0.0, "heat": 0.05}
            events.append("「%s」在街巷间传开" % topic)

    for topic in list(rumors):
        row = rumors[topic]
        s, i, r = sir_step(float(row.get("s", 0.95)), float(row.get("i", 0.05)),
                           float(row.get("r", 0.0)),
                           beta=0.35 * intensity, gamma=0.12)
        row["s"], row["i"], row["r"] = s, i, r
        row["heat"] = round(i, 4)
        if float(row.get("heat", 0)) >= 0.30 and ("谣言:%s 沸腾" % topic) not in state.setdefault("world_flags", []):
            state["world_flags"].append("谣言:%s 沸腾" % topic)
            events.append("「%s」愈演愈烈，街谈巷议皆在此事" % topic)
        if i < 0.01 and r > 0.9:
            rumors.pop(topic, None)
    return events


def evolve_culture(state: dict) -> List[str]:
    """文化漂移：保守/求变两轴按 Deffuant 有界信任向地方均值靠拢。

    每 10 回合结算一次，避免逐回合抖动成噪声。
    """
    tick = int(state.get("tick", 0) or 0)
    if tick % 10 != 0:
        return []
    seed = state.get("rng_seed") or 0
    culture = state.setdefault("culture", {"tradition": 0.5, "innovation": 0.5})
    trad = float(culture.get("tradition", 0.5))
    inno = float(culture.get("innovation", 0.5))
    # 邻居观点 = 当前值 + 一个由种子决定的微小扰动（地方风气）
    n_trad = [trad, trad + (_unit(seed, tick, "cul:t") - 0.5) * 0.1]
    n_inno = [inno, inno + (_unit(seed, tick, "cul:i") - 0.5) * 0.1]
    culture["tradition"] = round(deffuant_update(trad, n_trad, mu=0.3), 4)
    culture["innovation"] = round(deffuant_update(inno, n_inno, mu=0.3), 4)
    if abs(culture["innovation"] - culture["tradition"]) >= 0.5:
        flag = "文化:新旧之争"
        flags = state.setdefault("world_flags", [])
        if flag not in flags:
            flags.append(flag)
            return ["新旧风气相争，地方上开始站队"]
    return []


def evolve_npcs(state: dict) -> List[str]:
    """NPC 走动：只有显式标记 `roam: true` 的 NPC 会换地点（默认不动，避免打断剧情）。"""
    interval = int((state.get("config") or {}).get("npc_roam_every", 5) or 5)
    tick = int(state.get("tick", 0) or 0)
    if interval <= 0 or tick % interval != 0:
        return []
    seed = state.get("rng_seed") or 0
    places = sorted(set(state.get("market") or {})
                    | {str(e.get("location") or "") for e in (state.get("entities") or {}).values()}
                    | set((state.get("locations") or {})))
    places = [p for p in places if p]
    if len(places) < 2:
        return []
    events = []
    for eid, ent in sorted((state.get("entities") or {}).items()):
        if eid == "player" or not ent.get("roam"):
            continue
        cur = str(ent.get("location") or "")
        idx = int(_unit(seed, tick, "npc:" + eid) * len(places)) % len(places)
        dest = places[idx]
        if dest == cur:
            continue
        ent["location"] = dest
        events.append("%s 动身去了「%s」" % (ent.get("name", eid), dest))
    return events


def panarchy_step(state: dict) -> Dict:
    """推进 Panarchy 适应性循环（显式四相位状态机，由真实存量驱动）。

    Holling 的适应性循环不是"查表得一个相位"，而是一个会走完的环：
      r（开发/增长）→ K（保护/守恒）→ Ω（崩溃/释放）→ α（重组/革新）→ r

    这里把相位做成状态机，每一步的存量变化都调用既有闭式函数：
      - 增长：`models.logistic_growth`（有环境容量上限，不会指数爆炸）
      - 衰减：`models.thermal_relaxation`（向平衡态松弛）
    相变阈值由真实世界量决定（势力存量、关系密度、世界标记、业债、物价偏离），
    因此同一个世界在不同玩家行为下会走到不同的相位轨迹——这是旧实现
    （相位恒为 K，因为 connectedness 依赖一个从未被写入的字段）的直接修复。

    返回带 capital/connectedness/stress 的相位字典，供 tick、status、面板共用。
    """
    pan = state.setdefault("panarchy", {})
    tick = int(state.get("tick", 0) or 0)
    fac = _factions(state)
    avg_power = (sum(float(v.get("power", 50.0)) for v in fac.values()) / len(fac)) if fac else 50.0
    rel_n = len(state.get("relations") or {})
    ent_n = max(1, len(state.get("entities") or {}))
    flag_n = len(state.get("world_flags") or [])

    capital = float(pan.get("capital", 0.18 + avg_power / 400.0))
    conn = float(pan.get("connectedness", 0.12))
    stress = float(pan.get("stress", 0.0))
    phase = str(pan.get("phase") or "r")
    hold = int(pan.get("hold", 0) or 0)
    # 手改状态/坏存档里可能出现未知相位（实测 phase="X" 直接 KeyError 炸掉整个 tick）：
    # fail-closed 归位到 r（增长期，最温和的默认），坏数据不再阻断世界演化。
    if phase not in ("r", "K", "Ω", "α"):
        phase, hold = "r", 0

    dest_capital = 0.36 + avg_power / 90.0          # 势力越强，世界存量天花板越高
    dest_conn = min(1.0, 0.30 + rel_n / (ent_n * 1.5) + flag_n / 20.0)

    if phase == "r":
        # 开发期：存量与连接度都快涨
        capital = logistic_growth(capital, 0.14, dest_capital)
        conn = logistic_growth(conn, 0.16, max(0.15, dest_conn))
        if capital >= 0.60 and conn >= 0.40:
            phase, hold = "K", 0
        elif capital >= 0.72:
            phase, hold = "K", 0
    elif phase == "K":
        # 守恒期：存量见顶、连接度继续收紧，压力累积
        capital = logistic_growth(capital, 0.05, dest_capital)
        conn = logistic_growth(conn, 0.09, max(0.2, dest_conn))
        karma = sum(int(e.get("amount", 0) or 0) for e in (state.get("karma_ledger") or [])
                    if e.get("from") == "player" and not e.get("settled"))
        stress += 0.008 + min(0.03, karma / 6000.0) + max(0.0, _market_index(state) - 1.1) * 0.10
        if stress >= 1.0 or conn >= 0.92:
            phase, hold = "Ω", 1
    elif phase == "Ω":
        # 释放期：只持续一回合，存量被砸下去
        capital = thermal_relaxation(capital, 0.12, tau=1.0)
        conn = thermal_relaxation(conn, 0.10, tau=1.0)
        stress = 0.0
        pan["collapses"] = int(pan.get("collapses", 0) or 0) + 1
        flags = state.setdefault("world_flags", [])
        tag = "纪元:第%d次大崩解" % pan["collapses"]
        if tag not in flags:
            flags.append(tag)
        if len(flags) > MAX_FLAGS:
            del flags[:len(flags) - MAX_FLAGS]
        phase, hold = "α", 8
    else:  # α 重组期
        capital = logistic_growth(capital, 0.10, max(0.25, dest_capital * 0.75))
        conn = logistic_growth(conn, 0.08, max(0.15, dest_conn * 0.8))
        hold -= 1
        if hold <= 0:
            phase = "r"

    capital = max(0.0, min(1.0, capital))
    conn = max(0.0, min(1.0, conn))
    pan["capital"] = round(capital, 4)
    pan["connectedness"] = round(conn, 4)
    pan["stress"] = round(stress, 4)
    pan["phase"] = phase
    # hold 必须落盘：α 期的倒计时是跨回合状态，只在局部变量里减会每回合从 8 读回，
    # 相位永远卡在 α（实测 hold 恒为 8、四段环断掉）。r/K 期写 0 让状态可读。
    pan["hold"] = int(hold)

    # 状态机相位是权威；描述文案按相位查表（四段环必须都走得到才叫"适应性循环"）
    info = dict(PHASE_INFO[phase])
    info["tick"] = tick
    info["capital"] = pan["capital"]
    info["connectedness"] = pan["connectedness"]
    info["stress"] = pan["stress"]
    info["collapses"] = int(pan.get("collapses", 0) or 0)
    return info


def evolve(state: dict) -> Dict:
    """推进一回合世界演化，返回摘要（事件文案 + 相位 + 势力快照）。

    调用方（tick）负责把事件写进编年史——本函数不写 event_log，保持纯。
    """
    events = []
    events.extend(evolve_factions(state))
    events.extend(evolve_rumors(state))
    events.extend(evolve_culture(state))
    events.extend(evolve_npcs(state))
    phase = panarchy_step(state)
    fac = _factions(state)
    top = sorted(fac.items(), key=lambda kv: -float(kv[1].get("power", 0)))[:5]
    return {
        "phase": phase.get("phase"),
        "capital": phase.get("capital"),
        "connectedness": phase.get("connectedness"),
        "intensity": phase_intensity(state),
        "events": events,
        "factions": [{"name": k, "power": round(float(v.get("power", 0)), 1)} for k, v in top],
        "rumors": len(state.get("rumors") or {}),
        "market_index": round(_market_index(state), 3),
    }


def world_summary(state: dict) -> Dict:
    """只读快照：面板与 status 用（不推进任何演化）。"""
    fac = state.get("factions") or {}
    top = sorted(fac.items(), key=lambda kv: -float(kv[1].get("power", 0)))[:6]
    pan = state.get("panarchy") or {}
    return {
        "factions": [{"name": k, "power": round(float(v.get("power", 0)), 1)} for k, v in top],
        "phase": pan.get("phase"),
        "capital": pan.get("capital"),
        "connectedness": pan.get("connectedness"),
        "collapses": int(pan.get("collapses", 0) or 0),
        "rumors": [{"topic": k, "heat": round(float(v.get("heat", 0)), 3)}
                   for k, v in sorted((state.get("rumors") or {}).items(),
                                      key=lambda kv: -float(kv[1].get("heat", 0)))[:5]],
        "culture": state.get("culture") or {},
        "market_index": round(_market_index(state), 3),
        "intensity": phase_intensity(state),
    }
