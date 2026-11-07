# 更新日志

本项目遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。
版本号的单一信源是 `__init__.py:__version__`，`pyproject.toml` 必须与之一致（由测试断言）。

---

## v1.9.0 — 2026-11-07

**亮色默认的可用性版本：把"能看"做成"看得清"，把先贤调研剩下的四项建议全部落地。**

这一版没有新增游戏机制门类，只做两件事：让面板在强光、投屏、截图、打印这些
真实场景下可读，以及把 `docs/PRIOR_ART.md` 里仍标着"建议"的四项补齐。

### 新增：亮色主题（默认）与明暗切换

- **亮色成为默认**。面板是玩家长时间盯着的读屏，深色在强光与投屏下文字发灰。
  暗色保留为夜间/直播模式，顶栏一键切换，选择写入 `localStorage`，刷新不闪。
- `panel.theme.js`：**首帧前**同步应用主题。放在 `<head>` 且不 defer——晚一步就会
  先画亮色再跳暗色，这种闪烁在录屏里非常明显。
- 主题跟随系统偏好（`prefers-color-scheme`），但显式选择优先。
- `panel.css` 的 token 拆成三组：`--accent`（可读的强调文字）、`--accent-line`
  （装饰描边）、`--accent-fill`（实心按钮底）。**v1.8 让三者共用一个变量，
  导致亮底上的强调文字只有 1.92:1**——这是本轮实测抓到的真缺陷，不是风格偏好。
- 皮肤主色改为 `{light, dark}` 成对下发（`panel.py: SKINS`），前端不再用
  `accent + "88"` 拼半透明色。自定义 `ui.accent` 支持单值（两主题共用）或字典。

### 新增：首屏加载态

- 骨架屏 + 顶部 2px 进度条，替换"整屏转圈"：面板是读屏，整屏 spinner 会被当成卡死。
- 数据到达即撤（成功与失败都撤，失败交给错误横幅）；8 秒兜底，避免脚本异常时
  用户对着一张永远闪的骨架屏。
- SSE 后续每回合刷新**不再**回到骨架屏——局部重绘不该闪整页。

### 新增：先贤调研剩余四项（`docs/PRIOR_ART.md` 的 `[建议]` 清零）

| 来源 | 机制 | 落点 | 断言 |
|---|---|---|---|
| ink `{ visit_knot }` / `TURNS_SINCE` | 幕的访问计数与距上次访问回合数 | `rules/questline.py: evaluate`（`visits` / `turns_since`） | N10a–N10d |
| Open Dungeon `packStoryHistory` | 提示词前缀指纹，宿主据此决定是否复用缓存 | `rules/context.py: _prefix_hash` → `pack()["prompt_prefix_hash"]` | N11a–N11c |
| OASIS hot-score | 谣言热度 = 感染率 × log(1+提及数) × 时间衰减 | `rules/world_evolution.py: rumor_heat` | N12a–N12c |
| CWS `sect_decider` | 势力目标权重 argmax 选意向（招募/经商/结盟/兴兵） | `rules/world_evolution.py: _faction_intents` | N13a–N13d |

- `visits` / `turns_since` 从已有 `history` 派生，不新增平行状态：同一份数据
  既能画事业线图也能做进入条件，快照回退后依然一致。
- 势力意向是**确定性 argmax**，收益函数只读真实状态（力量差、物价偏离、连接度），
  不消耗 `rng_counter`，因此不破坏重放。第一版收益函数让所有势力长期停在
  "结盟"（看起来像功能，实际是常数），改为归一化驱动量后才四项可达——N13d 锁住这一点。
- 谣言 `heat` 不再是 SIR 感染率的别名；`mentions` / `last_mention` 让"旧事重提"
  能被表达出来。

### 新增：主题与体验的自动化门禁

`scripts/verify_theme.py`（25 项，接入 pre-push）：

- **实测对比度**：真实浏览器里遍历每一个可见文本节点，算前景/背景相对亮度比，
  两套主题都必须满足 WCAG AA（正文 4.5:1、大字 3:1）。不靠目测，不靠截图评审。
- 首帧无闪烁、选择可持久化、图表 canvas 像素在切换后确实变化（ECharts 不继承 CSS 变量，
  只改 CSS 会留下"亮底 + 深图表"的半截效果）。
- token 完整性：两套主题声明同一组变量；组件规则里不允许出现颜色字面量。

### 修复

- **面板强调文字在亮色下对比度不足**（见上，`--accent` 一词多用是根因）。
- `panel.css` 引用未定义的 `--faint`（`next-moves` 的两处小字实际继承了默认色），
  统一为 `--text-faint`。
- `ARCHITECTURE.md` 三处仍写「64 工具」，与源码 67 不一致；`README` 的规则函数数
  停在 205（实际 206）。
- `CHANGELOG.md` 的版本段乱序（v1.6 排在 v1.8 之前），已按版本号倒序重排。
- `admin.html` 与 `docs/index.html` 同步改为亮色默认（控制台跟随系统，展示站跟随访客）。

### 变更

- 门禁 32 → 33 步（新增主题与对比度）。
- `verify_panel` 93 → 98 项（主题引导、默认亮色、切换按钮、骨架屏、皮肤亮暗成对）。
- `verify_mechanics` 25 → 39 项。
- 自检脚本 21 → 22 个；规则公开函数 205 → 206。

### 验证

pre-push 33 步全绿；`verify_theme` 25/25；`verify_mechanics` 39/39；`verify_panel` 98/98；
`verify_docs` 27/27；变异 53/53 全杀（新增 M51–M53，见 `scripts/verify_mutation.py`）。

---

## v1.8.0 — 2026-11-05

**从"可审计"升级到"可重放"，并补齐让它更像游戏的四块机制。**

### 新增：动作日志与重放（D2）

`action_log.py` 每次写操作追加一行到 `<state>.actions.jsonl`：
`seq` / `tick` / `tool` / `args_sha256` / `rng_before` / `rng_after` /
`state_before` / `state_after`。

- 参数只存哈希不存明文——玩家输入可能有私密内容，落第二个文件没有收益。
- 指纹用 canonical JSON（排序键、固定分隔符、拒绝 NaN），否则同样的调用会算出不同哈希。
- `state_fingerprint` 刻意**排除** `actions_seq`：它因记录而变，包含进去会让重放的
  "after" 永远对不上。
