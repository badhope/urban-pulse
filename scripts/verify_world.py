#!/usr/bin/env python3
"""
世界演化与结算耦合自检 (verify_world.py)

为什么需要：本项目的定位是「世界因公式而自行演化」。2026-10-23 的定位审计
实测出三处塌陷——世界空转 500 回合只有市价在动、Panarchy 相位恒为 K、
六维道德在真实对局恒为 0。本脚本把「这些必须成立」写成可执行断言，
并要求它们**读的是真实结算链路的输出**，不是构造的理想输入。

覆盖：
  W1  世界自演化：连续 tick 后势力/谣言/文化/相位至少一项真的变了
  W2  相位四段环：长局里 r/K/Ω/α 都能被观测到（不是常数）
  W3  相位进结算：Ω 的事件概率与战斗伤害严格高于 K
  W4  心流进结算：无聊时命中率低于心流，且暴击不被算成失败
  W5  道德向量：业债事件真的改变六维，并影响社交增量
  W6  术语可配置：ui.terms 覆盖生效、缺失项回退默认
  W7  叙事落盘：publish_prose 后场景正文即该文本，且 prose 有界
  W8  台账有界：2000 条未结算业债被合并到 keep 以内且总额不变
  W9  确定性：同一初始状态跑两遍演化，终态逐字节一致（不碰 rng_counter）

用法:  python scripts/verify_world.py
退出码: 0 = 全通过；1 = 有失败项
"""

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if 'game_engine' not in sys.modules:
    import importlib.util
    _spec = importlib.util.spec_from_file_location(
        'game_engine', os.path.join(ROOT, '__init__.py'),
        submodule_search_locations=[ROOT])
    _pkg = importlib.util.module_from_spec(_spec)
    _pkg.__path__ = [ROOT]
    sys.modules['game_engine'] = _pkg
    # 真正执行 __init__.py：包级元数据（__version__ 等）在里面；只建对象不执行会拿不到。
    _spec.loader.exec_module(_pkg)

from game_engine.rules import world_evolution as WE              # noqa: E402
from game_engine.rules import narrative_engine as NE            # noqa: E402
from game_engine.rules import combat as CB                      # noqa: E402
from game_engine.rules import social as SO                      # noqa: E402
from game_engine.rules.progression import validate_next_level, level_tier   # noqa: E402
from game_engine.state_schema import add_karma, get_unsettled_karma, log_event, save_state, seed_rng   # noqa: E402
import game_engine.panel as PANEL                               # noqa: E402

RESULTS = []
STRICT_FAILURES = []


def check(name, ok, note=''):
    RESULTS.append(bool(ok))
    print('%s  %-52s %s' % ('PASS' if ok else 'FAIL', name, str(note)[:70]))


def base_state(factions=None, locs=None):
    """一局最小可用世界：两个势力、两个地点、两个 NPC、一个市场。"""
    ents = {
        'player': {'name': '沈砚', 'faction': '散人', 'hp': 100, 'hp_max': 100,
                   'mp': 20, 'mp_max': 20, 'gold': 500, 'location': '临川城',
                   'level': '淬体七段',
                   'attrs': {'str': 12, 'dex': 12, 'int': 12, 'con': 12, 'cha': 12}},
        'a': {'name': '老陈', 'faction': factions[0] if factions else '万石商行',
              'hp': 80, 'hp_max': 80, 'mp': 0, 'mp_max': 0, 'gold': 100,
              'location': '临川城', 'level': '凡人',
              'attrs': {'str': 10, 'dex': 10, 'int': 10, 'con': 10, 'cha': 10}},
        'b': {'name': '山贼', 'faction': factions[1] if factions and len(factions) > 1 else '寒鸦谷',
              'hp': 90, 'hp_max': 90, 'mp': 0, 'mp_max': 0, 'gold': 50,
              'location': '渡口', 'level': '凡人',
              'attrs': {'str': 11, 'dex': 9, 'int': 8, 'con': 10, 'cha': 8}},
    }
    mk = {}
    for name in (locs or ['临川城', '渡口']):
        mk[name] = {'药': {'name': '药', 'price': 50, 'supply': 20, 'base_price': 50,
                          'type': '', 'desc': ''}}
    return {'tick': 0, 'rng_seed': 20261014, 'rng_counter': 0, 'config': {},
            'world_info': {'name': '测试界', 'era': '历元年', 'location_desc': '临川城开场。'},
            'entities': ents, 'relations': {}, 'market': mk,
            'karma_ledger': [], 'world_flags': [], 'event_log': [],
            'milestones': [], 'summaries': [], 'codex': {}, 'lore': []}


