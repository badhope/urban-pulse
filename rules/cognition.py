"""
认知科学规则 (Cognition)

基于: 认知科学文献（Kahneman 双系统 / 前景理论 / ACT-R / 心流理论等
      7 个核心理论, 21 个公式）
包含: 双系统理论, 前景理论, ACT-R记忆, 有限理性, 心流/沉浸, 具身认知
"""

import math, random
from typing import List, Dict, Tuple, Callable, Any

# ============================================================
# 1. 双系统理论 (Kahneman 2011)
# ============================================================

def inhibition_ability(spirituality: float, mental_clarity: float, training_in_reasoning: float) -> float:
    """System 2 抑制 System 1 的能力。返回值需与 random.random() 比较判定成功"""  # nosec B311 —— 游戏骰子，非密码学用途
    return (spirituality * 1.0 + mental_clarity * 0.8 + training_in_reasoning * 0.5) / 2.3

def daily_cognitive_budget(realm_level: int, mental_state: str) -> float:
    """每日认知能耗预算。耗尽后强制退化到 System 1（冲动/偏见）"""
    state_mod = {"充沛": 1.2, "正常": 1.0, "疲惫": 0.6, "走火入魔边缘": 0.2}
    return 100.0 * (1.0 + realm_level * 0.3) * state_mod.get(mental_state, 1.0)

def should_use_system2(inhibition_budget: float, mental_clarity: float, noise: float = 0.0,
                      roll: float | None = None) -> bool:
    """判定当前是否启用 System 2（慢思考）。

    预算必须参与判定：旧实现完全忽略 inhibition_budget，导致"预算耗尽强制退化"
    的设计从未生效（实测 budget=1 与 budget=100000 输出分布相同）。
    这里把预算映射成 0..1 的可用度乘到抑制能力上。

    `roll` 供只读查询使用：传入 0..1 的确定性伪随机量后不再读全局 random，
    这样 `status` 在同一状态上多次查询得到同一答案（只读工具不该有抖动）。
    """
    ability = inhibition_ability(mental_clarity, mental_clarity * 0.8, 0.3)
    try:
        budget = max(0.0, float(inhibition_budget))
    except (TypeError, ValueError):
        budget = 0.0
    # 预算 0 → 0 倍；100 及以上视为充足；对数尺度避免高等级瞬间封顶
    budget_factor = min(1.0, math.log1p(budget) / math.log1p(100.0))
    p_system2 = (ability * budget_factor) / (ability * budget_factor + 1.0)
    sample = random.random() if roll is None else max(0.0, min(1.0, float(roll)))
    return (sample + noise) < p_system2  # nosec B311 —— 游戏骰子，非密码学用途

# ============================================================
# 2. 前景理论 (Prospect Theory, Kahneman & Tversky 1979)
# ============================================================

def value_function(change: float, alpha: float = 0.88, beta: float = 0.88, lam: float = 2.25) -> float:
    """前景理论价值函数。损失被放大 ≈2.25 倍"""
    if change >= 0:
        return change ** alpha
    else:
        return -lam * ((-change) ** beta)

def probability_weighting(p: float, gamma: float) -> float:
    """决策权重函数。gamma 受悟性调节，越高越理性"""
    if p <= 0 or p >= 1:
        return p
    return (p ** gamma) / ((p ** gamma + (1 - p) ** gamma) ** (1.0 / gamma))

def decision_utility(options: List[Dict], gamma: float = 0.65,
                     alpha: float = 0.88, beta: float = 0.88, lam: float = 2.25) -> List[Tuple[Dict, float]]:
    """
    综合前景效用。返回 (option, utility) 排序列表。
    每个 option = {"outcomes": [{"probability": 0.3, "value": 100}, ...]}
    """
    results = []
    for opt in options:
        V = 0.0
        for outcome in opt.get("outcomes", []):
            p = outcome["probability"]
            x = outcome["value"]
            w = probability_weighting(p, gamma)
            v = value_function(x, alpha, beta, lam)
            V += w * v
        results.append((opt, V))
    results.sort(key=lambda x: x[1], reverse=True)
    return results