- 修了一个真 bug：`seq` 原本在事务外递增，写的是没人回写的内存对象，导致每条记录都是
  `seq=1`。改为在事务内递增，`verify_replay.py: R9` 锁住。

### 新增：世界特例不用改引擎（B4 rulebook）

`rules/rulebook.py`，设定包用 `rules` 字段声明：

```json
{"id": "scorch", "when": {"flag": "burning"}, "then": [{"op":"resource","key":"hp","delta":-2}],
 "order": 50, "stop": false}
```

- 谓词**复用** `questline.evaluate`，效果**复用** `systems.EFFECT_OPS` 白名单——
  没有第二套谓词语言，也没有第二条改状态的路径。
- `order` 降序 + `stop` 截断 = Inform 的 "instead of" 语义，不需要新概念。
- 加载期校验：未知 op、重复 id、非整数 order 一律报错并指出规则 id。

### 新增：循环检测（B3）

`rules/loopguard.py`。状态签名覆盖位置/资源/背包/旗标/事业阶段/物价/业债，
**不含** tick 与时间戳。同一签名 20 窗内出现 3 次 → `loop_suspected` 并给出建议。
dead-end 路线记失败次数，≥3 次只从**建议**里隐藏，不禁止走。

### 新增：NPC 知识边界（A6）

LLM 叙事最常见的硬伤是 NPC 说出只有玩家看见的秘密。提示词不可靠，改由数据回答：

- `context_remember(witnesses=[...], public=false)`，默认只有 player 知道。
- 新工具 `context_known(character)`：写 NPC 对话前查他到底知道什么。
- 新工具 `context_tell(fact_id, to, how)`：转述并留下传播链。
- 旧存档没有 witnesses 字段时按"只有玩家知道"处理——保守读法，绝不泄露旧秘密。

### 新增：游戏化与可视化

- **事业线地图**：把 `stages[].next` 的 DAG 画成分层图（x = 跳数，y = 层内分布）。
  不用 force 布局——力导向会把节点甩成一团、标签重叠；分层布局能看出故事形状。
- **战斗推演** `combat_preview`：命中率/期望伤害/是否致命，只读、不消耗随机。
  没有重写 `resolve_combat`（它身上有 12 条不变量），只补了玩家真正需要的"打之前知道风险"。
- **下一步提示**：面板在输入框上方列出可执行的具体动作（来自事业线目标、气血、
  业债、市价、循环信号），点一下填进输入框。

### 新增：使用指南

`docs/USE_CASES.md`——回答"别人拿它干什么"：五种使用者、三条上手路径、
它解决的具体问题、不该用它做什么。

### 变更

- 工具 64 → **67**（`context_known`、`context_tell`、`combat_preview`）。
- 规则函数 191 → **205**；自检脚本 18 → **20**。
- 门禁 30 → **32 步**（新增 `verify_mechanics`、`verify_replay`）。

---

## v1.7.0 — 2026-11-05

**交付形态与企业级能力：从"能跑"到"能装、能管、能被宿主发现"。**

### 新增：MCP 生态对齐

- **MCP resources（4 个）**：`world://state/current`、`world://summary/current`、
  `world://settings/index`、`world://docs/protocol`。工具是模型控制的，资源是应用控制的：
  宿主可把实时对局状态直接钉进上下文，不必每回合花一次工具往返。
- **Tool annotations（64 个全覆盖）**：`readOnlyHint` 让宿主自动放行只读调用，
  `destructiveHint` 让破坏性操作（`restore` / `session_manage` / `session_import` /
  `system_remove`）必须人工确认。此前 64 个工具在宿主眼里危险程度完全相同。
- 依据 MCP 规范：annotations 只是 hints，客户端不得据此对不可信服务端做安全决策。

### 新增：统一 CLI（`wg`）

一个入口覆盖全部用法，每个子命令都委托给既有模块，行为只有一份实现：

```
wg init [path]          生成开局存档
wg play [--state P]     打开实况主舞台（自动选空闲端口，不杀别人进程）
wg serve [--state P]    无头运行
wg mcp                  以 stdio 运行 MCP 服务器
wg run <action> ...     执行单条规则动作
wg doctor               环境与素材自检（JSON）
wg version              版本
```

### 新增：Windows 单文件可执行

- `scripts/build_exe.py` → `dist/world-games.exe`（约 30 MB，无需 Python 环境）。
- 素材清单由仓库扫描得出而非手写，缺文件时**拒绝构建**，不会产出"能启动但白屏"的 exe。
- 实测：`init` → 生成存档；`serve` → HTTP 200；`doctor` → 完整 JSON。

### 新增：Web 管理控制台

- `/admin` 只读控制台：运行态卡片、存档库列表、诊断项（状态可读性、归档 pending、
  侧写、面板素材）。数据经 `sessions.list_saves()` 取，与 `session_list` 同一来源。
- 严格遵守面板只读不变量：控制台不提供切换/删除，一切写操作仍在宿主。
- CSP 保持 `script-src 'self'`，脚本外置为 `admin.js`，不使用内联脚本。

### 变更

- 版本 1.6.0 → 1.7.0（新增公开 CLI 入口与 MCP 资源，向后兼容）。
- `pyproject.toml` 新增 `wg` 入口点；`world-games` 指到统一 CLI。

---

## v1.6.0 — 2026-11-04

**先贤调研落地：把 12 个开源叙事项目的记忆算法搬进确定性内核。**

### 新增

- `docs/PRIOR_ART.md`：12 个项目（SillyTavern / AI Dungeon / NovelAI / generative_agents /
  修仙世界模拟器 / Open Dungeon / Ink / Twine-Harlowe / Inform 7 / Evennia / mem0 /
  CAMEL+AutoGen+ZorkGPT+OASIS）的架构对照、可落地借鉴点与"明确不抄"清单。
- `rules/context.py`：GA 三分量检索（`recency 0.99^age` / `importance` 类型权重 /
  `relevance` 中文二元组重叠，权重 0.5/3/2，候选集内 min-max），`context_search(ranked=true)`。
  `recall` 与新增 `rank_events` 共用同一打分，久远突破不再被近期噪声淹没。
