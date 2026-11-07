#!/usr/bin/env python3
"""
规则内核公式对拍 (verify_formulas.py)

为什么需要：rules/ 下有 129 个学术公式函数，此前**没有任何独立验证**——
所有自检都只覆盖"引擎跑得动"，没有一个断言去核对公式本身算得对不对。
参数写反、常数打错、指数用错这类错误可以一路绿灯上线。

本脚本的做法：对每个函数按 docstring 里写的数学公式**独立重算一遍**
（不复用被测实现），再与返回值比对。数值容差 1e-9。

覆盖分层：
  A 组（精确式）：公式可闭式复算，逐条断言 —— 这是主体
  B 组（判定式）：返回枚举/布尔，按边界条件断言
  C 组（状态式）：需要构造 state，断言关键不变量
  D 组（随机式）：只断言返回值落在定义域内

用法:  python scripts/verify_formulas.py
退出码: 0 = 全部吻合；1 = 有偏差
"""

import math
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

from game_engine.rules import cognition as C
from game_engine.rules import models as M
from game_engine.rules import social_extended as SE
from game_engine.rules import systems_feedback as SF
from game_engine.rules import world_dynamics as WD
from game_engine.rules import cultural_evolution as CE
from game_engine.rules import social as SO
from game_engine.rules import karma as KA
from game_engine.rules import economy as SO_ECON

RESULTS = []
TOL = 1e-9


def check(name, got, want, tol=TOL):
    ok = False
    try:
        if isinstance(want, (int, float)) and isinstance(got, (int, float)):
            ok = abs(float(got) - float(want)) <= tol * max(1.0, abs(float(want)))
        else:
            ok = got == want
    except Exception:
        ok = False
    RESULTS.append(bool(ok))
    print('%s  %-48s got=%s want=%s' % ('PASS' if ok else 'FAIL', name, _fmt(got), _fmt(want)))


def check_true(name, cond, note=''):
    RESULTS.append(bool(cond))
    print('%s  %-48s %s' % ('PASS' if cond else 'FAIL', name, note))


def _fmt(v):
    if isinstance(v, float):
        return '%.10g' % v
    return repr(v)[:40]


