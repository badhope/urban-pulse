"""
模型层 (Model Layer) —— 命名闭式公式目录

用途: 宿主 AI 不再每回合"看文章去推理", 而是直接调一个命名模型算出效果。
每个模型是一个小纯函数, 确定性: 需要随机的模型一律显式接收 `u`(标准正态)或
`x`(0~1 均匀)参数, 由宿主注入引擎的受控随机 (mcp_server._seed_rng), 保证
"同 state + 同 tick + 同输入 = 同结果"。

域: economics / population / epidemiology / probability / thermodynamics /
     opinion_dynamics / momentum

调用方式:
    from game_engine.rules.models import model
    model("ou_price", price=37, base=30, theta=0.15, sigma=0.0, dW=0.0)
    -> {"model": "ou_price", "value": ..., "formula": "x' = x - theta*(x-theta0)*dt + sigma*dW"}

    或直接取函数:
    from game_engine.rules.models import lotka_volterra, sir_step, logistic_growth
"""

import math


# ============================================================
# economics
# ============================================================

def ou_price(price: float, base: float, theta: float = 0.15, sigma: float = 0.0, dW: float = 0.0) -> float:
    """Ornstein-Uhlenbeck 均值回归一步: x' = x + (-theta*(x-base) + sigma*dW)*1。

    替代原来 tick_market 里粗糙的 `int(price*0.95)`。价格被大宗交易推离 base 后,
    每回合按指数规律被拉回 base, 离得越远回归力越强 (非线性), 不会像线性 0.95 那样
    在贴地时死守 0。theta 越大回归越快; sigma*dW 是随机扰动 (宿主注入 dW)。
    """
    pull = -theta * (price - base)
    return price + pull + sigma * dW


def ou_price_reverted(price: float, base: int, theta: float = 0.15) -> int:
    """OU 的确定性整数版 (sigma=0), 供 tick 自动演化用: 保证 0<=结果 且贴 base 收敛。"""
    nxt = ou_price(price, float(base), theta, 0.0, 0.0)
    return max(0, int(round(nxt)))


def lerner_price(cogs: float, elasticity: float) -> float:
    """Lerner 规则定价: (P-MC)/P = 1/ε  =>  P = MC * ε/(ε-1)。

    需求弹性 ε>1 (弹性需求) 才有意义; ε->1+ 时 P 趋于无穷 (卖方垄断), 宿主应按世界常识截断。
    """
    if cogs <= 0:
        return 0.0
    if elasticity <= 1.0:
        return float("inf")
    return cogs * elasticity / (elasticity - 1.0)


def cobb_douglas(labor: float, capital: float, alpha: float = 0.6, beta: float = 0.4, A: float = 1.0) -> float:
    """Cobb-Douglas 生产曲线: Y = A * L^α * K^β。用来估"药田/矿脉/猎兽"的产能上限。"""
    L = max(0.0, labor)
    K = max(0.0, capital)
    if L == 0 or K == 0:
        return 0.0
    return A * (L ** alpha) * (K ** beta)


# ============================================================
# population / ecology (棋局线: 势力消长)
# ============================================================

def logistic_growth(n: float, r: float, K: float, dt: float = 1.0) -> float:
    """Logistic: N' = N + r*N*(1-N/K)*dt。带环境容量 K 的势力人口/声望增长, 封顶 K。"""
    if K <= 0:
        return n
    return n + r * n * (1.0 - n / K) * dt


def lotka_volterra(prey: float, predator: float, a: float = 0.0, b: float = 0.2,
                   c: float = 0.2, d: float = 0.0, dt: float = 1.0) -> tuple:
    """Lotka-Volterra 捕食者-猎食者一步 (Euler):

    dP/dt = aP - b*P*R   (猎食者自然增长 a, 被捕食率 b)
    dR/dt = c*P*R - d*R  (捕食者靠猎食 c, 自然死亡 d)

    对应"宗门与散修/世家与寒门"的相互制约: 谁吃谁、谁被谁压制, 会自己摆荡。
    返回 (prey', predator')。
    """
    dp = a * prey - b * prey * predator
    dr = c * prey * predator - d * predator
    return (prey + dp * dt, predator + dr * dt)


# ============================================================
# epidemiology (谣言/「元力流失」事件传播)
# ============================================================

def sir_step(s: float, i: float, r: float, beta: float, gamma: float, dt: float = 1.0) -> tuple:
    """SIR 一步: 易感 S / 感染 I / 恢复 R (归一到 1 的占比)。

    dI = beta*S*I - gamma*I;  dS = -beta*S*I;  dR = gamma*I。
    beta*Σ(S/I) 判断谣言是否压得住——这就是下面 R0 的用途。
    """
    total = s + i + r
    if total <= 0:
        return (s, i, r)
    s /= total; i /= total; r /= total
    flow = beta * s * i * dt
    recov = gamma * i * dt
    s2 = max(0.0, s - flow)
    i2 = max(0.0, i + flow - recov)
    r2 = max(0.0, r + recov)
    return (s2, i2, r2)