- `remember(subject=..., supersede=true)`：mem0 式写入期冲突消解——同 kind + 同 subject 的
  旧事实标 `superseded` 并写 `superseded_by` / `closed_tick`，原文保留可审计。
- `reflection_due` / `mark_reflected`：GA 的重要性累积反思阈值（默认 `config.context_reflect_threshold=10`），
  `write_summary` 推进水位，`context_pack` / `context_summary` 带 `reflection` 块。
- 事件单调 `seq`（`state_schema.log_event`）：同一 tick 内多条事件可定序；
  面板事件 id 改为 `tick.seq:type:hash`，修掉同 tick 同描述撞键被前端去重丢掉的问题。
- 世界书 `once` / `max_fires`（借 ink once-only choice）：关键剧情条目不再重复注入，
  跳过原因写入 `skipped`。
- 世界书 `use_group_scoring`（借 SillyTavern `filterGroupsByScoring`）：同组按命中键数取最高，
  同分才回退 `group_weight` 抽签；默认关闭，保持旧行为。
- 检索排序量化到 0.25 分桶 + id 稳定排序（借 Open Dungeon 的 prompt 前缀缓存教训）。

### 修复

- `context_pack` 的「未结案」与「其他事实」曾因 dict 相等比较在新打分字段下失效而重复同一事实，
  改为按 fact id 去重。
- 事件 id 同 tick 同类型同描述撞键：前端按 id 去重会丢掉两条中的一条。

### 说明

- 归档与快照的事务边界不变：存在 `<state>.archive-pending` 或库级
  `.ww-session-transaction-pending` 时拒绝相关受保护读写，不会自动恢复；异常或崩溃后应停写、
  保留现场并人工核对，详见[归档人工恢复指南](docs/ARCHIVE_RECOVERY.md)。
  保存失败时恢复调用方内存中的状态对象，不等于磁盘归档回滚；不承诺断电安全。
- 新增变异 M45-M50；`verify_generic` 104 条、`verify_gameplay` 65 条、`verify_world` 54 条（含 MCP 路径）。

---

## v1.5.1 — 2026-11-03

**面板国际化：产品唯一"看得见"的界面终于和 README 说同一种语言。**

### 新增

- `panel.i18n.js`：运行时 DOM 翻译层，254 条固定词条 + 141 条模板。
  面板默认英文，顶栏 EN / 中文 一键切换，选择记入 `localStorage`。
- `scripts/shots.py --lang en|zh --suffix`：截图流水线可在首次导航前注入语言，
  产出纯英文或纯中文两套素材；`docs/screenshots/` 已全部重拍为英文版。
- `scripts/verify_i18n.py`（12 条断言）：键唯一、模板占位符不重复、模板输出无中文、
  页面接线顺序、服务端白名单与 MIME、渲染管线确实调用翻译层。已接入三处门禁。
- `verify_panel.py` 增至 91 条，新增翻译层可达性与切换按钮存在性断言。

### 修复

- 面板主界面此前只有中文，而英文 README 展示的正是它——内外不一致。
- `玄晶 19 玄晶`：货币单位与"钱财"泛称同名时重复输出。
- 中英混排：`势力 has not started evolving`。翻译层改为对捕获片段递归翻译，
  并以"模板骨架是否仍含中文"判断匹配，避免半翻译结果。
- 行动输入框 placeholder 过长被裁切（v1.5.0 遗留的同类问题在英文下更明显）。

### 说明

设定包内容（人名、地名、物品、世界书条目、叙事正文）**不翻译**——
"换世界就换词"是产品设计。英文界面里出现的中文专名属于预期行为。

---

## v1.5.0 — 2026-11-02

**定位与交付层：把"能跑"变成"可发布、可核对、可维护"。**

### 新增：数字单一信源

- `scripts/metrics.py` 从源码实测工具数、规则函数数、自检脚本数、门禁步骤数、变异条目数、
  模型数、模板数、设定包数与覆盖率，写入 `docs/metrics.json`。
- `scripts/verify_docs.py` 的 D19 断言文档引用的所有计数与该文件一致；
  文档不再手写数字，漂移在门禁阶段即被拦下。

### 新增：双语对外介绍

- `README.md` 改为英文主版，`README.zh-CN.md` 为中文版；两版互相链接，
  D20 断言英文版正文不含中文正文（示例载荷与设定包路径除外）。
- 展示站 `docs/index.html` 增加 EN / 中文 切换，默认英文，选择记入 `localStorage`；
  两种语言互斥渲染，不会同屏混排。

### 修复：文档与实测不一致

- 覆盖率 88% → 86%（按门禁同一条 coverage 命令实测 4181 行 / 578 缺失）。
- `verify_injection` 断言数 21 → 23（实测 23/23）。
- 门禁步骤数 25 → 27（`pre_push_gate.sh` 实际 27 个 `step`）。
- 两份 README 各有一处损坏的对照表（只有 `---|---|---|` 而无表头），已重写。
- `README` 的"项目范围"小节补回被截断的对照表与说明。

### 变更：仓库治理

- 分支收敛为单一 `main`，本地与远程同名同源；`fix/*` 与 `sync/*` 已合并后删除。
- 版本号统一升到 `1.5.0`（`__init__.py`、`pyproject.toml` 与文档一致）。
- `.gitignore` 增加 `.zcode/`（编辑器会话状态不入库）。
- 审计报告归档到 `docs/PROJECT_AUDIT_2026-11-01.md`，不再散落在仓库根目录。

### 验证

- 完整 pre-push 门禁 27 步全绿；覆盖率 86%（阈值 70%）；变异 44/44 全杀；
  `verify_tests` 819 条断言审计 0 可疑；真实 MCP stdio 64/64；500 轮压测 0 违规。

---

## v1.4.1 — 未发布（审计加固，已并入 v1.5.0）