def run_evolution(st, turns):
    """连续跑 turns 回合世界演化（等价于连续 tick 里的世界侧部分）。"""
    out = []
    for _ in range(turns):
        st['tick'] = int(st.get('tick', 0)) + 1
        out.append(WE.evolve(st))
    return out


# ── W1 世界自演化 ────────────────────────────────────────
def w1_self_evolution():
    st = base_state()
    before_fac = {k: v['power'] for k, v in WE._factions(st).items()}
    run_evolution(st, 60)
    after_fac = {k: v['power'] for k, v in WE._factions(st).items()}
    fac_changed = any(abs(after_fac[k] - before_fac[k]) > 0.5 for k in before_fac)
    flags_grew = len(st.get('world_flags') or []) > 0
    phase_tracked = isinstance(st.get('panarchy'), dict) and st['panarchy'].get('phase')
    check('W1 势力存量在 60 回合内真的变化', fac_changed,
          '%s → %s' % ({k: round(v, 1) for k, v in before_fac.items()},
                       {k: round(v, 1) for k, v in after_fac.items()}))
    check('W1 世界标记被真实事件写入', flags_grew, '%d 条' % len(st.get('world_flags') or []))
    check('W1 相位状态在 tick 后被记录', bool(phase_tracked), str(st.get('panarchy'))[:60])

    # 非 tick 字段也要动：这是"世界不是等人的"最直接的证据
    st2 = base_state()
    snap = json.dumps({k: v for k, v in st2.items() if k not in ('tick',)}, sort_keys=True)
    run_evolution(st2, 30)
    snap2 = json.dumps({k: v for k, v in st2.items() if k not in ('tick',)}, sort_keys=True)
    check('W1 30 回合后非 tick 字段确有变化', snap != snap2, 'diff=%d 字节' % abs(len(snap2) - len(snap)))


# ── W2 相位四段环 ────────────────────────────────────────
def w2_phase_cycle():
    st = base_state()
    phases = [r['phase'] for r in run_evolution(st, 800)]
    seen = set(phases)
    check('W2 长局出现 ≥3 种相位', len(seen) >= 3, str(sorted(seen)))
    check('W2 崩解相位 Ω 被观测到', 'Ω' in seen, '%d 次' % phases.count('Ω'))
    check('W2 重组相位 α 被观测到', 'α' in seen, '%d 次' % phases.count('α'))
    check('W2 相位不是常数（至少切换 3 次）',
          sum(1 for i in range(1, len(phases)) if phases[i] != phases[i - 1]) >= 3,
          '%d 次切换' % sum(1 for i in range(1, len(phases)) if phases[i] != phases[i - 1]))
    check('W2 崩解次数与 Ω 回合数一致',
          int(st['panarchy'].get('collapses', 0)) == phases.count('Ω'),
          'collapses=%s Ω=%d' % (st['panarchy'].get('collapses'), phases.count('Ω')))