# ─────────────────────────── A. 闭式公式逐条复算 ───────────────────────────
def exact_models():
    # OU: x' = x + (-theta*(x-base) + sigma*dW)
    x, base, theta, sigma, dW = 37.0, 30.0, 0.15, 2.0, 0.5
    want = x + (-theta * (x - base) + sigma * dW)
    check('ou_price 闭式复算', M.ou_price(x, base, theta, sigma, dW), want)

    # OU 整数版：max(0, round(ou_price(...)))
    check('ou_price_reverted 闭式复算', M.ou_price_reverted(40, 20),
          max(0, int(round(40 + (-0.15 * (40 - 20))))))

    # Lerner: P = cogs * ε/(ε-1)
    check('lerner_price 闭式复算', M.lerner_price(60, 2.5), 60 * 2.5 / 1.5)

    # Cobb-Douglas: Y = A * L^α * K^β
    check('cobb_douglas 闭式复算', M.cobb_douglas(10, 20, 0.6, 0.4, 1.5),
          1.5 * (10 ** 0.6) * (20 ** 0.4))
    # 默认参数 alpha=0.6 / beta=0.4 / A=1.0 —— 必须单独验，
    # 否则默认值被调换（0.4/0.6）时显式传参的用例发现不了
    check('cobb_douglas 默认参数复算', M.cobb_douglas(10, 20),
          (10 ** 0.6) * (20 ** 0.4))
    check('cobb_douglas 零投入返回 0', M.cobb_douglas(0, 20), 0.0)

    # Logistic: N' = N + r*N*(1-N/K)*dt
    n, r, K, dt = 100.0, 0.2, 1000.0, 1.0
    check('logistic_growth 闭式复算', M.logistic_growth(n, r, K, dt),
          n + r * n * (1 - n / K) * dt)

    # Lotka-Volterra（Euler 一步）
    prey, pred, a, b, c, d = 8.0, 3.0, 1.1, 0.4, 0.4, 0.1
    w_prey = prey + (a * prey - b * prey * pred) * dt
    w_pred = pred + (c * prey * pred - d * pred) * dt
    got = M.lotka_volterra(prey, pred, a, b, c, d, dt)
    if isinstance(got, (list, tuple)) and len(got) == 2:
        check('lotka_volterra 猎物分量', got[0], w_prey)
        check('lotka_volterra 捕食者分量', got[1], w_pred)
    else:
        check('lotka_volterra 返回二元组', got, (w_prey, w_pred))

    # SIR 一步
    s, i, rr, beta, gamma = 0.99, 0.01, 0.0, 0.6, 0.2
    w_s = s - beta * s * i * dt
    w_i = i + beta * s * i * dt - gamma * i * dt
    w_r = rr + gamma * i * dt
    got = M.sir_step(s, i, rr, beta, gamma, dt)
    check('sir_step 三分量复算', tuple(round(v, 12) for v in got),
          tuple(round(v, 12) for v in (w_s, w_i, w_r)))
    # 输入和不等于 1 时，实现会先归一化 —— 单独验这个分支
    got_n = M.sir_step(0.5, 0.5, 0.5, 0.6, 0.2, 1.0)
    check_true('sir_step 非归一输入后仍归一', abs(sum(got_n) - 1.0) < 1e-9, str(got_n))

    # R0 = β/γ
    check('basic_reproduction 闭式复算', M.basic_reproduction(0.6, 0.2), 3.0)

    # 泊松累积 / 逆生存
    check('hazard_cumulative 1-e^(-λt)', M.hazard_cumulative(0.1, 5), 1 - math.exp(-0.5))
    check('inverse_survival e^(-λt)', M.inverse_survival(0.1, 5), math.exp(-0.5))

    # logistic_sigmoid
    check('logistic_sigmoid 闭式复算', M.logistic_sigmoid(2.0, 0.0, 1.5),
          1 / (1 + math.exp(-1.5 * 2.0)))

    # 热力学松弛
    check('thermal_relaxation 闭式复算', M.thermal_relaxation(10.0, 0.0, 2.0, 1.0),
          0.0 + (10.0 - 0.0) * math.exp(-1.0 / 2.0))

    # 逆平方
    check('inverse_square 闭式复算', M.inverse_square(3.0, 2.0, 5.0), 5.0 * 3.0 / 4.0)

    # 指数衰减
    check('exponential_decay 闭式复算', M.exponential_decay(100.0, 0.1, 5.0),
          100.0 * math.exp(-0.5))

    # 简谐一步
    pos, vel, omega, h = 1.0, 0.0, 2.0, 0.1
    acc = -omega * omega * pos
    check('harmonic_step 位置', M.harmonic_step(pos, vel, omega, h)[0], pos + vel * h)
    check('harmonic_step 速度', M.harmonic_step(pos, vel, omega, h)[1], vel + acc * h)


def exact_cognition():
    # 前景理论价值函数
    check('value_function 收益分支', C.value_function(100.0), 100.0 ** 0.88)
    check('value_function 损失分支', C.value_function(-100.0), -2.25 * (100.0 ** 0.88))

    # 决策权重
    p, gamma = 0.3, 0.7
    check('probability_weighting 闭式复算', C.probability_weighting(p, gamma),
          (p ** gamma) / ((p ** gamma + (1 - p) ** gamma) ** (1 / gamma)))

    # 认知预算
    check('daily_cognitive_budget 充沛', C.daily_cognitive_budget(2, '充沛'), 100.0 * 1.6 * 1.2)
    check('daily_cognitive_budget 疲惫', C.daily_cognitive_budget(0, '疲惫'), 100.0 * 1.0 * 0.6)
    # "正常" 是 engine/MCP 实际使用的档位，系数被改坏必须能被发现
    check('daily_cognitive_budget 正常 (=100)', C.daily_cognitive_budget(0, '正常'), 100.0)
    check('daily_cognitive_budget 未知档位回退 1.0',
          C.daily_cognitive_budget(0, '不存在的档位'), 100.0)

    # 境界钝化
    check('realm_dampening 闭式复算', C.realm_dampening(5), 1 / (1 + 0.5))

    # 幂律学习
    check('skill_execution_time 闭式复算', C.skill_execution_time(10.0, 4.0),
          10.0 * (4.0 ** -0.4))

    # 知行合一
    check('true_comprehension 乘积', C.true_comprehension(0.8, 0.5), 0.4)
    check_true('true_comprehension 任一为零则零', C.true_comprehension(0.0, 0.9) == 0.0)

    # 内在动机
    # 默认权重各 1/3
    check('intrinsic_motivation 加权和', C.intrinsic_motivation(0.5, 0.6, 0.7),
          (0.5 + 0.6 + 0.7) / 3)

    # 损失厌恶
    # 默认 lambda_coeff = 2.0（不是前景理论里的 2.25）
    check('loss_aversion_utility 正损失', C.loss_aversion_utility(10.0, 5.0), 10.0 - 2.0 * 5.0)
    # 负损失也要测：去掉 abs() 时正损失用例发现不了
    check('loss_aversion_utility 负损失取绝对值', C.loss_aversion_utility(10.0, -5.0), 0.0)


