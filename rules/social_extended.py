"""
扩展社交系统 (Social Extended)

基于: 道德心理学与社会心理学文献（Haidt 道德基础 / Tajfel 社会认同 /
      Opotow 道德排除 / Lerner 正义动机 / Bandura 道德推脱 /
      Milgram 服从 / Cialdini 影响力原则）
包含: 六维道德基础(Haidt), 社会认同(Tajfel), 道德排除(Opotow), 
      正义动机(Lerner), 道德推脱(Bandura), 群体服从(Milgram),
      影响力原则(Cialdini), 社会网络分析, 责任扩散
"""

import math
from typing import List, Dict

from game_engine.rules.models import basic_reproduction

# ============================================================
# 1. 道德基础理论 (Moral Foundations Theory, Haidt 2001)
# ============================================================

MORAL_DIMENSIONS = ["care", "fairness", "loyalty", "authority", "sanctity", "liberty"]

def moral_resonance(npc_weights: List[float], action_activations: List[float]) -> float:
    """
    共振值 = Σ w_i × a_i
    正=认可, 负=反对, 接近0=无关
    npc_weights:    NPC在6大道德基础上的权重向量 [0,1]
    action_activations: 行为在6基础上的激活强度 [-1,1]
    """
    return sum(w * a for w, a in zip(npc_weights, action_activations))

def moral_vector_update(player_moral: List[float], delta_action: List[float],
                        dt_days: int, tau: float = 90.0) -> List[float]:
    """玩家道德向量衰减更新: 远期行为影响指数衰减"""
    gamma = math.exp(-dt_days / tau)
    return [p * gamma + d * (1 - gamma) for p, d in zip(player_moral, delta_action)]

def order_chaos_axis(p_auth: float, p_loyal: float, p_free: float) -> float:
    """秩序-混沌轴。正=秩序派, 负=混沌派"""
    return (p_auth + p_loyal - p_free) / 2.0

def altruism_egoism_axis(p_care: float, p_fair: float) -> float:
    """利他-利己轴"""
    return (p_care + p_fair) / 2.0

# ============================================================
# 2. 社会认同理论 (Social Identity Theory, Tajfel & Turner 1979)
# ============================================================

def self_esteem_social(PI: float, SI: float, alpha: float = 0.5, beta: float = 0.5) -> float:
    """自尊 = α·个人认同 + β·社会认同"""
    return alpha * PI + beta * SI

def ingroup_discrimination(is_ingroup: bool) -> float:
    """内群体高区分度 (0.9) vs 外群体同质化 (0.3)"""
    return 0.9 if is_ingroup else 0.3

def cross_identity_tension(identities: List[Dict], conflict_matrix: Dict) -> float:
    """交叉认同张力。高值触发身份撕裂"""
    n = len(identities)
    if n < 2:
        return 0.0
    total = 0.0
    count = 0
    for i in range(n):
        for j in range(i + 1, n):
            key = (identities[i].get("group", ""), identities[j].get("group", ""))
            total += conflict_matrix.get(key, 0.0)
            count += 1
    return total / max(1, count)

# ============================================================
# 3. 道德排除 (Moral Exclusion, Opotow 1990)
# ============================================================

def moral_circle_penetration(base: float, expansions: List[float],
                             contractions: List[float], empathy_mod: float) -> float:
    """玩家对特定群体的道德义务感强度"""
    return base * (1 + sum(expansions)) * (1 - sum(contractions)) * empathy_mod

# ============================================================
# 4. 正义动机 (Justice Motive, Lerner 1980)
# ============================================================

def blame_victim_probability(BJW: float, perceived_threat: float) -> float:
    """责备受害者概率 = BJW × 威胁感"""
    return min(1.0, BJW * perceived_threat)

def justice_response(BJW: float, threat: float, empathy: float) -> str:
    """四种正义反应路径"""
    z = BJW * threat - empathy * 0.5
    defense_prob = 1.0 / (1.0 + math.exp(-z))
    if defense_prob > 0.8:
        return "blame_victim"
    elif defense_prob > 0.5:
        return "reinterpret"
    elif defense_prob > 0.2:
        return "rational_intervene"
    return "existential_crisis"

def bjw_collapse(cumulative_injustice: float, tolerance_threshold: float) -> bool:
    """正当世界信念崩塌 — 触发'天道可疑'叙事线"""
    return cumulative_injustice > tolerance_threshold

# ============================================================
# 5. 道德推脱 (Moral Disengagement, Bandura 1999)
# ============================================================

