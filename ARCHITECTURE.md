# 架构设计文档：World Games（world-walker 仓库）

> 本文档是本项目的唯一真理源（Single Source of Truth）。
> 任何影响架构、接口、数据模型、依赖或目录结构的代码变更，都必须同步更新本文档。
> 最后更新：2026-11-05 ｜ 文档版本：v1.22

## 1. 概述与目标

- **项目定位**：通用互动游戏框架——规则结算内核（Python）+ 上下文台账 + 存档库 + MCP 服务器 + 只读网页主舞台。
  任何题材（跑团/调查/经营/生存/桌游/文字冒险）都能用同一套内核；内置四套设定包只是示例。
- **核心问题**：AI 宿主（Claude Code / Codex / Cursor 等）通过 MCP 工具结算玩家行动；玩家需要"文字叙事 + 面板/弹窗/提示"的混合游戏体验，而不是纯文字流。
- **质量属性优先级**：数值确定性（可复现） > 只读安全（面板不许写状态） > 可维护（零依赖、原生实现） > 性能。
- **范围边界**：
  - In scope：MCP 规则结算、通用判定、游戏档案、上下文台账、存档库、长局记忆、模型层、实况主舞台。
  - Out of scope（当前阶段）：网页直接提交游戏行动（第二阶段再评估）、AI 文本流式聊天、地图/立绘/音效、前端框架迁移。

## 2. 约束

- 技术约束：Python ≥3.10；仅标准库（http.server 等）+ 可选 `mcp>=2`；前端为原生 HTML/CSS/JS，无构建链、无第三方运行时依赖。
- 关键假设：
  1. 状态文件是本局唯一权威数据源；面板只读渲染它。
  2. MCP 是第一阶段唯一的状态写入 / 数值结算入口。
  3. 面板运行在本机（127.0.0.1），不做公网鉴权。

### 2.1 状态与输入边界

- `state_schema.py` 提供可重入 `state_lock`：先取得存档库共享的排他锁，再取得状态文件锁；存档库与 `.trash` 共用库锁。Windows 使用 `msvcrt`，POSIX 使用 `fcntl`；`transact_state` 在同一锁内完成读-改-写。
- 状态 JSON 严格拒绝非有限数值；保存异常时恢复调用方内存中的状态对象，不承诺回滚磁盘归档；`.bak` 备份发生普通 I/O 错误时不阻断主状态替换。
- `<state>.archive-pending` 或库级 `.ww-session-transaction-pending` 存在时，受保护的状态读取、写入及面板队列等操作拒绝继续；列表可标记 `pending_review`，不自动解析或恢复记录。异常或崩溃后应停写、保留现场并人工核对，详见 [归档人工恢复指南](docs/ARCHIVE_RECOVERY.md)。子进程中断回归仅覆盖部分进程崩溃窗口，不构成断电安全保证。
- 存档移入回收站或还原时，主存档与识别到的备份、日志、快照及其侧写一起迁移；迁移先写 pending 标记，不覆盖已有目标，未完成时保留现场待人工核对。
- MCP 状态变更工具使用事务绑定的状态路径/对象；生命周期切换串行化，避免多个存档之间串写。
- `input_policy.py` 对状态、设定、快照、角色卡和世界书执行路径段、符号链接、扩展名、文件大小、JSON 结构与基础 schema 校验；错误信息不回显绝对路径。

## 3. 架构总览（C4 - Context & Container）

### 3.1 系统上下文

```
玩家(人) ──对话/行动──> 宿主 AI Agent（Claude Code / Codex / 自建）
                              │  MCP (stdio)
                              ▼
                     World Games MCP 服务器 (mcp_server.py, 64 工具)
                              │  规则结算 (rules/*)
                              ▼
                     状态文件 ww_state.json ◄──只读── 实况主舞台 (panel.py + panel.html/css/js)
                              │                          ▲
                        归档 .log.jsonl            SSE /state /events
                                                         │
                                                    玩家浏览器
```

### 3.2 容器视图

| 容器 | 职责 | 关键约束 |
|---|---|---|
| `bootstrap.py` | 入口引导：把仓库目录注册成 `game_engine` 包 | 幂等；供 mcp_server / panel / engine 共用，禁止各自复制 `spec_from_file_location` |
| `rules/*` | 纯规则结算（战斗/经济/社交/因果/叙事/模型层） | 无副作用，状态由调用方传入传出 |
| `mcp_server.py` | 67 个 MCP 工具；读写状态文件；tick 推进 | 唯一写入源（第一阶段） |
| `state_schema.py` | 状态结构、事件日志、归档、业债裁剪 | `save_state` 统一归档 |
| `engine.py` | CLI 14 命令（手动结算/调试） | 与 MCP 共用 rules |
| `panel.py` | 只读视图模型 + HTTP/SSE 服务 | 不写状态；静态资源白名单 |
| `panel.html/css/js` | 游戏主舞台（叙事/HUD/时间线/弹窗/皮肤） | 原生实现；状态值一律 textContent |

## 4. 技术栈

| 层 | 选型 | 版本 | 理由 |
|---|---|---|---|
| 语言 | Python | ≥3.10 | 引擎/规则/MCP 已定 |
| MCP | `mcp` SDK | >=2.3,<3（可选装，锁定见 requirements-mcp.lock.txt） | 宿主对接标准 |
| 面板服务 | 标准库 `http.server` + SSE | 内置 | 零依赖、已存在 |
| 面板前端 | 原生 HTML/CSS/JS | — | 免构建、免框架；单机只读足够 |
| 数据源 | JSON 状态文件 | — | 可续跑、可 diff、可归档 |

## 5. 模块 / 目录结构

```
world-walker/                      # 仓库根即 game_engine 包
├── bootstrap.py                  # 入口引导：仓库根 → game_engine 包（幂等，三个入口共用）
├── mcp_server.py                  # MCP 服务器（64 工具；MCP 1.x/2.x 双布局）
├── sessions.py                    # 存档库（多局/快照/回收站，只碰文件系统）
├── rules/checks.py                # 通用判定（d20/2d6/d100/4dF/骰池、对抗、成功等级）
├── rules/gamesystem.py            # 游戏档案（自定义属性/资源/进度轨/标签/表格 + 旧存档回退）
├── rules/context.py               # 上下文台账（事实/线索/承诺 + 三分量检索 + 预算打包 + 反思阈值）
├── rules/systems.py               # 七类可插拔体系（时间/掉落/制造/声望/成就/成长/自定义）
├── templates.py                   # 八套完整游戏模板（世界→体系→事业线→游戏档案）
├── engine.py                      # CLI 入口（14 命令）
├── state_schema.py                # 状态结构 + 归档 + 业债裁剪
├── panel.py                       # 实况主舞台：只读视图模型 + HTTP/SSE
├── panel.html                     # 主舞台壳层（语义化结构，无内联渲染逻辑）
├── panel.i18n.js                  # 面板中英翻译层（运行时 DOM 翻译，默认英文）
├── panel.css                      # 视觉系统（token/皮肤/响应式/动效降级）
├── panel.js                       # 数据层 + 状态层 + 渲染/反馈层
├── rules/                         # 规则内核（含 models.py 命名闭式模型层）
│   ├── playbook.py                # 玩法剧本（循环/进度/失败/节拍）
│   ├── questline.py               # 事业线（stage DAG + 世界状态谓词）
│   └── lorebook.py                # 世界书引擎（selectiveLogic/递归/sticky/cooldown/分组）
├── settings_loader.py             # 设定包 → 状态（纯标准库，零依赖路径共用）
├── settings/                      # 设定包（玄枢界 / 折剑行 / 霓虹深渊 / 雾港）
├── docs/demo/                     # 真实演示存档（截图与视频的数据源）
├── docs/screenshots/              # README 预览（真实渲染 + 逐项断言 + 交互录屏）
└── scripts/                       # 17 个自检 + 变异测试 + 演示存档 / 截图视频流水线
```

## 6. 核心数据模型

### 6.1 面板视图模型（/state 与 SSE 载荷，字段名冻结）

