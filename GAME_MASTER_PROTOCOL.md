# World Games 主持协议 (AI → 引擎调用约定 v3)

> 核心原则:**所有确定性计算交给引擎,Agent 只负责文学叙事与对话**。
>
> **v3 变化**：新增通用判定（`roll`）、游戏档案（`game_*`）、上下文台账（`context_*`）、存档库（`session_*`）四组工具。
> 工具既包括角色扮演式结算，也包括适用于不同题材的通用能力。

> **MCP 模式**：宿主是 MCP 客户端（Claude Code / Codex / Cursor 等）时，用 `mcp_server.py`
> 暴露的 67 个工具，语义与本文命令一一对应：`cognition`/`flow`/`identity`/`panarchy`/
> `moral_update` 合并为 `status`，`info_weight` 改名为 `narrative_weight`；`world_state`
> 仍是独立只读工具（与 `read_state` 并存：前者返回世界侧摘要，后者返回完整状态）；另增建局三件套 `world_schema` / `world_init` / `world_open`、
> 叙事层 `narration_context`（关键词触发设定 + 在场角色卡面 + 编年史，每回合调）、
> 酒馆生态 `character_card_read` / `add_character` / `import_lorebook`、回退 `snapshot` / `restore`、移动 `travel`（记图鉴）、叙事正文 `publish_prose`（把本回合正文写进状态，面板主舞台直接显示）、实况主舞台 `open_panel`（只读：叙事主舞台 + HUD + 事件时间线 + 分级弹窗/提示 + 图鉴/市场/大事记/世界脉搏抽屉；缺档可读报错并可重试）、面板行动队列 `pending_actions`（玩家在浏览器排的行动写进侧写文件，宿主取走后照常经引擎结算）、设定包 `load_setting`、长局 `advance` / `recall` / `write_summary` / `recap` / `configure`、物资 `use_item`（持有则自备消耗、买入时已付；未持有按所在地市场价现买现用，引擎结算花钱）、自由生成 `spawn_npc`（无角色卡也能入局）、模型层 `model` / `model_list`（查 16 个命名闭式模型：经济 Lerner/OU 价格、Cobb-Douglas、种群 logistic/Lotka-Volterra、流行病 SIR、风险 Poisson/生存、热力学松弛、舆论 bounded-confidence；宿主直接用公式推导效果，不再逐事件拍脑袋）。
> 一键开局：调 `new_game` prompt（参数填设定），产出「协议 + 设定 + 状态文件」的完整开局指令。
> 核心使用 Python 标准库；MCP 模式需额外安装 `pip install -e ".[mcp]"`。客户端命令填 `world-games-mcp`，旧命令 `world-walker-mcp` 保留为兼容别名。

---

## 0. 通用局怎么带（任何题材）

不是修仙/武侠也没关系。宿主按这五步带任意游戏：

```
1. session_new(name="我的团", setting_path="settings/雾港.setting.json")
   # 或用 world_init 自定义世界；session_list 可随时看所有存档
2. game_profile({...})            # 可选：定义这一局的资源/属性/进度轨（不填就走默认）
3. roll(attribute="int", difficulty=12, dice="2d6", reason="翻查档案")
   # 任何需要"判定"的地方都走它；combat/trade/social 只适合有数值冲突的场景
4. context_remember("门房说昨夜灯塔亮过", kind="clue", keys=["灯塔"]) 
   context_pack(scene_text="灯塔")          # 每回合把该记的东西打包给自己
5. publish_prose(正文) → tick()（需要推进世界时）
```

**上下文纪律**：玩家说过的承诺、发现的线索、NPC 的关键台词，都要 `context_remember` 落盘；
否则长局里"AI 忘了"是无法追责的。`context_pack` 每回合调一次，按预算取材料。

- 检索默认按 `recency/importance/relevance` 三分量排序；查旧事用 `context_search(ranked=true)`，
  想按原始入库顺序核对用 `ranked=false`。
- 事实更新（守夜人换人、承诺改了条件）用 `context_remember(..., subject="灯塔守夜人", supersede=true)`：
  旧条目变成 `superseded` 并留 `superseded_by`，不会被静默删除。
- `context_pack` 返回的 `reflection.due=true` 表示新增信息的 importance 已过阈值，
  该调 `write_summary` 压缩这一段了（摘要会推进反思水位）。
- 世界书条目可加 `once: true` / `max_fires: N` 控制"关键剧情只讲一次"；
  同组条目加 `use_group_scoring: true` 时按命中关键词数选最优，而不是抽签。

