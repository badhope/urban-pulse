# 玩法层：剧本 · 事业线 · 世界书

> 这份文档回答一个问题：**同一个引擎，凭什么能跑出"玩法不一样"的游戏？**
> 答案分三层：`playbook` 决定怎么玩，`questlines` 决定故事往哪走，`lorebook` 决定每一回合该给宿主什么素材。

---

## 一、为什么需要玩法层

只有"世界观可换"不够。把修真换成赛博，玩家仍然在点"攻击/交易/社交"，玩起来是同一种游戏。
真正的差异在**循环结构**：

| 类型 | 核心循环 | 进度轴 | 失败条件 | 代表 |
|---|---|---|---|---|
| 自由推进 | 玩家任意输入 → 模型续写 | 无内建（靠摘要维持） | 无 | AI Dungeon / NovelAI |
| 选项推进 | 选一个选项 → 节点跳转 → 变量更新 | 章节 / 变量 | 作者写死 | ink / Twine / ChoiceScript |
| 地点命令 | 房间 → 命令 → 对象 → 战斗 | 等级 / 装备 / 任务 | 死亡惩罚 | MUD / Evennia |
| 桌面 RPG | 声明 → 判定 → 后果 | 进度钟 / 伤势 / 任务 | 钟满 | Blades in the Dark |

`playbook` 把这四类差异变成配置，规则函数一行不改。

---

## 二、`playbook` 字段

```json
{
  "loop": "ttrpg",
  "input": "natural",
  "progress": {"axis": "level", "label": "身手", "max": 7},
  "failure": {"mode": "clock", "label": "债主上门", "max": 12},
  "beat": {"pattern": ["接活", "踩点", "动手", "收尾", "代价"], "every": 4},
  "settlement": ["combat", "trade", "social", "karma"],
  "context": {"inject": ["lore", "cast", "chronicle", "quests"], "max_lore": 10, "scan_depth": 2}
}
```

| 字段 | 取值 | 说明 |
|---|---|---|
| `loop` | `freeform` / `choice` / `mud` / `ttrpg` | 决定宿主该怎么带团（见 `loop_guide`） |
| `input` | `natural` / `choice` / `command` | 只是声明，引擎不限制输入形态 |
| `progress.axis` | `level` / `gold` / `reputation` / `knowledge` / `clock` | **看哪个已有字段**，不引入新数据 |
| `progress.max` | 整数 | 仅用于显示比例，不强制封顶 |
| `failure.mode` | `hp` / `sanity` / `clock` / `deadline` / `none` | `clock` 才接受 `failure_tick` |
| `beat.pattern` | 字符串数组 | 循环播放的叙事节拍 |
| `beat.every` | 整数 | 每 N 回合换一拍 |
| `context.max_lore` | 整数 | 每回合最多注入多少条世界书 |
| `context.scan_depth` | 整数 | 参与关键词扫描的最近文本条数 |

**容错**：写错的值逐项回退默认值，并在 `state.playbook_notes` 里记录原因（面板「玩法」卡会显示）。
一个坏字段不会让整局开不起来。

### 四种循环的叙事指南

引擎把 `loop_guide` 一并返回给宿主，避免"配置改了但 Agent 还是老一套写法"：

- **freeform**：玩家自由输入，引擎只结算有数值后果的部分，其余由模型描写。不写选项、不催促。
- **choice**：每场景给 2–4 个**有代价差异**的选项；选项由当前状态与任务目标生成，不预写剧情树。
- **mud**：用「地点—出口—在场者—可交互对象」组织；玩家用简短命令式行动。
- **ttrpg**：声明 → 判定 → 后果三步走；判定必须落到工具，失败要有后果，不许用叙述抹掉。

---

## 三、`questlines` 事业线

### 数据结构

```
quest {
  id, title, summary, tags,
  visibility: predicate | null      # 满足才从 dormant 变 active
  stages: [
    { id, title, objectives[], 
      enter_if: predicate | null,   # 进入这一幕的条件
      exit_if:  predicate | null,   # 离开这一幕的条件（null = 永不自动离开）
      next: [stage_id],             # DAG 后继
      on_enter: [flag] }            # 进入时写入 world_flags
  ],
  fail_if: predicate | null,
  deadline_tick: int | null,
  reward: {gold, flags}
}
```

### 推进规则

1. **dormant → active**：`visibility` 满足。
2. **进入第一幕**：第一个 `enter_if` 满足（或为 null）的 stage。
3. **离开当前幕**：只有 `exit_if` 满足，或宿主调用 `quest_advance`。
4. **进入下一幕**：`next` 里第一个 `enter_if` 满足的；都不满足就停在原地等条件。
5. **整条完成**：没有 `next` 且离开最后一幕 → 发奖励（只发一次）。
6. **失败**：`fail_if` 或 `deadline_tick` 命中，**优先于**任何推进。

### 谓词