```text
view_model = {
  world: { name, era, location_desc },
  tick: int, updated_at: str, seed, flags: [str],
  skin: { id: "xuanshu"|"neutral", accent: "#rrggbb" },
  terms: { hero, level, location, hp, mp, gold, flow, phase, karma, track, ... },  # v1.12
  player: { name, level, stage, stage_max, tier, tier_max, location, hp, hp_max,
            mp, mp_max, gold, karma, attrs, inventory: [{ key, name, quantity, type }] },
  scene: { location, title, description, mood: "neutral|danger|trade|social|growth|discovery",
           focus_event: str|null, prose_tick: int|null },   # description 优先取最新 prose
  events: [{ id, tick, type, kind, severity: "info|success|warning|danger",
             title, desc, icon, milestone: bool }],      # 最多 40 条，旧→新
  present: [{ id, name, level, hp, hp_max, desc, relation }],
  relations: [{ id, name, affinity, respect }],           # 只含与 player 有关
  market: [{ location, items: [{ key, name, price, base_price, supply, delta, type }] }],
  codex: { locations, people, items, lore },
  insights: { flow, phase, identity },
  world_state: { factions, phase, capital, connectedness, collapses, rumors, culture,
                 market_index, intensity },               # v1.12 世界侧摘要
  moral: { dims, values, derived },                       # derived = 引擎推导六维
  chronicle: [event_log 最近 24 条], milestones: [str], summaries: int,
  archived_events: int, others: [{ id, name, location }], lore_total: int, prose_count: int,
  game: { profile: {title, kind, attributes[], resources[], meters[], tags[], sheet{}},
          checks: [{tick, actor, dice, total, difficulty, margin, level, reason}],
          check_rate: {total, success, rate}, context: {total, open, superseded, by_kind, recent[], reflection} },
  sessions: { root, count, saves: [{name, world, player, tick, updated, active, broken}], trash }
}
```

- `events.id = "tick:type:sha1(desc)[:8]"`，确定性去重键。
- 事件分类（kind/severity/title/icon）只由 `panel.py` 决定；前端不做关键词判断。

### 6.1d 体系与模板契约（v1.4.0）

**状态形状**

```text
state["systems"] = {
  defs: {system_id: {id, kind, label, note, config}},     # 声明式定义（有界 40）
  rt:   {system_id: {...}}                                 # 运行态（随快照回退）
}
state["game"] = {title, kind, attributes[], resources[], meters[], tags[], sheet{}}
state["counters"] = {key: int}                             # 成就/模板谓词计数器（有界 200 键）
```

**七类 kind 的动作集**

| kind | 动作 | 随机源 |
|---|---|---|
| time | status / advance(minutes) | `sha256(seed,tick,"weather",day)` |
| loot | list / roll(table,times,grant) | `sha256(seed,tick,"loot",table,i,slot)` |
| craft | list / craft(recipe) | `sha256(seed,tick,"craft",recipe)` |
| reputation | status / adjust | 无 |
| achievement | list / check | 无（谓词求值） |
| progression | status / grant | 无 |
| custom | list / `<action>` | 内部效果各自决定 |

**模板契约**：`templates.to_bundle()` 产出与 `settings/*.setting.json` 同构的 bundle，
因此 `load_setting` / `world_init` / `session_new` / `template_start` 共用同一条建局路径。
`templates.validate()` 强制检查：必填字段、`places[].market` 必须指向存在的市场、
事业线 `visited` 必须指向存在的地点。

**计数器写入点**（成就与模板谓词的数据来源）：
图鉴首次收录（`locations/people/items/lore`）、`context_remember(kind="clue")`（`clues`）、
`roll`（`checks`）、击杀（`kills`）。

### 6.1c 面板运行时契约（v1.3.0）

| 端点 | 语义 | 上限 / 保护 |
|---|---|---|
| `GET /state` | 完整视图模型 | 商品 400 / 图鉴每类 200 / 剧情 20 段；实测 300 NPC+3000 事件 ≈ 110KB |
| `GET /history` | 正文 + 归档检索 | `limit` ≤ 200；归档从最新世代往前扫，命中即停 |
| `GET /series` | 长局态势侧写 | 600 样本封顶 |
| `GET /health` | 面板版本/状态大小/队列长度 | — |
| `GET /events` | SSE | 单连接 ≤ 30 分钟 / 3600 帧；无变化只发心跳 |
| `POST /action` | 排队一条行动 | 进程内锁 + 文件锁 + 原子替换；正文 ≤2000 字、体 ≤8KB |

**隔离性**：`state_path` 绑定在 `_PanelServer` 实例上（不是 Handler 类属性），同进程多面板互不串台。
**只读性**：唯一写入是 `<state>.inbox.jsonl` 侧写；状态文件字节不变由 `verify_panel.py` 断言。
**容错**：`load_state_retry`（3 次退避）应对 MCP 原子替换瞬间；脏数据经 `_coerce_state` 归一后渲染。

### 6.1b 玩法层视图模型（v1.14 新增）

```text
playbook = {
  loop: "freeform"|"choice"|"mud"|"ttrpg", input: "natural"|"choice"|"command",
  loop_guide: str,                       # 给宿主的叙事指南（单一信源在 rules/playbook.py）
  progress: {axis, label, value, max, ratio},
  failure: {mode, label, value, max, ratio, failed, reasons},
  beat: {index, name, every, next_in},
  settlement: [str], context: {inject, max_lore, scan_depth}, notes: [str]
}
quests = {rows: [{id, title, summary, status, stage, stage_title, objectives, next,
                  deadline_tick, tags, history}], total: int, visible: int}
lorebook = {rows: [{id, comment, keys, constant, enabled, fired, last_tick,
                    sticky_left, cooldown_left, order}], total: int}
```

`status` 工具与 `/state` 返回上述三块；CLI 与 MCP 的 `tick` 均推进世界和事业线，返回 `quest_changes`、`playbook` 与当回合事业线事件，完成奖励只发放一次。`lore_lookup` 在副本上预演，不保存状态、不消耗冷却；正式叙事上下文生成仍按规则触发世界书。

### 6.2 运行时不变量（Runtime Invariants）

| # | 不变量描述 | 作用域 | 维护方 | 校验方式 |
|---|---|---|---|---|
| INV-V1 | 面板任何请求不修改状态文件（字节不变） | 面板全请求 | panel.py | verify_panel.py（sha256 前后对比） |
| INV-V2 | 视图模型数值直接来自存档或引擎推导，前端不重算游戏结果 | 视图模型 | panel.py | verify_panel.py 契约断言 |
| INV-V3 | 每条 events 条目齐备 9 字段且 severity 合法 | /state | panel.py | verify_panel.py 遍历断言 |
| INV-V4 | 旧存档（缺 items/relations/market/event_log）返回合法空值与中性皮肤 | /state | panel.py | verify_panel.py legacy fixture |
| INV-V5 | 弹窗焦点不逃逸、Escape 可关、关闭后焦点回到触发控件 | 前端 | panel.js | 浏览器键盘冒烟 |
| INV-V6 | 320px 无横向滚动；颜色非唯一语义；reduced-motion 关动效 | 前端 | panel.css/js | 浏览器尺寸冒烟 + CSS 审查 |
| INV-V7 | SSE 断开后轮询继续刷新且连接状态可见 | 前端 | panel.js | 浏览器断线冒烟 |
| INV-V8 | 静态资源仅白名单文件；路径穿越/任意文件读取一律 404 | HTTP 层 | panel.py | verify_panel.py 安全断言 |
| INV-E1 | 状态文件 price ∈ (0, 3×base_price]，hp/gold ≥ 0，事件日志 ≤ keep | 引擎 | mcp_server/rules | stress_freeplay.py |
| INV-E2 | 卖出须持有；自备物品使用不再扣钱 | 引擎 | rules/economy.py | user_playtest.py |
| INV-E3 | 只读子命令不重写状态文件（字节不变）且不推进 rng_counter | CLI | engine.py | verify_cli.py（sha256 前后对比） |
| INV-E4 | 同一状态文件 + 同一行动 → 同结果（CLI 与 MCP 双通道），快照回退后重放亦然 | 引擎 / MCP | state_schema.seed_rng | verify_cli.py 确定性断言 + verify_mcp_stdio.py 快照重放 |
| INV-E5 | 玩家气血不得归零（保底 1）；归零改判濒死：掉钱 30%、心伤 +1、事件与大事记留痕，且必须落盘 | 引擎 | rules/combat.py | verify_near_death.py（R1-R3 七项断言 + 重读落盘） |
| INV-E6 | 世界必须在无玩家行动时也演化：`tick` 后势力存量/世界标记/Panarchy 相位至少一项变化 | 引擎 | rules/world_evolution.py | verify_world.py W1/W11 |
| INV-E7 | 世界演化只用 `sha256(seed\|tick\|key)` 派生随机，不消耗 `rng_counter`、不调用 random | 引擎 | rules/world_evolution.py | verify_world.py W9（双副本逐字节一致） |
| INV-E8 | 相位/心流/道德必须参与结算（不是仅展示）：Ω 事件概率与伤害 > K，无聊命中 < 心流，恶名降低社交增量 | 引擎 | rules/combat.py / narrative_engine.py / social.py | verify_world.py W3/W4/W5 |
| INV-E9 | 等级阶梯配置了 `level_tiers` 时，`advance` 只能逐阶递进（跳阶/倒退/未知名一律拒） | 引擎 | rules/progression.py | verify_world.py W10 |
| INV-E10 | 未结算因果债台账有界（≤ karma_ledger_keep），合并后总额逐分不变 | 引擎 | state_schema.py | verify_world.py W8 |
| INV-E11 | 只读工具（`status` / `world_state` / `read_state`）不写状态文件、不推进 `rng_counter` | MCP | mcp_server._read | verify_mcp_stdio.py（字节 + mtime 双重断言） |
| INV-E12 | CLI 与 MCP 的 `tick` 同义：市场 + 世界演化 + tick+1（含势力/相位落盘） | 引擎 / MCP | engine._do_tick / mcp_server.tick | verify_cli.py（CLI 侧）+ verify_world.py W11 |
| INV-E13 | 面板行动队列只写 `<state>.inbox.jsonl` 侧写；状态文件字节不变；`pending_actions` 是唯一读取入口 | 面板 / MCP | panel.inbox_* | verify_panel.py（同源/内容类型/长度/有界四道断言） |
| INV-E14 | 势力演化不得饱和：长局后头部与尾部存在差距（排行榜可读），且不收敛到单一赢家 | 引擎 | world_evolution.evolve_factions | verify_world.py W1 + make_demo 验收 |
| INV-G1 | 事业线只在 `exit_if` 满足或宿主显式 `quest_advance` 时推进；dormant 不出现在任何展示层 | 引擎 | rules/questline.py | verify_gameplay.py G2 |
| INV-G2 | 事业线 stage 图必须无环、next 必须存在；失败（deadline/fail_if）优先于推进；奖励只发一次 | 引擎 | rules/questline.py | verify_gameplay.py G2 |
| INV-G3 | 世界书触发确定性：同 seed + 同 tick + 同文本 → 同命中集合，且不消耗 rng_counter | 引擎 | rules/lorebook.py | verify_gameplay.py G3/G5 |
| INV-G4 | sticky 不续期、cooldown 从 sticky 结束后起算、递归默认关闭 | 引擎 | rules/lorebook.py | verify_gameplay.py G3 |
| INV-G5 | `playbook`/`questlines` 必须经 `settings_loader` 落盘；MCP 与零依赖路径共用同一实现 | 引擎 / MCP | settings_loader.py | verify_gameplay.py G4 + verify_settings.py |
| INV-E15 | 每条事件带单调 `seq`（从 1 起，跨 tick 不回退）；归档逐行保留 seq，可按 `(tick, seq)` 复算顺序 | 引擎 | state_schema.log_event | verify_world.py W12（六条） |
| INV-E16 | 事实检索 `ranked=true` 时按 GA 三分量（0.5/3/2）打分；同状态同查询结果逐条一致，且新增无关事实不改变已有排序 | 引擎 | rules/context.py | verify_generic.py N3（六条） |
| INV-G6 | 世界书支持 `once` / `max_fires`：达到上限后不再注入，原因写入 `skipped` 供面板解释 | 引擎 | rules/lorebook.py | verify_gameplay.py G3（三条） |
| INV-G7 | 同组条目在 `use_group_scoring` 开启时按命中键数取最高者（同分才回退权重抽签）；未开启时保持原抽签语义 | 引擎 | rules/lorebook.py | verify_gameplay.py G3（两条） |

