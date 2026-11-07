# 先贤调研：12 个互动叙事 / 世界模拟项目的可落地借鉴

> 采集日期：**2026-11-04**。star 数、语言、许可证、最近活跃时间取自 GitHub API
> `repos/{owner}/{repo}` 的 `stargazers_count / language / license.spdx_id / pushed_at`；
> 星数为近似值，会随时间变化。NovelAI 为闭源服务，无仓库指标，按文档与生态实现核对。
>
> 这不是项目介绍合集。它只回答一件事：**哪个机制值得抄，抄成我们代码里的什么。**
> 每条给出「来自哪个项目 + 具体机制（文件/字段/公式）+ 我们怎么用（落到哪个文件）」。
> 已落地的标 `[已落地]` 并附验证脚本；未落地的标 `[建议]`，附数据结构与验收方式。

---

## 一、项目档案（12 项）

| # | 项目 | 仓库 / 入口 | stars | 语言 | 许可证 | 最近活跃 |
|---|---|---|---|---|---|---|
| 1 | SillyTavern | `SillyTavern/SillyTavern` | 35,273 | JavaScript | AGPL-3.0 | 2026-10-02 |
| 2 | AI Dungeon 开源版 | `latitudegames/AIDungeon` | 3,220 | Python | MIT | 2020-07-25 |
| 3 | NovelAI Lorebook | `docs.novelai.net/text/lorebook.html`（闭源） | — | — | 专有 | 文档站本次采集不可达（字段以 SillyTavern 导入器 `convertNovelLorebook` 为准） |
| 4 | 生成式智能体 | `joonspk-research/generative_agents` | 22,338 | Python（GitHub 未标注） | Apache-2.0 | 2024-08-05 |
| 5 | 修仙世界模拟器 | `4thfever/cultivation-world-simulator` | 2,142 | Python | CC BY-NC-SA 4.0（API 显示 NOASSERTION） | 2026-08-16 |
| 6 | Open Dungeon | `newideas99/open-dungeon` | 240 | TypeScript | MIT | 2026-07-06 |
| 7 | Ink / inkle | `inkle/ink` | 5,004 | C# | MIT | 2026-05-05 |
| 8 | Twine / Harlowe | `klembot/twinejs`；Harlowe 在 `foss.heptapod.net/games/harlowe` | 2,938（Twine） | TypeScript；Harlowe 为 JS | GPL-3.0；Harlowe Zlib | 2026-10-07 |
| 9 | Inform 7 / Z-machine | `ganelson/inform` | 1,663 | C（编译器用 InC） | Artistic-2.0 | 2026-06-24 |
| 10 | Evennia | `evennia/evennia` | 2,118 | Python | BSD-3-Clause | 2026-11-03 |
| 11 | mem0 | `mem0ai/mem0` | 68,386 | Python | Apache-2.0 | 2026-11-04 |
| 12 | LLM 文字冒险框架族 | `camel-ai/camel` / `microsoft/autogen`；补充 `stickystyle/ZorkGPT`、`camel-ai/oasis` | 18,013 / 61,699；36；5,383 | Python | Apache-2.0 / MIT（代码）+ CC-BY-4.0（文档）/ MIT / Apache-2.0 | 2026-11-02 / 2026-10-28 / 2026-04-05 / 2026-11-02 |

第 12 项是一个族而非单仓库：CAMEL 是角色扮演式多智能体编排，AutoGen 是事件驱动 actor 运行时，
ZorkGPT 是"LLM 玩文字冒险"最完整的工程样本，OASIS 是百万 agent 社交模拟的规模样本。
四者可抄点不同，下文按机制拆开引用。

---

## 二、架构核心对照