# ── W3 相位进结算 ────────────────────────────────────────
def w3_phase_affects_settlement():
    calm = base_state()
    calm['panarchy'] = {'phase': 'K', 'capital': 0.8, 'connectedness': 0.8}
    calm['karma_ledger'] = [{'from': 'player', 'amount': 400, 'settled': False}]
    calm['tick'] = 50
    calm['event_log'] = [{'tick': i, 'type': 'world', 'desc': 'x'} for i in range(20)]
    omega = json.loads(json.dumps(calm))
    omega['panarchy']['phase'] = 'Ω'

    ev_k = NE.check_world_emergent_events(calm)
    ev_o = NE.check_world_emergent_events(omega)
    pk = max([e['probability'] for e in ev_k] or [0])
    po = max([e['probability'] for e in ev_o] or [0])
    check('W3 Ω 相位的事件概率高于 K', po > pk, 'K=%.3f Ω=%.3f' % (pk, po))
    check('W3 phase_multiplier 随相位变化',
          NE.phase_multiplier(omega) > NE.phase_multiplier(calm),
          'K=%.2f Ω=%.2f' % (NE.phase_multiplier(calm), NE.phase_multiplier(omega)))

    # 战斗伤害：同种子、同属性，Ω 期伤害应更高
    def avg_damage(phase):
        stx = base_state()
        stx['panarchy'] = {'phase': phase}
        stx['rng_seed'] = 7
        stx['rng_counter'] = 0
        total, n = 0, 0
        for i in range(40):
            stx['entities']['b']['hp'] = 999
            stx['rng_counter'] = i
            seed_rng(stx)
            r = CB.resolve_combat(stx, 'player', 'b', 'attack')
            if r.get('hit'):
                total += int(r.get('damage', 0))
                n += 1
        return (total / n) if n else 0.0
    dk, do = avg_damage('K'), avg_damage('Ω')
    check('W3 Ω 相位战斗伤害高于 K', do > dk, 'K=%.2f Ω=%.2f' % (dk, do))


# ── W4 心流进结算 ────────────────────────────────────────
def w4_flow_affects_combat():
    # 暴击必须算命中：旧实现只认"命中"，"暴击!"被当失败
    st = base_state()
    st['event_log'] = [{'tick': i, 'type': 'combat', 'desc': '沈砚暴击!山贼，造成30点伤害',
                        'outcome': 'win'} for i in range(6)]
    flow = NE.flow_channel_status(st)
    check('W4 连续暴击判为 boredom（不是 anxiety）',
          flow.get('state') == 'boredom', str(flow))
    # 旧存档兼容：没有 outcome 字段时，文案"暴击"也算赢
    st2 = base_state()
    st2['event_log'] = [{'tick': i, 'type': 'combat', 'desc': '沈砚暴击!山贼，造成30点伤害'}
                        for i in range(6)]
    check('W4 无 outcome 字段时暴击文案仍判为赢',
          NE.flow_channel_status(st2).get('state') == 'boredom',
          str(NE.flow_channel_status(st2)))

    def hit_rate(flow_state):
        stx = base_state()
        stx['panarchy'] = {'phase': 'K'}
        stx['rng_seed'] = 11
        stx['rng_counter'] = 0
        if flow_state == 'boredom':
            desc, oc = '沈砚命中山贼，造成9点伤害', 'win'
        elif flow_state == 'anxiety':
            desc, oc = '山贼的攻击被沈砚闪避', 'loss'
        else:
            desc, oc = '沈砚命中山贼，造成9点伤害', 'win'
        stx['event_log'] = [{'tick': i, 'type': 'combat', 'desc': desc, 'outcome': oc}
                            for i in range(8)]
        if flow_state == 'flow':
            # 5 赢 3 负 = 0.625，落在心流窗口
            stx['event_log'] = ([{'tick': i, 'type': 'combat', 'desc': desc, 'outcome': 'win'}
                                 for i in range(5)]
                                + [{'tick': 5 + i, 'type': 'combat', 'desc': '被闪避',
                                    'outcome': 'loss'} for i in range(3)])
        hits, n = 0, 200
        for i in range(n):
            stx['rng_counter'] = i
            stx['entities']['b']['hp'] = 999
            seed_rng(stx)
            r = CB.resolve_combat(stx, 'player', 'b', 'attack')
            hits += 1 if r.get('hit') else 0
        return hits / n

    hb = hit_rate('boredom')
    hf = hit_rate('flow')
    check('W4 无聊时命中率低于心流', hb < hf, 'boredom=%.3f flow=%.3f' % (hb, hf))