### 6.3 公式的调用路径（哪些在跑、哪些按需）

v1.12 起把"公式库"与"结算回路"的边界写死在这里，防止再出现「公式能对拍、但从不进对局」的情况。

| 路径 | 触发者 | 用到的公式 |
|---|---|---|
| **回合回路**（自动） | `tick` → `world_evolution.evolve` | `logistic_growth`（势力增长）、`lotka_volterra`（强弱压制）、`sir_step`（谣言）、`deffuant_update`（风气）、`thermal_relaxation`（崩解后松弛）、Panarchy 状态机（r/K/Ω/α） |
| **行动结算** | `combat` / `trade` / `social` / `karma` | `resolve_combat`（含相位与心流修正、阶梯战力）、`resolve_trade` + `tick_market`（OU 回归）、`resolve_social_event`（含道德乘数）、`resolve_karma`（业债台账） |
| **派生判定** | `narrative` / `status` / 面板 `insights` | `flow_channel_status`（结构化胜负）、`player_identity_vector`、`update_player_moral_identity`、`panarchy_phase_check`、`daily_cognitive_budget` |
| **宿主按需**（不自动跑） | 宿主调 `model(name, params)` | 16 个命名闭式模型（Lerner/Cobb-Douglas/SIR R0/泊松/热力学/舆论…）；结果不回写状态，是给叙事算草稿的 |

不在这四条路径上的 `rules/*` 公开函数，是**公式库**（供宿主与未来的系统调用），
不宣称它们参与当前回合结算。

## 7. 关键接口 / API 约定

| 接口 | 语义 | 响应 |
|---|---|---|
| `GET /`、`GET /panel.html` | 主舞台页面 | 200 text/html |
| `GET /panel.css`、`GET /panel.js` | 静态资源 | 200 text/css / text/javascript |
| `GET /assets/echarts.min.js` | 离线图表库（vendored Apache-2.0, echarts@5.5.1） | 200 text/javascript |
| `GET /state` | 视图模型 JSON | 200 application/json |
| `GET /series` | 长局态势样本（tick 升序，封顶 600）+ 皮肤调色板 | 200 application/json |
| `GET /actions` | 未处理的行动队列（只读侧写） | 200 application/json |
| `POST /action` | 把一条行动写进收件箱（同源 + JSON + ≤2000 字） | 200 JSON / 400 / 403 / 415 |
| `GET /export` | 直出当前状态文件（只读下载） | 200 application/json + attachment |
| `GET /events` | SSE：状态文件签名变化即推 `event: state` + 完整视图模型 | text/event-stream |
| 其他路径 | 一律拒绝 | 404（不含任何文件内容） |

### 7.1 长局态势侧写（viz_series.py）

- 侧写文件 `<状态文件>.viz.jsonl`：每 tick 一条样本 `{tick, hp, hp_max, mp, mp_max, gold, karma, price_index, affinity_avg, codex_total, location}`；封顶 600 条。
- **双写点**：引擎 `_finish`（每次结算落盘后）与面板 `view_model`（打开时兜底）都调用 `viz_series.record_sample`；
  同 tick 覆盖、旧 tick 丢弃（快照回退不追旧点），因此幂等，且玩家不开面板的回合也不断档。
- 该文件由面板侧持有，**从不写状态文件**（INV-V1 不变）。

### 7.2 皮肤与品牌契约（面板）

- `/state.skin` 携带 `brand`（默认「万界·行者」）与 `tagline`（默认「万界为卷 · 因果为墨」）；
  `ui.brand` / `ui.tagline` 整局覆盖（服务端截断 brand≤24、tagline≤48）。品牌单一信源为 `panel.py::DEFAULT_BRAND`
  + `BRAND.md`，verify_panel 断言默认字符串防漂移。
- `/state.meta` 提供 `state_path` / `sidecar` / `read_only`，供帮助弹窗展示数据位置（面板默认只绑 127.0.0.1，属本机信息）。
- 帮助体系（只读展示层，无新接口）：顶栏按钮 + `?` 快捷键 → 帮助弹窗（这是什么/术语表/图表读法/键盘/
  数据与隐私/皮肤）；首访一次性引导条（localStorage，隐私模式降级为会话内记忆）。


- 皮肤 id：`xuanshu`（玄门·墨金）/ `neutral`（通用·石墨）/ `ink`（水墨）/ `neon`（霓虹）。
- 解析顺序：状态 `ui.skin`（可由设定包/`world_init` 传入）→ 世界名启发式（含「玄枢」→ xuanshu）→ `neutral` 兜底；
  `ui.accent`/`ui.motif` 可覆盖主色与风格文案。
- 每套皮肤带图表调色板（line/area/bar/hp/mp/grid/text），随 `/state.skin` 与 `/series.palette` 下发；前端不在 JS 里维护配色表。

## 8. 架构决策记录（ADR 索引）

- [ADR-001] 原生模块化网页主舞台（panel.html/css/js 三件套，无框架无构建）— 已采纳
- [ADR-002] 第一阶段面板严格只读，MCP 保持唯一写入源 — 已采纳
- [ADR-003] 事件分级/皮肤判定集中在 panel.py 服务端，前端零关键词表 — 已采纳

### ADR-001：原生模块化主舞台
- **状态**：已采纳 ｜ **日期**：2026-10-15
- **背景**：现有单文件 panel.html 更适合监控仪表盘，要做叙事主舞台 + 弹窗 + 皮肤会膨胀且难维护；引入 React/Vite 则带来构建链与新依赖。
- **候选**：A 继续单文件内联；B 原生模块化（html 壳层 + css + js）；C React/Vite 独立前端。
- **决定**：B。
- **理由**：质量属性优先"可维护 + 零依赖"；单机只读面板规模不需要框架；后续若网页行动/路由/多会话证明不足再走 ADR 迁移。
- **后果**：正面——无构建、可直接开文件调试、部署成本为零；负面——组件复用靠约定而非框架，复杂交互增多后需自律分层（panel.js 固定三层）。