def realm_dampening(realm_level: int) -> float:
    """高阶修士对同等得失感知减弱（麻木效应）"""
    return 1.0 / (1.0 + realm_level * 0.1)

def adaptation_curve(days_since_change: int, boost: float = 2.0, adaptation_days: int = 30) -> float:
    """参考点适应曲线。突破后短期快乐，逐渐回归平淡"""
    if days_since_change >= adaptation_days:
        return 1.0
    return boost - (boost - 1.0) * (days_since_change / adaptation_days)

# ============================================================
# 3. ACT-R 认知架构 (Anderson 2007)
# ============================================================

def total_activation(base_activation: float, attention_weights: Dict[str, float],
                     association_strengths: Dict[str, float]) -> float:
    """A_i = B_i + Σ_j W_j · S_ji （总激活量）"""
    sum_ws = sum(w * association_strengths.get(k, 0.0) for k, w in attention_weights.items())
    return base_activation + sum_ws

def base_activation(access_times: List[float], current_time: float, decay: float = 0.5) -> float:
    """B_i = ln(Σ_k t_k^{-d}) -- 记忆衰减公式"""
    if not access_times:
        return -float('inf')
    sum_decay = sum(max(0.01, current_time - t) ** (-decay) for t in access_times if t < current_time)
    if sum_decay <= 0:
        return -float('inf')
    return math.log(sum_decay)

def conflict_resolution_prob(utilities: List[float], temperature: float = 1.0) -> List[float]:
    """P(rule_i) = e^(u_i/τ) / Σ_j e^(u_j/τ) -- Softmax 规则选择"""
    if not utilities:
        return []
    tau = max(temperature, 1e-6)  # 防止除零
    max_u = max(utilities)
    exp_u = [math.exp((u - max_u) / tau) for u in utilities]
    total = sum(exp_u)
    return [e / total for e in exp_u]

def skill_execution_time(base_time: float, skill_level: float, alpha: float = 0.4) -> float:
    """T = T_0 × skill_level^{-0.4} -- 幂律学习曲线"""
    return base_time * (max(0.01, skill_level) ** (-alpha))

def skill_success_probability(skill_level: float, difficulty: float) -> float:
    """P(success) = 1 / (1 + e^{-(skill_level - difficulty)}) -- Logistic 成功率"""
    return 1.0 / (1.0 + math.exp(-(skill_level - difficulty)))

def recall_probability(activation: float, threshold: float) -> float:
    """P(recall) = 1 / (1 + e^{-(A_i / threshold)}) -- 记忆召回概率"""
    return 1.0 / (1.0 + math.exp(-activation / max(0.1, threshold)))

# ============================================================
# 4. 具身认知 (4E)
# ============================================================

def true_comprehension(theoretical_knowledge: float, embodied_practice: float) -> float:
    """true = theory × practice。知行合一，任一为零则乘积为零"""
    return theoretical_knowledge * embodied_practice

# ============================================================
# 5. 有限理性 (Bounded Rationality)
# ============================================================

def satisficing_choice(options: List[Any], eval_func: Callable, aspiration: float,
                       max_explore: int = 100) -> Dict:
    """Simon 满意化：找到够好的就停"""
    opts = list(options)  # 复制，避免修改调用方数据
    random.shuffle(opts)  # nosec B311 —— 游戏骰子，非密码学用途
    explored = 0
    best_seen = None
    best_val = -float('inf')
    for opt in opts[:max_explore]:
        val = eval_func(opt)
        explored += 1
        if val >= aspiration:
            return {"choice": opt, "explored": explored, "confidence": 0.8, "satisfied": True}
        if val > best_val:
            best_val = val
            best_seen = opt
    return {"choice": best_seen, "explored": explored, "confidence": 0.4 if best_seen else 0.0, "satisfied": False}

def equal_division(resources: float, n_options: int) -> List[float]:
    """Diversify 1/N: 悟性低的修士面对多种选择时的等权分配"""
    if n_options <= 0:
        return []
    return [resources / n_options] * n_options

