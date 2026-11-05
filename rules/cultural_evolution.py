"""
文化进化规则 (Cultural Evolution)

基于: 文化进化理论文献（Boyd & Richerson 双重继承 / Dawkins 模因学 /
      Tomasello-Henrich 累积文化 / Eerkens-Lipo 三维变异）
包含: 双重继承(Boyd-Richerson), 模因学(Dawkins/Blackmore),
      文化群体选择, 累积文化(Tomasello/Henrich),
      三维变异(Eerkens-Lipo), 精神分析重构

依赖约束: 仅标准库（ARCHITECTURE.md §2），矩阵运算纯 Python 实现。
"""

import math, random
from typing import List

# ============================================================
# 1. 双重继承理论 (Boyd & Richerson 1985)
# ============================================================

def cultural_frequency_change(p: float, alphas: List[float], B: List[float],
                              C: float, mu: float) -> float:
    """Δp = p(1-p)·[Σ α_i·B_i - C] + μ(1-2p)"""
    biased_pressure = sum(a * b for a, b in zip(alphas, B)) - C
    mutation_term = mu * (1 - 2 * p)
    return p * (1 - p) * biased_pressure + mutation_term

def meme_fitness(L_m: float, Fec_m: float, Fid_m: float) -> float:
    """模因适应度 = 长寿度 × 繁殖力 × 复制保真度"""
    return L_m * Fec_m * Fid_m

def sect_cultural_fitness(Std_j: float, Coop_j: float, I_j: float,
                          I_region_mean: float, alpha: float = 0.33,
                          beta: float = 0.33, gamma: float = 0.34) -> float:
    """宗门文化适应度 Φ_j"""
    return alpha * (1.0 / (Std_j + 1e-9)) + beta * Coop_j + gamma * (I_j / (I_region_mean + 1e-9))

def cultural_transmission_update(p_t: List[float], T: List[List[float]]) -> List[float]:
    """p_{t+1} = T · p_t（纯 Python 矩阵-向量乘）"""
    return [sum(row[j] * p_t[j] for j in range(len(p_t))) for row in T]

def vertical_transmission_prob(both_parent: bool, one_parent: bool, mutant_prob: float) -> float:
    """血脉特质遗传概率"""
    if both_parent:
        return 1.0 - mutant_prob
    elif one_parent:
        return 0.5 * (1.0 - mutant_prob)
    return mutant_prob

# ============================================================
# 2. 偏见驱动的采纳决策
# ============================================================

def adopt_probability(g_c: float, p: float, pi_j: float, sim_ij: float,
                      alpha_c: float = 0.5, beta_p: float = 0.3, gamma_s: float = 0.2) -> float:
    """内容偏见×从众×权威×相似性"""
    return g_c * (p ** alpha_c) * (pi_j ** beta_p) * (sim_ij ** gamma_s)

# ============================================================
# 3. 功法传承系统
# ============================================================

def method_transmission(master_trait: float, comprehension: float, sigma: float = 1.0) -> float:
    """T_disciple = T_master + N(0, σ² × (100/comprehension))"""
    sigma_actual = sigma * (100.0 / max(1.0, comprehension))
    return master_trait + random.gauss(0, sigma_actual)

def cumulative_fidelity(f0: float, n: int, lambda_drift: float = 0.01, t: float = 1.0) -> float:
    """n步传递后保真度 = f0^n · exp(-λt)"""
    return (f0 ** n) * math.exp(-lambda_drift * t)

def ratchet_product(S: float, I: float, T: float) -> float:
    """文化棘轮强度 R = S × I × T"""
    return S * I * T

def next_generation_quality(Q_n: float, epsilon: float, eta: float) -> float:
    """Q_{n+1} = Q_n + ε + η"""
    return Q_n + epsilon + eta

# ============================================================
# 4. 三要素变异
# ============================================================

def total_cultural_variation(V_production: float, V_copying: float, V_transmission: float) -> float:
    """V_total = V_prod + V_copy + V_trans"""
    return V_production + V_copying + V_transmission

# ============================================================
# 5. BwO / 精神分析重构
# ============================================================

def body_without_organs(omega_desire: float, territorializations: List[float],
                        deterritorializations: List[float]) -> float:
    """BwO 状态 = 欲望流 — Σ约束 + Σ解域"""
    return omega_desire - sum(territorializations) + sum(deterritorializations)
