"""
世界演化动力学 (World Dynamics)

基于: 混沌/非线性动力学、复杂系统与进化动力学理论文献
包含: 洛伦兹吸引子, Lyapunov指数, Logistic映射, 可预测窗口,
      Price方程, Hamilton规则, ESS, Hawk-Dove, 复制动力学,
      Panarchy适应性循环, 红皇后协同进化, 间断平衡

依赖约束: 仅标准库（ARCHITECTURE.md §2）——矩阵运算用纯 Python 实现，
调用方传 list / tuple / numpy.ndarray 均可（只按下标与迭代取用）。
"""

import math, random
from typing import List, Dict, Tuple

# ============================================================
# 1. 混沌理论 (CHAOS_NONLINEAR.md)
# ============================================================

def lyapunov_exponent(dx_t: float, dx_0: float, t: float) -> float:
    """最大李雅普诺夫指数 λ = (1/t) · ln(|δx(t)|/|δx(0)|)。

    |δx(t)|=0 在数学上是 -∞（轨迹完全收敛）；返回 -inf 而不是抛 math domain error，
    因为 model() 走的是宿主任意入参，纯函数不该把异常当输入校验。
    """
    if dx_0 <= 0 or t <= 0:
        return 0.0
    if abs(dx_t) == 0:
        return float("-inf")
    return (1.0 / t) * math.log(abs(dx_t) / abs(dx_0))

def lorenz_step(x: float, y: float, z: float,
                sigma: float = 10.0, rho: float = 28.0, beta: float = 8.0/3.0,
                dt: float = 0.01) -> tuple:
    """洛伦兹系统一步迭代 (RK1/Euler) — 用于心魔/丹田动态"""
    dx = sigma * (y - x)
    dy = x * (rho - z) - y
    dz = x * y - beta * z
    return (x + dx * dt, y + dy * dt, z + dz * dt)

def predictability_horizon(lyapunov_lambda: float, delta_0: float, delta_max: float) -> float:
    """T_predict ≈ (1/λ) · ln(Δ_max/Δ_0) — 天道推演的极限时间窗口"""
    if lyapunov_lambda <= 0 or delta_0 <= 0 or delta_max <= 0:
        return float('inf')
    return (1.0 / lyapunov_lambda) * math.log(delta_max / delta_0)

def logistic_map(x_n: float, r: float) -> float:
    """x_{n+1} = r·x_n·(1 - x_n) — 修炼进度/瓶颈模拟"""
    return r * x_n * (1.0 - x_n)

def cultivation_stability(r: float) -> Dict:
    """
    根据综合 r 值判定修炼状态
    r<3: 收敛（停滞），r≈3.4: 周期波动，r>3.57: 混沌（走火入魔）
    """
    if r < 3.0:
        return {"state": "convergence", "desc": "修炼缓慢进展，瓶颈稳固"}
    elif r < 3.45:
        return {"state": "period2", "desc": "境界在两层之间来回摇摆"}
    elif r < 3.57:
        return {"state": "period4", "desc": "周期波动加速，心境不稳"}
    else:
        return {"state": "chaos", "desc": "⚠️ 心魔区 — 走火入魔风险极高"}

# ============================================================
# 2. Price 方程 (EVOLUTIONARY_DYNAMICS.md)
# ============================================================

def price_equation(group_fitnesses: List[float], trait_means: List[float],
                   delta_traits: List[float]) -> float:
    """Δz̄ = Cov(w_i/w̄, z_i) + E((w_i/w̄) · Δz_i) — 选择 + 传输

    纯 Python 实现（总体协方差，语义等价 np.cov(bias=True)）；
    空输入或适应度均值为 0 时返回 0（不抛、不发散）。
    三个入参必须等长，不等长直接断言失败（与原 numpy 版抛错语义一致，不静默截断）。
    """
    n = len(group_fitnesses)
    if n == 0:
        return 0.0
    # 用 raise 而不是 assert：assert 在 python -O 下会被剥离，
    # 那样长度不一致会退化成静默截断（正是本校验要防的行为）。
    if len(trait_means) != n or len(delta_traits) != n:
        raise ValueError("price_equation: group_fitnesses/trait_means/delta_traits 长度不一致")
    mean_fitness = sum(group_fitnesses) / n
    if mean_fitness == 0:
        return 0.0
    rel_fitness = [w / mean_fitness for w in group_fitnesses]
    mean_trait = sum(trait_means) / n
    cov_term = sum((r - 1.0) * (z - mean_trait)
                   for r, z in zip(rel_fitness, trait_means)) / n
    transmission = sum(r * d for r, d in zip(rel_fitness, delta_traits)) / n
    return cov_term + transmission

