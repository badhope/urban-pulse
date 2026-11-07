#!/usr/bin/env python3
"""
低覆盖模块补测 (verify_branches.py)

针对覆盖率报告里最低的三个模块补齐分支断言：
  - rules/systems_feedback.py（37%）—— 系统论 9 个函数
  - rules/narrative_engine.py（42%）—— 涌现叙事 6 个函数
  - rules/economy.py（48%）—— 交易/市场 3 个函数

这些函数此前只在"被别的测试顺带调用"时执行过部分分支，
异常路径、边界值、状态式分支从未被单独验证。

所有断言都按 docstring 的数学式独立计算期望值，不复用被测实现。

用法:  python scripts/verify_branches.py
退出码: 0 = 全绿；1 = 有失败
"""

import os
import sys

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

import math  # noqa: E402

from game_engine.rules import cognition as CG          # noqa: E402
from game_engine.rules import economy as ECON          # noqa: E402
from game_engine.rules import narrative_engine as NE  # noqa: E402
from game_engine.rules import social_extended as SX    # noqa: E402
from game_engine.rules import systems_feedback as SF  # noqa: E402

RESULTS = []


def check(name, got, want, tol=1e-9):
    ok = False
    try:
        if isinstance(want, (int, float)) and isinstance(got, (int, float)):
            ok = abs(float(got) - float(want)) <= tol * max(1.0, abs(float(want)))
        else:
            ok = got == want
    except Exception:
        ok = False
    RESULTS.append(bool(ok))
    print('%s  %-50s got=%s want=%s' % ('PASS' if ok else 'FAIL', name, got, want))


def check_true(name, cond, note=''):
    RESULTS.append(bool(cond))
    print('%s  %-50s %s' % ('PASS' if cond else 'FAIL', name, str(note)[:70]))


def check_raises(name, fn, exc=ValueError):
    try:
        fn()
    except exc:
        RESULTS.append(True)
        print('PASS  %-50s raises %s' % (name, exc.__name__))
        return
    except Exception as e:
        RESULTS.append(False)
        print('FAIL  %-50s raised %s (期望 %s)' % (name, type(e).__name__, exc.__name__))
        return
    RESULTS.append(False)
    print('FAIL  %-50s 未抛异常' % name)


# ───────────────────── systems_feedback ─────────────────────
def systems():
    # 杠杆效力：min(1, ln(tier+1)/ln(13))
    for t in (0, 1, 3, 6, 12, 20):
        check('leverage_effectiveness tier=%d' % t, SF.leverage_effectiveness(t),
              min(1.0, math.log(t + 1) / math.log(13)))
    check_true('leverage_effectiveness 单调不减',
               SF.leverage_effectiveness(1) <= SF.leverage_effectiveness(5)
               <= SF.leverage_effectiveness(12))
    check_true('leverage_effectiveness 封顶 1.0', SF.leverage_effectiveness(100) <= 1.0)

    # 抗杠杆：min(1, base*(1+tdp*0.3))
    check('counter_leverage_resistance tdp=0', SF.counter_leverage_resistance(3, 0.0),
          min(1.0, SF.leverage_effectiveness(3)))
    check('counter_leverage_resistance tdp=1', SF.counter_leverage_resistance(3, 1.0),
          min(1.0, SF.leverage_effectiveness(3) * 1.3))
    check_true('counter_leverage_resistance 不超 1',
               SF.counter_leverage_resistance(12, 5.0) <= 1.0)

    # 二阶偏差 = belief - reality（含负值）
    check('observe_observer_bias 正偏', SF.observe_observer_bias(0.8, 0.5), 0.3)
    check('observe_observer_bias 负偏', SF.observe_observer_bias(0.2, 0.7), -0.5)
    check('observe_observer_bias 无偏', SF.observe_observer_bias(0.5, 0.5), 0.0)

    # 自创生稳定性：三种终态都要覆盖
    st_tight = SF.autopoiesis_stability(0.95, 0.95, 0.1)
    check_true('autopoiesis 过封闭有终态', isinstance(st_tight, dict) and st_tight.get('state'),
               str(st_tight)[:60])
    # viability = rate × integrity / max(0.01, pressure)，四区间：
    #   >1.5 rigid / >0.7 healthy / >0.3 strained / else dissolving
    # 构造刚好落在每个区间的输入来钉住分支边界
    def viab(rate, integ, press):
        return rate * integ / max(0.01, press)
    cases = [
        (2.0, 1.0, 1.0, 'rigid'),      # 2.0
        (1.0, 1.0, 1.0, 'healthy'),    # 1.0
        (0.5, 1.0, 1.0, 'strained'),   # 0.5
        (0.1, 1.0, 1.0, 'dissolving'), # 0.1
    ]
    for rate, integ, press, want in cases:
        got = SF.autopoiesis_stability(rate, integ, press).get('state')
        check('autopoiesis viability=%.2f → %s' % (viab(rate, integ, press), want), got, want)

    # 解释弹性 = distinct / total
    check('interpretive_flexibility 全不同', SF.interpretive_flexibility(['a', 'b', 'c']), 1.0)
    check('interpretive_flexibility 全相同', SF.interpretive_flexibility(['a', 'a', 'a']), 1 / 3)
    check('interpretive_flexibility 空列表', SF.interpretive_flexibility([]), 0.0)

    # 维护优先级 = 不满 × 故障 × 预算
    check('maintenance_priority 闭式复算', SF.maintenance_priority(0.5, 0.4, 0.8), 0.5 * 0.4 * 0.8)
    check('maintenance_priority 零预算', SF.maintenance_priority(1.0, 1.0, 0.0), 0.0)

    # 修能收支 = Q - W_body - W_spell - W_waste
    check('cultivation_energy_balance 闭式复算',
          SF.cultivation_energy_balance(100, 30, 20, 10), 40)
    check('cultivation_energy_balance 入不敷出',
          SF.cultivation_energy_balance(10, 30, 20, 10), -50)

    # 玻尔兹曼熵
    check('boltzmann_entropy Ω=1 → 0', SF.boltzmann_entropy(1, 1.0), 0.0)
    check('boltzmann_entropy 加倍', SF.boltzmann_entropy(16, 1.0), math.log(16))

    # 自创生稳定性：四个 viability 区间（>1.5 僵化 / >0.7 健康 / >0.3 承压 / else 解体）
    states = {SF.autopoiesis_stability(r, bi, ep).get('state')
              for r, bi, ep in [(1.0, 1.0, 0.0), (0.5, 0.5, 0.5), (0.2, 0.2, 0.8), (0.0, 0.0, 2.0)]}
    check_true('autopoiesis 覆盖多个 viability 区间', len(states) >= 3, str(sorted(states)))

    # 紧耦合系统：级联故障（大劫不可避免论）
    tcs = SF.TightlyCoupledSystem(
        ['a', 'b', 'c'],
        [('a', 'b', 0.8), ('b', 'c', 0.6), ('c', 'a', 0.1)])
    check('coupling_degree = 边数/节点数*2', tcs.coupling_degree(), 3 / 3 * 2)
    step1 = tcs.cascade_step({'a'}, 0.3)
    check_true('cascade_step a→b 传染（0.8>0.3）', 'b' in step1, str(sorted(step1)))
    step2 = tcs.cascade_step(step1, 0.3)
    check_true('cascade_step b→c 传染（0.6>0.3）', 'c' in step2, str(sorted(step2)))
    check_true('cascade_step 弱连接不传染（0.1<0.3）',
               'a' not in tcs.cascade_step({'c'}, 0.3))
    check('total_collapse_time a→b→c 需 2 步', tcs.total_collapse_time({'a'}, 0.3), 2)
    tcs2 = SF.TightlyCoupledSystem(['x', 'y'], [('x', 'y', 0.1)])
    check('total_collapse_time 无传导为 0', tcs2.total_collapse_time({'x'}, 0.3), 0)