### ADR-002：只读阶段（MCP 单一写入源）
- **状态**：已采纳 ｜ **日期**：2026-10-15
- **背景**：网页若能直接改状态，会出现第二套结算入口，破坏确定性（rng_counter/快照回退）与"所有数值经引擎"的协议。
- **决定**：第一阶段面板只读；行动仍由宿主经 MCP 结算。
- **后果**：正面——不变量简单、可复现性保住；负面——玩家需回到对话里发行动（第二阶段评估网页行动入口 + 一致性方案）。

### ADR-003：事件分级集中在服务端
- **状态**：已采纳 ｜ **日期**：2026-10-15
- **背景**：前端若自己做关键词表，两级逻辑会漂移。
- **决定**：`panel.py::classify_event` 是唯一分类器，输出 kind/severity/title/icon；前端只消费。
- **后果**：正面——分类可单测、可版本化；负面——新增事件类型需改 panel.py（有未知类型默认兜底）。

## 9. 实施计划（任务清单）

> 状态：[ ] 未开始  [~] 进行中  [x] 已完成
- [x] T1 架构基线与视图模型契约（ARCHITECTURE.md + AQG 账本）— 验证：文档落盘
- [x] T2 面板数据层与静态白名单 — 验证：verify_panel.py 契约全绿
- [x] T3 主舞台壳层与视觉系统（panel.html/css）— 验证：/ 200、皮肤/响应式冒烟
- [x] T4 前端状态层与反馈层（panel.js：SSE/toast/dialog/抽屉）— 验证：浏览器冒烟（弹窗/Escape/断线降级）
- [x] T5 回归与文档同步 — 验证：verify_panel / verify_mcp_stdio / user_playtest 全绿
- [x] T6 品牌与体验打磨（字标/标语/favicon/错误横幅/重试/中文化/弹窗居中）— 验证：verify_panel 28/28 + 浏览器冒烟 22/22
- [x] T7 长局态势可视化（采样侧写 + /series + 三图表 + 事件谱）— 验证：verify_panel 42/42 + 浏览器冒烟 14/14
- [x] T8 视觉组件深化（关系网/地点图/修行轨/徽章 + 长局折叠收敛）— 验证：2000 轮真实存档渲染冒烟
- [x] T9 世界观皮肤 v2（ui 配置 + 四套皮肤 + 图表配色联动）— 验证：改 state.ui 免重启即换肤
- [x] T10 品牌与帮助打磨（品牌可配置 + BRAND.md + 帮助弹窗/术语表/`?` + 首访引导 + 千分位）— 验证：verify_panel 48/48 + 品牌冒烟 20/20
- [x] T11 上传前置：打包完整性（package-data/MANIFEST.in，v0.8.0）+ 安装包真机验证 + 版本/文档对齐 + 残留清理 — 验证：wheel 内资源齐全 + 从安装包启动面板 5 端点全 200
- [x] T12 交付物完善：dist 发行包实打（sdist + wheel 落盘）+ 面板截图入仓（docs/screenshots，2000 回合存档现场重截、断言先行）+ 双 README 预览区 + 截图随 sdist/wheel 分发 — 验证：截图断言 35/35 + 产物条目核对 + 安装包冒烟 + 回归全绿
- [x] T13 确定性契约固化：新增 scripts/verify_cli.py（18 项）覆盖 CLI 只读写不变量/写通道落盘/双通道确定性；verify_mcp_stdio.py 增快照点重放断言（49 项）— 验证：verify_cli 18/18 + verify_mcp_stdio 49/49 + 全量回归绿
- [x] T15 濒死保护（玩家永不死亡 + 真实代价）：rules/combat.py 新增 _apply_near_death——玩家气血归零改判重伤退场，保底 1 血、掉 30% 钱财、心伤 +1、near_death_count 累加、事件与结算结果留痕；NPC 死亡语义不变；stress_freeplay 删除"改内存假装复活"的假修复，改为断言濒死保护未失效；面板显示濒死次数 — 验证：verify_near_death 7/7（含落盘复读）+ MCP 端到端实测 gold 100→70 且写盘
- [x] T16 测试可信度第二轮（独立专家团审计后）：verify_tests.py 重写为 9 条规则（R0 解析失败/R1 短路恒真/R2 常量表达式/R3 恒真下界/R5 恒假/R6 断言数量下限/R7 自反恒等式/R8 纯度型弱断言/R9 死分支），并兼容 stress 的三参数 check 签名（此前整个文件不在审计范围）；修复 verify_cli 写命令只验 rng_counter 不验业务效果（trade no-op 曾 19/19 全绿）、三副本全失败假通过；user_playtest 价格自比恒真改为独立手算 OU 闭式解、突破零成功恒真；stress 归档计数与回退断言由恒真改为严格等式；verify_mcp 补 trade 入库/减库存、social 落盘、merit 精确值；state_schema.save_state 修快照回退后归档文件与计数漂移（真 bug）— 验证：verify_tests 0/168 可疑 + 7 种假写法全部被抓 + 清空断言被 R6 抓 + 五类代码变异（trade/social/karma no-op、价格回归失效、归档计数归零）全部 FAIL
- [x] T17 归档安全与断言精确化（第三轮独立复验后）：回滚上一版"按计数截断归档文件"的错误修复（那会静默删除用户历史），改为按 archive_generation 分世代归档——回退只切文件、不删任何已有归档，recall 跨世代回捞；restore 时 archived_events 取历史总和（只增不减）；verify_tests 补齐关键字传参/裸常量/bool(常量比较)/(常量) is True/if 0 死分支/BoolOp 内恒真下界等 7 类绕过路径，EXPECTED 改为精确静态基数；verify_cli 四条写命令改为精确等式（伤害=扣血、扣款=total_cost、affinity/respect 固定增量、账本 amount/type/from/to）；verify_mcp 增"回退后旧归档逐条仍可召回"硬断言 — 验证：verify_tests 0/168 + 7 类绕过全抓 + 5 类变异全 FAIL + stress 2000/2000
- [x] T18 技术债清理（第四轮）：修 Python 3.10 的 BaseExceptionGroup NameError（stress 异常路径会崩）；verify_cli 12 步循环逐步校验 tick/rng_counter/combat 结算；user_playtest 的 OU 回归改为三组初值×3 步收敛并暴露整数取整在 |Δ|≤1 时卡边的已知局限；verify_tests 增数据流追踪（ok = True; check(x, ok)）并收窄不变式豁免；新增 scripts/compile_all.py 取代 compileall -x（后者在 Windows 上因反斜杠+shell 转义双重问题实测失效）；新增 scripts/check_wheel.py 供 CI 与门禁共用（消除两套判据漂移）；pre-push 门禁补齐 500 轮压测与打包校验 — 验证：门禁 9 项全绿 + 打包缺陷变异被拦（exit=1）+ 全部自检绿
- [x] T19 第五轮复验修复：修真 bug——死目标可继续攻击（hp=0 仍结算伤害并重复记击杀），rules/combat.py 加守卫；verify_cli 的 12 步 combat 校验从"有返回"改为"命中必有伤害、未中必零伤、血量不越界、至少命中 3 次"（原版 damage=0 与"只在满血命中"变异均漏网）；user_playtest 的 OU 死区修正为实测的 |Δ|<=3（原写 <=1 失实），第三组改到死区外，"死区内冻结"变异现可抓；verify_tests 的常量表改为按函数作用域，并补 AnnAssign/NamedExpr/二次赋值三种绕过；Gitee .workflow/ci.yml 对齐共用脚本；门禁在缺 mcp 时判失败（防"没跑却全绿"）；清理 scripts/ 与 state_schema/init_game 的 8 处死代码 — 验证：门禁 10 项全绿 + 死目标/满血命中/死区冻结三变异全 FAIL
- [x] T20 公式对拍与死代码清零（第六轮）：新增 scripts/verify_formulas.py——按 docstring 写的数学式**独立重算** 77 个函数再与返回值比对（模型层 OU/Lerner/Cobb-Douglas/Lotka-Volterra/SIR/泊松/热力学、认知前景理论/权重函数/幂律学习、社会扩展、系统论、世界动力学 Lyapunov/复利动力学、文化进化矩阵乘、因果记账），填补 rules/ 129 个公式此前零独立验证的空白；变异验证（Lerner ε±1、认知 α 0.88→0.99、记忆检索权重 0.33→0.44）均被抓；修 engine.py cognition 分支硬传 realm_level=0（任何实体得到同一认知预算，与 MCP status 的 int//5 不一致）及未用变量 spirit；全仓 pyflakes 清零（engine/rules/scripts 共 37 处未用导入与局部变量）— 验证：门禁 11 项全绿 + 公式变异 3/3 FAIL + verify_tests 0/246
- [x] T14 测试可信度治理：修复 5 处恒真/无效断言（verify_cli 只读探针比较两份副本、verify_panel 侧写 `or True`、皮肤循环 for/else 硬编码 True、stress 归档与回退断言恒真）；新增 scripts/verify_tests.py 做 AST 级断言审计（R1 恒真/R2 常量/R3 恒真下界/R4 弱断言）；修正 world_schema event_log 错误陈述（50→config.event_log_keep 默认 200）— 验证：verify_tests 0 可疑 + 三处变异测试均能被抓出