# ============================================================
# 6. 心流 / 沉浸 (Flow, Csikszentmihalyi; Björk & Holopainen)
# ============================================================

MODALITY_WEIGHTS = {"visual": 0.35, "auditory": 0.25, "olfactory": 0.10, "tactile": 0.20, "gustatory": 0.10}

def sensory_immersion(senses_covered: Dict[str, float], style_coherence: float = 1.0) -> float:
    """感官沉浸度 = Σ(感官覆盖 × 权重) × 风格一致性"""
    score = sum(senses_covered.get(s, 0.0) * w for s, w in MODALITY_WEIGHTS.items())
    return min(1.0, score * style_coherence)

def flow_state(flow_ratio: float) -> Dict:
    """
    判定玩家当前心理状态。
    flow_ratio = challenge / skill
    Returns {"state": "flow"/"anxiety"/"boredom", "immersion": 0-1}
    """
    if abs(flow_ratio - 1.0) < 0.15:
        return {"state": "flow", "immersion": 1.0}
    elif flow_ratio > 1.3:
        return {"state": "anxiety", "immersion": max(0.1, 1.0 - (flow_ratio - 1.0))}
    elif flow_ratio < 0.7:
        return {"state": "boredom", "immersion": max(0.1, flow_ratio / 0.7)}
    else:
        return {"state": "flow", "immersion": 0.8}

def total_immersion_metric(sensory: float, challenge: float, imaginative: float) -> float:
    """总沉浸度 = 几何平均。任一维度趋近 0 则整体趋近 0"""
    product = max(0.001, sensory) * max(0.001, challenge) * max(0.001, imaginative)
    return product ** (1.0 / 3.0)

def adjust_difficulty(win_rate: float, target: float = 0.65, adj_rate: float = 0.05,
                      max_offset: float = 0.3, current_offset: float = 0.0) -> Dict:
    """
    暗中调节难度，让胜率趋近 target。
    当 win_rate < 0.3 时触发隐藏机缘（否极泰来）。
    """
    delta = adj_rate * (target - win_rate)
    new_offset = max(-max_offset, min(max_offset, current_offset + delta))
    trigger_opportunity = win_rate < 0.3
    return {
        "difficulty_offset": new_offset,
        "trigger_opportunity": trigger_opportunity,
        "events": ["暗中调整难度"] if abs(delta) > 0.01 else []
    }

# ============================================================
# 7. 道德框架效应 (Tversky & Shafir 1992)
# ============================================================

FRAMEWORK_BIAS = {"close_victim": 2.5, "distant_victim": 0.8, "statistical_victim": 0.3}

def moral_bias_by_distance(victim_familiarity: str) -> float:
    """高阶长老对低阶弟子生命感知为数字。返回损失框架强度系数"""
    return FRAMEWORK_BIAS.get(victim_familiarity, 1.0)

# ============================================================
# 8. 马斯洛需求层次
# ============================================================

def maslow_dominant_need(satisfaction_levels: List[float],
                          thresholds: List[float] = None) -> int:
    """返回最低未满足需求层级 0-4"""
    if thresholds is None:
        thresholds = [0.8, 0.7, 0.6, 0.5, 0.4]
    for i, (level, th) in enumerate(zip(satisfaction_levels, thresholds)):
        if level < th:
            return i
    return 4  # 自我实现

# ============================================================
# 9. 内在动机 (自我决定理论)
# ============================================================

def intrinsic_motivation(autonomy: float, competence: float, relatedness: float,
                          w_a: float = 1/3, w_c: float = 1/3, w_r: float = 1/3) -> float:
    """IM = w_a·A + w_c·C + w_r·R"""
    return w_a * autonomy + w_c * competence + w_r * relatedness

# ============================================================
# 10. 损失厌恶效用
# ============================================================

def loss_aversion_utility(gain: float, loss: float, lambda_coeff: float = 2.0) -> float:
    """U = gain - λ · |loss|"""
    return gain - lambda_coeff * abs(loss)