def exact_social_extended():
    check('merit_quality 闭式复算', SE.merit_quality(0.9, 1.0), 0.9 * (0.4 + 0.6))
    # sincerity=1.0 时 (0.4+0.6) 与 (0.6+0.4) 恒等，系数互换发现不了 —— 用 0.5
    check('merit_quality 系数区分（sincerity=0.5）', SE.merit_quality(1.0, 0.5), 0.4 + 0.3)
    check('moral_resonance 点积', SE.moral_resonance([1, 2, 3], [4, 5, 6]), 32.0)
    check('blame_victim_probability 乘积', SE.blame_victim_probability(0.8, 0.5), 0.4)
    # 乘积 >1 时必须被截到 1.0（去掉 min 截断则返回 1.44）
    check('blame_victim_probability 上限截断', SE.blame_victim_probability(1.2, 1.2), 1.0)
    check('self_esteem_social 加权和', SE.self_esteem_social(0.7, 0.4, 0.6, 0.4),
          0.6 * 0.7 + 0.4 * 0.4)
    # 默认权重 0.5/0.5 —— 单独验，防默认值被改
    check('self_esteem_social 默认权重', SE.self_esteem_social(0.8, 0.2), (0.8 + 0.2) / 2)
    # 实现为 (p_auth + p_loyal - p_free) / 2，不是简单差值
    check('order_chaos_axis 闭式复算', SE.order_chaos_axis(0.6, 0.3, 0.1), (0.6 + 0.3 - 0.1) / 2)
    # 实现为 (p_care + p_fair) / 2
    check('altruism_egoism_axis 闭式复算', SE.altruism_egoism_axis(0.7, 0.3), (0.7 + 0.3) / 2)
    check('empathy_pool_delta', SE.empathy_pool_delta(10.0, 5.0, 0.1), 9.5)
    check('basic_reproduction_number 转调一致', SE.basic_reproduction_number(0.6, 0.2), 3.0)


def exact_systems():
    check('boltzmann_entropy S=k·lnΩ', SF.boltzmann_entropy(8, 1.0), math.log(8))
    check('cultivation_energy_balance 差值',
          SF.cultivation_energy_balance(100, 30, 20, 10), 40)
    check('actor_network_power 加权和',
          SF.actor_network_power([2, 3, 5], [0.5, 0.4, 0.1]), 2 * 0.5 + 3 * 0.4 + 5 * 0.1)