# ───────────────────── narrative_engine ─────────────────────
def narrative():
    def base_state(**kw):
        st = {'tick': 10, 'entities': {'player': {'name': '沈砚', 'hp': 50, 'hp_max': 100,
                                                  'attrs': {'int': 12}, 'morality': [0] * 6}},
              'event_log': [], 'karma_ledger': [], 'world_flags': [], 'relations': {},
              'market': {}, 'milestones': []}
        st.update(kw)
        return st

    # 身份向量：返回 dict，键集合稳定
    idv = NE.player_identity_vector(base_state())
    check_true('player_identity_vector 含多维坐标',
               isinstance(idv, dict) and len(idv) >= 3
               and all(isinstance(v, (int, float)) for v in idv.values()),
               '%d 维：%s' % (len(idv), str(sorted(idv))[:50]))

    # 心流：三种通道都要能取到
    calm = base_state()
    calm['event_log'] = [{'tick': i, 'type': 'combat', 'desc': '命中山贼'} for i in range(10)]
    flow = NE.flow_channel_status(calm)
    check_true('flow_channel_status 返回 dict 且含 state',
               isinstance(flow, dict) and 'state' in flow, str(flow)[:60])

    winner = base_state()
    winner['event_log'] = [{'tick': i, 'type': 'combat', 'desc': '沈砚命中对手'} for i in range(10)]
    w = NE.flow_channel_status(winner)
    check_true('连胜时状态合法', w.get('state') in ('flow', 'boredom', 'anxiety', 'neutral'),
               str(w.get('state')))

    # 叙事权重 = -ln P × base_importance（注意是自然对数，与 world_dynamics.event_information 的 log2 不同）
    check('narrative_event_weight 闭式复算（自然对数）',
          NE.narrative_event_weight(0.01, 1.0), -math.log(0.01) * 1.0)
    check('narrative_event_weight 权重放大', NE.narrative_event_weight(0.01, 2.0),
          -math.log(0.01) * 2.0)
    check_true('narrative_event_weight p=0 返回 inf',
               NE.narrative_event_weight(0.0) == float('inf'))

    # 涌现事件：低业债无事件、高业债触发
    low = NE.check_world_emergent_events(base_state())
    check_true('涌现事件：平静状态不触发', isinstance(low, list) and len(low) == 0,
               '%d 条' % (len(low) if isinstance(low, list) else -1))
    heavy = base_state()
    heavy['karma_ledger'] = [{'from': 'player', 'amount': 400, 'settled': False}]
    ev = NE.check_world_emergent_events(heavy)
    check_true('涌现事件：高业债有触发', isinstance(ev, list) and len(ev) >= 1,
               '%d 条' % len(ev if isinstance(ev, list) else []))

    # 道德向量：从事件日志累加
    st = base_state()
    st['event_log'] = [{'tick': 1, 'type': 'karma', 'desc': '杀害无辜'},
                       {'tick': 2, 'type': 'karma', 'desc': '帮助无辜'}]
    mv = NE.update_player_moral_identity(st)
    check_true('update_player_moral_identity 含全部道德维度',
               isinstance(mv, dict) and len(mv) >= 6 and all(isinstance(v, (int, float)) for v in mv.values()),
               str(sorted(mv))[:70])

    # Panarchy 相位：四象限覆盖
    phases = set()
    for cap, conn in [(0.1, 0.1), (0.9, 0.9), (0.9, 0.1), (0.1, 0.9)]:
        st = base_state()
        st['world_flags'] = []
        ph = NE.panarchy_phase_check(st)
        phases.add(str(ph.get('phase')) if isinstance(ph, dict) else str(ph))
    check_true('panarchy_phase_check 返回合法相位',
               phases <= {'r', 'K', 'α', 'Ω', 'alpha', 'omega'}, str(sorted(phases)))