| 谓词 | 例子 | 语义 |
|---|---|---|
| `flag` | `{"flag": "无署名信"}` | `world_flags` 含该值 |
| `visited` | `{"visited": "灯塔"}` | 探索图鉴里有该地点 |
| `gold_gte` | `{"gold_gte": 300}` | 玩家钱财 ≥ N |
| `karma_gte` | `{"karma_gte": 150}` | 未清业债 ≥ N |
| `tier_gte` | `{"tier_gte": 3}` | 等级阶梯序号 ≥ N |
| `relation_gte` | `{"relation_gte": {"with": "echo", "affinity": 40}}` | 与某人的关系 ≥ N |
| `item_gte` | `{"item_gte": {"key": "jinchuang_yao", "n": 2}}` | 持有某物 ≥ N |
| `counter_gte` | `{"counter_gte": {"key": "kills", "n": 5}}` | 计数器 ≥ N |
| `stage_done` | `{"stage_done": {"quest": "q1", "stage": "s1"}}` | 某条线的某幕已完成 |
| `quest_done` | `{"quest_done": "q1"}` | 某条线已完成 |
| `all` / `any` / `not` | `{"all": [...]}` | 逻辑组合 |

未知谓词键返回 `False`（fail-closed），不会静默放行。

### 设计反模式（写进校验）

- **不要在目标里写过程**：「打败守卫」「找到钥匙」是目标；「先去东边再去西边」是过程，应交给玩家。
- **不要把所有任务都设成可见**：dormant 池让世界有"还没发生的故事"。
- **不要用对话文本当完成条件**：谓词只看世界状态，否则同一句话换个说法就判不出来。

---

## 四、世界书（Lorebook）

### 支持的语义

完整实现见 `rules/lorebook.py`。关键点：

| 语义 | 实现方式 |
|---|---|
| `selectiveLogic` 四值 | AND_ANY（默认）/ NOT_ALL / NOT_ANY / AND_ALL |
| `probability` | `sha256(seed\|tick\|entry)` 派生，同状态同结果 |
| `sticky` | 触发后保持 N 回合，**不重新掷概率、不续期** |
| `cooldown` | 从 sticky 结束后起算，N 回合内不再触发 |
| `delay` | 前 N 回合不触发 |
| `group` | 同组只出一条，`group_weight` 加权，`group_override` 直取 |
| `scan_depth` | 只扫最近 N 段文本 |
| `match_whole_words` | 非字母数字边界匹配（中英文都成立） |
| 递归扫描 | 默认**关闭**；`configure(lore_recursion=N)` 打开，最多 3 层 |

### 为什么递归默认关闭

实测：21 条世界书里，条目正文互相含关键词（"元力"出现在七条正文里），
打开递归后一次触发会拉进 20 条，把真正的当轮设定挤出上下文预算。
SillyTavern 的 Recursive scanning 也是默认关闭的，这里保持一致。

### 为什么时间单位是 tick 而不是消息条数

酒馆的 sticky/cooldown 按"消息条数"计。本引擎的回合是**离散且落盘的**：
每个 tick 一定写一次状态文件，快照回退能把 tick 退回去。用 tick 计时，
`sticky_until` / `cooldown_until` 随状态一起回退，重放结果一致（INV-E4）；
用消息条数计则无法保证。

### 不支持的部分及理由

| 字段 | 为什么不做 |
|---|---|
| `position` / `depth` / `role` / `outlet` | 这是"插到 prompt 的哪个位置"，本引擎不拼 prompt，上下文装配归宿主 |
| `vectorized` | 需要嵌入模型，违背零依赖 |
| `automationId` / `triggers` / `characterFilter` | SillyTavern 前端脚本能力，不属于规则层 |

---

## 五、四套设定包的玩法差异

| 设定包 | loop | 进度轴 | 失败 | 节拍 |
|---|---|---|---|---|
| 玄枢界 | `freeform` | 修行阶 0–10 | 重伤退场（hp） | 日常修行 → 资源争夺 → 势力摩擦 → 生死一线 → 代价与回收（每 6 回合） |
| 折剑行 | `ttrpg` | 身手 0–7 | 债主上门（clock 12） | 接活 → 踩点 → 动手 → 收尾 → 代价（每 4 回合） |
| 霓虹深渊 | `mud` | 评级 0–7 | 被盯上（clock 10） | 跑腿 → 接头 → 侵入 → 翻车 → 善后（每 4 回合） |
| 雾港 | `choice` | 线索 0–24 | 理智（sanity） | 异常 → 线索 → 更深的疑问 → 代价 → 回收（每 5 回合） |

每套各配 2 条事业线（1 主线 + 1 支线），全部用世界状态谓词推进。

---

## 六、怎么给自己的世界写一层

1. 在设定包里加 `playbook`（最简只写 `{"loop": "freeform"}`）。
2. 加 `questlines`：先写 1 条主线，3 幕足够；每幕给 `objectives` 与 `exit_if`。
3. 跑 `python scripts/verify_gameplay.py` —— 它会校验 DAG、谓词、奖励、可见性。
4. 跑 `python scripts/make_demo.py --only <世界名>` 生成演示存档，看面板上的「玩法」与「事业线」两卡是否符合预期。