- 状态写入增加 Windows/POSIX 可重入锁与事务读改写；严格拒绝 NaN、Infinity 和溢出数值；`.bak` 备份发生普通 I/O 错误时不阻断主状态保存。
- MCP 状态变更绑定事务路径/状态对象，生命周期切换串行化；只读 `game_profile`、`system_run` 和快照读取不触发状态保存。
- 新增 `input_policy.py`，统一限制状态、设定、快照、角色卡和世界书的路径、符号链接、扩展名、大小、JSON 结构和基础 schema，并脱敏错误路径。
- CLI 与 MCP 的 tick 对齐事业线推进、当回合事件与奖励；修复失败模式 `none` 的判定。
- 世界书 `lore_lookup` 改为无状态副作用预演，保留既有冷却规则。
- 存档库与回收站共享排他锁；移入或还原时连同识别到的快照、备份、日志和侧写迁移。存在 `<state>.archive-pending` 或库级 `.ww-session-transaction-pending` 时拒绝相关受保护读写，不会自动恢复；异常或崩溃后应停写、保留现场并人工核对，详见[归档人工恢复指南](docs/ARCHIVE_RECOVERY.md)。保存失败时恢复调用方内存中的状态对象，不等于磁盘归档回滚；不承诺断电安全。
- 行为回归覆盖判定、tick、变异、MCP stub 和归档中断，并接入本地及 CI 门禁。
- GitHub/Gitee MCP 作业使用锁定依赖并执行 `pip check`；缺少 MCP/Playwright 时门禁失败而非跳过。

## v1.4.0 — 2026-10-27

**体系与模板层：把"一款游戏"变成"一套可组合的机制积木 + 八套完整骨架"。**

### 新增：七类可插拔体系（`rules/systems.py`，21 个公开函数）

| kind | 能力 | 关键约束 |
|---|---|---|
| `time` | 日/时/分、季节轮转、按天派生天气 | 日志有界；天气由 `sha256(seed,tick,day)` 派生 |
| `loot` | 加权掉落表、`rolls` 多次、数量区间、空掉落权重 | 抽样确定性；`grant` 才入库 |
| `craft` | 配方、材料校验、属性驱动成功率、失败按比例返还 | 概率 logistic；材料不足不改库存 |
| `reputation` | 势力声望 −100..100、五档、未知势力自动建档 | clamp + 上限 40 势力 |
| `achievement` | 条件复用事业线谓词、奖励金币/flag/XP、只解锁一次 | 坏条件视为未达成 |
| `progression` | XP 曲线（base×growth^n）、跨级、每级属性成长、等级上限 | 满级不再溢出 |
| `custom` | 受限效果白名单（resource/attribute/meter/flag/fact/reputation/xp/advance_time/loot） | **定义期就拒绝非法 op** |

- 统一入口 `system_define` / `system_run` / `system_status` / `system_remove` / `system_schema`
- 运行态落 `state["systems"]["rt"]`，**快照回退连体系状态一起回退**（INV-E4）
- 定义数上限 40、时间日志 100、成就 200、配方 80、势力 40、效果 12

### 新增：八套完整模板（`templates.py`）

| 模板 | 题材 | 循环 | 体系 |
|---|---|---|---|
| `jrpg` | 日式奇幻冒险 | freeform | 7 |
| `mystery` | 本格推理调查 | choice | 5 |
| `management` | 店铺经营 | mud | 4 |
| `survival` | 末日生存 | mud | 4 |
| `narrative` | 情感叙事 | freeform | 4 |
| `cozy` | 田园生活 | freeform | 4 |
| `tabletop` | 桌面跑团 | ttrpg | 5 |
| `immersive` | 沉浸模拟 | ttrpg | 4 |

每套模板都自带：世界、主角、NPC（含卡面文字）、市场、关系、等级阶梯、术语、
地点（含市场绑定）、世界书、玩法剧本、事业线（含 `exit_if` 谓词）、体系、游戏档案。

- `templates_list` / `template_info` / `template_apply` / `template_start`
- `validate()` 结构校验：缺件、`places[].market` 悬空、事业线 `visited` 指向不存在地点都会被拦下
- `overrides` 深合并 dict、列表整体替换；`template_apply` 不落盘

### 修复：计数器从未被写入（模板成就原本是死条件）

`counter_gte` 谓词一直存在，但 `state["counters"]` 没有任何代码写入——模板里
"探索三处地点""找到第一条线索"这类成就在任何对局里都不可能解锁。现在：

- `state_schema.bump()` 统一累加（有界 200 键、值封顶 1e9）
- 图鉴首次收录 → `locations/people/items/lore`
- `context_remember(kind="clue")` → `clues`
- 每次 `roll` → `checks`；每次击杀 → `kills`

### 面板

- 新增「体系」卡：列出每套体系与实时摘要（时间/声望/成就进度/等级 XP/掉落表数/配方数）
- `/state` 新增 `systems` 区块（含 `kinds` 元数据）
- 模板开局后面板第一帧就能看到体系

### 测试

- 新增 `scripts/verify_systems.py`（161 项断言，S1–S10 + S8b）：
  七类体系行为、八套模板完整性、覆盖合并、计数器驱动成就、MCP 端到端、有界性、旧设定包兼容
- 断言审计 726 → 816 条 0 可疑
- 门禁 23 → 24 项；GitHub / Gitee CI 同步接入
- 变异测试 40 → 44（M41–M44：声望 clamp、等级上限、成就重复解锁、效果白名单），全杀

---

## v1.3.0 — 2026-10-27

**面板加固：让"所有剧情、所有内容"都能在面板上过一遍，并且扛得住并发与复杂状态。**

### 修复（会导致数据错乱的）

- **多面板互相串台**：`state_path` 原是 `Handler` 的类属性，同进程起第二个面板（换一局/换存档）
  会把第一个也指向新文件——实测两个面板同时开着都显示后启动那一局。现在绑定在 server 实例上。
- **并发排队丢数据**：收件箱是"读全部 → 改 → 整文件重写"，两个标签页同时提交会互相覆盖——
  实测 20 个并发提交只剩 1 条。现在加进程内锁 + 跨进程文件锁（msvcrt/fcntl）+ 原子替换，
  20 线程 → 20 条、3 进程 × 10 → 30 条全部保留。
- **面板读状态时撞上 MCP 原子替换**：Windows 上杀毒/索引器短暂持有句柄会让 `open` 失败，
  整页变成错误态。新增 `load_state_retry`（3 次退避重试），实测 3 秒高频读写 232 次 0 失败。