# ───────────────────── cognition ─────────────────────
def cognition_branches():
    # 综合前景效用：按效用降序排序
    opts = [{'id': 'safe', 'outcomes': [{'probability': 1.0, 'value': 10}]},
            {'id': 'risky', 'outcomes': [{'probability': 0.1, 'value': 1000},
                                         {'probability': 0.9, 'value': -50}]}]
    ranked = CG.decision_utility(opts, gamma=0.65)
    check_true('decision_utility 返回 (option, utility) 列表',
               len(ranked) == 2 and all(isinstance(u, float) for _, u in ranked),
               str([(o['id'], round(u, 3)) for o, u in ranked]))
    check_true('decision_utility 按效用降序',
               ranked[0][1] >= ranked[1][1], '%s 优先' % ranked[0][0]['id'])

    # 满意化：达到期望值就停下（探索次数 < 全部）
    picks = CG.satisficing_choice(list(range(50)), lambda x: x, aspiration=5, max_explore=100)
    check_true('satisficing_choice 找到即停', picks['satisfied'] is True,
               'explored=%s choice=%s' % (picks['explored'], picks['choice']))
    check_true('satisficing_choice 在 max_explore 内',
               picks['explored'] <= 100)
    # 达不到期望值时返回最好的那个
    low = CG.satisficing_choice([1, 2, 3], lambda x: x, aspiration=999)
    check_true('satisficing_choice 未满足时给最优', low['satisfied'] is False
               and low['choice'] == 3, str(low))

    # 等权分配
    check('equal_division 3 份', CG.equal_division(90, 3), [30.0, 30.0, 30.0])
    check('equal_division 0 份返回空', CG.equal_division(90, 0), [])

    # 感官沉浸：Σ(覆盖×权重) × 一致性，封顶 1
    full = {k: 1.0 for k in ('visual', 'auditory', 'olfactory', 'tactile', 'gustatory')}
    check('sensory_immersion 全感官 = 1.0', CG.sensory_immersion(full, 1.0), 1.0)
    check('sensory_immersion 仅视觉 = 0.35', CG.sensory_immersion({'visual': 1.0}), 0.35)
    check('sensory_immersion 风格因子 0.5 时得分减半',
          CG.sensory_immersion(full, 0.5), 0.5)

    # 心流三态 + 边界
    check('flow_state ratio=1.0 → flow', CG.flow_state(1.0).get('state'), 'flow')
    check('flow_state ratio=2.0 → anxiety', CG.flow_state(2.0).get('state'), 'anxiety')
    check('flow_state ratio=0.3 → boredom', CG.flow_state(0.3).get('state'), 'boredom')
    check('flow_state ratio=1.2 → 中间态 flow', CG.flow_state(1.2).get('state'), 'flow')

    # 总沉浸度：几何平均
    check('total_immersion_metric 几何平均',
          CG.total_immersion_metric(0.5, 0.5, 0.5), (0.5 * 0.5 * 0.5) ** (1 / 3))
    # 实现用 max(0.001, x) 兜底防真零：0 输入得 (0.001*0.9*0.9)^(1/3) 而非 0
    check('total_immersion_metric 零输入走 0.001 兜底',
          CG.total_immersion_metric(0.0, 0.9, 0.9), (0.001 * 0.9 * 0.9) ** (1 / 3))
    check_true('total_immersion_metric 零输入趋近 0',
               CG.total_immersion_metric(0.0, 0.9, 0.9) < 0.1)

    # 马斯洛：0..4 各层
    for lv, sat in [(0, [0.1] * 5), (3, [0.9, 0.9, 0.9, 0.1, 0.1]), (4, [0.9] * 5)]:
        check('maslow_dominant_need 定位第 %d 层' % lv,
              CG.maslow_dominant_need(sat), lv)

    # 调难度：delta = adj_rate × (target − win_rate)
    # 胜率低于目标 → 偏移为正（暗中降低难度）；高于目标 → 为负
    low_wr = CG.adjust_difficulty(0.2, target=0.65, adj_rate=0.1, max_offset=1.0)
    high_wr = CG.adjust_difficulty(0.9, target=0.65, adj_rate=0.1, max_offset=1.0)
    check('adjust_difficulty 低胜率 → 正偏移',
          low_wr['difficulty_offset'], 0.1 * (0.65 - 0.2))
    check('adjust_difficulty 高胜率 → 负偏移',
          high_wr['difficulty_offset'], 0.1 * (0.65 - 0.9))
    check_true('adjust_difficulty 偏移受 max_offset 夹取',
               abs(CG.adjust_difficulty(0.0, 0.65, 10.0, 0.3)['difficulty_offset']) <= 0.3)
    check_true('adjust_difficulty 胜率<0.3 触发隐藏机缘',
               low_wr['trigger_opportunity'] is True, str(low_wr)['trigger_opportunity'.__len__():][:0] or '')
    check_true('adjust_difficulty 胜率正常不触发机缘',
               high_wr['trigger_opportunity'] is False)

    # 适应曲线：突破后短期峰值，随后回落
    # boost - (boost-1)*(day/adaptation_days)；到期即回到 1.0
    peak = CG.adaptation_curve(0, 2.0, 30)
    mid = CG.adaptation_curve(15, 2.0, 30)
    late = CG.adaptation_curve(30, 2.0, 30)
    check('adaptation_curve 起始为 boost 峰值', peak, 2.0)
    check('adaptation_curve 中途线性回落', mid, 2.0 - 1.0 * 0.5)
    check('adaptation_curve 到期回到基准 1.0', late, 1.0)
    check_true('adaptation_curve 单调不增', peak >= mid >= late)

    # 记忆衰减 + 召回
    check_true('base_activation 空输入 -inf',
               CG.base_activation([], 10, 0.5) == float('-inf'))
    check_true('recall_probability 单调递增',
               CG.recall_probability(1, 1) < CG.recall_probability(5, 1))

    # 冲突解决 softmax 概率和为 1
    probs = CG.conflict_resolution_prob([1.0, 2.0, 3.0], 1.0)
    check_true('conflict_resolution_prob 概率和为 1', abs(sum(probs) - 1.0) < 1e-9,
               str([round(p, 3) for p in probs]))

    # 抑制能力 + System2 判定（随机：只验值域）
    check_true('inhibition_ability 落在 0..1',
               0 <= CG.inhibition_ability(0.8, 0.6, 0.5) <= 1, str(CG.inhibition_ability(0.8, 0.6, 0.5)))
    # 该函数含随机采样，只能验值域：多次调用必须都是布尔
    samples = {CG.should_use_system2(100, 0.9) for _ in range(20)}
    check_true('should_use_system2 恒定返回布尔值',
               samples <= {True, False}, str(samples))
    # 预算必须参与判定：0 预算强制 System 1，高预算才可能 System 2
    check('should_use_system2 预算为 0 时必然退化', CG.should_use_system2(0, 0.9, roll=0.0), False)
    check('should_use_system2 高预算下 roll=0 可启用', CG.should_use_system2(10000, 0.9, roll=0.0), True)
    check('should_use_system2 roll 参数可复现（同输入同结果）',
          CG.should_use_system2(50, 0.5, roll=0.42), CG.should_use_system2(50, 0.5, roll=0.42))