| 项目 | 状态如何组织 | 规则与叙事如何分离 | 确定性 | 已知缺点 |
|---|---|---|---|---|
| SillyTavern | 聊天记录 + World Info 条目 + 角色卡；状态主要在提示词里 | 只有"触发哪些设定"是规则；数值无引擎 | 触发闸门可复现（同文本同条目），生成不可复现 | 无世界状态、无数值结算；长局靠扩展；作者脚本可任意改上下文 |
| AI Dungeon OSS | `Story.actions[]` + `results[]` + `game_state` 字典 + 固定 20 条滑动窗口 | 基本不分离：`latest_result()` 把最近 20 对文本拼给模型 | 采样不可复现；`seed` 只在 constrained 模式有意义 | 状态只在文本里；无检索、无归档、无规则；项目 2020 年后停更 |
| NovelAI Lorebook | 条目（keys/text/enabled/budgetPriority）+ 生成上下文 | 只有激活规则；叙事完全由模型 | 激活可复现，生成不可复现 | 无历史检索；预算按 token 而非语义；闭源无法审计 |
| generative_agents | Memory Stream：`ConceptNode`（s/p/o、description、poignancy、embedding、keywords、depth、last_accessed）+ 事件/思考/对话三序列 | 认知模块分 perceive/retrieve/reflect/plan；规则只在"何时反思/取多少" | **否**：LLM 生成 + embedding + 采样 | 每 agent 每 tick 多次 LLM，成本高；无持久世界规则；记忆只增不删 |
| 修仙世界模拟器 | SQLite：`events` 主表 + `event_avatars` / `event_sects` / `event_observations` 关联表；世界对象在内存与存档 | LLM 只产出 `action_name_params_pairs`，动作注册表校验后执行；事件在提交阶段生成 | **否**：LLM 决策不可复现；事件库可审计但决策不可重放 | 依赖模型服务；每 NPC 一次 LLM；CC BY-NC-SA 不能商用；状态与模型输出强耦合 |
| Open Dungeon | 本地 SQLite：`chats` / `messages` / `characters`；`story_summary` + `story_summary_count` 水位 | 叙事全交给模型；只有上下文打包是工程规则 | 否（采样）；打包逻辑确定 | 无规则结算；无世界状态；长局只靠滚动摘要 |
| Ink | 运行时 `StoryState`：变量表、调用栈、访问计数、当前指针、`storySeed` / `previousRandom`，整体可 JSON 序列化 | 剧本（knot/stitch）与运行时分离；选择/分流是显式指令 | **是**：给定选择序列与种子可完全重放 | 无世界模拟；作者要手写分支；C# 运行时不便于嵌入 Python 服务 |
| Twine / Harlowe | passage 图 + 变量；Harlowe 用 `(set:)` 改状态，历史栈支持回退 | 编辑器与运行时分离；故事格式定义渲染与宏 | 基本是：给定选择与随机宏种子可重放 | Twine 是编辑器不是引擎；无世界模型；大型故事图难维护 |
| Inform 7 / Z-machine | 对象树（rooms/things/people）+ 属性 + 关系；Z-machine 内存对象表 | 规则书分层：check/carry out/report；`instead of` 覆盖；每回合规则 | **是**：无隐式随机；`@random` 可用种子复现；Quetzal 存档完整 | 学习曲线陡；自然语言语法有歧义；不适合自由叙事 |
| Evennia | Django ORM 持久对象（`db_key` / `db_typeclass_path` / 属性处理器）+ 持久脚本 | typeclass 定义行为，命令/锁定义权限；叙事由开发者写 | 引擎层确定（无隐式随机）；但持久脚本的定时任务按墙钟触发，带定时逻辑的场景不可重放 | 重框架、重依赖；为 MUD 设计，不适用单机叙事 |
| mem0 | 向量库 + SQLite 历史表；每条记忆有 `hash`、`created_at/updated_at`、变更历史 | LLM 只做增量事实抽取；覆盖/删除是显式 API，检索是向量相似度 | **否**：LLM 抽取 + embedding | 依赖外部模型与向量库；抽取错误污染长期记忆；无领域规则 |
| CAMEL / AutoGen / ZorkGPT / OASIS | CAMEL：角色+消息；AutoGen：actor 消息总线；ZorkGPT：地图图 + 记忆库 + 知识库；OASIS：百万 agent 图 + 推荐系统 | ZorkGPT 的 Critic 两段校验（对象树快检 → LLM 评估）是唯一把"规则"放进决策环的 | 均否；ZorkGPT 用状态哈希做循环检测但不重放 | 多 agent 框架普遍重、成本高；ZorkGPT 依赖 Z-machine 专用接口；OASIS 面向社交平台而非单人叙事 |

**结论**：做到可复现的只有"规则/剧本先行"的四家（Ink、Twine、Inform、Evennia 引擎层）；
LLM 先行的八家全部不可复现。这验证了本项目的路线（状态文件 + 种子 + 规则结算），
也说明该抄的是它们的**状态组织与记忆算法**，不是生成方式。

---

## 三、可落地借鉴点

### A. 记忆系统

#### A1. GA 三分量检索：recency / importance / relevance，权重 0.5 / 3 / 2 `[已落地]`

- **来自**：`generative_agents`，`reverie/backend_server/persona/cognitive_modules/retrieve.py:132-260`；
  超参在 `persona/memory_structures/scratch.py:57-63`（`recency_decay = 0.99`）。
- **机制**：
  1. `recency = 0.99 ** i`，`i` 是节点在时间序列里的位置（越新越大）。
  2. `importance = poignancy`，LLM 打的 1–10 分。
  3. `relevance = cos_sim(node_embedding, focal_embedding)`。
  4. 三个分量在**候选集内**各自 min-max 归一到 0–1（`normalize_dict_floats`，range=0 取中点）。
  5. `score = 0.5*recency + 3*relevance + 2*importance`，取 top-k；命中节点更新 `last_accessed`。
- **我们怎么用**：`rules/context.py:31-165`。
  - 权重原样保留 `SCORE_WEIGHTS = {"recency": 0.5, "relevance": 3.0, "importance": 2.0}`。
  - relevance 换成**确定性词元重叠**：ASCII 词 + 中文二元组（`_tokens`，`rules/context.py:72`），
    无嵌入模型、无第三方依赖；`灯塔三年前熄了` 与 `灯塔早已不亮` 共享 `灯塔`。
  - importance 换成 `IMPORTANCE_BY_KIND`（承诺 1.0 / 线索 0.9 / …）× confidence，可被 `importance` 参数覆盖。
  - recency 用 `0.99 ** (tick - fact.tick)`。
  - 暴露为 `context_search(ranked=true)`（默认开）；`context_pack` 两处检索都走打分。
- **验收**：`verify_generic.py` N3「高相关旧事实排在低相关新事实之前」「总分等于三分量加权和」
  「同状态检索完全可复现」；变异 M45（relevance 权重清零）必须变红。

#### A2. GA 反思触发：importance 累积到阈值才反思 `[已落地]`

- **来自**：`generative_agents`：`cognitive_modules/perceive.py:178-179` 每次感知执行
  `importance_trigger_curr -= event_poignancy`；`cognitive_modules/reflect.py:135-185`
  在计数器 ≤0 时触发反思：生成 3 个 focal point、检索相关节点、产出带证据节点 id 的洞察，
  再作为 `thought` 节点写回（`depth = 1 + max(证据节点 depth)`），最后重置到 150。