### 新增：剧情回放（"所有剧情都能过一遍"）

- `GET /history?q=&scope=all|prose|archive&limit=N`：正文与归档统一检索，分页有上限（200）。
- `/state` 新增 `prose` 区块：最近 20 段**完整正文**（不再只给截断到 700 字的最新一段）。
- 面板新增「剧情回放」抽屉 + 顶部「剧情」按钮 + `S` 快捷键：
  每段显示回合/地点/字数，超过 320 字折叠为"展开全文"，支持关键词过滤与范围切换（全部/正文/归档）。

### 新增：面板健壮性

- **脏数据不再崩页**：顶层字段类型全错（`entities` 是字符串、`tick` 是 "abc"、`market` 是列表……）
  也能产出合法视图模型（`tick=0`、空玩家、空事件），不再 500。
- **超大状态下发有上限**：商品 400 条、图鉴每类 200 条、剧情 20 段；实测 300 NPC / 800 商品 /
  3000 事件的存档，`/state` 只有 110KB（此前会线性膨胀到数 MB）。
- **HTTP 请求处理分级报错**：缺 `Content-Length` → 411、超限 → 413、非 UTF-8 → 415、
  非 JSON → 400、非对象 → 400（旧实现一律 400 或静默 None）。
- **DNS rebinding 防护**：`Host` 必须是回环名（`127.0.0.1`/`localhost`/`::1`），否则 403。
- **SSE 有寿命**：单连接最长 30 分钟 / 3600 帧，浏览器 EventSource 自动重连；
  状态未变时只发心跳注释，不再重复序列化整份视图模型。
- **静态资源 ETag**：1MB 的 ECharts 重复刷新走 304。
- **`/health` 端点**：面板版本、状态文件大小、队列长度，便于排障。
- **优雅停止**：`panel.stop()` 同时 `shutdown()` + `server_close()`（只 shutdown 会占着端口）；
  新增 `close_panel` 工具，MCP 侧可主动释放端口与 SSE 连接。

### 性能

- `classify_event` 不再对每条事件重复构造 milestone 集合（原 O(n·m)）。
- 编年史复用时间线已合并的序列，不再对同一份 `event_log` 合并两次。

### 测试

- `verify_panel.py` 75 → 89 项：新增 12 组复杂场景——多实例隔离、20 线程并发、
  脏数据、超大状态下发上限、SSE 寿命、Host 校验、`/history` 检索与分页、`/health`。
- `smoke_ui.py` 17 → 20 项：剧情回放渲染三段完整正文 + 倒序 + 新抽屉可展开。
- 断言审计 711 → 726 条 0 可疑。

---

## v1.2.0 — 2026-10-27

**从「一个修仙文字游戏」升级为「装任何游戏的框架」**：更名 World Games，新增通用判定、
游戏档案、上下文台账、存档库四层；面板补上这四层的可视化。原有四套设定包与全部规则不变。

### 更名（保留兼容）

- 产品名 World Games；面板默认字标/标语、MCP server name、CLI 描述全部切换。
- `pyproject.toml` 新增 `world-games` / `world-games-mcp` 入口；`world-walker` / `world-walker-mcp`
  保留为**兼容别名**，Python 包名仍是 `game_engine`，现有客户端配置无需改动。

### 新增：通用判定（`rules/checks.py`，6 个公开函数）

任何游戏都能用的一套判定，不再假设"攻击-防御-伤害"：

| 能力 | 说明 |
|---|---|
| 骰型 | `d20` / `2d6` / `3d6` / `d100` / `4dF` / `pool`（骰池），支持 `2d6+1` 修正 |
| 模式 | `add`（总值比难度）/ `roll_under`（低于目标）/ `pool`（数成功骰）/ `fate` |
| 修正 | 属性值 + 任意修正列表（带标签），全部计入 margin |
| 成功等级 | 大成功 / 成功 / 部分成功 / 失败，按 margin 分档；自然极值上下调一档 |
| 对抗 | `opposed_by` 用同一骰型与属性再掷，margin = 我 − 对方 |
| 台账 | 写 `state["checks"]`，`checks_keep` 有界（默认 200） |

MCP 工具 `roll`；面板新增「判定记录」卡（成功率 + 最近 10 条）。

### 新增：游戏档案（`rules/gamesystem.py`，6 个公开函数）

把"这一局是什么游戏"从代码里拿出来：

- `attributes` / `resources` / `meters` 三类自定义条目，各自带 `min`/`max` 与颜色；
- `tags`（戒严/雨季/被通缉）与自由 `sheet`（职业、目标、住所……）任意题材可用；
- **旧存档零迁移**：没有显式档案时自动从 `hp`/`mp`/`gold`/`attrs`/`playbook` 推导；
- 全部条目有上限（32 条 / 40 字段 / 24 标签），写入前 clamp。
- `game_adjust` 的 `kind` 可省：key 只属于另一类时自动定位（`线索` 在 meters、`力量` 在 attributes 都能直接改）。

MCP 工具 `game_profile` / `game_adjust` / `game_tag` / `game_sheet`；面板新增「游戏档案」卡。

### 新增：上下文台账（`rules/context.py`，6 个公开函数）

互动对话的核心是"AI 该记住什么"，现在这件事可核对：

- `remember` / `search` / `forget` / `set_status`：事实、线索、承诺、人物、地点、物品、规则、备注八类；
- `confidence` 与 `ttl`：低置信度先被淘汰，过期事实默认不出现在检索里；
- `pack`：按字符预算拼「玩法 + 未结案 + 场景相关 + 最近事件 + 其他事实」，超预算截断并报告；
- 输出统一带 `untrusted` 与 `content_policy`（与角色卡同规格，数据不是指令）；
- 台账有界（400 条），去重（同类型同正文刷新而非追加）。

MCP 工具 `context_remember` / `context_search` / `context_forget` / `context_pack`；
面板新增「上下文台账」抽屉。

### 新增：存档库（`sessions.py`）