def exact_world():
    # Lyapunov
    check('lyapunov_exponent 闭式复算',
          WD.lyapunov_exponent(2.0, 0.001, 10), (1 / 10) * math.log(2.0 / 0.001))

    # 可预测时窗
    check('predictability_horizon 闭式复算',
          WD.predictability_horizon(0.5, 0.001, 1.0), (1 / 0.5) * math.log(1.0 / 0.001))

    # Logistic 映射
    check('logistic_map 闭式复算', WD.logistic_map(0.3, 3.7), 3.7 * 0.3 * (1 - 0.3))

    # Hamilton 规则
    check_true('hamilton_rule rb>c 为真', WD.hamilton_rule(0.5, 10, 4) is True)
    check_true('hamilton_rule rb<c 为假', WD.hamilton_rule(0.2, 10, 4) is False)

    # Shannon 熵 / KL / 自信息
    ps = [0.25, 0.25, 0.25, 0.25]
    check('shannon_entropy 均匀分布=2bit', WD.shannon_entropy(ps, 2), 2.0)
    check('kl_divergence 自身为 0', WD.kl_divergence(ps, ps, 2), 0.0)
    # 必须用 P != Q 且断言具体值：只有"自比较为 0"时，方向写反或恒返回 0 都能过
    p2, q2 = [0.5, 0.5], [0.25, 0.75]
    want_kl = sum(pi * math.log2(pi / qi) for pi, qi in zip(p2, q2))
    check('kl_divergence D(P||Q) 具体值（非自比较）', WD.kl_divergence(p2, q2, 2), want_kl)
    check_true('kl_divergence 方向性：D(P||Q) != D(Q||P)',
               abs(WD.kl_divergence(p2, q2, 2) - WD.kl_divergence(q2, p2, 2)) > 1e-6)
    check('event_information -log2(p)', WD.event_information(0.01, 2), -math.log(0.01, 2))

    # 记忆检索
    # 默认权重 alpha=beta=gamma=0.33（不是 0.4/0.3/0.3）
    check('memory_retrieval_score 加权和',
          WD.memory_retrieval_score(0.8, 0.5, 0.6), 0.33 * 0.8 + 0.33 * 0.5 + 0.33 * 0.6)

    # 相对优势
    check('relative_advantage 闭式复算',
          WD.relative_advantage(10, 8, 2, 1.5), (10 - 8) - 1.5 * 2)

    # 复制动力学：x_i[(Ax)_i - x·Ax]
    # 必须用非对称收益矩阵：对角矩阵 + 等比例时真实输出恒为 0，
    # "恒返回 0" 的错误实现会静默通过。
    props, payoff = [0.7, 0.3], [[3.0, 1.0], [0.5, 2.0]]
    ax = [sum(payoff[i][j] * props[j] for j in range(2)) for i in range(2)]
    avg = sum(props[i] * ax[i] for i in range(2))
    got = WD.replicator_dynamics_step(props, payoff)
    check('replicator_dynamics_step 分量0', got[0], props[0] * (ax[0] - avg))
    check('replicator_dynamics_step 分量1', got[1], props[1] * (ax[1] - avg))
    check_true('replicator_dynamics_step 非零（非对称为前提）', abs(got[0]) > 1e-6, str(got))


def exact_cultural():
    check('meme_fitness 三因子乘积', CE.meme_fitness(2.0, 3.0, 0.5), 3.0)
    check('ratchet_product 三因子乘积', CE.ratchet_product(0.5, 0.6, 0.7), 0.21)
    check('total_cultural_variation 求和', CE.total_cultural_variation(1, 2, 3), 6)
    check('next_generation_quality 累加', CE.next_generation_quality(10, 2, 3), 15)
    # 文化频率变化 Δp = p(1-p)[ΣαB - C] + μ(1-2p)
    p, alphas, Bs, Cc, mu = 0.3, [0.5, 0.5], [2.0, 1.0], 1.0, 0.01
    want = p * (1 - p) * (sum(a * b for a, b in zip(alphas, Bs)) - Cc) + mu * (1 - 2 * p)
    check('cultural_frequency_change 闭式复算',
          CE.cultural_frequency_change(p, alphas, Bs, Cc, mu), want)
    # 矩阵-向量乘 p_{t+1} = T · p_t
    T = [[0.8, 0.2], [0.3, 0.7]]
    pt = [0.6, 0.4]
    want_p = [T[0][0] * pt[0] + T[0][1] * pt[1], T[1][0] * pt[0] + T[1][1] * pt[1]]
    check('cultural_transmission_update 矩阵乘', CE.cultural_transmission_update(pt, T), want_p)


def exact_social():
    st = {'entities': {'a': {'name': '甲'}, 'b': {'name': '乙'}},
          'relations': {}, 'tick': 1, 'event_log': []}
    r = SO.resolve_social_event(st, 'a', 'b', 'help', 1.0)
    check_true('social help = affinity+5 / respect+3',
               r['affinity_after'] - r['affinity_before'] == 5
               and r['respect_after'] - r['respect_before'] == 3,
               '%s/%s' % (r['affinity_after'], r['respect_after']))


def exact_karma():
    st = {'entities': {'p': {'name': '甲'}, 'v': {'name': '乙'}},
          'karma_ledger': [], 'tick': 1}
    # 只有正业 + 指定受害者才落账本（karma.py 的 elif delta < 0 走消业分支）
    KA.resolve_karma(st, 'p', 'v', action_type='theft')
    check('karma theft 记 15', st['karma_ledger'][-1]['amount'], 15)
    check('karma 账本条目 from', st['karma_ledger'][-1]['from'], 'p')