**存档纪律**：一局一个 `session_new`；重大节点 `session_snapshot`；不要手改 JSON，用工具。

---

## 0b. 体系与模板（v1.4，先读这一节再建局）

### 用模板开局（最快路径）

```
templates_list()                                  # 8 套：jrpg/mystery/management/survival/
                                                  #        narrative/cozy/tabletop/immersive
template_info(template="mystery")                 # 看完整内容 + 结构校验结果
template_start(template="mystery", name="我的调查局",
               player_name="陆离",
               overrides={"world": {"name": "雨港"}})
```

模板是**起点不是锁死**：`overrides` 深合并 dict、列表整体替换。
只想拿骨架：`template_apply(template=...)` 返回 bundle 不落盘，改完再交给
`world_init` / `session_new`。

### 七类体系与可用动作

| kind | 动作 | 典型用法 |
|---|---|---|
| `time` | `status` / `advance(minutes)` | 每回合推进 30–60 分钟；过夜 480 |
| `loot` | `list` / `roll(table, times, grant)` | 击杀后 `grant=True` 直接入库 |
| `craft` | `list` / `craft(recipe)` | 材料不足会返回 `missing`，不改库存 |
| `reputation` | `status` / `adjust(faction, delta, reason)` | 每个势力独立 −100..100 |
| `achievement` | `list` / `check` | 每回合结算后调一次；只解锁一次 |
| `progression` | `status` / `grant(amount)` | 战斗/任务结束给 XP，自动跨级 |
| `custom` | `list` / `<动作名>` | 预设动作组合（休息/训练/搜刮…） |

```
system_status()                                   # 列出所有体系与实时摘要
system_run("clock", "advance", {"minutes": 60})
system_run("loot_wolf", "roll", {"table": "wolf", "times": 2, "grant": True})
system_run("xp", "grant", {"amount": 120})
system_run("achievements", "check")
```

### 新增自定义体系

```
system_schema()                                   # 先看每类 kind 的 config 字段
system_define({"id": "weather", "kind": "time", "config": {...}})
system_define({"id": "moves", "kind": "custom", "config": {"actions": {
    "pray": {"label": "祈祷", "effects": [{"op": "resource", "key": "sanity", "delta": 2}]}}}})
```

`custom` 的 `effects` 只允许 9 种 op：`resource` / `attribute` / `meter` / `flag` /
`fact` / `reputation` / `xp` / `advance_time` / `loot`。**定义期就会拒绝白名单外的 op**。

**纪律**：体系运行态随存档落盘、随快照回退；不要手改 `state["systems"]`，用 `system_*`。

---

## 1. 引擎命令总览

| 命令 | 用途 | 关键参数 |
|------|------|---------|
| `combat` | 战斗结算 | --attacker --defender --action_type |
| `trade` | 交易结算 | --location --item --quantity --direction（买入记入持有；卖出须先持有） |
| `social` | 关系更新 | --actor --target --event --intensity |
| `karma` | 因果债分录 | --actor --victim --karma_type |
| `tick` | 回合结束 | (无额外参数) |
| `cognition` | 双系统判定 | --entity |
| `flow` | 心流状态检查 | (无) |
| `identity` | 玩家身份画像 | (无) |
| `narrative` | 涌现叙事+Panarchy | (无) |
| `panarchy` | 世界相位判定 | (无) |
| `moral_update` | 道德向量更新 | (无) |
| `merit` | 功德计算 | --aid --sincerity |
| `info_weight` | 叙事信息权重 | --probability |
| `world_state` | 世界侧摘要（势力/相位/谣言/风气/物价） | (无) |

---

## 1b. 玩家在面板里排的行动

面板是只读的，但玩家可以在主舞台下方的输入框里把行动排队——它们写进 `<状态文件>.inbox.jsonl`
（侧写文件），不会改状态。宿主每回合开头调一次：

```
pending_actions(mark_done=True)
→ {"pending": [{"id": "...", "text": "我想去渡口打听消息", "tick": 12}], "count": 1}
```

把每条 `text` 当作玩家这一回合的行动，照常调用 `combat` / `trade` / `social` / `travel` / `use_item`
结算，然后继续常规流程。`mark_done=True` 会把取走的条目标记为已处理，避免重复结算。

---

## 1c. 玩法剧本与事业线（先读这一节再带团）