- [x] T21 公式对拍封后门与盲区补全（第六轮复验）：scripts/verify_tests.py 取消对 verify_formulas 的 `continue` 后门（原 `check_true('x',True)` 与自证式对拍可静默通过），改对拍特检后继续走 R1–R9 通用规则；verify_formulas 扩至 77 函数 / 122 运行时断言（原误称 79/58），补默认参数（cobb_douglas αβ、self_esteem、daily_cognitive_budget 正常档）、边界分支（blame_victim min、loss_aversion abs、SIR 归一化、base_activation 空输入）、退化断言（replicator 非对称收益、hawk_dove 频率、maslow 层级、KL 非对称）、C 组状态式（trade 三一致 / social gift=(8,0) / influence 有限 / karma 不触发 / 注册表）；price_equation docstring 改正为相对适应度 `w_i/w̄`；修正 README/ARCHITECTURE/门禁表述 — 验证：verify_formulas 122/122 + verify_tests 0/289 可疑 + verify_cli 20/20 + verify_panel 53/53 + verify_near_death 7/7 + verify_mcp_stdio 55/55 + user_playtest 47/47 + pyflakes 0 + 门禁 11 项绿

- [x] T22 全维度审查修复与界面打磨（覆盖率 66%→81%）：按产品级代码审查/安全/SRE/竞品对标四合一标准（见 docs/PROJECT_AUDIT_2026-10-22.md）修复——界面真 bug（`.chip[hidden]` 被 `display` 覆盖、抽屉溢出视口、编年史 32% 心跳/重复合并）；bandit High 12→0（SHA1 去重键 `usedforsecurity=False`、`assert` 改 `raise ValueError`、骰子 `# nosec`）；`panel.py::view_model` 复杂度 E(35)→8 个 `_build_*` 纯函数 B(6)；新增 scripts/verify_branches.py（111 断言）补 systems_feedback/narrative/cognition/economy/social_extended 覆盖至 96/83/97/91/72%；新增 scripts/audit_ui.py + smoke_ui.py（UI 自动化）接入门禁；README/截图重做 — 验证：门禁 14 项绿 + verify_branches 111 条 + verify_panel 54/54 + radon cc B(6) + pyflakes 0

- [x] T23 审查遗留清零（第七轮）：U-001 MCP 覆盖率可测（scripts/coverage_mcp.py，sitecustomize 子进程插桩，实测 mcp_server 行 34%/分支 37 部分）；U-002 依赖 CVE 用 OSV.dev 逐包查（10 包全 0）；F-008 新增 requirements-mcp.lock.txt + mcp>=2.3,<3；F-015 提示词注入防护（9 条特征扫描 + untrusted/content_policy 标记，标记而非删除保叙事）；F-014 补齐 24 个剩余纯公式（公式覆盖 105→127/129）；覆盖率 81%→87% — 验证：verify_injection 21/21（含 2 个变异）+ verify_branches 155/155 + 门禁 15 项全绿

- [x] T24 审查最后三项清零：F-002 用**真变异测试**替代静态审计的信任缺口——scripts/verify_mutation.py 内置 19 个已知错误变异（濒死/经济/社交/公式/归档/注入/面板），逐一应用到源码、跑验证脚本、期望变红，存活率红线 0%；首轮跑出 2 个存活（归档计数漂移、重复事件合并未被断言），补断言后 19/19 全杀。U-003 新增 scripts/verify_memory.py 三段对照测泄漏：实测 1500 轮 RSS 增量 -0.4MB（无泄漏），状态文件稳 7KB、侧写封顶 600 条；F-009 判定不适用（本地单机工具无 SRE 指标体系）；F-011 判定承认差距 — 验证：门禁 17 项全绿 + 变异 19/19 + 内存 7/7 + 覆盖率 88%

- [x] T25 可视化真修（三图从"画了"到"看得懂"）：物价指数图因 OU sigma=0 恒为 1.0 平线，加按 (rng_seed,tick,地点,商品) 派生的确定性扰动（4% 基准价，不耗 rng_counter、可 `configure(market_jitter=False)` 关）；气血/内力曲线图例按实际标注"几乎恒定/100% 回合为 100%"；纵轴自适应；图鉴累计 codex_total 作为第 4 系列上图；修面板端口被抢占（HTTPServer.allow_reuse_address=False 端口冲突抛错顺延）；修击杀不给战利品（接管 `loot_gold`）— 验证：门禁 17 项绿 + verify_* 七套全过 + 图表数据实测 price_index 442 种(0.93–1.09)/gold 30→6040/codex 8→19 + pyflakes 0

- [x] T26 第二轮全维度审查 3 个 High（见 docs/AUDIT_ROUND2_2026-10-22.md）：F-001 状态文件非原子写入→临时文件+fsync+os.replace 原子替换并保留 .bak（4 条回归断言）；F-002 补 X-Content-Type-Options/X-Frame-Options/Referrer-Policy/CSP 四安全头（静态核验 0 内联 script/style/事件处理器，curl -D 四头齐全，六端点 200）；F-003 时间线条目可点击（click+Enter/Space 复用 #eventdlg）；新增 21 项 UI 逐元素巡检 — 验证：verify_branches 159/159（含 4 条原子写断言）+ 其余六套全过 + bandit High/Med/Low 0 + 门禁全绿

- [x] T27 定位闭环（2026-10-23）：新增 `rules/world_evolution.py`（势力/谣言/风气/NPC/Panarchy 四段状态机）并挂进 `tick`；相位进战斗与事件结算、心流进命中、六维道德进社交；`ui.terms`/`level_tiers`/`places`/`publish_prose` 让术语与正文都可配置可落盘；修 3 个真 bug（暴击计败/道德恒 0/涌现重复）与未结算台账无界；新增 scripts/verify_world.py（46 项）与变异 M20-M25 — 验证：verify_world 46/46 + 门禁 18 项绿 + 变异 25/25 + 覆盖率 88%

## 10. 变更日志（Changelog）