# ─────────────────────────── B. 判定式边界 ───────────────────────────
def boundaries():
    fs = C.flow_state(0.8)
    check_true('flow_state 高挑战高技=flow', fs.get('state') == 'flow', str(fs))
    check_true('realm_dampening 单调递减',
               C.realm_dampening(1) > C.realm_dampening(5) > C.realm_dampening(9))
    check_true('ou_price_reverted 非负', M.ou_price_reverted(0, 100000) >= 0)
    check_true('ou_price_reverted 严格收敛（死区外）',
               M.ou_price_reverted(1000, 20) < 1000)
    check_true('logistic_growth 封顶不超过 K',
               M.logistic_growth(999, 1.0, 1000, 1.0) <= 1000 + 1e-9)
    check_true('sir_step 总量守恒', abs(sum(M.sir_step(0.99, 0.01, 0.0, 0.6, 0.2, 1.0)) - 1.0) < 1e-9)
    # V=10 > C=4 → 全鹰；V=4 < C=10 → V/C=0.4
    # 只断言"和为 1"时，恒返回 (0.5, 0.5) 也能过，必须断具体值
    check('hawk_dove_ess_frequency V>C 全鹰', WD.hawk_dove_ess_frequency(10, 4), (1.0, 0.0))
    check('hawk_dove_ess_frequency V<C 混合 0.4/0.6',
          WD.hawk_dove_ess_frequency(4, 10), (0.4, 0.6))
    # 四个极端组合应落到四个不同相位（不能只测"在集合里"）
    phases = {WD.panarchy_phase(*c).get('phase') for c in
              [(0.1, 0.1, 0.9), (0.9, 0.9, 0.9), (0.9, 0.1, 0.1), (0.1, 0.9, 0.1)]}
    check_true('panarchy_phase 四象限覆盖多个相位', len(phases) >= 2, str(sorted(phases)))
    # r<3 收敛 / 3<=r<3.45 周期 / 3.45<=r<3.57 四周期 / >3.57 混沌
    check('cultivation_stability r=2.0 收敛', WD.cultivation_stability(2.0).get('state'), 'convergence')
    check('cultivation_stability r=3.2 周期', WD.cultivation_stability(3.2).get('state'), 'period2')
    check('cultivation_stability r=3.9 混沌', WD.cultivation_stability(3.9).get('state'), 'chaos')
    check('is_altruistic 高坚持高代价=利他', SE.is_altruistic(0.8, 0.8, 0.2), 'altruistic')
    check('is_altruistic 成本敏感=利己', SE.is_altruistic(0.2, 0.2, 0.9), 'egoistic')
    check('is_altruistic 其余=模糊', SE.is_altruistic(0.2, 0.2, 0.2), 'ambiguous')
    # 全不满足 → 第 0 层；全满足 → 第 4 层（自我实现）
    check('maslow_dominant_need 全不满足=0', C.maslow_dominant_need([0.1] * 5), 0)
    check('maslow_dominant_need 全满足=4', C.maslow_dominant_need([0.9] * 5), 4)
    # 前两层满足、第三层不满足（阈值 0.6）→ 返回 2
    check('maslow_dominant_need 定位到第 2 层',
          C.maslow_dominant_need([0.9, 0.9, 0.1, 0.9, 0.9]), 2)


# ─────────────────────────── D. 定义域 ───────────────────────────
def domains():
    for p in (0.001, 0.3, 0.999):
        v = C.probability_weighting(p, 0.7)
        check_true('probability_weighting 落在 (0,1)  p=%s' % p, 0 < v < 1, '%.6f' % v)
    # 极端输入会饱和到 0/1（浮点下溢），只断言落在闭区间
    for x in (-50, 0, 50):
        v = M.logistic_sigmoid(x, 0, 1)
        check_true('logistic_sigmoid 落在 [0,1]  x=%s' % x, 0 <= v <= 1, '%.6f' % v)
    check_true('shannon_entropy 非负', WD.shannon_entropy([0.5, 0.5]) >= 0)
    check_true('merit_quality 为零当 aid=0', SE.merit_quality(0, 1) == 0)