def basic_reproduction(beta: float, gamma: float) -> float:
    """R0 = β/γ。R0>1 谣言会自扩散, <1 会自行熄灭。宿主拿它决定要不要"灭火"。"""
    if gamma <= 0:
        return float("inf")
    return beta / gamma


# ============================================================
# probability / stochastic (确定性期望版)
# ============================================================

def hazard_cumulative(hazard: float, t: float) -> float:
    """泊松过程累积概率 P(≥1 次) = 1 - e^(-λt)。用于"天劫/厄运何时降临"的期望估计。"""
    if hazard <= 0 or t <= 0:
        return 0.0
    return 1.0 - math.exp(-hazard * t)


def logistic_sigmoid(x: float, x0: float = 0.0, k: float = 1.0) -> float:
    """S 曲线 P = 1/(1+e^(-k*(x-x0)))。把"业债总量/心境值"映射成"走火入魔概率"等 0~1 效果。"""
    z = -k * (x - x0)
    if z > 350:
        return 0.0
    if z < -350:
        return 1.0
    return 1.0 / (1.0 + math.exp(z))


def inverse_survival(hazard: float, t: float) -> float:
    """存活曲线 P(未发生) = e^(-λt)。与 hazard_cumulative 互补, 用于"还能撑几回合"。"""
    if hazard <= 0 or t <= 0:
        return 1.0
    return math.exp(-hazard * t)


# ============================================================
# thermodynamics / momentum (物理味: 冷却/震荡/势阱)
# ============================================================

def thermal_relaxation(x: float, x_eq: float, tau: float, dt: float = 1.0) -> float:
    """牛顿冷却: x' = x_eq + (x - x_eq)*e^(-dt/tau)。心魔/怒气/元力浓度向平衡态松弛。tau 越大越缓。"""
    if tau <= 0:
        return x_eq
    return x_eq + (x - x_eq) * math.exp(-dt / tau)


def harmonic_step(pos: float, vel: float, omega: float, dt: float = 0.1) -> tuple:
    """简谐震荡一步 (x 绕 0 摆, 加速度 -ω²x)。用于心境在"亢奋/低落"间周期性摆荡。

    x'' = -ω²x;  半步 Euler: x += v*dt; v += -ω²*x*dt。返回 (pos', vel')。
    """
    new_pos = pos + vel * dt
    new_vel = vel - (omega * omega) * pos * dt
    return (new_pos, new_vel)


def inverse_square(magnitude: float, distance: float, k: float = 1.0) -> float:
    """逆平方: F = k*M/d²。影响/威压/气息随距离衰减 (远处的人感受到的威势)。"""
    d = max(0.001, distance)
    return k * magnitude / (d * d)


def exponential_decay(x0: float, rate: float, t: float) -> float:
    """衰减律 x = x0*e^(-rate*t)。灵气浓度/记忆鲜活度/伤势随时间消退 (大气学里"痕量气体扩散"同型)。"""
    return x0 * math.exp(-rate * t)


# ============================================================
# opinion dynamics (棋局线舆论漂移)
# ============================================================

def deffuant_update(agent_op: float, neighbors: list, mu: float = 0.1) -> float:
    """Deffuant 有界信任: 与"观点差距 ≤ μ"的邻居向彼此均值靠拢一步, 太远则不动。

    agent_op: 该实体当前观点; neighbors: 邻居观点列表; mu: 有界信任阈值。
    返回值: 更新后的观点。用于"学宫名额分配越来越向某世家倾斜"这种缓慢共识漂移。
    """
    reachable = [n for n in neighbors if abs(n - agent_op) <= mu]
    if not reachable:
        return agent_op
    target = sum(reachable) / len(reachable)
    step = 0.5 * (target - agent_op)
    return agent_op + step


# ============================================================
# 注册表 + 统一入口
# ============================================================