| 日期 | 变更摘要 | 影响的章节 | 关联任务/ADR | 验证方式 |
|---|---|---|---|---|
| 2026-10-15 | 初始架构建立：只读主舞台（视图模型契约、静态白名单、事件分级、皮肤、a11y） | 全部 | T1–T5 / ADR-001..003 | verify_panel.py 全绿 + 浏览器冒烟 |
| 2026-10-15 | 品牌与体验打磨：字标/标语/favicon/theme-color/页签标题；缺档/读取失败 → 横幅 + 重试（SSE 不断流推错误态）；弹窗居中修复；气血吃紧标记、大事记芯片、相位中文、货币名；karma/交易事件文本中文化与显示名 | §6.1（player.currency 新字段）、§7（/state 错误态）、§9 T6 | T6 | verify_panel 28/28 + 浏览器冒烟 22/22 + 回归 48/48 & 41/41 |
| 2026-10-15 | 长局可视化深化：离线 ECharts（vendored）+ 态势侧写 `/series`（600 封顶）+ 三图表/事件谱/关系网/地点图/修行轨/徽章 + 皮肤 v2（ui 配置/四皮肤/图表配色）+ 长局折叠收敛 | §5、§6.1、§7、新增 §7.1-7.2、§9 T7-T9 | T7-T9 / ADR-004 | verify_panel 42/42 + 浏览器冒烟 14/14 + 2000 轮 stress 全绿 + 2000 轮真实存档渲染冒烟 |
| 2026-10-15 | 品牌与帮助打磨：品牌可配置（ui.brand/tagline + DEFAULT_BRAND 单一信源 + BRAND.md）+ meta 暴露数据路径 + 帮助弹窗（术语表/图表读法/键盘/数据隐私/皮肤）+ `?` 快捷键 + 首访引导条 + 大数千分位 | §7.2、§9 T10、新增 BRAND.md | T10 | verify_panel 48/48 + 品牌冒烟 20/20 + viz 冒烟 14/14 + 回归 48/48 & 41/41 |
| 2026-10-15 | 上传准备（v0.8.0）：wheel 资源完整性修复（panel.*/assets/settings 进包）、MANIFEST.in、服务端版本对齐 0.7.0→0.8.0、文档断言计数与结构清单对齐、残留运行文件清理 | §4、§5、§9 T11 | T11 | wheel 36 条目含全部资源 + pip --target 安装后面板 5 端点 200 + 全量回归绿 |
| 2026-10-15 | 交付物完善：dist 发行包实打落盘（sdist + wheel）+ 面板截图入仓（docs/screenshots 六张，2000 回合存档现场重截、截图前 35 项断言）+ 双 README 界面预览区 + 截图与来源说明随 sdist/wheel 分发（package-data/MANIFEST 纳入 docs） | §4、§5、§9 T12 | T12 | 见 .aqg/code-construction/screenshots-and-dist.md 验证日志 |
| 2026-10-19 | 依赖澄清与确定性修复（v1.1）：移除 rules 对 numpy 的隐性硬依赖（world_dynamics/cultural_evolution 共 4 个矩阵函数改纯 Python，与 numpy 对拍 200 组最大偏差 3.6e-15；ndarray 入参仍兼容），§2「仅标准库」约束自此真实成立；`seed_rng` 下沉 state_schema 供 CLI 与 MCP 共用，CLI 补齐种子确定性（修复前同状态两次 combat 伤害 19/16 不等）；engine.py 只读命令不再重写状态文件（dirty flag）；panel.py 清除被 shadow 的死代码（旧 skin_for_world + SKIN_ACCENTS）；rules 各模块 docstring 的理论引用改文献出处（原引用的 .md 不在仓库）；social_extended.basic_reproduction_number 转调模型层保单一实现；demo_state.json 按现行引擎重生（补 rng_seed、因果中文标签） | §2、§4、§5 | — | 本机复跑：无 numpy 环境 verify_panel 48/48 + CLI 确定性 A=B；venv（numpy+mcp）verify_panel 48/48、verify_mcp_stdio 48/48、user_playtest 41/41、stress 300/300 零违规 |
| 2026-10-20 | 确定性契约固化（v1.2）：新增 `scripts/verify_cli.py`（18 项）把 CLI 通道的三类性质变成常驻断言——9 条只读命令前后状态文件 sha256 不变且不推进 `rng_counter`、combat/trade/social/karma/tick 五条 dirty 分支全部落盘且字段有界、三副本同行动与双副本 12 步混合动作终态逐字节一致；`verify_mcp_stdio.py` 增 1 项快照点重放断言（49 项），覆盖 `rng_counter` 随快照回退后的确定性语义；§6.2 新增 INV-E3/E4；文档断言计数与结构清单同步 | §4、§6.2、§9 T13 | T13 | verify_cli 18/18 + verify_mcp_stdio 49/49 + verify_panel 48/48 + user_playtest 41/41 + stress 2000/2000 零违规 |
| 2026-10-20 | 测试可信度治理（v1.3）：逐条审计四套自检共 160+ 断言，修掉 5 处假测试——① verify_cli 只读探针比较两份 demo 副本而非被测命令结果；② verify_panel 侧写断言 `os.path.exists(...) or True` 恒真；③ 皮肤调色板循环用 for/else 把结论硬编码成 True；④ stress `失败回退后 stage 保持` 只判 tick>=0；⑤ stress `archived_events 与归档行数一致` 只判文件存在。新增 `scripts/verify_tests.py`（AST 级审计 R1-R4，拒绝恒真/常量/恒真下界/弱断言），并以三处代码变异反向验证其有效性；修正 world_schema `event_log 最多 50 条` 与默认 keep=200 不符的错误陈述。断言数：verify_cli 18→19、verify_panel 48→52 | §4、§9 T14 | T14 | verify_tests 0 可疑 + verify_cli 19/19 + verify_panel 52/52 + verify_mcp_stdio 49/49 + user_playtest 41/41 + stress 2000/2000 零违规 |
| 2026-10-20 | 濒死保护（v1.4）：玩家永不真正死亡——气血归零改判「重伤退场」，保底 1 气血，代价为掉 30% 钱财 + 心伤 +1 + near_death_count 累加 + 事件与结算结果留痕，全部写入状态文件；NPC 死亡语义不变。删除 stress_freeplay 中「直接改内存 p['hp']=hp_max 假装复活」的假修复（状态文件从未变化），改为断言濒死保护未失效；面板与视图模型新增 near_death_count。§6.2 新增 INV-E5 | §6.1、§6.2、§9 T15 | T15 | verify_near_death 7/7（含 save_state 后重读核验）+ MCP stdio 端到端 gold 100→70 且磁盘一致 + 全套自检绿 |
| 2026-10-21 | 测试可信度第二轮（v1.5）：独立专家团审计发现上一轮 5 处修复中 1 处未真正修复（归档断言 `arch>=0` 仍恒真）、1 处只修一半（回退断言 no-op restore 仍过），且 verify_tests 只能抓 20+ 种假写法中的 3 种、stress 的 10 条断言因签名不同完全不在审计范围。本轮重写审计器为 9 条规则并兼容双签名；补齐 verify_cli 写通道业务断言（trade no-op 曾 19/19 全绿）、user_playtest 价格自比与突破零成功、stress 归档/回退严格断言、verify_mcp 的 trade 入库/social 落盘/merit 精确值；并修出真 bug：快照回退后归档文件行数与 archived_events 永久漂移（300 轮实测差 2 行），save_state 现按计数截断归档文件 | §6.2、§9 T16 | T16 | verify_tests 0/168 + 7 种假写法全抓 + 清空断言被 R6 抓 + 五类变异全 FAIL + 回归全绿 |
| 2026-10-22 | 公式对拍封后门与盲区补全（第六轮复验）：scripts/verify_tests.py 取消对 verify_formulas 的 `continue` 后门（原 `check_true('x',True)` 与自证式对拍可静默通过），改对拍特检后继续走 R1–R9 通用规则；verify_formulas 扩至 77 函数 / 122 运行时断言（原误称 79/58），补默认参数（cobb_douglas αβ、self_esteem、daily_cognitive_budget 正常档）、边界分支（blame_victim min、loss_aversion abs、SIR 归一化、base_activation 空输入）、退化断言（replicator 非对称收益、hawk_dove 频率、maslow 层级、KL 非对称）、C 组状态式（trade 三一致 / social gift=(8,0) / influence 有限 / karma 不触发 / 注册表）；price_equation docstring 改正为相对适应度 `w_i/w̄`；修正 README/ARCHITECTURE/门禁表述 | §4、§9 T21 | T21 | verify_formulas 122/122 + verify_tests 0/289 可疑 + verify_cli 20/20 + verify_panel 53/53 + verify_near_death 7/7 + verify_mcp_stdio 55/55 + user_playtest 47/47 + pyflakes 0 + 门禁 11 项绿 |
| 2026-10-22 | 全维度审查修复与界面打磨（覆盖率 66%→81%）：按产品级代码审查/安全/SRE/竞品对标四合一标准（见 docs/PROJECT_AUDIT_2026-10-22.md）修复——界面真 bug（`.chip[hidden]` 被 `display` 覆盖、抽屉溢出视口、编年史 32% 心跳/重复合并）；bandit High 12→0（SHA1 去重键 `usedforsecurity=False`、`assert` 改 `raise ValueError`、骰子 `# nosec`）；`panel.py::view_model` 复杂度 E(35)→8 个 `_build_*` 纯函数 B(6)；新增 scripts/verify_branches.py（111 断言）补 systems_feedback/narrative/cognition/economy/social_extended 覆盖至 96/83/97/91/72%；新增 scripts/audit_ui.py + smoke_ui.py（UI 自动化）接入门禁；README/截图重做 | §4、§7、§9 T22 | T22 | 门禁 14 项绿 + verify_branches 111 条 + verify_panel 54/54 + radon cc B(6) + pyflakes 0 |
| 2026-10-22 | 审查遗留清零（第七轮）：U-001 MCP 覆盖率可测（scripts/coverage_mcp.py，sitecustomize 子进程插桩，实测 mcp_server 行 34%/分支 37%）；U-002 依赖 CVE 用 OSV.dev 逐包查（10 包全 0）；F-008 新增 requirements-mcp.lock.txt + `mcp>=2.3,<3`；F-015 提示词注入防护（9 条特征扫描 + untrusted/content_policy 标记，标记而非删除保叙事）；F-014 补齐 24 个剩余纯公式（覆盖 105→127/129）；覆盖率 81%→87% | §4、§6.2、§9 T23 | T23 | verify_injection 21/21（含 2 变异）+ verify_branches 155/155 + 门禁 15 项绿 |
| 2026-10-22 | 审查最后三项清零：F-002 用**真变异测试**替代静态审计信任缺口——scripts/verify_mutation.py 内置 19 个已知错误变异（濒死/经济/社交/公式/归档/注入/面板），逐一应用源码、跑验证脚本、期望变红，存活率红线 0%（首轮 2 存活已补断言）；U-003 新增 scripts/verify_memory.py 三段对照测泄漏：实测 1500 轮 RSS 增量 -0.4MB（无泄漏），状态文件稳 7KB、侧写封顶 600 条；F-009 判定不适用（本地单机工具无 SRE 指标体系）；F-011 判定承认差距 | §4、§6.2、§9 T24 | T24 | 门禁 17 项绿 + 变异 19/19 + 内存 7/7 + 覆盖率 88% |
| 2026-10-22 | 可视化真修（三图从"画了"到"看得懂"）：物价指数图因 OU sigma=0 恒为 1.0 平线→加按 (rng_seed,tick,地点,商品) 派生的确定性扰动（4% 基准价，不耗 rng_counter、可 `configure(market_jitter=False)` 关）；气血/内力曲线图例按实际标注"几乎恒定/100% 回合为 100%"；纵轴自适应；图鉴累计 codex_total 作为第 4 系列上图；修面板端口被抢占（HTTPServer.allow_reuse_address=False 端口冲突抛错顺延）；修击杀不给战利品（接管 `loot_gold`） | §5、§7、§9 T25 | T25 | 门禁 17 项绿 + verify_* 七套全过 + 图表数据实测 price_index 442 种(0.93–1.09)/gold 30→6040/codex 8→19 + pyflakes 0 |
| 2026-10-22 | 第二轮全维度审查 3 个 High（见 docs/AUDIT_ROUND2_2026-10-22.md）：F-001 状态文件非原子写入→临时文件+fsync+os.replace 原子替换并保留 .bak（4 条回归断言）；F-002 补 X-Content-Type-Options/X-Frame-Options/Referrer-Policy/CSP 四安全头（静态核验 0 内联 script/style/事件处理器，curl -D 四头齐全，六端点 200）；F-003 时间线条目可点击（click+Enter/Space 复用 #eventdlg）；新增 21 项 UI 逐元素巡检 | §4、§6.2、§7、§9 T26 | T26 | verify_branches 159/159（含 4 条原子写断言）+ 其余六套全过 + bandit High/Med/Low 0 + 门禁全绿 |