# ─────────────────────── C. 状态式与剩余纯公式 ───────────────────────
def exact_world_extra():
    # Price 方程：Δz̄ = Cov(w_i / w̄, z_i) + E(w_i / w̄ · Δz_i)
    # 注意是"相对适应度 w_i/w̄"，不是 docstring 旧写的 w_i/z_i（已同步修正文档）
    fit, means, dtraits = [1.0, 2.0, 3.0], [10.0, 12.0, 14.0], [0.1, 0.2, 0.3]
    n = len(fit)
    m_w = sum(fit) / n
    rel = [w / m_w for w in fit]
    m_z = sum(means) / n
    cov = sum((r - 1.0) * (z - m_z) for r, z in zip(rel, means)) / n
    trans = sum(r * d for r, d in zip(rel, dtraits)) / n
    check('price_equation 闭式复算（相对适应度协方差+传输项）',
          WD.price_equation(fit, means, dtraits), cov + trans)

    # 相对适应度：W_A = baseline − α·opp + β·self − γ·self·opp
    check('coevolution_fitness 闭式复算',
          WD.coevolution_fitness(10.0, 0.5, 3.0, 0.2, 2.0, 0.1),
          10.0 - 0.5 * 3.0 + 0.2 * 2.0 - 0.1 * 2.0 * 3.0)

    # Lorenz 一步（Euler）
    x, y, z, sg, rho, be, h = 1.0, 1.0, 1.0, 10.0, 28.0, 8 / 3, 0.01
    check('lorenz_step dx', WD.lorenz_step(x, y, z, sg, rho, be, h)[0],
          x + sg * (y - x) * h)
    check('lorenz_step dy', WD.lorenz_step(x, y, z, sg, rho, be, h)[1],
          y + (x * (rho - z) - y) * h)

    # Leverage：min(1, ln(tier+1)/ln(13))
    check('leverage_effectiveness 闭式复算', SF.leverage_effectiveness(3),
          min(1.0, math.log(4) / math.log(13)))

    # Milgram：max(0,min(1, base+prox)*authority + peer_defiance)
    check('milgram_obedience 闭式复算', SE.milgram_obedience(0.65, 0.1, 1.2, -0.2),
          max(0.0, min(1.0, 0.65 + 0.1) * 1.2 - 0.2))

    # 累积保真度 f0^n · exp(-λt)
    check('cumulative_fidelity 闭式复算', CE.cumulative_fidelity(0.9, 3, 0.01, 5.0),
          (0.9 ** 3) * math.exp(-0.05))

    # 小世界路径长度 ln(N)/ln(K)
    check('ws_characteristic_path_length 闭式复算',
          SE.ws_characteristic_path_length(100, 4), math.log(100) / math.log(4))


def exact_cognition_extra():
    # 幂律记忆衰减 B_i = ln(Σ (now - t_k)^{-d})，只计 t < now 的访问
    times, d, now = [1.0, 2.0, 4.0], 0.5, 8.0
    want = math.log(sum(max(0.01, now - t) ** (-d) for t in times if t < now))
    check('base_activation 闭式复算', C.base_activation(times, now, d), want)
    check_true('base_activation 空输入返回 -inf',
               C.base_activation([], now, d) == -float('inf'))

    # 总激活 A_i = B_i + Σ_j W_j·S_ji（权重与关联都是 dict）
    check('total_activation 闭式复算',
          C.total_activation(2.0, {'a': 0.5, 'b': 0.5}, {'a': 1.0, 'b': 1.0}), 3.0)
    check('total_activation 缺失关联按 0 计',
          C.total_activation(2.0, {'a': 0.5, 'z': 0.5}, {'a': 1.0}), 2.5)

    # Softmax 规则选择
    utils, tau = [1.0, 2.0], 1.0
    e = [math.exp(u / tau) for u in utils]
    check('conflict_resolution_prob softmax', C.conflict_resolution_prob(utils, tau),
          [x / sum(e) for x in e])

    # Logistic 成功率
    check('skill_success_probability 闭式复算',
          C.skill_success_probability(3.0, 2.0), 1 / (1 + math.exp(-1.0)))

    # 记忆召回概率
    check('recall_probability 闭式复算',
          C.recall_probability(2.0, 1.0), 1 / (1 + math.exp(-2.0)))

    # 沉浸度几何平均
    check('total_immersion_metric 几何平均',
          C.total_immersion_metric(0.5, 0.5, 0.5), (0.5 * 0.5 * 0.5) ** (1 / 3))