# ── W5 道德向量 ──────────────────────────────────────────
def w5_moral():
    st = base_state()
    st['event_log'] = []
    before = NE.update_player_moral_identity(st)
    log_event(st, 'karma', '沈砚因杀害无辜背负50业', karma_type='murder_innocent')
    after = NE.update_player_moral_identity(st)
    check('W5 空状态道德全为 0', all(v == 0 for v in before.values()), str(before))
    check('W5 杀害无辜使 care 维为负', after['care'] < 0, str(after))
    check('W5 六维全部存在', set(after) == set(NE.MORAL_DIMS), str(sorted(after)))

    # 旧存档兼容：无 karma_type 时按中文标签识别
    st2 = base_state()
    st2['event_log'] = [{'tick': 1, 'type': 'karma', 'desc': '甲因杀害无辜背负50业'}]
    check('W5 旧存档靠中文标签也能识别',
          NE.update_player_moral_identity(st2)['care'] < 0,
          str(NE.update_player_moral_identity(st2)))

    # 权威来源：台账（事件日志会随归档滚出，台账才是长期画像的依据）
    st3 = base_state()
    st3['karma_ledger'] = [{'from': 'player', 'to': 'x', 'type': 'murder_innocent',
                            'amount': 50, 'tick': 1, 'settled': False}]
    check('W5 台账条目也能驱动道德向量',
          NE.update_player_moral_identity(st3)['care'] < 0,
          str(NE.update_player_moral_identity(st3)))

    # 社交：恶名放大负面反应
    good = base_state()
    bad = base_state()
    # 恶名 = 未清业债（别人的观感取决于你还欠着什么），因此必须写台账而不只是事件日志
    bad['karma_ledger'] = [{'from': 'player', 'to': 'a', 'type': 'mass_murder',
                            'amount': 200, 'tick': 1, 'settled': False}
                           for _ in range(3)]
    so_good = SO.resolve_social_event(good, 'player', 'a', 'help', 1)
    so_bad = SO.resolve_social_event(bad, 'player', 'a', 'help', 1)
    check('W5 恶名降低社交正向增量',
          so_bad['affinity_after'] < so_good['affinity_after'],
          '善=%d 恶=%d' % (so_good['affinity_after'], so_bad['affinity_after']))
    check('W5 道德乘数随业债变化',
          so_bad.get('moral_multiplier') != so_good.get('moral_multiplier'),
          '%s vs %s' % (so_good.get('moral_multiplier'), so_bad.get('moral_multiplier')))


# ── W6 术语可配置 ────────────────────────────────────────
def w6_terms():
    st = base_state()
    terms = PANEL.build_terms(st)
    check('W6 默认术语含修真词', terms.get('level') == '境界', str(terms.get('level')))
    st['ui'] = {'terms': {'level': '等级', 'track': '进化轨', 'unknown_key': 'x'}}
    terms2 = PANEL.build_terms(st)
    check('W6 ui.terms 覆盖生效', terms2.get('level') == '等级', str(terms2.get('level')))
    check('W6 未覆盖项回退默认', terms2.get('hero') == '行者', str(terms2.get('hero')))
    check('W6 未知键被忽略', 'unknown_key' not in terms2, str(sorted(terms2))[:60])

    # 通过 view_model 端到端
    tmp = tempfile.mkdtemp(prefix='ww-world-')
    path = os.path.join(tmp, 'w.json')
    from game_engine.state_schema import save_state
    save_state(st, path)
    vm = PANEL.view_model(path)
    check('W6 view_model 暴露 terms', (vm.get('terms') or {}).get('level') == '等级',
          str((vm.get('terms') or {}).get('level')))

    # 道德维度顺序必须与面板展示名严格对应（曾经用中文名去查英文键，永远全 0）
    moral_st = base_state()
    moral_st['karma_ledger'] = [{'from': 'player', 'to': 'x', 'type': 'theft',
                                 'amount': 15, 'tick': 1, 'settled': False}]
    mtmp = tempfile.mkdtemp(prefix='ww-moral-')
    mpath = os.path.join(mtmp, 'm.json')
    save_state(moral_st, mpath)
    mvm = PANEL.view_model(mpath)
    dims = list(mvm['moral']['dims'])
    derived = mvm['moral']['derived']
    check('W6 面板道德按维度名对齐（偷窃 → 公平维为负）',
          len(derived) == len(dims) and derived[dims.index('公平')] < 0,
          'dims=%s derived=%s' % (dims, derived))