| 2026-11-04 | **v1.6.0 先贤调研落地**：按 `docs/PRIOR_ART.md` 的 12 项目调研落地六处机制——① `rules/context.py` GA 三分量检索（recency 0.99^age / importance 类型权重 / relevance 中文二元组重叠，权重 0.5/3/2，候选集内 min-max，0.25 分桶稳定排序）；② `recall` 与 `rank_events` 用同一打分，久远突破不再被近期噪声淹没；③ `remember(subject, supersede)` 的 mem0 式冲突消解（旧事实 `superseded` + `superseded_by`，不删除）；④ GA 反思阈值 `reflection_due` / `mark_reflected`（`write_summary` 推进水位）；⑤ 事件单调 `seq`（`state_schema.log_event` + 面板事件 id `tick.seq:type:hash`）；⑥ 世界书 `once` / `max_fires`（ink once-only）与 `use_group_scoring`（SillyTavern 组内评分）。新增 §6.2 INV-E15/E16、INV-G6/G7；新增变异 M45-M50 | §5、§6.1、§6.2、§10 | v1.6.0 | verify_generic 104/104 · verify_gameplay 65/65 · verify_world 54/54 · verify_panel 93/93 · verify_tests 853 条 0 可疑 · 变异 M45-M50 全杀死 |
| 2026-10-27 | **v1.4.0 体系与模板**：新增 `rules/systems.py`（七类数据驱动体系：time/loot/craft/reputation/achievement/progression/custom，21 个公开函数，统一 `system_run` 入口，运行态随快照回退）；新增 `templates.py`（八套完整模板：jrpg/mystery/management/survival/narrative/cozy/tabletop/immersive，每套含世界/角色/市场/地点/世界书/剧本/事业线/体系/游戏档案 + `validate()` 结构校验 + `overrides` 深合并）；新增 9 个 MCP 工具（system_define/run/status/remove/schema + templates_list/info/apply/start）；修复 `counters` 从未写入导致模板成就是死条件（新增 `state_schema.bump()` 并接到图鉴/线索/判定/击杀）；面板新增体系卡与 `/state.systems` | §5、§6.1d | v1.4.0 | verify_systems 161/161 · 断言审计 816 条 |
| 2026-10-27 | **v1.3.0 面板加固**：修复多面板串台（state_path 从 Handler 类属性改为 server 实例）、并发排队丢数据（进程内锁 + 跨进程文件锁 + 原子替换，20 线程/3 进程零丢失）、读状态撞上原子替换（3 次退避重试）；新增剧情回放（`/history` 检索正文与归档、`/state.prose` 完整正文、面板抽屉 + `S` 快捷键）；新增脏数据归一、超大状态下发上限（商品 400/图鉴 200/剧情 20）、HTTP 分级错误码、DNS rebinding 防护、SSE 寿命、ETag、`/health`、`close_panel` 与优雅停止 | §5、§6.1c | v1.3.0 | verify_panel 89/89（含 12 组并发/脏数据/超大状态场景）· smoke_ui 20/20 · 断言审计 726 条 |
| 2026-10-27 | **v1.2.0 World Games**：产品从"修仙文字游戏"升级为通用互动游戏框架。新增 `rules/checks.py`（6 个函数：d20/2d6/d100/4dF/骰池、roll_under、对抗、成功等级、有界台账）、`rules/gamesystem.py`（6 个函数：自定义属性/资源/进度轨/标签/自由表格，旧存档自动回退推导）、`rules/context.py`（6 个函数：八类事实、confidence/ttl、预算打包）、`sessions.py`（存档库：列表/新建/切换/快照/回收站/导入/清空）；新增 15 个 MCP 工具（roll / game_* / context_* / session_*）；面板新增游戏档案卡、判定记录卡、上下文台账抽屉、存档库抽屉；品牌默认值切到 World Games，`world-walker` 命令保留为兼容别名 | §5、§6.1、§6.2、§9 | v1.2.0 | verify_generic 87/87 · 断言审计 705 条 0 可疑 |
| 2026-10-27 | **v1.1.1 审计修复**：全量审计 22 项门禁基线后修复 9 类真实缺陷——逃跑除零/语义、social 非有限输入、无受害者业债漏记、台账合并跨债务人串账、Panarchy α 期 hold 不落盘、事业线重复奖励与 stage_done 重复、世界书 probability=1 被当成 100%、侧写半行导致整段曲线丢失、event_log_keep<=0 归档最新事件；另修 playbook 浅拷贝污染默认值、负价商品反向加钱、model 非有限结果、面板重复 open_panel 泄漏线程。文档层统一工具数 39 / 规则函数 162 / 自检 14 / 门禁 22，并把 verify_docs 扩到覆盖中英文 README 与展示站 | §5、§6.2、§9 | v1.1.1 | verify_branches 192/192 · verify_tests 632 条 0 可疑 · 门禁 22 项绿 |
| 2026-10-24 | **v1.1.0 玩法层**：新增 `playbook`（四种循环/五种进度轴/五种失败模式/节拍序列）、`questline`（stage DAG + 世界状态谓词 + 奖励，失败优先、dormant 不显示、无 exit_if 不自动推进）、`lorebook`（selectiveLogic 四值、概率确定性、sticky/cooldown/delay 按 tick、同组互斥、递归默认关闭）；新增 5 个 MCP 工具（playbook_info / quest_status / quest_advance / lore_lookup / failure_tick）；面板新增玩法卡、事业线卡、世界书抽屉；四套设定包配四种循环；`load_setting` 与 `build_state` 统一委托 `settings_loader`（此前 playbook/questlines 会在载入时被静默丢弃） | §5、§6.1b、§6.2 | v1.1.0 | verify_gameplay 60/60 · 变异 44/44 · 断言 614 条 0 可疑 |
| 2026-10-24 | **v1.0.0 交付版**：修 MCP SDK 布局不兼容（1.x `fastmcp` / 2.x `mcpserver` 双支持）、`seed_rng` 裸 import numpy 导致 MCP 子进程挂死、包元数据未执行三个阻断级缺陷；CLI `tick` 补齐世界演化（INV-E12）；只读工具零副作用（INV-E11）；死目标不再写编年史；势力演化改为禀赋上限 + 温和 LV + 挑战者回流（INV-E14）；新增行动队列双向通道（INV-E13）、世界脉搏卡、命令面板、分享模式、导出、时间线搜索、角色卡详情；新增三套设定包与 `verify_settings.py`；`engine.py` / `panel.py` / `mcp_server.py` 复杂度治理；变异测试 30/30 | §5、§6.2、§7、§9 | v1.0.0 | 门禁 17 项绿 · 变异 30/30 · 覆盖率 88% · 截图 17 张 + 录屏 |
| 2026-10-23 | **定位闭环（v1.12）**：修复定位审计指出的三处塌陷——① 世界不自演化（500 回合只有市价在动）：新增 `rules/world_evolution.py`（势力 logistic+Lotka-Volterra、谣言 SIR、风气 Deffuant、NPC 走动、Panarchy 四段状态机 r→K→Ω→α），挂进 `tick`；② 派生指标只展示不结算：相位调制事件概率与战斗伤害、心流调制命中、六维道德由业债累加并调制社交；③ 世界观无关只到引擎不到界面：`ui.terms` 覆盖面板词、`level_tiers` 定义阶梯并由 `advance` 逐阶校验、`places`/`publish_prose` 让正文落盘。同时修 3 个真 bug（暴击被当失败、道德映射恒 0、涌现事件重复落盘）与 1 处无界增长（未结算业债台账改合并保留总额）。新增 verify_world.py（46 项）与变异 M20-M25；门禁 18 项、覆盖率 88%。ARCHITECTURE 新增 §6.3 公式调用路径，明确哪些公式在回路里、哪些是宿主按需 | §6.1、§6.2（INV-E6..E10）、§6.3 | T27 | verify_world 46/46 · 全量回归 12 套绿 · 门禁 18 项绿 · 变异 25/25 杀死 |