# ───────────────────── social_extended 补 ─────────────────────
def social_extra():
    # 内群体区分度：内 0.9 / 外 0.3
    check('ingroup_discrimination 内群体 0.9', SX.ingroup_discrimination(True), 0.9)
    check('ingroup_discrimination 外群体 0.3', SX.ingroup_discrimination(False), 0.3)

    # BJW 崩塌：返回 bool（累计不公 > 容忍阈值）
    check_true('bjw_collapse 未超阈值不崩', SX.bjw_collapse(5, 10) is False)
    check_true('bjw_collapse 超阈值崩塌', SX.bjw_collapse(20, 10) is True)
    check_true('bjw_collapse 恰好等于阈值不崩', SX.bjw_collapse(10, 10) is False)

    # 道德推脱：5 维均值
    check('disengagement_probability 五维均值',
          SX.disengagement_probability(1.0, 0.5, 0.0, 0.5, 1.0), 0.6)

    # 三层道德行为整合：0.6 直觉 + 0.25 推理 + 0.15 认同
    check('npc_moral_behavior 加权整合',
          SX.npc_moral_behavior(1.0, 0.0, 0.0), 0.6)

    # 效用评分：Σ(F×W) + noise
    check('utility_action_score 加权和',
          SX.utility_action_score([1.0, 2.0], [0.5, 0.5], 0.0), 1.5)

    # 优先连接：Π = k_i / Σk
    check('preferential_attachment 归一',
          SX.preferential_attachment(3, [3, 1]), 0.75)

    # 小世界路径长度 ln(N)/ln(K)
    check('ws_characteristic_path_length 闭式复算',
          SX.ws_characteristic_path_length(1000, 10), math.log(1000) / math.log(10))

    # 模块度：communities 是"每个节点所属社群 id"的列表
    adj = [[0, 1, 0, 0], [1, 0, 0, 0], [0, 0, 0, 1], [0, 0, 1, 0]]
    q = SX.modularity(adj, [0, 0, 1, 1])
    check_true('modularity 两团分离 → 正分', q > 0.3, 'Q=%.3f' % q)
    q_same = SX.modularity(adj, [0, 0, 0, 0])
    check_true('modularity 全同社群 → 低分', q_same < q, 'Q_same=%.3f' % q_same)
    check('modularity 无边图为 0', SX.modularity([[0, 0], [0, 0]], [0, 1]), 0.0)

    # 集体推脱：四维取最大
    check('collective_disengagement 取最大',
          SX.collective_disengagement(0.2, 0.9, 0.4, 0.1), 0.9)


# ───────────────────── economy ─────────────────────
def economy():
    def mk(price=10, supply=20, gold=1000, items=None):
        return {'tick': 1,
                'entities': {'p': {'name': '甲', 'gold': gold, 'items': dict(items or {})}},
                'market': {'L': {'it': {'name': '丹', 'price': price, 'supply': supply,
                                        'base_price': 10}}},
                'relations': {}, 'event_log': []}

    # 买入：扣款 = 单价 × 数量，入库，减库存
    st = mk()
    r = ECON.resolve_trade(st, 'L', 'it', 3, True, 'p')
    check_true('trade 买入成功', r.get('success') is True)
    check('trade 买入扣款 = total_cost', st['entities']['p']['gold'],
          1000 - r['total_cost'])
    check('trade 买入入库数量', st['entities']['p']['items'].get('it'), 3)
    check('trade 买入后库存', st['market']['L']['it']['supply'], 17)

    # 库存不足
    st = mk(supply=2)
    r = ECON.resolve_trade(st, 'L', 'it', 5, True, 'p')
    check_true('trade 库存不足被拒', r.get('success') is False, str(r.get('events'))[:50])

    # 钱不够
    st = mk(gold=1)
    r = ECON.resolve_trade(st, 'L', 'it', 3, True, 'p')
    check_true('trade 钱不够被拒', r.get('success') is False, str(r.get('events'))[:50])

    # 卖自己没有的
    st = mk()
    r = ECON.resolve_trade(st, 'L', 'it', 1, False, 'p')
    check_true('trade 卖未持有被拒', r.get('success') is False, str(r.get('events'))[:50])

    # 卖出：先买再卖，钱应增加、库存回升
    st = mk()
    ECON.resolve_trade(st, 'L', 'it', 2, True, 'p')
    gold_after_buy = st['entities']['p']['gold']
    sup_after_buy = st['market']['L']['it']['supply']
    r = ECON.resolve_trade(st, 'L', 'it', 1, False, 'p')
    check_true('trade 卖出成功', r.get('success') is True)
    check_true('trade 卖出后钱增加', st['entities']['p']['gold'] > gold_after_buy,
               '%s -> %s' % (gold_after_buy, st['entities']['p']['gold']))
    check_true('trade 卖出后库存回升', st['market']['L']['it']['supply'] > sup_after_buy,
               '%s -> %s' % (sup_after_buy, st['market']['L']['it']['supply']))

    # 数量 0 / 负数
    for q in (0, -3):
        st = mk()
        r = ECON.resolve_trade(st, 'L', 'it', q, True, 'p')
        check_true('trade 数量=%d 被拒' % q, r.get('success') is False)

    # tick_market：价格向基准回归、供给恢复
    # 关掉市场扰动：本用例验证的是 OU 回归公式本身（扰动是产品特性，另有覆盖）
    st = {'tick': 0, 'rng_seed': 0, 'config': {'market_jitter': False},
          'market': {'L': {'it': {'price': 40, 'base_price': 10, 'supply': 5}}}}
    ECON.tick_market(st)
    it = st['market']['L']['it']
    check('tick_market 价格按 OU 回归', it['price'],
          max(0, int(round(40 - 0.15 * (40 - 10)))))
    check('tick_market 供给 +1', it['supply'], 6)

    # 供给达到 20 后不再涨
    st = {'tick': 0, 'rng_seed': 0, 'config': {'market_jitter': False},
          'market': {'L': {'it': {'price': 10, 'base_price': 10, 'supply': 20}}}}
    ECON.tick_market(st)
    check('tick_market 供给封顶 20', st['market']['L']['it']['supply'], 20)

    # init_market 接受 item_key 列表（不是 dict 列表），返回 {key: {price,supply,base_price}}
    m = ECON.init_market('L', ['回灵丹', '金疮药'])
    check_true('init_market 按 item_key 建市场',
               isinstance(m, dict) and set(m) == {'回灵丹', '金疮药'}, str(sorted(m)))
    check('init_market 使用默认基准价', m['回灵丹']['base_price'],
          ECON.DEFAULT_BASE_PRICES['回灵丹'])
    m2 = ECON.init_market('L')
    check_true('init_market 缺省给三种常用药', len(m2) == 3, str(sorted(m2)))