- **机制要点**：**不是每回合反思，也不是按时间反思，而是按"信息量"反思**；洞察带证据链。
- **我们怎么用**：`rules/context.py:477-520`。
  - `reflection_due(state)`：累加 `reflected_upto` 之后新增开放事实的 importance，
    默认阈值 `config.context_reflect_threshold = 10`，返回 `due / accumulated / candidates`。
  - `mark_reflected(state)` 由 `write_summary` 调用（`mcp_server.py:1401`），推进水位，
    同一批事实不会反复提示"该反思了"。
  - `context_pack` 与 `context_summary` 都带 `reflection` 块，宿主每回合都能看到"信息是否该压缩"。
  - 引擎不生成洞察文本——那是叙事模型的事；引擎只做**何时压缩**的确定性判断。
- **验收**：`verify_generic.py` N3 四条（未达阈值不触发 / 过阈值触发 / mark 后归零 / pack 输出建议块）。

#### A3. mem0 写入期冲突消解：显式 subject + 留档代替删除 `[部分落地]`

- **来自**：`mem0ai/mem0`，`mem0/memory/main.py:881-1096`。
- **机制**（以当前 OSS `main` 的 v3 管线为准）：
  1. 先向量检索 top-10 现有记忆，把 UUID 映射成小整数交给 LLM（防幻觉出不存在的 id）。
  2. 单次 LLM 调用只做**增量抽取**（`ADDITIVE_EXTRACTION_PROMPT`）：把新对话里值得记的事实抽成文本，
     不在这一步决定覆盖谁。
  3. 每条文本取 `md5(text)` 去重（库内 + 本批内），再批量嵌入入库。
  4. 合并/修正/删除走**显式 API**（`update(memory_id)` / `delete(memory_id)`），
     每次变更写 `history`（`old_memory` / `new_memory` / event / created_at），可审计。
- **我们怎么用**：`rules/context.py:205-275` 的 `remember(..., subject=..., supersede=True)`。
  - 不做 LLM 抽取：**冲突条件由调用方显式给出**（同 kind + 同 subject）。
  - 旧事实不删除，标 `status="superseded"` 并写 `superseded_by` + `closed_tick`；
    `context_search(status="superseded")` 可查回审计链。
  - 纯文本重复仍按"同 kind + 同正文"刷新（原有行为，等价于 mem0 的 hash 去重）。
- **没抄的部分**：让模型自动判定"覆盖哪一条"。mem0 的当前实现也把覆盖交给显式 API，
  这一点与我们的 `supersede + subject` 同构；差别只在它用向量召回候选、我们要求调用方点明 subject。
- **下一步**：给 fact 增加 `derived_from: [fact_id]` 与逐条 `history: [{tick,event,from,to}]`，
  补齐 mem0 的变更历史（当前只有一跳 `superseded_by`）。

#### A4. 压缩水位：summary 记录"覆盖到哪里" `[已落地；建议升级到 seq]`

- **来自**：Open Dungeon `src/lib/db.ts:107-115`：`story_summary` + `story_summary_count`
  两个字段一起存，`setStorySummary(chatId, summary, coveredCount)` 明确摘要覆盖了多少条消息；
  新消息只追加在覆盖点之后，不会重复摘要。
- **对照**：AI Dungeon 只有 `Story.memory = 20` 的固定滑动窗口（`story/story_manager.py:34,68-82`），
  无水位，旧内容一过窗口永久丢失；NovelAI 只有常驻 Lorebook，没有历史压缩。
- **我们怎么用**：`summaries[]` 已有 `upto_tick`（等价水位），`write_summary` 追加并裁剪到 `summary_keep`。
  本轮事件序号落地后，建议把水位升级为 `upto_seq`：`write_summary` 同时记 `state["event_seq"]`，
  这样同一 tick 内多次摘要也不会漏事件。
- **验收**：`verify_generic.py` N3 预算打包 + `verify_world.py` W12 归档窗口。

#### A5. 前缀稳定：量化排序，别让提示词缓存每回合失效 `[已落地]`

- **来自**：Open Dungeon `src/lib/story-prompt.ts:33-66`。注释写得很直白：
  逐条驱逐历史会改变 prompt 起点，让模型服务的 prefix cache 失效，整段重新 prefill；
  它用 `HISTORY_EVICTION_BLOCK = 16` 按块丢弃，保持前缀长时间稳定。
- **我们怎么用**：`rules/context.py:145-165`。
  - 打分是**候选集内相对值**，新增一条事实会让所有分数轻微漂移；若按全精度排序，
    每回合 section 顺序都在抖。排序键量化到 `0.25` 的桶，桶内按 fact id 稳定排序；
    `config.context_stable_order=false` 可关（调试用）。
  - `pack` 的 section 顺序仍由固定 priority 决定（玩法 → 未结案 → 场景 → 事件 → 其他），
    只有同一节内部按打分排。
- **验收**：`verify_generic.py` N3「新增无关事实不改变已有排序」。

#### A6. 事件观察者模型：NPC 只知道他看见/被告知的事 `[已落地]`

- **来自**：`cultivation-world-simulator`，`src/classes/event_storage.py:76-160,260-310` 与
  `event_query.py`：
  - `event_observations(event_id, observer_avatar_id, subject_avatar_id, propagation_kind, relation_type)`，
    `UNIQUE(event_id, observer, propagation_kind)`；写入时先给所有 `related_avatars` 建 `self_direct`，
    再合并显式传入的 observation。
  - 查询分 `EventAudience.DIRECT` / `OBSERVED`，记忆范围分 `ALL / MAJOR / MINOR`
    （`is_major` + `is_story` 决定长期/短期记忆）。
- **为什么值得抄**：LLM 叙事最常见的硬伤是"NPC 说出了玩家独自看到的秘密"。
  这是**知识边界**问题，提示词解决不可靠；需要数据层回答"谁知道这件事"。