def multilevel_selection(group_means: List[float], group_fitnesses: List[float],
                         group_sizes: List[int],
                         within_group_vars: List[float]) -> Tuple[float, float]:
    """多层选择分解: (群体间选择量, 群体内选择量)"""
    total_n = sum(group_sizes)
    if total_n <= 0:
        return 0.0, 0.0
    mean_fitness = sum(w * n for w, n in zip(group_fitnesses, group_sizes)) / total_n
    mean_trait = sum(z * n for z, n in zip(group_means, group_sizes)) / total_n
    
    # 群体间 (防止 mean_fitness=0 除零)
    safe_mf = mean_fitness if abs(mean_fitness) > 1e-12 else 1e-12
    between = sum(n * (w / safe_mf - 1) * (z - mean_trait)
                  for n, w, z in zip(group_sizes, group_fitnesses, group_means))
    
    # 群体内 (用方差近似)
    within = sum(var * n for var, n in zip(within_group_vars, group_sizes)) / total_n
    
    return between, within

# ============================================================
# 3. Nowak + Hamilton 合作进化
# ============================================================

def hamilton_rule(r: float, benefit: float, cost: float) -> bool:
    """r · b > c — 利他行为进化判定"""
    return r * benefit > cost

def kin_selection(r: float, cost: float, benefit: float) -> bool:
    """亲缘选择: r > c/b"""
    return r > cost / benefit if benefit > 0 else False

def direct_reciprocity(w: float, cost: float, benefit: float) -> bool:
    """直接互惠: w > c/b"""
    return w > cost / benefit if benefit > 0 else False

def network_selection(benefit: float, cost: float, k: int) -> bool:
    """网络选择: b/c > k (邻居度数)"""
    return benefit / cost > k if cost > 0 else True

def inclusive_fitness(direct_fitness: float, kin_benefits: List[float],
                      kin_costs: List[float], r_values: List[float]) -> float:
    """IF = d_i + Σ_j r_ij·b_j - Σ_k r_ik·a_ki"""
    gains = sum(r * b for r, b in zip(r_values, kin_benefits))
    costs = sum(r * c for r, c in zip(r_values, kin_costs))
    return direct_fitness + gains - costs

# ============================================================
# 4. ESS + Hawk-Dove
# ============================================================

def is_ess(payoff_matrix: List[List[float]], strategy_i: int) -> bool:
    """ESS 严格判定"""
    n = len(payoff_matrix)
    for j in range(n):
        if j == strategy_i:
            continue
        e_ii = payoff_matrix[strategy_i][strategy_i]
        e_ji = payoff_matrix[j][strategy_i]
        if e_ii < e_ji:
            return False
        if e_ii == e_ji and payoff_matrix[strategy_i][j] <= payoff_matrix[j][j]:
            return False
    return True

def hawk_dove_payoff(my_move: str, opponent_move: str, V: float, C: float) -> float:
    """Hawk-Dove 收益矩阵"""
    if my_move == "H" and opponent_move == "H":
        return (V - C) / 2.0
    elif my_move == "H" and opponent_move == "D":
        return V
    elif my_move == "D" and opponent_move == "H":
        return 0.0
    elif my_move == "D" and opponent_move == "D":
        return V / 2.0
    return 0.0

def hawk_dove_ess_frequency(V: float, C: float) -> Tuple[float, float]:
    """混合ESS: 返回 (鹰频率, 鸽频率)。C=0 时没有代价，鹰派占满。"""
    if C <= 0:
        return (1.0, 0.0)
    if V > C:
        return (1.0, 0.0)
    p = min(1.0, max(0.0, V / C))
    return (p, 1.0 - p)

def replicator_dynamics_step(strategy_props: List[float],
                             payoff_matrix: List[List[float]]) -> List[float]:
    """复制动力学一步 dx_i/dt = x_i[(Ax)_i - x·Ax]（纯 Python 矩阵-向量乘）"""
    n = len(strategy_props)
    avg_payoffs = [sum(row[j] * strategy_props[j] for j in range(n)) for row in payoff_matrix]
    mean_payoff = sum(p * a for p, a in zip(strategy_props, avg_payoffs))
    return [p * (a - mean_payoff) for p, a in zip(strategy_props, avg_payoffs)]

# ============================================================
# 5. 间断平衡 (Punctuated Equilibrium, Eldredge & Gould)
# ============================================================

def ou_process(z: float, theta: float, alpha: float, sigma: float, dt: float) -> float:
    """Ornstein-Uhlenbeck: dz = -α(z-θ)dt + σ·dW — 长稳定期"""
    dW = random.gauss(0.0, math.sqrt(dt))
    return z + (-alpha * (z - theta) * dt) + sigma * dW

def extinction_check(hazard_rate: float, dt: float = 1.0) -> bool:
    """灭绝为泊松过程，风险率恒定"""
    return random.random() < hazard_rate * dt  # nosec B311 —— 游戏骰子，非密码学用途

# ============================================================
# 6. 红皇后 (Red Queen Hypothesis, Van Valen 1973)
# ============================================================

def coevolution_fitness(baseline: float, alpha: float, opponent_trait: float,
                        beta: float, self_trait: float, gamma: float) -> float:
    """W_A = baseline − α·opponent_trait + β·self_trait − γ·self·opponent"""
    return baseline - alpha * opponent_trait + beta * self_trait - gamma * self_trait * opponent_trait