### ADR-004：长局可视化的三个取舍
- **状态**：已采纳 ｜ **日期**：2026-10-15
- **背景**：目标"玩很多轮、很多系统、很多变化"，需要趋势而不只是当前值；同时有多个世界观要适配；且面板必须保持只读。
- **决定**：
  1. **趋势数据用侧写文件**（`<state>.viz.jsonl`，600 条封顶、tick 幂等去重），而不是把历史塞进状态文件或内存。
  2. **图表库本地 vendored**（echarts@5.5.1，1.0MB，Apache-2.0），不引 CDN——面板离线可用，资产缺失时整块降级为文案。
  3. **皮肤由状态配置驱动**（`ui.skin/accent/motif` + 世界名启发式兜底），而不是写死一套视觉或让前端猜。
- **后果**：正面——长局有趋势图、换世界换皮肤零代码、面板仍然只读且离线可用；负面——仓库多 1MB 静态资产；侧写是"面板自己的账"，删除该文件只丢历史曲线，不影响对局。

## 12. 数字信源与发布治理（v1.5.0）

文档里的每个计数都不允许手写。

- `scripts/metrics.py` 从源码实测：工具数（AST 解析 `@server.tool`）、规则函数数（`rules/` 顶层公开函数）、
  自检脚本数、门禁步骤数、变异条目数、模型数、模板数、设定包数、覆盖率。
- 结果写入 `docs/metrics.json`；覆盖率由 `pre_push_gate.sh` 在测完后以 `--coverage` 回写。
- `scripts/metrics.py --check` 与 `scripts/verify_docs.py` 的 D19 共同保证：
  源码与账本不一致、或文档引用了账本以外的数字，门禁即失败。
- 发布流程见 [docs/RELEASING.md](docs/RELEASING.md)；版本号唯一信源仍是 `__init__.py:__version__`，
  `pyproject.toml` 必须同步。

### 12.1 双语对外呈现

- `README.md` 是英文主版，`README.zh-CN.md` 是中文版，两者互链且断言表必须一致（D7b）。
- 英文版正文不得出现中文正文（示例载荷、设定包路径、市场键名等代码内容除外），由 D20 静态检查。
- `docs/index.html` 提供 EN / 中文 切换，默认英文，语言选择存 `localStorage`；
  两种语言互斥渲染，不会同屏混排。


### 12.2 面板国际化（v1.5.1）

面板是产品唯一"看得见"的界面，因此与 README 保持同一语言策略：**英文默认，可切中文**。

- `panel.i18n.js` 提供运行时翻译层：渲染完成后遍历 DOM，改写文本节点与
  `placeholder / title / aria-label / alt`。24 个 `render*` 函数不感知语言，
  新增渲染逻辑不会漏翻。
- 匹配顺序：固定词条 → 模板（`回合 {n}`）→ 放弃（原样保留）。
  捕获到的片段递归翻译，且以"骨架是否仍含中文"判断模板是否匹配，
  因此 `势力还没开始演化` 不会产出中英混排。
- 切换语言无损：首次改写前把原文记在节点的 `__wgI18n` 上，切回中文时还原。
- 设定包内容（人名、地名、物品、世界书条目、正文）**不翻译**——
  换世界就换词是产品设计，不是缺陷。
- 语言选择写入 `localStorage.wg-panel-lang`；`scripts/shots.py --lang` 在首次导航前
  注入该键，截图流水线因此可以产出纯英文或纯中文两套素材。
- `scripts/verify_i18n.py` 锁定：键唯一、模板占位符不重复、模板输出无中文、
  页面接线顺序、服务端白名单与 MIME、渲染管线确实调用翻译层。


### 12.3 交付面（v1.7.0）

**统一入口。** `cli.py` 提供 `wg`，一个入口覆盖 `init / play / serve / mcp / run / doctor / version`。
每个子命令都委托给既有模块，行为只有一份实现；`wg doctor` 输出机器可读的环境与素材报告。

**三种交付形态，同一份数据。**

| 形态 | 入口 | 说明 |
|---|---|---|
| 单文件可执行 | `dist/world-games.exe` | PyInstaller 打包，~30 MB，无需 Python |
| 命令行 | `wg` / `world-games` | pip 安装后的标准入口 |
| Web | `wg play` / `wg serve` → `/` 与 `/admin` | 只读主舞台 + 只读控制台 |

**打包的两条硬约束。**

1. 素材清单由仓库扫描得出（`DATA_FILES`），缺任何一个**拒绝构建**——
   否则会产出"能启动、界面白屏"的 exe，而这类缺陷只在用户机器上暴露。
2. 仓库根就是 `game_engine` 包，但检出目录名任意，`import game_engine` 在分析期无法解析。
   构建脚本先把源码暂存成真正的 `game_engine/` 目录再交给 PyInstaller，
   并显式声明全部动态导入的模块，避免"数据文件进了包、代码没进包"。

**MCP 原语补齐。** 此前只有 tools 和 1 个 prompt，缺 resources：

- **resources（4）** —— `world://state/current`、`world://summary/current`、
  `world://settings/index`、`world://docs/protocol`。工具由模型决定调用，资源由应用决定注入；
  宿主可把实时状态直接钉进上下文，不必每回合花一次工具往返。
- **tool annotations（64 个全覆盖）** —— `readOnlyHint` 让宿主自动放行只读调用，
  `destructiveHint` 让 `restore` / `session_manage` / `session_import` / `system_remove`
  必须人工确认。规范明确 annotations 只是 hints，不可用于对不可信服务端的安全决策。

**Web 控制台。** `/admin` 提供运行态、存档库与诊断，数据经 `sessions.list_saves()` 取得，
与 `session_list` 同源；不提供任何写操作，遵守"单一写入源"不变量。
CSP 保持 `script-src 'self'`，脚本外置为 `admin.js`。

**锁实现收敛。** `panel._file_lock` 与 `state_schema._key_lock` 曾是两套独立的跨进程文件锁。
收件箱与状态文件同处一个存档库作用域，因此面板改为复用 `_key_lock`——
同一语义只有一个实现，修一处即全局生效。


### 12.4 叙事机制（v1.8.0）

五个此前只有建议、没有实现的机制，本轮全部落地。共同原则：**能复用就复用，不新增第二套语义。**

| 机制 | 落点 | 关键决策 |
|---|---|---|
| 动作日志（D2） | `action_log.py` | 只存参数哈希不存明文；指纹排除 `actions_seq` |
| 规则书（B4） | `rules/rulebook.py` | 谓词复用 `questline.evaluate`，效果复用 `systems.EFFECT_OPS` |
| 循环检测（B3） | `rules/loopguard.py` | 签名不含 tick/时间戳；告警不阻断 |
| 知识边界（A6） | `rules/context.py` | 旧存档缺字段按"只有玩家知道"保守处理 |
| 事业线图（C2） | `panel.py` `_build_quest_graph` | 分层布局而非 force 布局 |

**动作日志的三个设计约束。**

1. `args_sha256` 而非明文。玩家输入可能含隐私，复制进第二个文件没有收益；
   `tool` + `tick` + `seq` 足以回查事件日志。
2. canonical JSON（`sort_keys`、固定分隔符、`allow_nan=False`）。字典序或浮点格式
   不同会让相同调用算出不同哈希，而哈希的意义就是稳定指纹。
3. `state_fingerprint` 排除 `actions_seq`。这个字段因记录而变，包含它会让重放的
   "after" 永远对不上——这是重放能否成立的开关。

**为什么 C3 只做 check 阶段。** `resolve_combat` 身上有 12 条不变量（死目标守卫、
死攻击方守卫、自攻击守卫、逃跑独立判定、技能 inf/nan 兜底……）。拆成
check/carry_out/report 三段需要重写整个函数体，回归面远大于收益。
补一个**只读 `preview()`** 就拿到了玩家最需要的价值（打之前知道风险），
且零风险：不写状态、不消耗随机，`verify_mechanics` N8b/N8c 断言了这两点。

**循环检测为什么不阻断。** 重复刷同一个地点、原地疗伤，都是合法玩法。
检测器只回答"你好像在打转"，把决定权留给玩家。这是从 ZorkGPT 只抄检测器、
不抄 LLM 生成环的同一个判断。

### 12.5 可玩性设计

引擎再准，玩家不知道能做什么也没用。面板因此提供三件东西：

- **下一步提示**：从事业线目标、气血、业债、市价、循环信号推导出的具体动作，
  点一下填进输入框。数据来自同一份状态，不可能与工具能力脱节。
- **事业线地图**：分层 DAG，一眼看出故事有多长、走到哪、还能去哪。
- **战斗推演**：打之前先看命中率与期望伤害。

这三处都只读，符合"单一写入源"不变量。