- **具体落地**：
  1. `context.remember(..., witnesses=["player","npc_lin"])` 写入 `witnesses`（默认 `["player"]`）。
  2. `context.pack(..., knower="npc_lin")` 只打包 `witnesses` 含该 NPC 或 `public=True` 的事实。
  3. `narration_context` 对每个在场者返回 `known_facts` 摘要，宿主叙述对话前先看这一块。
  4. 传播：`context.tell(fact_id, to="npc_lin", propagation="told")` 追加 witness 并记来源。
- **验收**：新增 N3 断言「不在场 NPC 检索不到玩家独见事实」「被转述后可见」。

### B. 世界状态与事件溯源

#### B1. 事件表 + 关联表 + 观察表，以及单调序号 `[已落地最小集]`

- **来自**：`cultivation-world-simulator` `src/classes/event_storage.py`：
  `events(id PK, month_stamp, content, is_major, is_story, event_type, render_key, render_params,
  subject_snapshots, created_at)`；`event_avatars` / `event_sects` 多对多；
  游标分页 `(month_stamp, rowid)`；`cleanup(keep_major=True, before_month_stamp)` 只删小事。
- **可抄的三点**：
  1. **事件 id 是主键，不是自增行号**——重复写入用 `INSERT OR IGNORE` 幂等。
  2. **渲染参数与事件正文分离**（`render_key` + `render_params` + `subject_snapshots`），
     正文可重新本地化/重渲染，不必改历史。
  3. **大事保留、小事清理**：长局不会把磁盘吃光，编年史仍有骨架。
- **我们怎么用**：
  - 已有 `.log[.gen].jsonl` 追加归档 + `.archive-pending` 哈希日志 + 世代隔离（`state_schema.py:103-113,266-420`）。
  - 本轮给每条事件加**单调 `seq`**（`state_schema.py:604-616`）：同一 tick 内多条事件的真实先后
    不再依赖文件行号；归档逐行保留 seq，`verify_world.py` W12 断言"逐行递增、可重放、窗口只留最新 N 条"。
  - 面板事件 id 改为 `tick.seq:type:hash`（`panel.py:150-160`），修掉同一 tick 同类型同描述撞键
    被前端去重丢掉的问题。
  - **没抄**：SQLite。JSONL 可 diff、可随快照迁移、零依赖；等归档超过十万条再评估
    （`sqlite3` 是标准库，迁移不破坏零依赖原则）。
- **验收**：`verify_world.py` W12 六条 + 变异 M49（seq 不推进）/ M18（面板事件 id）。

#### B2. 分支与回退：世代归档，而不是截断共享文件 `[已落地]`

- **来自**：Twine/Harlowe 的历史栈与 undo；Open Dungeon 的分支叙事（设计文档）；
  Aventuras 的 delta log 设计（`docs/data-model.md`，**该项目处于 pre-implementation，
  只有设计没有运行代码**，不能当实现样本）。
- **我们怎么用**：已有 `archive_generation`：快照回退时递增世代，归档切到新文件，
  旧分支的历史物理保留（`state_schema.py:103-113`）；`restore` 里 `archive_generation = max(...) + 1`。
  本轮不新增机制，只把它写进结论：**分支不是删除未来，是换一条归档线**。

#### B3. 状态哈希与循环检测 `[已落地]`

- **来自**：`stickystyle/ZorkGPT` README「State Manager」：用状态哈希发现"完全相同的状态重复出现"，
  提示 agent 陷入循环；地图系统给每条边记 confidence，连续失败的出口会被剪掉。
- **具体落地**：
  - `state_hash = sha256(canonical_json({location, hp, inventory, world_flags, quest stages,
    market prices}))`，不含 tick/时间戳。
  - `state["_state_hashes"]` 保留最近 20 个（有界）；同一 hash 出现 ≥3 次时 `tick` 返回
    `loop_suspected=true` 并给出"改变场景/推进时间"的建议。
  - 地图边：`travel` 记录 `(from,to)` 成功次数，失败 ≥3 的边从建议出口里隐藏（不禁止）。
- **验收**：新增 W 断言「同状态重复 3 次触发 loop_suspected」「剪枝只影响建议不影响可达性」。
- **注意**：ZorkGPT 本身不可复现（LLM 决策），只抄它的**检测器**，不抄生成环。

#### B4. 规则优先级：Inform 的 rulebook + Evennia 的 typeclass `[已落地]`

- **来自**：
  - Inform 7：rulebook 分层（check → carry out → report），`instead of` 高优先级覆盖，
    "every turn" 规则，对象有属性与关系。
  - Evennia：`db_typeclass_path` 决定对象行为类；`AttributeHandler` 用 `db_key/db_category/db_value`
    存任意属性；持久脚本跑定时逻辑。
- **可抄的**：**规则优先级 + 例外声明**。现在特例写死在 `combat.py` / `social.py` 里，
  每加一条世界观特例就要改引擎，违反"换设定包不改代码"。
- **具体落地**：新增 `rules/rulebook.py`：
  ```
  rule = {
    "id": str, "when": predicate,          # 复用 questline.evaluate 的谓词
    "then": [effect],                      # 复用 systems.EFFECT_OPS 白名单
    "order": int, "stop": bool,            # 数值大者先跑；stop=true 截断后续规则
  }
  ```
  `apply(state, event, rules)` 按 order 降序执行，返回 `{applied:[id], stopped_by:id}`；
  设定包在 `bundle.rules` 里声明，`validate()` 检查 when/then 合法性。
  这把 Inform 的 rulebook 压成约 40 行可测试函数，不引入新依赖。
- **验收**：`verify_systems.py` 新增「高 order 先执行」「stop 截断」「非法 effect 定义期拒绝」。

#### B5. 状态爆炸的三个已有阀门 `[已确认]`