def relative_advantage(speed_A: float, speed_B: float, tech_gap: float, lam: float) -> float:
    """相对优势 = [A优势] — λ·Δtech_gap（被追赶拉回）"""
    return (speed_A - speed_B) - lam * tech_gap

def red_queen_field(competition_coeffs: List[float], opponent_states: List[float]) -> float:
    """F_i(A) = Σ_j C(A,j) · σ(j) — 聚合所有对手的竞争压力

    两入参必须等长，不等长直接抛 ValueError（不静默截断）。
    """
    if len(competition_coeffs) != len(opponent_states):
        raise ValueError("red_queen_field: competition_coeffs/opponent_states 长度不一致")
    return float(sum(c * s for c, s in zip(competition_coeffs, opponent_states)))

# ============================================================
# 7. Panarchy 适应性循环 (Holling 1986, COMPLEX_SYSTEMS.md)
# ============================================================

PANARCHY_PHASES = ["r", "K", "Ω", "α"]

def panarchy_phase(capital: float, connectedness: float, resilience: float) -> Dict:
    """
    判定当前适应性循环阶段
    
    capital:     存量/积累量 (资源、制度密度)
    connectedness: 连接度/制度化程度
    resilience:   恢复力 (越高越不怕崩溃)
    """
    # 四象限判定
    if capital < 0.3 and connectedness < 0.3:
        return {"phase": "Ω", "desc": "崩溃/释放", "color": "red",
                "trigger": "大劫爆发，旧秩序解体"}
    elif capital < 0.5 and connectedness > 0.5:
        return {"phase": "α", "desc": "重组/革新", "color": "yellow",
                "trigger": "新秩序也在废墟中萌芽"}
    elif capital < 0.7 and connectedness < 0.6:
        return {"phase": "r", "desc": "开发/增长", "color": "green",
                "trigger": "快速扩张期，机会涌现"}
    else:
        return {"phase": "K", "desc": "保护/守恒", "color": "blue",
                "trigger": "稳定但也僵化，创新受抑"}

def panarchy_tick(capital: float, connectedness: float, event_impact: float = 0.0) -> dict:
    """模拟一回合 Panarchy 相变。外部冲击可能触发相位跳跃"""
    if event_impact > 0.5 and capital > 0.6:
        return {"phase": "Ω", "delta_capital": -0.4, "delta_conn": -0.3}
    elif capital > 0.8 and connectedness > 0.8:
        # 过于僵化 → 自发起的崩溃
        return {"phase": "Ω", "delta_capital": -0.3, "delta_conn": -0.2}
    else:
        # 正常推进
        return {"phase": "progress", "delta_capital": 0.02, "delta_conn": 0.01}

# ============================================================
# 8. 信息论 (INFORMATION_THEORY.md)
# ============================================================

def shannon_entropy(probabilities: List[float], base: float = 2.0) -> float:
    """H(X) = -Σ p(x) · log p(x) — 不确定性/意外度"""
    H = 0.0
    for p in probabilities:
        if p > 0:
            H -= p * math.log(p, base)
    return H

def kl_divergence(p: List[float], q: List[float], base: float = 2.0) -> float:
    """D_KL(P||Q) — NPC认知偏差 / 信息失真"""
    dk = 0.0
    for pi, qi in zip(p, q):
        if pi > 0:
            if qi <= 0:
                return float('inf')
            dk += pi * math.log(pi / qi, base)
    return dk

def event_information(probability: float, base: float = 2.0) -> float:
    """I(E) = -log P(E) — 叙事权重。小概率事件权重更高"""
    if probability <= 0:
        return float('inf')
    return -math.log(probability, base)

def memory_retrieval_score(recency: float, importance: float, relevance: float,
                           alpha: float = 0.33, beta: float = 0.33, gamma: float = 0.33) -> float:
    """记忆检索评分 = α·recency + β·importance + γ·relevance"""
    return alpha * recency + beta * importance + gamma * relevance

# ============================================================
# 9. PID 控制器 (天道负反馈)
# ============================================================

class PIDController:
    def __init__(self, Kp: float, Ki: float, Kd: float, integral_limit: float = 100.0):
        self.Kp, self.Ki, self.Kd = Kp, Ki, Kd
        self.integral_limit = integral_limit
        self.integral = 0.0
        self.prev_error = 0.0
    
    def step(self, setpoint: float, measured: float, dt: float = 1.0) -> Dict:
        error = setpoint - measured
        self.integral += error * dt
        # 积分限幅 (anti-windup)
        self.integral = max(-self.integral_limit, min(self.integral_limit, self.integral))
        derivative = (error - self.prev_error) / max(dt, 0.001)
        output = self.Kp * error + self.Ki * self.integral + self.Kd * derivative
        self.prev_error = error
        return {"output": output, "error": error, "integral": self.integral}