MODELS = {
    "ou_price": {"fn": ou_price, "domain": "economics",
                 "formula": "x' = x + (-theta*(x-base) + sigma*dW)",
                 "desc": "价格均值回归 (Ornstein-Uhlenbeck), 替代线性 0.95",
                 "use": "大宗交易后估算下回合价格"},
    "ou_price_reverted": {"fn": ou_price_reverted, "domain": "economics",
                          "formula": "round(max(0, ou_price))",
                          "desc": "tick 自动市场演化的确定性回归步",
                          "use": "每回合 tick_market 用"},
    "lerner_price": {"fn": lerner_price, "domain": "economics",
                     "formula": "P = MC * ε/(ε-1)",
                     "desc": "按需求弹性定价 (Lerner 规则)",
                     "use": "拍卖/垄断货的成交价"},
    "cobb_douglas": {"fn": cobb_douglas, "domain": "economics",
                     "formula": "Y = A·L^α·K^β",
                     "desc": "产能曲线 (药田/矿脉/猎兽)",
                     "use": "估一条采集线单回合产出"},
    "logistic_growth": {"fn": logistic_growth, "domain": "population",
                       "formula": "N' = N + r·N·(1-N/K)",
                       "desc": "带环境容量的势力增长",
                       "use": "势力声望/人口向 K 收敛"},
    "lotka_volterra": {"fn": lotka_volterra, "domain": "population",
                       "formula": "dP=aP-bPR; dR=cPR-dR",
                       "desc": "捕食者-猎食者摆荡 (宗门 vs 散修)",
                       "use": "两方势力相互制约的消长"},
    "sir_step": {"fn": sir_step, "domain": "epidemiology",
                 "formula": "dI=βSI-γI",
                 "desc": "谣言/事故传播一步",
                 "use": "「元力流失」怪事在城中扩散"},
    "basic_reproduction": {"fn": basic_reproduction, "domain": "epidemiology",
                           "formula": "R0 = β/γ",
                           "desc": "判断谣言是否压得住",
                           "use": "R0>1 需灭火"},
    "hazard_cumulative": {"fn": hazard_cumulative, "domain": "probability",
                         "formula": "P=1-e^(-λt)",
                         "desc": "天劫/厄运 t 回合内降临概率",
                         "use": "业债越重 λ 越大"},
    "logistic_sigmoid": {"fn": logistic_sigmoid, "domain": "probability",
                         "formula": "P=1/(1+e^(-k(x-x0)))",
                         "desc": "把累积量映射成 0~1 效果概率",
                         "use": "业债->走火入魔概率"},
    "inverse_survival": {"fn": inverse_survival, "domain": "probability",
                         "formula": "P=e^(-λt)",
                         "desc": "还能撑 t 回合的期望",
                         "use": "追杀/围剿的存活估计"},
    "thermal_relaxation": {"fn": thermal_relaxation, "domain": "thermodynamics",
                          "formula": "x'=xe+(x-xe)e^(-dt/τ)",
                          "desc": "心魔/怒气/浓度向平衡松弛",
                          "use": "负面情绪随时间消退"},
    "harmonic_step": {"fn": harmonic_step, "domain": "thermodynamics",
                      "formula": "x''=-ω²x",
                      "desc": "心境周期性摆荡",
                      "use": "亢奋<->低落的震荡"},
    "inverse_square": {"fn": inverse_square, "domain": "momentum",
                       "formula": "F=kM/d²",
                       "desc": "威势随距离衰减",
                       "use": "远处感受到的强者气息"},
    "exponential_decay": {"fn": exponential_decay, "domain": "thermodynamics",
                          "formula": "x=x0·e^(-rate·t)",
                          "desc": "灵气/记忆/伤势衰减",
                          "use": "痕量扩散同型 (大气学)"},
    "deffuant_update": {"fn": deffuant_update, "domain": "opinion_dynamics",
                        "formula": "x' = x + 0.5*(mean(reachable)-x)",
                        "desc": "有界信任舆论漂移",
                        "use": "名额/共识向某方倾斜"},
}


def model(name: str, **params) -> dict:
    """统一入口: model('lotka_volterra', prey=8, predator=3) -> {model, value, formula, desc}。

    未知模型名 -> KeyError(带可用清单)。返回把闭式结果包一层, 宿主可直接读"效果"。
    非有限结果（如 Lerner 在弹性 <=1 时的 inf）直接报错：JSON 的 Infinity
    不是合法 JSON，严格客户端解析会失败，也会污染 Agent 的判断。
    """
    if name not in MODELS:
        raise KeyError("未知模型 %r; 可用: %s" % (name, ", ".join(sorted(MODELS))))
    meta = MODELS[name]
    value = meta["fn"](**params)
    _nums = list(value) if isinstance(value, (list, tuple)) else [value]
    for v in _nums:
        if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
            raise ValueError("模型 %s 的参数产生了非有限结果（%r），请检查输入" % (name, v))
    return {"model": name, "domain": meta["domain"], "formula": meta["formula"],
            "desc": meta["desc"], "value": value}


def model_names() -> list:
    """列出全部命名模型 (宿主 world_schema / 文档用)。"""
    return [
        {"name": n, "domain": m["domain"], "formula": m["formula"],
         "desc": m["desc"], "use": m["use"]}
        for n, m in sorted(MODELS.items())
    ]