- CWS 用 `memory_scope = ALL/MAJOR/MINOR` 控制"查全部/只查大事/只查小事"，配合 `is_major/is_story`。
- 我们对应三处：
  1. `event_log_keep`（默认 200）只留最近窗口，溢出进归档（`state_schema.py:329-420`）。
  2. `context.MAX_FACTS = 400`，淘汰顺序：先已结案/过期，再最低 `confidence × tick`
     （`rules/context.py:287-297`）。
  3. `lore_runtime` 每类映射 `RUNTIME_CAP = 400`，历史 `HISTORY_CAP = 200`（`rules/lorebook.py:19-22`）。
- **结论**：不需要再加"记忆范围"枚举；需要的是给归档检索一个入口（已有 `recall` + 本轮打分）。
  写下来是为了防止以后重复造一套 MAJOR/MINOR 字段。

### C. 叙事结构

#### C1. ink 的 knot/stitch + once-only + visit count `[已落地]`

- **来自**：`inkle/ink`，`Documentation/WritingWithInk.md` §3/§6/§7：
  - `=== knot ===` 是基本单元，`= stitch` 是子节；`->` 是无输入跳转；
  - `*` 选项**默认只能选一次**，`+` 是 sticky（可重复）；
  - knot/stitch 名字本身就是**访问计数**：`{ visit_paris }` 是"去过"，
    `visit_paris.met_estelle` 精确到子节；
  - `TURNS_SINCE(-> knot)` 返回距上次访问的回合数。
- **我们怎么用**：
  - `lorebook` 新增 `once` / `max_fires` 两个闸（`rules/lorebook.py:147-165`），
    语义直接对应 ink 的 once-only choice：关键剧情条目不会因为关键词再次出现而重复注入。
    计数复用已有 `fired_count`，随快照回退，重放一致。
  - `questline` 的 stage DAG 等价于 knot 图。v1.9.0 补齐 `visit_count` 与 `TURNS_SINCE`：
    谓词 `{"visits": {"quest": "q", "stage": "x", "gte": 2}}` 与
    `{"turns_since": {"quest": "q", "stage": "x", "gte": 10}}` 在 `questline.evaluate` 里求值，
    数值从 `history` 的 `enter` 记录派生（`_visits` / `_turns_since`），不新增平行状态。
    从未进入的幕 `turns_since` 返回 None 且判为 False（fail-closed）。
    **验收**：`verify_mechanics.py` N10a–N10d。
  - **不抄**：ink 的 C# 运行时与 `.ink` 编译器。只借语义，不引第二套脚本语言。

#### C2. Twine/Harlowe 的 passage 图与变量作用域 `[已落地]`

- **来自**：Twine 的故事格式规范（passage 为节点、链接为边）；Harlowe 的 `(set:)` / `(if:)` / hooks；
  Harlowe 3 的 story 变量与 temp 变量**作用域分离**。
- **可抄的**：**图可视化**与**作用域声明**。
  - 我们有 `questlines[].stages[].next` 的完整 DAG，但面板只显示"当前幕"。
    用已 vendored 的 ECharts 画一张 stage DAG（节点按 done/current/dormant 着色），
    数据完全来自状态，不需要新字段。
  - 变量作用域：`game_adjust` 目前全部写进持久状态；建议加 `scope="turn"` 的临时资源，
    由 `tick` 清空（对应 Harlowe 的 temp 变量），用于"本回合 +2 命中"这类一次性修正。
- **不抄**：Twine 作为运行时。它是编辑器，故事格式与渲染强绑定；只需要它的图模型。

#### C3. Inform 7 的规则引擎与 Z-machine 的对象模型 `[建议/方向已验证]`

- **来自**：`ganelson/inform`：自然语言规则、rulebook 优先级、check/carry out/report 三阶段；
  Z-machine 标准：对象树（父/兄弟/子）、属性表、字典与语法行、Quetzal 存档。
- **可抄的**：
  1. **三阶段结算**：现在 `resolve_combat` 把"判定/扣血/写事件"揉在一个函数里。
     建议拆成 `check`（掷骰与修正）→ `carry_out`（改数值）→ `report`（生成事件文案），
     报告阶段只读结算结果。宿主可以只取 check 做预览，也方便测试对拍。
  2. **语法行**：MUD 玩法需要确定性的 `verb [prep] noun` 解析器（如 `go north`、`take lamp`），
     解析失败再交给 LLM。Inform 的 grammar line 是成熟范式：动词表 + 名词模式 + 优先级。
  3. **存档完整性**：Quetzal 保存整个对象树与调用栈；我们的状态文件等价，
     但 `event_log` 只是窗口。B1 的 seq 是补齐"历史可重放"的第一步。
- **不抄**：Inform 的自然语言语法本身（歧义大、实现重）；只抄规则优先级与对象模型。

#### C4. 提示词装配：固定窗口 vs 预算打包 vs 滚动摘要

- **AI Dungeon**：`Story.latest_result()` 把 `context` + 最近 20 对 action/result 直接字符串拼接
  （`story/story_manager.py:34,68-82`）。**缺点**：窗口外永久丢失，无检索、无摘要、无规则。
- **NovelAI Lorebook**：按键激活条目，`budgetPriority` 决定预算紧张时谁先保留
  （SillyTavern 的 `convertNovelLorebook` 把 `entry.contextConfig.budgetPriority` 映射到 `order`，
  见 `public/scripts/world-info.js:5560-5610`）。**缺点**：只解决设定注入，不解决历史检索。
- **Open Dungeon**：`packStoryHistory(messages, charBudget)` 从后往前按 `content.length + 80` 计费，
  超预算按 16 条一块丢弃；摘要放 system 段，标注 "treat as established canon"。