- `session_new` / `session_switch` / `session_list` / `session_snapshot` / `session_manage` / `session_import`；
- 所有存档集中在一个目录（默认 `<对局目录>/saves/`，可用 `WORLD_GAMES_SAVES` 覆盖）；
- 局名安全化（保留中英文数字，其余折叠为 `_`，长度 48 上限）；
- 快照同 tick 只留一份、最多 20 份；删除是**移入回收站**，可还原；`purge` 才是真删；
- 面板新增「存档库」抽屉（只读列出，切换/新建由宿主执行）。

### 面板

- 新增 3 个区块：游戏档案卡（左栏）、判定记录卡（中栏）、上下文台账与存档库抽屉；
- 所有渲染走 `textContent`，不拼 HTML；`/state` 视图模型新增 `game` 与 `sessions` 两个顶层字段；
- 面板仍然是**严格只读**：新增内容全部来自状态文件与目录扫描。

### 测试

- 新增 `scripts/verify_generic.py`（87 项断言）：判定四模式/自然极值/对抗/确定性/台账有界、
  档案回退与 clamp、上下文检索与预算、存档库全生命周期与路径安全、MCP 集成、品牌默认值。
- `verify_tests.py` 审计 705 条 0 可疑；`verify_panel.py` 品牌断言切到 World Games。
- `verify_docs.py` 的 D11/D12/D13 自动跟随新的函数数/自检数/工具数。
- 变异测试扩到 **40 个**（M37–M40：判定忽略属性、资源不夹紧、ttl 不生效、局名不安全），全部被新断言杀死。

---

## v1.1.1 — 2026-10-27

全量审计（22 项门禁基线 + 代码/文档/CI 交叉核对）后的修复版，不改架构、不加依赖。

### 修复（会让结果算错的）

- **逃跑除零**：双方 `dex=0` 时 `dex_a/(dex_a+dex_b)` 抛 `ZeroDivisionError`，整次战斗失败。
  逃跑现在先于命中判定结算，结果写 `fled` + `outcome="draw"`，不再被当成"攻击被闪避"。
- **无受害者业债漏记**：`karma(victim=None)` 的恶行（屠城/纵火）不写台账、返回 `risk_level="low"`。
  现在用 `world` 占位记账，业债与天劫机制无法被绕过。
- **台账合并串账**：超过 `karma_ledger_keep` 时把最旧 N 条合并成一条，A/B/C 的债全挂到 A 名下。
  改为按债务人分组合并，归属与总额都保持；部分消业留下 `settled` 记录，不再改写原条目金额。
- **Panarchy α 期永不结束**：`hold` 只在局部变量递减、从不落盘，相位卡在 α。
  现在 `pan["hold"]` 每回合写回，四段环可以走完。
- **事业线重复奖励**：重复 `complete_stage` 或重复 tick 会重复发 `reward.gold`；
  `exit_if` 满足但下一幕 `enter_if` 未满足时每回合重复记 `stage_done`。两者都改为幂等。
- **世界书概率语义反了**：`probability=1`（1%）被当成 100% 恒触发，`0.9` 被 `int()` 截成 0 永不触发。
  现在按酒馆百分比语义存浮点，并保留旧比例写法的兼容解释；条目 `id/uid` 不再丢失。
- **侧写半行毁掉整段曲线**：`.viz.jsonl` 最后一行损坏时 `record_sample` 清空历史再覆盖写。
  现在只丢弃坏行，保留全部有效样本。
- **`event_log_keep<=0` 归档最新事件**：`log[:-keep]` 在负值时取错切片，最新事件反被归档。夹到最小 1。
- **负价商品反向加钱**：`price<0` 时买入 `gold -= total` 反而增加金币；市场与交易双层校验。
- **playbook 浅拷贝污染默认值**：修改返回的 `beat.pattern` 会永久改变 `DEFAULT_PLAYBOOK`。改深拷贝。

### 修复（边界与资源）

- `social` 的 `intensity` 接受 `NaN/Inf/0/负数` 并写坏关系值；未知事件静默加 0。改为 `ValueError`。
- `should_use_system2` 完全忽略 `inhibition_budget`（预算耗尽强制退化从未生效）；改为预算参与判定，并支持确定性 `roll` 供只读查询。
- `apply_runtime_fields` 重复导入同一世界书会把条目翻倍（21→42）；按 id/正文去重。
- `character_card_read` 不标记 `untrusted`、不报告注入命中；现在与 `narration_context` 同规格。
- `lyapunov_exponent` / `predictability_horizon` / `hawk_dove_ess_frequency` 的数学域错误改为返回极限值。
- `model` 对 `lerner_price(elasticity<=1)` 返回 `inf`，不是合法 JSON；改为明确报错。
- `open_panel` 每次调用都新建 HTTP 服务器线程；同状态复用、换局重建。
- `load_setting` 在 wheel 安装场景下找不到相对路径 `settings/...`；增加包内路径回退。
- 设定包规范化补上下界：`hp_max>=1`、`hp/gold` 非负、市场价 `>=1`、库存 `>=0`、关系 clamp 到 ±100。
- 等级阶梯改用最长匹配，避免「练气」吃掉「练气三层」；事业线关系谓词复用 `entity_key`。

### 测试

- `verify_branches.py` 新增 33 条回归断言（159→192 运行时断言），覆盖上述每条修复。
- `verify_docs.py` 由 16 项扩到 22 项：新增规则函数数、自检脚本数、英文 README / 展示站工具数、
  全仓 Markdown 脚本引用、展示站相对链接、快速上手示例可执行性六类漂移检测。
- `verify_injection.py` 由 9 项扩到 11 项：角色卡预检入口的 `untrusted` / `content_policy` 契约。
- `verify_tests.py` 的断言基线校准到静态真实值（panel 66 / mcp 64 / cli 9 / memory 7 / branches 175 / docs 22 / injection 11）。
- `verify_mutation.py` 的 M06 / M25 片段随实现更新（片段失效会被判为失败，不再静默跳过）。
- `pre_push_gate.sh` 修两处假绿/假红：覆盖率采样失败标志写错导致永远 FAIL；本机缺 coverage /
  playwright 时由 SKIP 改为 FAIL（CI 会跑这两项，本机不能跳过）。Gitee CI 补齐 `verify_world`、
  覆盖率门禁与 wheel 安装验证，与 GitHub 判据对齐。
- 断言审计 632 条 0 可疑；门禁 22 项全绿。