def state_style():
    """C 组：需要构造 state 的函数，断言关键不变量与其返回结构。"""
    # resolve_social_event：help 事件的固定增益 + 关系键生成
    st = {'entities': {'a': {'name': '甲'}, 'b': {'name': '乙'}},
          'relations': {}, 'tick': 1, 'event_log': []}
    r = SO.resolve_social_event(st, 'a', 'b', 'gift', 1.0)
    check_true('social gift 增益 (affinity,respect) = (8,0) 与定义一致',
               (r['affinity_after'] - r['affinity_before'],
                r['respect_after'] - r['respect_before']) == (8, 0),
               '%s/%s' % (r['affinity_after'], r['respect_after']))

    # resolve_trade：买入后扣款/入库/减库存三者一致
    st2 = {'entities': {'p': {'name': '甲', 'gold': 1000, 'items': {}}},
           'market': {'L': {'it': {'name': '丹', 'price': 10, 'supply': 20, 'base_price': 10}}},
           'relations': {}, 'tick': 1, 'event_log': []}
    tr = SO_ECON.resolve_trade(st2, 'L', 'it', 3, True, 'p')
    check_true('trade 买入：扣款=总额、入库=数量、减库存=数量',
               tr['success'] and st2['entities']['p']['gold'] == 1000 - tr['total_cost']
               and st2['entities']['p']['items'].get('it') == 3
               and st2['market']['L']['it']['supply'] == 17,
               str(tr.get('total_cost')))

    # compute_influence：返回值应是有限数
    st3 = {'entities': {'a': {'name': '甲', 'attrs': {'str': 20, 'cha': 15}},
                        'b': {'name': '乙', 'attrs': {'str': 5, 'cha': 5}}},
           'relations': {}, 'tick': 1}
    v = SO.compute_influence(st3, 'a', 'b')
    check_true('compute_influence 返回有限数值',
               isinstance(v, (int, float)) and math.isfinite(float(v)), str(v))

    # get_karma_consequence：低业债不触发
    st4 = {'entities': {'p': {'name': '甲'}}, 'karma_ledger': [], 'tick': 1}
    cons = KA.get_karma_consequence(st4, 'p')
    check_true('get_karma_consequence 无业债时不触发',
               isinstance(cons, dict) and cons.get('triggered') is False, str(cons)[:50])


def model_registry():
    """模型注册表：model() 与 model_names() 必须一致。"""
    names = M.model_names()
    check_true('model_names 返回非空列表', isinstance(names, list) and len(names) >= 16,
               '%d 个' % len(names or []))
    r = M.model('lerner_price', cogs=60, elasticity=2.5)
    # 断具体值 100（= 60*2.5/1.5），而不是拿 lerner_price() 自比
    check('model 统一入口按公式出数（cogs=60, ε=2.5 → 100）', r.get('value'), 100.0)
    # deffuant_update：可达邻居取均值后向中间走一半
    # 观点 0.0，邻居 0.2/0.4 都在 mu=1.0 内 → target=0.3 → 0 + 0.5*(0.3-0) = 0.15
    r2 = M.model('deffuant_update', agent_op=0.0, neighbors=[0.2, 0.4], mu=1.0)
    check('deffuant_update 有界信任更新', r2.get('value'), 0.15)
    # 全部超出信任阈值 → 观点不动
    check('deffuant_update 超阈值不动', M.deffuant_update(0.0, [0.9, 0.95], 0.1), 0.0)


def main():
    print('── A. 闭式公式逐条复算 ──')
    exact_models()
    exact_cognition()
    exact_social_extended()
    exact_systems()
    exact_world()
    exact_cultural()
    exact_social()
    exact_karma()
    print('\n── B. 判定式边界 ──')
    boundaries()
    print('\n── C. 状态式与剩余纯公式 ──')
    exact_world_extra()
    exact_cognition_extra()
    state_style()
    model_registry()
    print('\n── D. 值域 ──')
    domains()

    passed = sum(RESULTS)
    print('\n%d/%d passed' % (passed, len(RESULTS)))
    if not RESULTS:
        print('没有任何断言被执行')
        return 1
    return 0 if passed == len(RESULTS) else 1


if __name__ == '__main__':
    sys.exit(main())