- **我们怎么用**：`context.pack` 已是"预算 + 优先级"；`recap` 是"摘要 + 大事记 + 最近事件"。
  本轮补的是**排序稳定性**（A5）。v1.9.0 补上 `prompt_prefix_hash`
  （section 标题 + 行序的 sha256，`rules/context.py: _prefix_hash`），宿主据此判断本轮前缀
  是否变化，从而决定是否复用 KV 缓存。零成本字段，不改变内容。
  **验收**：`verify_mechanics.py` N11a–N11c（同内容同哈希 / 内容变则哈希变）。

#### C5. SillyTavern World Info：命中评分、时间闸与槽位预算 `[已落地部分]`

- **来自**：`SillyTavern/SillyTavern`，`public/scripts/world-info.js`：
  - `WorldInfoBuffer.getScore(entry, scanState)`：主键命中数 +（`AND_ANY` 时）副键命中数；
    `AND_ALL` 只在**全部**副键命中时加分，否则只算主键分。`AND_ANY / NOT_ALL / NOT_ANY / AND_ALL`
    四种 `selectiveLogic` 决定副键是"任一 / 非全部 / 全无 / 全部"。
  - `filterGroupsByScoring`：同组内按 `getScore` 取最高分者，低分条目从本轮移除；
    组内没有 `useGroupScoring` 且全局开关关闭时，退回权重抽签。
  - 时间闸 `sticky / cooldown / delay`：sticky 期间条目保持注入且不重掷概率；
    cooldown 从 sticky 结束后起算；delay 表示第 N 条消息后才可用。
  - `scanDepth` 控制扫描最近多少条消息；`constant` 条目每轮常驻；`order/insertion_order`
    决定注入顺序；`position/depth/role` 决定插到提示词的哪个槽位。
- **我们怎么用**：
  - 四种 `selectiveLogic`、`sticky/cooldown/delay`、`scanDepth`、递归默认关闭在 v1.1.0 已落地
    （`rules/lorebook.py:56-140,147-200`，`verify_gameplay.py` G3 逐条断言）。
  - 本轮补 `_match_score` + `_pick_group(scoring=True)`（`rules/lorebook.py:224-260,294-310`）：
    同组按命中键数取最高，同分才回退 `group_weight` 抽签；默认关闭，保持旧行为。
  - **没抄**：`position / depth / role / outlet`——提示词槽位属于宿主（它才知道自己的模板），
    引擎只返回"命中哪些、按什么顺序"，不假设提示词布局。
  - **没抄**：`vectorized`——需要嵌入模型，理由见 D3。
- **为什么值得抄**：这是"同一份设定书在长局里不会每轮把全部条目塞进上下文"的工业级答案；
  比单纯的"关键词命中就注入"多出三层控制：命中强度、时间闸、组内互斥。

### D. 确定性

#### D1. 四个可复现项目的共同做法 `[已确认，部分已落地]`

| 项目 | 做法 | 能直接用的 |
|---|---|---|
| Ink | `StoryState.ToJson()` 保存变量、调用栈、访问计数、`storySeed`、`previousRandom`、`currentTurnIndex`；随机是**显式状态**，不是全局 `random` | 已有 `rng_seed + rng_counter`；建议把"上一次派生值"也落盘，便于审计随机序列 |
| Inform / Z-machine | 无隐式随机；`@random` 可种子；Quetzal 保存完整对象树 | 状态文件已等价；补"动作日志"才能真正重放（D2） |
| Twine/Harlowe | 给定选择序列与随机宏种子可重放；历史栈可回退 | 快照 + 世代归档已覆盖回退；选择序列未记录 |
| Evennia | 引擎层确定，但持久脚本定时器按墙钟触发，破坏重放 | 反例：我们的世界演化只挂 `tick`，不读墙钟，这是对的 |

#### D2. 动作日志：事件溯源缺的最后一块 `[已落地]`

- **现状**：`event_log` 记录"发生了什么"（desc + type + 结构化字段），但没有记录
  "玩家/宿主下了什么命令"。因此可以审计，不能**重放**：同样的归档 + 同样的种子，
  重跑不出同样的状态。
- **来自**：CWS 事件表只存事件不存命令；ZorkGPT 存状态哈希但不存命令；
  Ink 存的是选择序列（本质就是命令）。**四家里只有 Ink 做到命令级重放。**
- **具体落地**：在 MCP 事务包装器 `_run_state_transaction`（`mcp_server.py:233-260`）里，
  对写工具追加一行到 `<state>.actions.jsonl`：
  ```
  {"tick": 12, "tool": "combat", "args_sha256": "...", "rng_before": 41, "rng_after": 42,
   "state_before": "sha256:...", "state_after": "sha256:...", "seq": 87}
  ```
  - 只存 args 的哈希，不存明文（避免把玩家私密文本复制到第二个文件）；
    需要人类可读时用 `tool` + `tick` + `seq` 回查 `event_log`。
  - 读取工具不写（沿用 `_should_state_transaction`）。
  - 新增重放验证脚本（暂名 `verify_replay.py`，落地时再进门禁）：取快照 + actions.jsonl，逐条调用同名工具，
    断言每一步 `state_after` 哈希一致；不一致就指出第一个分叉点。
- **风险**：args 里有浮点数/顺序不确定的 list；哈希前要 canonical JSON
  （`sort_keys=True`、浮点 `repr` 固定）。
- **验收**：`verify_cli.py` 增加"同动作日志重放哈希一致"；变异"日志少写一条"必须变红。

#### D3. 为什么不引入 embedding `[决策记录]`

- GA、mem0、NovelAI（向量化条目）都用 embedding。收益是语义召回；代价是：
  1. 违反零依赖（需模型/服务）；2. 不可复现（不同模型版本不同向量）；3. 每回合延迟与成本。