### 文档

- 工具数统一为 39（英文 README 补玩法/世界书 5 个工具）、规则函数 162、自检 14、门禁 22。
- 修正 `__init__.py` 里指向不存在的版本校验脚本的幽灵引用（版本一致性实际由 `verify_docs.py` 承担）。
- 展示站修复 `../GAMEPLAY.md` 与 `../README.md` 死链，示例命令改为可执行（初始金币买得起）。
- `docs/demo/README.md` 的截图命令改为真实可用的 `scripts/shots.py`。

---

## v1.1.0 — 2026-10-24

在 v1.0.0 的"世界观可换"之上，补齐**玩法可换**：同一个规则内核，四种完全不同的游戏循环。

### 新增：玩法层（playbook）

`playbook` 决定这一局"怎么玩"，规则函数一行不改：

| 字段 | 作用 |
|---|---|
| `loop` | `freeform`（自由推进）/ `choice`（选项推进）/ `mud`（地点命令）/ `ttrpg`（声明→判定→后果） |
| `progress` | 进度轴：`level` / `gold` / `reputation` / `knowledge` / `clock` |
| `failure` | 失败条件：`hp` / `sanity` / `clock` / `deadline` / `none` |
| `beat` | 节拍序列与切换节奏（如「日常·摩擦·升级·代价·回收」每 6 回合） |
| `settlement` / `context` | 允许的结算方式、每回合上下文注入策略 |

新增工具 `playbook_info`（含给宿主的叙事指南 `loop_guide`）与 `failure_tick`（失败钟）。

### 新增：事业线（questlines）

stage DAG + 世界状态谓词 + 奖励，取代"待办清单"式的任务系统：

- `visibility` 决定何时从 dormant 浮现（不满足就不占面板）
- `enter_if` / `exit_if` 控制每一幕的进入与离开；没有 `exit_if` 的一幕**永不自动推进**
- `fail_if` / `deadline_tick` 失败优先于任何推进
- 谓词只看世界状态：`flag` / `visited` / `gold_gte` / `karma_gte` / `tier_gte` / `relation_gte` / `item_gte` / `counter_gte` / `stage_done` / `quest_done` + `all` / `any` / `not`
- 载入时校验 DAG：有环、next 指向不存在的 stage 一律报错
- 新增工具 `quest_status` / `quest_advance`

### 重写：世界书引擎（lorebook）

旧实现只有"constant + 主键 + 副键 AND"的近似，导入真酒馆世界书会静默丢语义。现在：

- `selectiveLogic` 四值（AND_ANY / NOT_ALL / NOT_ANY / AND_ALL）
- `probability` / `use_probability`（`sha256(seed|tick|entry)` 派生，确定性）
- `sticky` / `cooldown` / `delay`（按 tick 计，写进状态文件，随快照回退）
- `group` / `group_weight` / `group_override`（同组只出一条）
- `scan_depth` / `match_whole_words` / `exclude_recursion`
- 递归扫描**默认关闭**（实测打开会把 21 条里的 20 条拉进上下文）；`configure(lore_recursion=N)` 可开
- 新增工具 `lore_lookup`（按任意文本预演触发结果，回答"为什么这段被触发"）
- 面板新增「世界书」抽屉：每条设定的触发次数、sticky/cooldown 剩余

### 新增：面板玩法区

- 左栏「玩法」卡：循环类型、进度条、失败条、当前节拍、宿主指南
- 中栏「事业线」卡：已浮现的线（最多 4 条）、当前幕、目标清单、期限
- 「世界书」抽屉与命令面板入口

### 四套设定包全部升级

| 设定包 | loop | 进度轴 | 失败 |
|---|---|---|---|
| 玄枢界 | freeform | 修行阶 0–10 | 重伤退场（hp） |
| 折剑行 | ttrpg | 身手 0–7 | 债主上门（clock 12） |
| 霓虹深渊 | mud | 评级 0–7 | 被盯上（clock 10） |
| 雾港 | choice | 线索 0–24 | 理智（sanity） |

每套各配 2 条事业线（主线 + 支线），全部用世界状态谓词推进。

### 修复

- `load_setting` 与 `build_state` 认的字段不是同一批：设定包里的 `playbook` / `questlines`
  会在载入时被静默丢掉。现在统一委托 `settings_loader.apply_runtime_fields`。
- 面板「事业线」卡在演示存档里永远显示"还没到浮现的时候"——`make_demo` 没调 `questline.advance`。
- 空状态下调 `playbook.summary` 会误报 `failed=True`（无 player 时不该判失败）。
- 世界书递归默认打开导致上下文被整本书塞满。

### 测试

- 新增 `scripts/verify_gameplay.py`（60 项）：剧本四循环、进度轴、失败钟幂等、节拍循环；
  事业线 DAG/可见性/exit_if/奖励只发一次/失败优先/谓词；世界书四值逻辑/sticky/cooldown/同组/概率确定性/递归；
  四套设定包集成；回退一致性。
- 变异测试扩到 **36 个**（新增 M33–M36：事业线绕过 exit_if、递归默认打开、sticky 无限续期、失败钟不幂等）。
- 断言审计 596 条 0 可疑；面板断言 72；MCP 64。

### 文档

- 新增 `docs/GAMEPLAY.md`：玩法层设计文档（为什么需要、字段表、DAG 规则、世界书语义与不支持项）。
- `GAME_MASTER_PROTOCOL.md` 增加 §1c「玩法剧本与事业线」。
- `settings/README.md` 增加 `playbook` / `questlines` 字段说明。

---

## v1.0.0 — 2026-10-24

首个"可以直接交付给别人玩"的版本。相比 v0.9.0，这一版修掉了三个**会让项目在某些环境里根本跑不起来**
的缺陷，并把"世界自己会动"从"部分成立"做到"四套世界观都成立"。

### 修复（阻断级）

- **MCP SDK 布局不兼容**：`mcp_server.py` 只 `from mcp.server.mcpserver import MCPServer`，
  而 PyPI 当前稳定版（mcp 1.30）的入口是 `mcp.server.fastmcp.FastMCP`。
  结果是：装了 mcp 的环境下**所有 31 个工具全部无法调用**（客户端只看到 "Connection closed"）。
  现在两套布局都支持（`_MCPServer` 兼容层），并且 `FastMCP` 不接受 `version` 参数的情况也已处理。
