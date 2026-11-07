"""
系统反馈 / 控制论规则 (Systems & Cybernetics)

基于: 控制论与复杂系统文献（Meadows 杠杆点 / Maturana 自创生 /
      Perrow 正常事故理论 / Latour 行动者网络 / Panarchy 适应性循环）
包含: 负反馈环, 二阶控制论, 杠杆点 (Meadows 12),
       系统动力学, 全局稳定性
"""

import math
from typing import List, Dict

# ============================================================
# 1. Meadows 12 杠杆点 (按效力升序)
# ============================================================

LEVERAGE_POINTS = {
    1:  {"name": "numbers",         "desc": "数值参数（最低效力）"},
    2:  {"name": "buffers",         "desc": "稳定缓冲"},
    3:  {"name": "stock_flow",      "desc": "存量-流量结构"},
    4:  {"name": "delays",          "desc": "延迟长度"},
    5:  {"name": "feedback",        "desc": "负反馈强度"},
    6:  {"name": "feedback_pos",    "desc": "正反馈强度"},
    7:  {"name": "info_flow",       "desc": "信息流结构"},
    8:  {"name": "rules",           "desc": "系统规则"},
    9:  {"name": "self_org",        "desc": "自组织能力"},
    10: {"name": "goals",           "desc": "系统目标"},
    11: {"name": "paradigm",        "desc": "系统范式"},
    12: {"name": "transcend",       "desc": "超越范式（最高效力）"},
}

def leverage_effectiveness(tier: int) -> float:
    """
    杠杆点效力 0~1
    低阶: 玩家"逆天"可以撬动 1-3 阶
    高阶: 需要悟道/身份转换
    """
    # 使用对数缩放（高阶效力递增缓慢）
    return min(1.0, math.log(tier + 1) / math.log(13))

def counter_leverage_resistance(tier: int, tian_dao_power: float) -> float:
    """天道对玩家逆天行为的压制效力"""
    base_resistance = leverage_effectiveness(tier)
    # 天道在高阶杠杆时更强压制
    return min(1.0, base_resistance * (1 + tian_dao_power * 0.3))

# ============================================================
# 2. 二阶控制论 (Von Foerster / Maturana)
# ============================================================

def observe_observer_bias(player_belief: float, reality: float) -> float:
    """
    二阶效应:玩家的观察本身改变了被观察的系统
    bias = belief - reality 即理解为"玩家对世界的影响量"
    """
    return player_belief - reality

def autopoiesis_stability(self_reproduction_rate: float, 
                           boundary_integrity: float,
                           external_pressure: float) -> Dict:
    """
    自组织临界性 / 自创生系统的稳定性
    过于封闭 → 僵化; 过于开放 → 解体
    """
    viability = self_reproduction_rate * boundary_integrity / max(0.01, external_pressure)
    if viability > 1.5:
        return {"state": "rigid", "risk": "停滞僵化", "viability": viability}
    elif viability > 0.7:
        return {"state": "healthy", "risk": "平衡", "viability": viability}
    elif viability > 0.3:
        return {"state": "strained", "risk": "承压", "viability": viability}
    else:
        return {"state": "dissolving", "risk": "解体风险", "viability": viability}

# ============================================================
# 3. 修炼能量学 (从 TECH_REFERENCE 物理部分)
# ============================================================

def cultivation_energy_balance(qi_absorbed: float, body_cost: float,
                               spell_cost: float, waste: float) -> float:
    """ΔU = Q_in — W_body — W_spell — W_waste"""
    return qi_absorbed - body_cost - spell_cost - waste

def boltzmann_entropy(microstates: int, k_B: float = 1.0) -> float:
    """S = k_B · ln Ω"""
    return k_B * math.log(max(1, microstates))

# ============================================================
# 4. 紧耦合系统级联 (Perrow NAT, Normal Accident Theory)
# ============================================================

class TightlyCoupledSystem:
    """紧耦合系统 — 大劫不可避免论"""
    def __init__(self, components: List[str], interactions: List[tuple]):
        self.components = components
        self.interactions = interactions  # (from, to, strength)
        self.failed = set()
    
    def coupling_degree(self) -> float:
        """系统耦合度"""
        n_direct = len(self.interactions)
        n_total = max(1, len(self.components))
        return n_direct / n_total * 2  # 归一化到大致 0-1
    
    def cascade_step(self, failed_set: set, threshold: float = 0.3) -> set:
        """一步级联故障"""
        new_failed = set(failed_set)
        for src, dst, strength in self.interactions:
            if src in failed_set and dst not in failed_set:
                if strength > threshold:
                    new_failed.add(dst)
        return new_failed
    
    def total_collapse_time(self, initial_failure: set, threshold: float = 0.3) -> int:
        """模拟级联直到稳定"""
        current = set(initial_failure)
        steps = 0
        while True:
            next_set = self.cascade_step(current, threshold)
            if next_set == current:
                break
            current = next_set
            steps += 1
            if steps > 100:
                break
        return steps

# ============================================================
# 5. 行动者网络理论 (Actor-Network Theory, Latour 2005)
# ============================================================

def actor_network_power(represented_counts: List[int], credibility: List[float]) -> float:
    """行动者网络力量 = Σ n_i × c_i"""
    return sum(n * c for n, c in zip(represented_counts, credibility))

def interpretive_flexibility(interpretations: List[str]) -> float:
    """解释弹性 IF(T) = distinct / total"""
    return len(set(interpretations)) / max(1, len(interpretations))

def maintenance_priority(political_grievance: float, recent_breakdown: float,
                         budget_available: float) -> float:
    """维护优先级 = 不满×故障×预算"""
    return political_grievance * recent_breakdown * budget_available