- 替代：中文二元组 + ASCII 词元 + 类型权重 + 0.99 衰减，已覆盖"同义改写"的常见情况；
  真正的语义检索留给宿主（宿主本来就是 LLM，可在调用 `context_search` 前自己扩展关键词）。
- **重新评估条件**：当 `context` 事实 > 2000 条且召回率成为可测瓶颈时，再加**可选**嵌入适配器，
  且只作为 `ranked=true` 的一个分量，不改变默认确定性路径。

### E. 世界演化

#### E1. 势力/经济：logistic + Lotka-Volterra + 挑战者回流 `[已落地]`

- **来自**：`cultivation-world-simulator` 的宗门体系（`sect.py` / `sect_decider.py` /
  `sect_diplomacy_state.py` / `war.py`）证明"势力要有独立目标与外交状态"才像活的；
  但它是 LLM 驱动的，成本高且不可复现。
- **我们的做法**：`rules/world_evolution.py:87-166` 用"禀赋上限 + logistic + 头部两家 LV +
  挑战者回流 + 强者治理成本"，零 LLM、确定性、可复现。调研确认这条路线正确。
- **v1.9.0 已补**：`rules/world_evolution.py: _faction_intents` 给每个势力带
  `{expand, wealth, fame}` 权重（可按势力名确定性派生，也可用
  `state["faction_goals"]` 覆盖），把四个驱动量归一化后做**确定性 argmax**：
  `recruit`（招募）/ `trade`（经商）/ `ally`（结盟）/ `war`（兴兵），意向写进
  `state["faction_intents"]` 并小幅影响存量。LLM 只负责把结果写成叙事。
  第一版收益函数让所有势力长期停在"结盟"，`verify_mechanics.py` N13d 用
  "四种意向必须都可达"锁住这个退化。

#### E2. 推荐系统：OASIS 的 interest-based / hot-score `[已落地]`

- **来自**：`camel-ai/oasis` README「Integrated Recommendation Systems」：
  interest-based（用户兴趣向量与内容主题的相似度）与 hot-score-based（热度 + 时间衰减）。
- **已抄**：谣言热度按 OASIS hot-score 计算——
  `heat = i * (1 + log1p(mentions)) * 0.95^(tick - last_mention)`，
  落点 `rules/world_evolution.py: rumor_heat`（面板与 status 共用同一口径，避免各算各的漂移）。
  `mentions` / `last_mention` 在谣言被再次触发时推进，于是"旧事重提"能被表达出来；
  v1.8 的 `heat` 只是 SIR 感染率的别名，冷下去就再也回不来。
- **验收**：`verify_mechanics.py` N12a–N12c（同感染率下新近者更高 / 提及多则更高 / 夹在 (0,1]）。

#### E3. 定时器：Evennia 持久脚本调度的反面教材 `[不抄]`

- Evennia 通过 Twisted reactor 调度持久脚本（`evennia/scripts` 的定时任务），按墙钟触发，适合 MUD 的实时世界，但会让"同状态同输入"不再成立。
- 我们的 `tick` 是离散回合，由玩家/宿主显式推进，所有世界演化挂在 `tick` 上。
- **如果将来要做实时**：用 `tick` 计数推导"游戏内时间"，不要把 `time.time()` 引入结算；
  面板的 SSE 刷新可以读墙钟，但不得写状态。

---

## 四、本次已落地的代码改动（可对账）

| 借鉴点 | 文件 | 验证 |
|---|---|---|
| GA 三分量检索 | `rules/context.py:31-165`（`RECENCY_DECAY` / `SCORE_WEIGHTS` / `_tokens` / `_rank`） | `verify_generic.py` N3 六条；变异 M45 |
| 编年史检索打分 | `rules/context.py:168-190`（`rank_events`）+ `mcp_server.py:1371-1398`（`recall`） | `verify_generic.py` N3 三条；变异 M50 |
| mem0 式冲突消解 | `rules/context.py:205-275`（`supersede` / `superseded_by` / `status="superseded"`） | `verify_generic.py` N3 五条；变异 M46 |
| GA 反思触发 | `rules/context.py:477-520`（`reflection_due` / `mark_reflected`）+ `mcp_server.py:1401-1415` | `verify_generic.py` N3 四条 |
| 事件序号 / 可重放归档 | `state_schema.py:604-616`；`panel.py:150-160` | `verify_world.py` W12 六条；变异 M49、M18 |
| ink once-only / max_fires | `rules/lorebook.py:147-165`；`settings_loader.py:277-350` | `verify_gameplay.py` G3 三条；变异 M47 |
| SillyTavern 组内评分 | `rules/lorebook.py:224-260,294-310`；`settings_loader.py` `use_group_scoring` | `verify_gameplay.py` G3 两条；变异 M48 |
| 前缀稳定排序 | `rules/context.py:145-165`（0.25 分桶 + id 稳定排序） | `verify_generic.py` N3「新增无关事实不改变排序」 |

验证结果（本机，2026-11-04，`bash scripts/pre_push_gate.sh` 全绿）：
`verify_generic 104/104`（含 MCP）、`verify_gameplay 65/65`、`verify_world 54/54`（含 MCP）、
`verify_panel 93/93`、`verify_formulas 122/122`、`verify_branches 192/192`、`verify_cli 21/21`、
`verify_settings 17/17`、`verify_near_death 7/7`、`verify_systems 161/161`、`verify_injection 23/23`、
`verify_mcp_stdio 64/64`、`verify_docs 27/27`、`smoke_ui 20/20`、
`verify_tests` 853 条断言 0 可疑；变异 50 个全部杀死（含新增 M45-M50）。
500 轮压力测试 0 违规；wheel 资源校验通过。

---