- **`seed_rng` 裸 import numpy 挂死 MCP 子进程**：每次结算都会 `import numpy` 试图重置全局种子。
  在本机 MCP stdio 子进程里，这个 import 会让 `status` / `narrative` / `tick` 全部超时（实测 15s+ 无响应），
  而 CLI 里完全正常——这是最难查的一类 bug。现在只在 numpy **已经被导入**时才同步种子，
  符合"零第三方依赖"的宣称，也消除了挂死。
- **包元数据未执行**：多处 `importlib` 别名注册只创建 module 对象、不执行 `__init__.py`，
  导致 `from game_engine import __version__` 永远失败。现在统一在注册后 `exec_module`。

### 修复（语义分裂）

- **CLI 的 `tick` 不驱动世界演化**：只有 MCP 的 `tick` 调 `evolve_world`。
  同一份存档走 CLI 与走 MCP 会得到两个不同的世界（违反 INV-E4/E6）。
  现在 CLI 的 `tick` 与 MCP 完全同构，`verify_cli.py` 新增断言锁定。
- **只读工具偷偷落盘**：`status` / `world_state` 会 `save_state` 并推进 `rng_counter`。
  这意味着"查没查状态"会改变后续战斗结果——直接破坏可复现性。
  现在只读工具零副作用（字节与 mtime 都不变），`verify_mcp_stdio.py` 断言。
- **死目标刷屏**：对已倒下目标继续攻击会重复写编年史，500 回合存档里同一条"已经没有还手之力"出现 ×12。
  现在返回提示但不写事件。
- **势力演化两个极端**：先"全体贴 100"（排行榜变平线），改成共享总容量后变成"全体 35.5"（同样没信息量）。
  现在每个势力有由名字确定性派生的禀赋上限 + 温和 LV 压制 + 挑战者回流，长期有格局、短期有换手。
- **`save_state` 偶发 PermissionError**：Windows 上杀毒/索引器瞬时占用目标文件会让一次正常回合失败。
  现在 `os.replace` 带 5 次退避重试。

### 新增

- **三套新设定包**：`折剑行`（武侠）、`霓虹深渊`（赛博朋克）、`雾港`（调查悬疑）。
  加上 `玄枢界` 共四套，覆盖四种完全不同的世界观与术语体系。
- **`scripts/verify_settings.py`（17 项断言）**：逐包验证载入完整性、术语覆盖、货币/品牌落盘、
  地点描写、连跑 15 回合后势力与相位都在动。已接入门禁与 CI。
- **面板：行动队列（双向通道）**：浏览器里可以排队行动，写入 `<state>.inbox.jsonl` 侧写；
  Agent 用新工具 `pending_actions` 取走并照常结算。状态文件仍然只读，确定性不被破坏。
  三道闸：同源 Origin、`application/json`、长度上限。
- **面板：世界脉搏卡**：Panarchy 相位 / 存量 / 连接度 / 烈度 / 势力存量 / 崩解次数。
- **面板：命令面板**（`Ctrl/⌘ + K`）、**分享模式**、**状态导出**、**时间线搜索与类型筛选**、
  **角色卡详情弹窗**（卡面文字来自设定包）。
- **`scripts/make_demo.py`**：确定性生成四套世界的真实演示存档（含世界演化、大事记、摘要、正文）。
- **`scripts/shots.py`**：真实浏览器逐项断言后截图 + 录制交互视频（`docs/screenshots/walkthrough.mp4`）。
- **`docs/BENCHMARK.md`**：7 个具名竞品的逐维度对标，含 10 条差距的四类处置。
- **`CHANGELOG.md` / `ROADMAP.md` / `CONTRIBUTING.md` / `SECURITY.md`**。
- **34 个 MCP 工具**（新增 `pending_actions`）。

### 重构（行为不变）

- `engine.py::main` 拆成命令表 + 14 个处理函数（圈复杂度 D(25) → A(1.75)）。
- `panel.py::build_scene` 拆成 7 个小函数（E(35) → A）；`classify_event` 拆成类型规则表（D(24) → A）。
- `mcp_server.py::load_setting` 拆出 `_apply_bundle_extras`（D(29) → C(16)）。
- `state_schema.seed_rng` 的 numpy 分支改为惰性。
- `init_game.py` 的 `current_location_desc` 改为 `location_desc`（与 engine/panel 一致）。

### 测试

- 断言审计：547 条（0 可疑）。
- 变异测试：**36 个变异，杀死 36，存活率 0%**（新增 M26–M36：只读落盘、CLI tick 分裂、死目标刷屏、
  队列无上限、跨站请求、文档版本漂移、README 工具数漂移、事业线绕过 exit_if、世界书递归默认打开、
  sticky 无限续期、失败钟不幂等）。同时把"变异片段失效"从静默 SKIP
  改为失败——历史上正是一次 SKIP 让一条规则从未被真正验证过。
- 门禁 17 项全绿（编译 / 审计 / 8 套自检 / 覆盖率 / 压测 / 界面 / 变异 / 打包 / wheel）。
- 覆盖率 88%（核心域），bandit 0 / pyflakes 0。

### 已知限制

- 面板未做 WCAG 2.1 AA 全量审计（无 axe-core 扫描）。
- 世界书 GUI 编辑器未做（与"面板严格只读"的架构决策冲突）。
- 长局记忆是关键词检索，不是向量语义检索（见 ROADMAP P2）。

---

## v0.9.0 — 2026-10-23

- 定位闭环：世界演化驱动（势力/谣言/风气/NPC/Panarchy）、相位与心流参与结算、
  六维道德由业债累加、面板术语可配置、叙事正文落盘。
- 修 3 个真 bug（暴击算成失败 / 道德恒 0 / 涌现事件重复）与台账无界。
- 新增 `verify_world.py`（46 项）与变异 M20–M25。

## v0.8.0 — 2026-10-15

- 打包完整性、面板截图、双 README 预览区，首个可安装版本。

更早的历史见 `ARCHITECTURE.md` 的任务清单（T1–T27）与 `docs/` 下的两轮审查报告。