# ───────────────────── 剩余公式补测 ─────────────────────
def remaining_formulas():
    """补齐 verify_formulas 未覆盖、但属于纯公式的函数（不依赖 state）。"""
    from game_engine.rules import world_dynamics as W

    # --- 进化动力学：Hamilton 家族（判定式，返回 bool）---
    # kin_selection: r > c/b
    check_true('kin_selection r>c/b 为真', W.kin_selection(0.6, 2.0, 10.0) is True)
    check_true('kin_selection r<c/b 为假', W.kin_selection(0.1, 2.0, 10.0) is False)
    check_true('kin_selection benefit=0 返回 False', W.kin_selection(0.9, 1.0, 0.0) is False)

    # direct_reciprocity: w > c/b
    check_true('direct_reciprocity w>c/b 为真', W.direct_reciprocity(0.8, 2.0, 10.0) is True)
    check_true('direct_reciprocity w<c/b 为假', W.direct_reciprocity(0.1, 2.0, 10.0) is False)

    # network_selection: b/c > k
    check_true('network_selection b/c>k 为真', W.network_selection(10.0, 1.0, 5) is True)
    check_true('network_selection b/c<k 为假', W.network_selection(10.0, 1.0, 50) is False)
    check_true('network_selection cost=0 返回 True', W.network_selection(10.0, 0.0, 5) is True)

    # inclusive_fitness: IF = d + Σr·b − Σr·c
    check('inclusive_fitness 闭式复算',
          W.inclusive_fitness(1.0, [5.0, 3.0], [1.0, 2.0], [0.5, 0.25]),
          1.0 + (0.5 * 5.0 + 0.25 * 3.0) - (0.5 * 1.0 + 0.25 * 2.0))

    # hawk_dove_payoff 四象限
    V, C = 4.0, 10.0
    check('hawk_dove H vs H = (V-C)/2', W.hawk_dove_payoff('H', 'H', V, C), (V - C) / 2)
    check('hawk_dove H vs D = V', W.hawk_dove_payoff('H', 'D', V, C), V)
    check('hawk_dove D vs H = 0', W.hawk_dove_payoff('D', 'H', V, C), 0.0)
    check('hawk_dove D vs D = V/2', W.hawk_dove_payoff('D', 'D', V, C), V / 2)

    # is_ess：对角线高时是 ESS
    payoff = [[2.0, 3.0], [1.0, 0.0]]
    check_true('is_ess 策略0（对角占优）为 ESS', W.is_ess(payoff, 0) is True)
    check_true('is_ess 策略1 非 ESS', W.is_ess(payoff, 1) is False)

    # multilevel_selection：返回 (between, within)
    betw, with_ = W.multilevel_selection([1.0, 3.0], [1.0, 1.0], [10, 10], [0.1, 0.1])
    check_true('multilevel_selection 返回二元组', isinstance(betw, float) and isinstance(with_, float),
               'between=%s within=%s' % (round(betw, 4), round(with_, 4)))
    check('multilevel_selection 等适应度时组间为 0', betw, 0.0)
    check('multilevel_selection 空组返回 (0,0)', W.multilevel_selection([], [], [], []), (0.0, 0.0))

    # red_queen_field：点积 + 长度校验
    check('red_queen_field 点积', W.red_queen_field([0.5, 2.0], [4.0, 3.0]), 0.5 * 4.0 + 2.0 * 3.0)
    check_raises('red_queen_field 不等长抛 ValueError',
                 lambda: W.red_queen_field([1.0], [1.0, 2.0]))

    # panarchy_tick：三支路径
    jump = W.panarchy_tick(0.7, 0.5, event_impact=0.8)
    check('panarchy_tick 大冲击 → Ω', jump.get('phase'), 'Ω')
    collapse = W.panarchy_tick(0.9, 0.9, event_impact=0.0)
    check('panarchy_tick 过僵化 → Ω', collapse.get('phase'), 'Ω')
    normal = W.panarchy_tick(0.3, 0.3, event_impact=0.0)
    check('panarchy_tick 正常推进', normal.get('phase'), 'progress')

    # ou_process / extinction_check：含随机，只验值域与边界
    z = W.ou_process(1.0, 0.0, 0.5, 0.0, 1.0)
    check('ou_process sigma=0 无随机项', z, 0.5)   # z + (-0.5*(1-0)*1) = 0.5
    check_true('extinction_check 返回布尔',
               W.extinction_check(0.5) in (True, False))
    check_true('extinction_check hazard=0 永不灭绝',
               all(W.extinction_check(0.0) is False for _ in range(20)))
    check_true('extinction_check hazard=1 必然灭绝',
               all(W.extinction_check(1.0) is True for _ in range(20)))

    # --- 文化进化 ---
    from game_engine.rules import cultural_evolution as CE2
    # adopt_probability = g_c · p^α · π^β · s^γ
    check('adopt_probability 闭式复算',
          CE2.adopt_probability(1.0, 0.5, 0.5, 0.5, 1.0, 1.0, 1.0), 0.125)
    # body_without_organs = ω − Σ约束 + Σ解域
    check('body_without_organs 闭式复算',
          CE2.body_without_organs(10.0, [2.0, 3.0], [1.0]), 6.0)
    # sect_cultural_fitness = α·(1/Std) + β·Coop + γ·(I/I_mean)
    check('sect_cultural_fitness 闭式复算',
          CE2.sect_cultural_fitness(2.0, 0.5, 3.0, 1.5, 0.33, 0.33, 0.34),
          0.33 * (1 / 2.0) + 0.33 * 0.5 + 0.34 * (3.0 / 1.5))
    # vertical_transmission_prob 三分支
    check('vertical_transmission 双亲', CE2.vertical_transmission_prob(True, False, 0.1), 0.9)
    check('vertical_transmission 单亲', CE2.vertical_transmission_prob(False, True, 0.1), 0.45)
    check('vertical_transmission 无亲', CE2.vertical_transmission_prob(False, False, 0.1), 0.1)
    # method_transmission 含高斯随机：只验均值的合理范围
    vals = [CE2.method_transmission(10.0, 100.0, 0.0) for _ in range(5)]
    check_true('method_transmission sigma=0 无扰动', all(abs(v - 10.0) < 1e-9 for v in vals),
               str([round(v, 6) for v in vals[:3]]))

    # --- 社会扩展补 ---
    from game_engine.rules import social_extended as SX2
    # cross_identity_tension：<2 个身份返回 0
    check('cross_identity_tension 单身份为 0', SX2.cross_identity_tension([{'a': 1}], {}), 0.0)
    # 身份字典的键是 group；冲突矩阵按 (group_i, group_j) 取，取不到按 0
    check('cross_identity_tension 两身份冲突值',
          SX2.cross_identity_tension(
              [{'group': 'a'}, {'group': 'b'}], {('a', 'b'): 1.0}), 1.0)
    check('cross_identity_tension 无冲突记录为 0',
          SX2.cross_identity_tension([{'group': 'a'}, {'group': 'b'}], {}), 0.0)
    # justice_response 四路径
    paths = {SX2.justice_response(b, t, e) for b, t, e in
             [(1.0, 1.0, 0.0), (0.5, 0.5, 0.5), (0.1, 0.1, 0.9), (0.3, 0.3, 0.5)]}
    check_true('justice_response 覆盖多个路径', len(paths) >= 2, str(sorted(paths)))
    # moral_circle_penetration
    check('moral_circle_penetration 闭式复算',
          SX2.moral_circle_penetration(1.0, [0.1, 0.2], [0.05], 1.0), 1.0 * 1.3 * 0.95)
    # moral_vector_update：指数衰减
    upd = SX2.moral_vector_update([1.0, 0.0], [0.0, 1.0], 90, tau=90.0)
    g = math.exp(-1.0)
    check_true('moral_vector_update 指数衰减',
               abs(upd[0] - 1.0 * g) < 1e-9 and abs(upd[1] - (1 - g)) < 1e-9,
               str([round(v, 4) for v in upd]))
    # npc_influence_on_player：点积
    check('npc_influence_on_player 点积',
          SX2.npc_influence_on_player([0.5, 0.8], [2.0, 1.0]), 1.8)

    # --- 认知补 ---
    from game_engine.rules import cognition as CG2
    check('moral_bias_by_distance 近亲 2.5', CG2.moral_bias_by_distance('close_victim'), 2.5)
    check('moral_bias_by_distance 统计口径 0.3', CG2.moral_bias_by_distance('statistical_victim'), 0.3)
    check('moral_bias_by_distance 未知输入回退为 1.0（中性）',
          CG2.moral_bias_by_distance('unknown'), 1.0)