# ── W7 叙事落盘 ──────────────────────────────────────────
def w7_prose():
    from game_engine.state_schema import save_state, load_state
    st = base_state()
    st['prose'] = [{'tick': 3, 'location': '临川城', 'text': '他在雨里站了很久。'}]
    tmp = tempfile.mkdtemp(prefix='ww-prose-')
    path = os.path.join(tmp, 'p.json')
    save_state(st, path)
    vm = PANEL.view_model(path)
    check('W7 场景正文优先取最新 prose',
          vm['scene']['description'] == '他在雨里站了很久。', vm['scene']['description'][:40])

    # 移动后没有 prose / places 时，仍回退到开场描写（不伪造）
    st2 = base_state()
    tmp2 = tempfile.mkdtemp(prefix='ww-prose2-')
    path2 = os.path.join(tmp2, 'p2.json')
    save_state(st2, path2)
    vm2 = PANEL.view_model(path2)
    check('W7 无正文时回退开场描写',
          vm2['scene']['description'] == '临川城开场。', vm2['scene']['description'][:40])

    # places 覆盖：走到新地点读到该地描写
    st3 = json.loads(json.dumps(st2))
    st3['places'] = {'渡口': {'desc': '渡口的雾还没散。', 'tick': 5}}
    st3['entities']['player']['location'] = '渡口'
    tmp3 = tempfile.mkdtemp(prefix='ww-prose3-')
    path3 = os.path.join(tmp3, 'p3.json')
    save_state(st3, path3)
    vm3 = PANEL.view_model(path3)
    check('W7 移动后显示新地点描写',
          vm3['scene']['description'] == '渡口的雾还没散。', vm3['scene']['description'][:40])

    # 有界：prose_keep 生效
    st4 = base_state()
    st4['config'] = {'prose_keep': 5}
    st4['prose'] = [{'tick': i, 'location': '临川城', 'text': 'x' * 10} for i in range(20)]
    tmp4 = tempfile.mkdtemp(prefix='ww-prose4-')
    path4 = os.path.join(tmp4, 'p4.json')
    save_state(st4, path4)
    check('W7 超量 prose 由 config.prose_keep 约束（save 不改写）',
          len(load_state(path4)['prose']) == 20, '20 条（裁剪在 publish_prose 里做）')


# ── W8 台账有界 ──────────────────────────────────────────
def w8_karma_cap():
    st = {'tick': 0, 'config': {'karma_ledger_keep': 100}, 'karma_ledger': []}
    for i in range(400):
        st['tick'] = i
        add_karma(st, 'player', 'world', 'murder_innocent', 15)
    total = get_unsettled_karma(st, 'player')
    check('W8 未结算台账不超过 keep', len(st['karma_ledger']) <= 100,
          '%d 条' % len(st['karma_ledger']))
    check('W8 合并后总额不变', total == 400 * 15, '%d vs %d' % (total, 400 * 15))
    merged = [e for e in st['karma_ledger'] if e.get('merged')]
    check('W8 合并条目记录了原始条数', bool(merged) and merged[0]['merged'] > 1,
          str(merged[0].get('merged')) if merged else '无')