一局游戏除了世界观，还有"怎么玩"。`playbook` 循环是供宿主遵循的指引，不由引擎强制执行。开局后可调用 `playbook_info()`：

```
→ {
    loop: "ttrpg",
    loop_guide: "按「玩家声明 → 引擎判定 → 后果描述」三步走…",
    progress: {axis: "level", label: "身手", value: 2, max: 7, ratio: 0.29},
    failure: {mode: "clock", label: "债主上门", value: 0, max: 12},
    beat: {name: "接活", every: 4, next_in: 3},
    quests: [...]
  }
```

- **按 `loop_guide` 带团**：freeform 不写选项；choice 每场给 2–4 个有代价差异的选项；
  mud 用「地点—出口—在场者—对象」组织；ttrpg 走"声明→判定→后果"。
- **按 `beat.name` 调节奏**：节拍是循环的，`next_in` 告诉你还有几回合换拍。
- **失败压力用 `failure`**：`clock` 模式下调 `failure_tick(amount, reason)` 推进败局钟，
  不要直接扣血；`sanity` 模式看 `mp`；`deadline` 模式看回合数。
- **事业线用 `quest_status()` 查**（只返回已浮现的）。玩家做到某件数值推断不出的事
  （"把信交给林小姐"）时，调 `quest_advance(quest, stage)` 记录；引擎自己判定下一幕的门禁。
  不要每回合都查、也不要主动把 dormant 的线告诉玩家——它们还没浮现。

## 2. 每回合强制流程

```
玩家输入行动
      │
      ▼
  [0] Agent 取走面板排队的行动（MCP: pending_actions(mark_done=True)，可选）
  [1] Agent 读取状态（MCP: read_state / CLI: cat game_state.json）
  [2] 判断行动是否涉及数值变化
  [3] 调用引擎结算（combat / trade / social / karma / travel / use_item）
  [4] 读取引擎输出 JSON（含 phase / morale / 世界侧变化；tick 还会返回 quest_changes 与 playbook）
  [4b] 每 3-5 回合：`playbook_info()` 看节拍与失败钟，`quest_status()` 看事业线进展
  [5] 生成文学描写
  [6] publish_prose 落盘正文 ← 面板主舞台显示的就是这段
  [7] tick 收回合 ← 世界演化（势力/谣言/风气/NPC/相位）在这里发生
```

**关键：`tick` 是活的。** 每次 tick 都会推进势力消长、谣言传播、风气漂移与 Panarchy 相位；
即使玩家没有行动，宿主调用 tick 仍会推进世界；不调用 tick 则不会自动推进。

---

## 3. 强制规则

1. ❌ **不能跳过引擎** — 所有数值结算必须经 engine.py
2. ❌ **不能让玩家看到结构化数值** — JSON 只在 Agent 内部使用
3. ✅ **必须**将道德向量、心流状态、Panarchy 融入叙事节奏
4. ✅ **必须**在每 3-5 回合检查一次 flow/narrative 命令
5. ❌ **不能**手写修改 state JSON (必须通过引擎)

---

## 4. 世界观无关

引擎是通用的。Agent 根据当前"叙事素材库"选择描写词汇:

| 世界观 | str 描写 | 境界体系 |
|--------|---------|---------|
| 修真 | 灵气/内力 | 练气→筑基→金丹→元婴 |
| 武侠 | 内力/后劲 | 三流→二流→一流→绝顶 |
| 奇幻 | 法力/精神 | 1st→9th circle |
| 科幻 | 能量/神经同步 | C-class→S-class |

引擎公式不变,描写词汇切换。

---

## 5. 调用示例

```bash
# 战斗
python3 engine.py combat --state g.json --attacker player --defender bandit --action_type heavy

# 检查玩家心理状态
python3 engine.py flow --state g.json
# 输出: {"state": "anxiety", "adjustment": -0.15, "trigger_luck": true}
# Agent: 描写一场"否极泰来"的奇遇作为缓冲

# 检查涌现事件
python3 engine.py narrative --state g.json
# 输出: {"emergent_events": [{"type":"calamity_omen", ...}]}
# Agent: 植入大劫将至的伏笔

# 业债积累触发后果
python3 engine.py karma --state g.json --actor player --victim villager --karma_type murder_innocent
# 输出: {"risk_level": "high", "karma_consequence": {"triggered": true, "effects": ["突破成功率-30%"]}}
# Agent: 描写玩家心中隐约的不安感,突破时心魔威力增大
```