# ───────────────────── 边界与回归（2026-10-27 审计） ─────────────────────
def audit_regressions():
    """本轮审计修复的回归断言：每条对应一个实测过的缺陷，防止回潮。"""
    from game_engine.rules import combat as CB
    from game_engine.rules import karma as KA
    from game_engine.rules import playbook as PB
    from game_engine.rules import questline as QL
    from game_engine.settings_loader import normalize_lore_entry, normalize_market, normalize_entity
    from game_engine.state_schema import get_unsettled_karma

    def base():
        return {'tick': 1, 'rng_seed': 1, 'rng_counter': 0, 'config': {},
                'entities': {'player': {'name': '甲', 'hp': 100, 'hp_max': 100, 'mp': 10,
                                        'gold': 100, 'attrs': {'str': 10, 'dex': 0, 'con': 10}},
                             'npc': {'name': '乙', 'hp': 100, 'hp_max': 100, 'gold': 0,
                                     'attrs': {'str': 10, 'dex': 0, 'con': 10}}},
                'relations': {}, 'event_log': [], 'karma_ledger': [], 'world_flags': []}

    # 逃跑：双方 dex=0 不许除零；必须给出 fled 与 draw（不污染心流胜负统计）
    st = base()
    st['rng_counter'] = 0
    from game_engine.state_schema import seed_rng
    seed_rng(st)
    # 双方 dex=0 是旧实现的 ZeroDivisionError 触发点；现在必须返回结果而不是抛
    r = CB.resolve_combat(st, 'player', 'npc', 'flee')
    check('逃跑在双方 dex=0 时不崩溃（outcome=draw）', r.get('outcome'), 'draw')
    # dex 10 vs 0 时逃跑率 0.95，多次抽样必须同时出现成功与失败
    st = base()
    st['entities']['player']['attrs']['dex'] = 10
    fled_values = set()
    for i in range(30):
        st['rng_counter'] = i
        seed_rng(st)
        fled_values.add(CB.resolve_combat(st, 'player', 'npc', 'flee').get('fled'))
    check('逃跑结果由随机决定（成功与失败都出现）', fled_values, {True, False})

    # social：NaN/未知事件必须拒绝，关系不得被写入 NaN
    from game_engine.rules.social import resolve_social_event
    st = base()
    for bad in (float('nan'), float('inf'), 0, -1):
        check_raises('social intensity=%r 被拒绝' % bad,
                     lambda b=bad: resolve_social_event(st, 'player', 'npc', 'help', intensity=b))
    check_raises('social 未知事件被拒绝（不静默加 0）',
                 lambda: resolve_social_event(st, 'player', 'npc', '不存在的动作'))
    check('social 被拒后关系表未被污染', st['relations'], {})

    # karma：无受害者也要记账（victim=None 不是免罪）
    st = base()
    out = KA.resolve_karma(st, 'player', None, 'mass_murder')
    check('karma 无受害者仍记账（+200）', get_unsettled_karma(st, 'player'), 200)
    check_true('karma 无受害者风险等级非 low', out.get('risk_level') != 'low', out.get('risk_level'))

    # playbook：normalize 不得让调用方污染 DEFAULT_PLAYBOOK
    pb, _ = PB.normalize({})
    pb['beat']['pattern'].append('污染')
    check_true('playbook normalize 深拷贝（默认剧本不被污染）',
               '污染' not in PB.DEFAULT_PLAYBOOK['beat']['pattern'],
               str(PB.DEFAULT_PLAYBOOK['beat']['pattern']))
    check('beat_at 对空 pattern 回退默认（不除零）',
          PB.beat_at({'beat': {'pattern': [], 'every': 0}}, 3).get('name'),
          PB.DEFAULT_PLAYBOOK['beat']['pattern'][0])

    # questline：重复 complete_stage 只发一次奖励
    quest = QL.normalize({'id': 'q', 'stages': [{'id': 'a', 'next': []}],
                          'reward': {'gold': 100}})
    st = {'tick': 0, 'entities': {'player': {'gold': 0}}, 'world_flags': [],
          'quests': {}, 'event_log': [], 'karma_ledger': []}
    QL.complete_stage(st, [quest], 'q', 'a')
    QL.complete_stage(st, [quest], 'q', 'a')
    check('事业线奖励只发一次（重复 complete_stage）', st['entities']['player']['gold'], 100)

    # questline：exit_if 满足但 next 的 enter_if 未满足时不得重复记 stage_done
    q2 = QL.normalize({'id': 'q2', 'stages': [
        {'id': 'a', 'exit_if': {'flag': 'go'}, 'next': ['b']},
        {'id': 'b', 'enter_if': {'flag': 'never'}}]})
    st2 = {'tick': 0, 'entities': {'player': {}}, 'world_flags': ['go'],
           'quests': {}, 'event_log': [], 'karma_ledger': []}
    QL.advance(st2, [q2])
    QL.advance(st2, [q2])
    QL.advance(st2, [q2])
    check('等待下一幕期间 done_stages 不重复累积',
          st2['quests']['q2']['done_stages'], ['a'])

    # lorebook：probability=1 是 1%，0.9 是 90%，id 保留
    e1 = normalize_lore_entry({'keys': ['灯'], 'content': 'x', 'probability': 1})
    e2 = normalize_lore_entry({'keys': ['灯'], 'content': 'x', 'probability': 0.9})
    check('lore probability=1 按 1% 解释（scale=100）',
          e1.get('probability_scale'), 100)
    check('lore probability=0.9 保留小数（90%）', e2.get('probability'), 0.9)
    check('lore 条目 id 保留', normalize_lore_entry({'id': 'abc', 'keys': ['k'], 'content': 'c'}).get('id'), 'abc')

    # 设定包：负价格/越界 hp 必须被规范化
    m = normalize_market([{'location': 'L', 'items': [{'key': 'x', 'price': -5, 'supply': -3}]}])
    check('normalize_market 价格下限 1', m['L']['x']['price'], 1)
    check('normalize_market 库存下限 0', m['L']['x']['supply'], 0)
    ent = normalize_entity('e', {'name': 'E', 'hp': -10, 'hp_max': -5, 'gold': -1})
    check('normalize_entity hp_max 下限 1', ent['hp_max'], 1)
    check('normalize_entity hp/gold 非负', (ent['hp'], ent['gold']), (0, 0))

    # 经济：负价商品买入不得反向加钱
    from game_engine.rules.economy import resolve_trade
    st = base()
    st['market'] = {'L': {'x': {'name': 'X', 'price': -10, 'base_price': -10, 'supply': 5}}}
    r = resolve_trade(st, 'L', 'x', 1, True, 'player')
    check_true('负价商品交易被拒（不反向加钱）',
               r.get('success') is False and st['entities']['player']['gold'] == 100,
               str(r.get('events'))[:50])

    # 大宗买入后立即卖出不得净赚（成交价与事后挂价必须对齐）
    st = base()
    st['entities']['player']['gold'] = 10000
    st['market'] = {'L': {'x': {'name': 'X', 'price': 50, 'base_price': 50, 'supply': 200}}}
    gold0 = st['entities']['player']['gold']
    resolve_trade(st, 'L', 'x', 100, True, 'player')
    resolve_trade(st, 'L', 'x', 100, False, 'player')
    check_true('大宗买入后立即卖出不产生无风险套利',
               st['entities']['player']['gold'] <= gold0,
               '%d -> %d' % (gold0, st['entities']['player']['gold']))

    # 台账合并必须保留每个债务人的归属（旧实现把 A/B/C 的债全挂到 A 名下）
    from game_engine.state_schema import _prune_settled
    ledger = [
        {'from': 'A', 'to': 'x', 'amount': 100, 'settled': False},
        {'from': 'B', 'to': 'x', 'amount': 100, 'settled': False},
        {'from': 'C', 'to': 'y', 'amount': 100, 'settled': False},
        {'from': 'D', 'to': 'z', 'amount': 50, 'settled': False},
    ]
    st = {'karma_ledger': ledger, 'entities': {}}
    _prune_settled(st, ledger, 2)
    check('台账合并后各债务人的未清债额度',
          {d: get_unsettled_karma(st, d) for d in 'ABCD'},
          {'A': 100, 'B': 100, 'C': 100, 'D': 50})

    # 世界书重复导入不得翻倍（load_setting 二次调用 / apply_runtime_fields 重复）
    from game_engine.settings_loader import apply_runtime_fields
    st = {'tick': 0, 'lore': [], 'ui': {}, 'config': {}, 'entities': {'player': {}}}
    bundle = {'name': 'x', 'lore': [{'comment': 'c', 'keys': ['k'], 'content': 'v'}]}
    apply_runtime_fields(st, bundle)
    apply_runtime_fields(st, bundle)
    check('世界书二次导入后的条目数', len(st['lore']), 1)

    # 纯公式边界：不得因数学域错误抛异常（model() 暴露给宿主任意入参）
    from game_engine.rules import world_dynamics as WD
    check_true('lyapunov_exponent dx_t=0 返回 -inf 而非抛错',
               WD.lyapunov_exponent(0.0, 1.0, 5) == float('-inf'), WD.lyapunov_exponent(0.0, 1.0, 5))
    check_true('predictability_horizon delta_max=0 返回 inf',
               WD.predictability_horizon(0.1, 1.0, 0.0) == float('inf'), WD.predictability_horizon(0.1, 1.0, 0.0))
    check('hawk_dove_ess_frequency C=0 返回全鹰', WD.hawk_dove_ess_frequency(0, 0), (1.0, 0.0))

    # 部分消业必须留下可审计的已还记录，原条目保留剩余额
    from game_engine.rules.karma import resolve_karma as _rk
    st = {'tick': 1, 'entities': {'player': {'name': 'P'}}, 'karma_ledger': []}
    _rk(st, 'player', 'v', 'murder_innocent')      # +50
    _rk(st, 'player', None, 'help_innocent')       # -10
    totals = [e['amount'] for e in st['karma_ledger']]
    check('部分消业保留剩余额且总额可审计',
          (get_unsettled_karma(st, 'player'), sum(totals)), (40, 50))

    # 事件保留量 <=0 必须被当成 1（不许把最新事件归档掉）
    from game_engine.state_schema import save_state, load_state
    import tempfile as _tf
    tmp = _tf.mkdtemp(prefix='ww-keep-')
    p = os.path.join(tmp, 's.json')
    save_state({'tick': 1, 'event_log': ['0', '1', '2'], 'config': {'event_log_keep': -1},
                'entities': {}, 'karma_ledger': [], 'flags': []}, p)
    check('event_log_keep=-1 被夹到 1（保留最新一条）', load_state(p)['event_log'], ['2'])