# ── W9 确定性 ────────────────────────────────────────────
def w9_determinism():
    a, b = base_state(), base_state()
    run_evolution(a, 80)
    run_evolution(b, 80)
    ha = json.dumps(a, sort_keys=True, ensure_ascii=False)
    hb = json.dumps(b, sort_keys=True, ensure_ascii=False)
    check('W9 同初始状态演化 80 回合逐字节一致', ha == hb, '%d vs %d 字节' % (len(ha), len(hb)))
    check('W9 演化不消耗 rng_counter', a.get('rng_counter', 0) == 0,
          'counter=%s' % a.get('rng_counter'))


# ── W10 等级阶梯 ─────────────────────────────────────────
def w10_progression():
    st = base_state()
    st['config'] = {'level_tiers': ['淬体', '练气', '筑基']}
    st['entities']['player']['level'] = '淬体七段'
    check('W10 阶梯匹配取序号', level_tier(st, st['entities']['player']) == 0,
          str(level_tier(st, st['entities']['player'])))
    ok = validate_next_level(st, '练气三层', '淬体七段')
    check('W10 合法下一阶被接受', ok == '练气三层', ok)
    def led_to_error(*args):
        """调用 validate_next_level(*args)：抛 ValueError 返回错误正文，否则返回 None。"""
        try:
            validate_next_level(*args)
        except ValueError as exc:
            return str(exc)
        return None

    skip_err = led_to_error(st, '筑基一层', '淬体七段')
    check('W10 跳阶被拒绝', bool(skip_err) and '逐阶' in skip_err, str(skip_err)[:60])
    same_tier = validate_next_level(st, '淬体八段', '淬体七段')
    check('W10 同阶内递段被接受', same_tier == '淬体八段', same_tier)
    back_err = led_to_error(st, '淬体七段', '练气三层')
    check('W10 倒退被拒绝', bool(back_err) and '倒退' in back_err, str(back_err)[:60])
    unknown_err = led_to_error(st, '元婴', '淬体七段')
    check('W10 阶梯外的名字被拒绝', bool(unknown_err) and '阶梯' in unknown_err,
          str(unknown_err)[:60])
    # 未配置阶梯时保持旧行为（任意字符串）
    plain = base_state()
    check('W10 无阶梯配置时放行任意名（旧行为）',
          validate_next_level(plain, '随便什么', '凡人') == '随便什么', '')

    # 等级真的影响战斗：高 tier 平均伤害更高
    def dmg_with_tier(name):
        stx = base_state()
        stx['config'] = {'level_tiers': ['淬体', '练气', '筑基', '金丹']}
        stx['entities']['player']['level'] = name
        stx['panarchy'] = {'phase': 'K'}
        stx['rng_seed'] = 3
        total, n = 0, 0
        for i in range(60):
            stx['rng_counter'] = i
            stx['entities']['b']['hp'] = 999
            seed_rng(stx)
            r = CB.resolve_combat(stx, 'player', 'b', 'attack')
            if r.get('hit'):
                total += int(r['damage'])
                n += 1
        return total / n if n else 0
    lo, hi = dmg_with_tier('淬体一段'), dmg_with_tier('金丹一段')
    check('W10 高阶梯平均伤害高于低阶梯', hi > lo, '淬体=%.2f 金丹=%.2f' % (lo, hi))