## 五、明确不抄的清单

| 不抄的 | 来自 | 理由 |
|---|---|---|
| 把世界状态放进提示词 | AI Dungeon / NovelAI / SillyTavern | 不可审计、不可 diff、不可回滚；我们已有状态文件 |
| 每 NPC 每回合一次 LLM | generative_agents / cultivation-world-simulator | 成本随 NPC 数线性增长；零 LLM 基线是产品差异点 |
| embedding 作为默认检索 | GA / mem0 / NovelAI | 破坏零依赖与可复现；改为可选适配器（D3） |
| 用 SQLite 替换 JSONL | cultivation-world-simulator | 当前数据量与单机场景不需要；会失去可 diff 与随快照迁移的便利 |
| wall-clock 定时任务 | Evennia | 破坏"同状态同输入 = 同结果"；世界只挂 `tick` |
| 第二套叙事脚本语言 | ink / Twine / Inform | 引入编译器与运行时；只借语义（once/visit/DAG/rulebook） |
| 向量召回决定覆盖哪条记忆 | mem0 | 需要 embedding 且不可复现；改为调用方显式 `subject` + `supersede` |

---

## 六、参考坐标

- SillyTavern World Info：`public/scripts/world-info.js`（`getScore` / `filterGroupsByScoring` /
  `convertNovelLorebook` / `convertCharacterBook`）；条目字段 `selectiveLogic`、`sticky`、
  `cooldown`、`delay`、`scanDepth`、`groupWeight`、`groupOverride`。
- AI Dungeon：`story/story_manager.py`（`Story.memory = 20`、`latest_result()`）。
- 生成式智能体：`persona/memory_structures/associative_memory.py`（`ConceptNode`）、
  `cognitive_modules/retrieve.py`（三分量）、`reflect.py`（反思）、`perceive.py:178`（累积器）。
- 修仙世界模拟器：`src/classes/event_storage.py`（事件表/观察表/游标/清理）、
  `event_query.py`（EventAudience / EventMemoryScope）、`src/classes/ai.py`（动作名+参数对）。
- Open Dungeon：`src/lib/db.ts`（`story_summary` 水位）、`src/lib/story-prompt.ts`（分块驱逐）。
- Ink：`Documentation/WritingWithInk.md` §3/§6/§7；`ink-engine-runtime/StoryState.cs`
  （`storySeed` / `previousRandom` / `currentTurnIndex`）。
- Evennia：`evennia/typeclasses/models.py`（`db_typeclass_path`）、
  `evennia/typeclasses/attributes.py`（`db_key` / `db_category` / `db_value`）。
- mem0：`mem0/memory/main.py`（`_add_to_vector_store`、hash 去重、`history`）。
- ZorkGPT：README「State Manager」「Map System」（状态哈希、边置信度、失败出口剪枝）。
- OASIS：README「Integrated Recommendation Systems」（interest-based / hot-score）。


---

## 落地台账（v1.9.0）

v1.9.0 补齐上一轮剩下的四条 `[建议]`，至此本文档不再有"建议"项：

| 机制 | 落点 | 验收 |
|---|---|---|
| C1 ink 访问计数 | `rules/questline.py` `visits` / `turns_since` 谓词，从 `history` 派生 | `verify_mechanics.py` N10a–N10d |
| C4 提示词前缀指纹 | `rules/context.py` `_prefix_hash` → `pack()["prompt_prefix_hash"]` | `verify_mechanics.py` N11a–N11d |
| E2 OASIS 谣言热度 | `rules/world_evolution.py` `rumor_heat()`；`mentions` / `last_mention` 随重复触发推进 | `verify_mechanics.py` N12a–N12c |
| E1 CWS 势力意向 | `rules/world_evolution.py` `_faction_intents()`：确定性 argmax 选招募/经商/结盟/兴兵 | `verify_mechanics.py` N13a–N13d |

## 落地台账（v1.8.0）

| 机制 | 落点 | 验收 |
|---|---|---|
| A6 事件观察者模型 | `rules/context.py` `remember(witnesses=, public=)` / `knows` / `tell` / `known_to`；工具 `context_known` `context_tell` | `verify_mechanics.py` N5–N7 |
| B3 状态哈希与循环检测 | `rules/loopguard.py`：16 位状态签名、20 窗环形缓冲、3 次重复告警、死路剪枝 | `verify_mechanics.py` N3–N4 |
| B4 规则优先级 rulebook | `rules/rulebook.py`：`order` 降序 + `stop` 截断；谓词复用 `questline.evaluate`，效果复用 `systems.EFFECT_OPS`；设定包 `rules` 字段声明 | `verify_mechanics.py` N1–N2 |
| C2 事业线图 | `panel.py` `_build_quest_graph` → 面板 `#questmap` 分层 DAG（x = 跳数，y = 层内分布） | `verify_mechanics.py` N9 |
| C3 三阶段结算（check 阶段） | `rules/combat.py` `preview()`：只读推演命中率/期望伤害/是否致命，不消耗随机 | `verify_mechanics.py` N8 |
| D2 动作日志 | `action_log.py`：`<state>.actions.jsonl`，canonical JSON + sha256，不含明文参数；`seq` 在事务内递增落盘 | `verify_replay.py` R1–R9 |

**为什么 C3 只做了 check 阶段**：`resolve_combat` 已有 12 条不变量依赖（死目标守卫、死攻击方守卫、
自攻击守卫、逃跑独立判定、技能 inf/nan 兜底……）。把判定/扣血/事件拆成三个函数需要重写这个
函数体，回归面远大于收益。只补一个**只读 preview** 就拿到了玩家最需要的价值（打之前知道风险），
且零风险——它不写状态、不消耗随机，N8b/N8c 断言了这两点。