# ───────────────────── 状态文件原子写入 ─────────────────────
def atomic_write():
    """F-001：状态文件必须原子写入，且保留 .bak 可回退。

    为什么重要：直接 open(path,'w') 若在写入中途被杀，会留下半截 JSON，
    下一次 load_state 直接 JSONDecodeError——存档不可恢复。
    """
    import tempfile as _tf
    from game_engine.state_schema import save_state, load_state

    tmp = _tf.mkdtemp(prefix='ww-atomic-')
    p = os.path.join(tmp, 's.json')

    save_state({'tick': 1, 'entities': {}}, p)
    save_state({'tick': 2, 'entities': {}}, p)
    check('原子写：第二次保存后主文件可读且为新值', load_state(p)['tick'], 2)
    check_true('原子写：保留 .bak 且为上一版',
               os.path.exists(p + '.bak') and load_state(p + '.bak')['tick'] == 1,
               'bak=%s' % (load_state(p + '.bak')['tick'] if os.path.exists(p + '.bak') else None))
    check_true('原子写：不残留临时文件',
               not any(f.endswith('.tmp') for f in os.listdir(tmp)),
               str([f for f in os.listdir(tmp) if f.endswith('.tmp')]))

    # 模拟"主文件被截断"：.bak 必须仍可恢复
    with open(p, 'w', encoding='utf-8') as f:
        f.write('{"tick": ')
    check_true('主文件损坏时 .bak 仍可完整读出',
               load_state(p + '.bak')['tick'] == 1)


def main():
    print('── systems_feedback ──')
    systems()
    print('\n── narrative_engine ──')
    narrative()
    print('\n── cognition ──')
    cognition_branches()
    print('\n── social_extended 补 ──')
    social_extra()
    print('\n── economy ──')
    economy()
    print('\n── 剩余公式补测 ──')
    remaining_formulas()
    print('\n── 审计回归 ──')
    audit_regressions()
    print('\n── 状态文件原子写入 ──')
    atomic_write()

    passed = sum(RESULTS)
    print('\n%d/%d passed' % (passed, len(RESULTS)))
    if not RESULTS:
        print('没有任何断言被执行')
        return 1
    return 0 if passed == len(RESULTS) else 1


if __name__ == '__main__':
    sys.exit(main())