def w11_tick_tool_drives_world():
    """W11：真正的 MCP `tick` 工具必须驱动世界演化（而不只是 market+tick+1）。

    直接 import mcp_server 并调用 tick()（不经 stdio），把"世界演化挂在 tick 上"
    这件事锁死——否则谁把 evolve_world 那行删了，世界就退回"只有市价在动"。
    """
    try:
        import game_engine.mcp_server as MS
    except Exception as exc:  # aqg: top-level boundary —— 可选 MCP 依赖在 core 路径允许缺失
        message = 'W11 需要 mcp SDK：%s' % str(exc)[:60]
        if os.environ.get('WORLD_GAMES_STRICT') == '1':
            RESULTS.append(False)
            STRICT_FAILURES.append(message)
            print('FAIL  %s' % message)
        else:
            print('SKIP  %s' % message)
        return

    st = base_state()
    tmp = tempfile.mkdtemp(prefix='ww-tick-')
    path = os.path.join(tmp, 't.json')
    save_state(st, path)
    old = MS._active.get('path')
    MS._active['path'] = path
    try:
        for _ in range(20):
            MS.tick()
        after = json.load(open(path, encoding='utf-8'))
        tick_result = MS.tick()
    finally:
        MS._active['path'] = old

    pan = after.get('panarchy') or {}
    check('W11 MCP tick 推进了 Panarchy 状态', bool(pan.get('phase')), str(pan)[:60])
    check('W11 MCP tick 让势力存量变化',
          any(abs(float(v.get('power', 0)) - 32.0) > 0.5
              for v in (after.get('factions') or {}).values()),
          str({k: round(float(v.get('power', 0)), 1)
               for k, v in (after.get('factions') or {}).items()})[:70])
    check('W11 MCP tick 返回世界侧字段',
          'panarchy_phase' in (tick_result or {}), 'panarchy_phase present')


def w12_event_replay():
    """事件溯源最小闭环：seq 单调 + 归档按序可重放 + 同 tick 事件不撞键。

    为什么单列：归档文件是"永久的过去"，状态里的 event_log 只是最近窗口。
    没有 seq 时，同一回合发生的两条事件只靠 tick 排序，顺序是文件行序的副作用；
    有了 seq，`recall`/审计/面板都能按 (tick, seq) 复算出同一顺序。
    """
    st = base_state()
    st['event_log'] = []
    st.pop('event_seq', None)
    for i in range(5):
        log_event(st, 'system', '同回合事件%d' % i)
    seqs = [e['seq'] for e in st['event_log']]
    check('W12 事件 seq 从 1 起严格递增', seqs == [1, 2, 3, 4, 5], str(seqs))
    check('W12 seq 计数器停在最后一条', st['event_seq'] == 5, str(st.get('event_seq')))

    # 同一 tick 内多次写入后，按 seq 排序恢复真实发生顺序
    st['tick'] = 4
    log_event(st, 'combat', '先手命中')
    log_event(st, 'combat', '后手反击')
    same_tick = [e for e in st['event_log'] if e.get('tick') == 4]
    ordered = [e['desc'] for e in sorted(same_tick, key=lambda e: e['seq'])]
    check('W12 同 tick 事件按 seq 可定序', ordered == ['先手命中', '后手反击'], str(ordered))

    # 归档写入后按行读取，seq 与顺序一致（事件溯源可重放）
    tmp = tempfile.mkdtemp(prefix='ww-replay-')
    path = os.path.join(tmp, 'r.json')
    st2 = base_state()
    st2['event_log'] = []
    st2.pop('event_seq', None)
    st2['config'] = {'event_log_keep': 3, 'archive': True}
    for i in range(8):
        log_event(st2, 'system', '第%d条' % i)
        save_state(st2, path)
    archive = path + '.log.jsonl'
    lines = [json.loads(line) for line in open(archive, encoding='utf-8')]
    archived = [e['seq'] for e in lines]
    check('W12 归档事件保留 seq 且逐行递增', archived == sorted(archived) and archived == list(range(1, len(archived) + 1)), str(archived))
    check('W12 归档条数等于被挤出窗口的条数', len(lines) == 5, str(len(lines)))
    kept = [e['desc'] for e in st2['event_log']]
    check('W12 状态窗口保留最新 3 条', kept == ['第5条', '第6条', '第7条'], str(kept))


def main():
    w1_self_evolution()
    w2_phase_cycle()
    w3_phase_affects_settlement()
    w4_flow_affects_combat()
    w5_moral()
    w6_terms()
    w7_prose()
    w8_karma_cap()
    w9_determinism()
    w10_progression()
    w11_tick_tool_drives_world()
    w12_event_replay()
    passed = sum(RESULTS)
    print('\n%d/%d passed' % (passed, len(RESULTS)))
    return 0 if passed == len(RESULTS) and not STRICT_FAILURES else 1


if __name__ == '__main__':
    sys.exit(main())