DISENGAGEMENT_DIMENSIONS = [
    "moral_justification", "euphemistic_label", "advantageous_comparison",
    "displacement_responsibility", "diffusion_responsibility",
    "disregard_consequences", "dehumanization", "blame_victim"
]

def disengagement_probability(threat_esteem: float, superiority: float,
                              authority_pressure: float, emotional_exhaustion: float,
                              gradual: float) -> float:
    """道德推脱激活概率 = 5维均值"""
    return (threat_esteem + superiority + authority_pressure + emotional_exhaustion + gradual) / 5.0

def npc_moral_behavior(intuition: float, reasoning: float, identity: float,
                        alpha: float = 0.6, beta: float = 0.25, gamma: float = 0.15) -> float:
    """三层整合: Final = 0.6×直觉 + 0.25×推理 + 0.15×认同"""
    return alpha * intuition + beta * reasoning + gamma * identity

# ============================================================
# 6. 影响力原则 (Cialdini 7 Principles) + Milgram 服从
# ============================================================

def npc_influence_on_player(satisfactions: List[float], weights: List[float]) -> float:
    """NPC对玩家的总影响力 = Σ(满足度 × 权重)"""
    return sum(s * w for s, w in zip(satisfactions, weights))

def milgram_obedience(base_rate: float = 0.65, proximity_bonus: float = 0.0,
                      authority_level: float = 1.0, peer_defiance: float = 0.0) -> float:
    """
    Milgram 服从概率。基础 65%，受权威可见度/同辈反抗影响
    proximity_bonus: 权威越近越高 (+0.0~+0.15)
    authority_level: 权威等级乘数
    peer_defiance: 他人反抗削弱 (-0.0~-0.3)
    """
    return max(0.0, min(1.0, base_rate + proximity_bonus) * authority_level + peer_defiance)

def utility_action_score(factors: List[float], weights: List[float], noise: float = 0.0) -> float:
    """效用 AI 评分 = Σ(Factor × Weight) + Noise"""
    return sum(f * w for f, w in zip(factors, weights)) + noise

# ============================================================
# 7. 社会网络分析
# ============================================================

def preferential_attachment(degree_i: int, all_degrees: List[int]) -> float:
    """BA 无标度网络优先连接: Π(k_i) = k_i / Σ_j k_j"""
    total = sum(all_degrees)
    return degree_i / total if total > 0 else 0.0

def ws_characteristic_path_length(N: int, K: int) -> float:
    """小世界特征路径长度: L ≈ ln(N)/ln(K)"""
    return math.log(N) / math.log(K)

def basic_reproduction_number(infection_rate: float, recovery_rate: float) -> float:
    """R_0 = β/γ — 信息传播阈值（与模型层 models.basic_reproduction 同式，转调保单一实现）"""
    return basic_reproduction(infection_rate, recovery_rate)

def modularity(adjacency: List[List[int]], communities: List[int]) -> float:
    """模块度 Q — 派系自动检测"""
    n = len(adjacency)
    m = sum(sum(row) for row in adjacency) // 2
    if m == 0:
        return 0.0
    degrees = [sum(row) for row in adjacency]
    Q = 0.0
    for i in range(n):
        for j in range(n):
            if communities[i] == communities[j]:
                Q += adjacency[i][j] - (degrees[i] * degrees[j]) / (2 * m)
    return Q / (2 * m)

# ============================================================
# 8. 共谋/集体推脱
# ============================================================

def collective_disengagement(leader_depth: float, ritual_frequency: float,
                             outgroup_stereotype: float, gradational: float) -> float:
    """宗门集体推脱水平 = 四维度最大值（木桶原理在恶意层面的应用）"""
    return max(leader_depth, ritual_frequency, outgroup_stereotype, gradational)

# ============================================================
# 9. 功德 / 共情资源
# ============================================================

def merit_quality(actual_aid: float, sincerity: float) -> float:
    """功德 = aid × (0.4 + 0.6 × sincerity) — 真善 vs 交易"""
    return actual_aid * (0.4 + 0.6 * sincerity)

def empathy_pool_delta(current_E: float, event_drain: float, recovery_rate: float = 0.1) -> float:
    """共情资源池更新"""
    return max(0.0, current_E - event_drain * recovery_rate)

def is_altruistic(help_persistence: float, escape_cost: float, cost_sensitivity: float) -> str:
    """Batson 判别器"""
    if help_persistence > 0.5 and escape_cost > 0.5:
        return "altruistic"
    elif cost_sensitivity > 0.6:
        return "egoistic"
    return "ambiguous"
