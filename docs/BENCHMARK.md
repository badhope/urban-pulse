# 竞品对标调研（2026-10-24）

> 方法：所有竞品数据取自公开仓库/官网/文档，采集日期 2026-10-24。
> 每条差距都归入四类之一：**关闭**（本项目已做到）/ **跨越**（本项目做法不同且更优）/
> **承认**（确实弱于对方，写进路线图）/ **忽略**（明确不做，附理由）。
> 无法核实的项标 `[未确认]` 并写明缺什么证据。

---

## 1. 对标对象

| 对象 | 定位 | 规模（公开数据） | 为什么选它 |
|---|---|---|---|
| **AI Dungeon**（Latitude） | 商业化 AI 文字冒险，品类代名词 | 闭源 SaaS | 同用户场景的标杆：输入任意行动 → 模型续写 |
| **NovelAI**（Anlatan） | AI 写作 / 角色扮演订阅服务，Lorebook 体系 | 闭源 SaaS | 世界观资产管理的成熟形态 |
| **SillyTavern** | 本地部署的 LLM 前端，社区生态最活跃 | 34,860 stars（GitHub API，2026-10-24） | 角色卡 / 世界书事实标准 |
| **修仙世界模拟器** `4thfever/cultivation-world-simulator` | AI Agent 工作流驱动的修仙世界模拟 | 2,121 stars，Python | 中文圈最接近"世界模拟"的开源项目 |
| **Open Dungeon** `newideas99/open-dungeon` | 全本地 AI 角色扮演（Ollama + 本地图像） | 237 stars，TypeScript，MIT | "全本地"路线的最直接同侪 |
| **Generative Agents** `joonspk-research/generative_agents` | 斯坦福生成式智能体研究实现 | 22,281 stars，Apache-2.0 | 学术界的 NPC 自主行为基线 |
| **ACE OS** `AgnosticArchitect/ace-os-v8` | 提示词层的"确定性因果引擎" | 22 stars，MIT | 同样主张"确定性"，但实现路径是纯提示词 |

补充参考：`atisharma/chasm`（角色状态管理，15 stars）、`bcorfman/freytag-forge`（事实锚定的互动小说，12 stars）。

---

## 2. 逐维度对比

### 2.1 数值由谁决定

| 项目 | 做法 | 可复现性 |
|---|---|---|
| AI Dungeon / NovelAI | LLM 生成文本，数值只存在于文本里 | 不可复现（同输入不同输出） |
| SillyTavern | LLM + 前端脚本（部分社区扩展做骰子） | 依赖扩展，核心不保证 |
| ACE OS v8 | 用提示词强制 LLM 按顺序逻辑推理 | `[未确认]`：README 主张 deterministic，但无种子/回放机制说明 |
| 修仙世界模拟器 | Agent 工作流 + LLM 生成事件 | `[未确认]`：README 未见确定性回放说明 |
| **本项目** | 191 个规则函数 + `rng_seed`/`rng_counter` 落盘 | **同状态 + 同行动 = 同结果**，CLI/MCP 双通道验证；变异测试锁定 |

**判定：跨越。** 差异不是"更好一点"，而是把"世界状态"从文本里拿出来变成可 diff 的数据结构。

### 2.2 世界会不会自己动

| 项目 | 不行动时世界如何 |
|---|---|
| AI Dungeon | 静止（等玩家输入） |
| NovelAI | 静止 |
| SillyTavern | 静止 |
| Generative Agents | **会动**：NPC 有日程、记忆流、反思；但每个 tick 需要大量 LLM 调用，成本高 |
| 修仙世界模拟器 | **会动**：Agent 驱动的世界事件 |
| **本项目** | **会动且零 LLM 成本**：`tick` 用 logistic / Lotka-Volterra / SIR / Deffuant / 热力学松弛 / Panarchy 状态机推进 |

**判定：跨越（成本维度）+ 承认（行为丰富度）。**
Generative Agents 的 NPC 会制定计划、社交、反思，行为层次远比我方的"势力存量 + 传闻热度"细。
本项目的取舍是：**不花 LLM token 也能让世界变化**，把 LLM 留给叙事。

### 2.3 世界观可换性

| 项目 | 换世界的代价 |
|---|---|
| AI Dungeon | 换 Scenario（提示词 + 少量状态） |
| NovelAI | 换 Lorebook + 提示词 |
| SillyTavern | 换角色卡 + 世界书 |
| **本项目** | 换一个 `settings/*.setting.json`：术语表、等级阶梯、货币名、地点描写、世界书、品牌名、皮肤 |

**判定：关闭差距 + 局部跨越。** 差异在于**界面术语也随世界变**：
`terms.level = "身手"` 后面板不会再出现"境界"。这一点在四套设定包上由
`verify_settings.py` 逐条断言。SillyTavern 的界面是通用英文 UI，不随世界改变。

### 2.4 长局记忆

| 项目 | 机制 | 主要限制 |
|---|---|---|
| AI Dungeon | 上下文窗口 + Memory（用户手动记） | 旧事逐条丢失 |
| NovelAI | 上下文 + Lorebook 常驻条目 | 依赖 token 预算，历史不进检索 |
| SillyTavern | 上下文 + World Info + 摘要扩展 | 无内建归档检索 |
| Generative Agents | 记忆流 + 检索（recency/importance/relevance） | 需要向量/嵌入，成本高 |
| **本项目** | 摘要（每 20–50 回合）+ 大事记 + 逐条归档（`<state>.log*.jsonl`）+ `recall` 关键词回捞 + `recap` 字符预算 | 关键词检索，非向量语义检索 |

**判定：关闭（工程层面）+ 承认（检索质量）。**
向量检索确实能召回"语义相关但用词不同"的旧事，本项目做不到。这是路线图里的 P2。

### 2.5 生态兼容

| 项目 | 角色卡 | 世界书 |
|---|---|---|
| SillyTavern | V1/V2/V3，PNG 内嵌 + JSON | world-info，selective/constant/disable |
| AI Dungeon | 自有格式 | 无 |
| NovelAI | 自有 Lorebook | 有 |
| **本项目** | **直接读** V1/V2/V3（PNG tEXt `chara`/`ccv3` + JSON） | **直接读** world-info 与卡内 `character_book`，含 selective/constant/disable 语义 |

**判定：关闭差距。** 这是"不重复造轮子"的具体落点：社区已有的角色资产可以直接用。
`verify_mcp_stdio.py` 里有真实 PNG 嵌卡的端到端断言。

### 2.6 界面

| 项目 | 形态 |
|---|---|
| AI Dungeon / NovelAI | 聊天流 + 侧栏 |
| SillyTavern | 聊天流 + 可定制主题 |
| **本项目** | **只读实况主舞台**：叙事卡 + HUD + 三张长局曲线 + 关系网 + 地点图 + 世界脉搏 + 图鉴/市场/大事记抽屉 + 命令面板 |

**判定：跨越（信息密度与可核对性）+ 承认（交互丰富度）。**
对方是聊天为主的编辑器，本项目是"看世界"的仪表盘。你要改剧情仍然回对话里说。

### 2.7 AI 应用安全

| 项目 | 外部内容处理 |
|---|---|
| SillyTavern | 有扩展做提示词注入防护，核心无统一策略 |
| AI Dungeon / NovelAI | 闭源，官方称有过滤 `[未确认]` |
| **本项目** | 角色卡/世界书统一打 `untrusted` 标记 + 9 类注入特征扫描 + `content_policy` 说明；**标记而不删除**（保叙事） |

**判定：跨越（可审计性）。** 我们不声称"防住了"，而是把"这段是数据不是指令"显式写进工具返回，
宿主据此决策。`verify_injection.py` 23 条断言锁定这个行为，其中 2 条由变异测试反证。

### 2.8 部署与依赖

| 项目 | 运行时依赖 |
|---|---|
| SillyTavern | Node.js + 一堆 npm 包 |
| Open Dungeon | Next.js + Ollama（模型数 GB） |
| 修仙世界模拟器 | Python + LLM API |
| **本项目** | **纯 Python 标准库**；MCP 可选；图表库 1MB 静态资产；无模型 |

**判定：跨越。** `pip install` 后立刻可跑，不需要 GPU、不需要 API Key、不需要联网。

---

## 3. 差距清单（含处置）

| # | 差距 | 对方做法 | 处置 | 理由 / 后续 |
|---|---|---|---|---|
| G1 | 向量语义检索 | Generative Agents 记忆流 + embedding | **承认** | 需要嵌入模型与向量库，违背"零依赖"；P2 路线图列为可选 extra |
| G2 | NPC 行为丰富度 | Generative Agents 的日程/反思/对话树 | **承认** | 当前只有 roaming + 势力归属；P2 |
| G3 | 图像生成 | Open Dungeon 本地 FLUX | **忽略** | 需要数 GB 模型与 GPU，与"零依赖内核"定位冲突 |
| G4 | 多人联机 / 分享 | AI Dungeon 的分享链接 | **忽略** | 单机本地工具；面板的"分享模式"只解决截图/直播需求 |
| G5 | 提示词工程生态 | SillyTavern 的 preset/扩展市场 | **忽略** | 本项目不托管提示词；提示词属于宿主 Agent |
| G6 | 移动端 App | AI Dungeon 有原生 App | **忽略** | 面板 320px 已可用；原生 App 投入产出比低 |
| G7 | 语音朗读 | NovelAI 无，第三方有 | **忽略** | 与规则内核无关 |
| G8 | 世界书 GUI 编辑器 | NovelAI / SillyTavern 都有 | **承认** | 越过 ADR-002「面板严格只读」红线；如要做需先改架构决策 |
| G9 | 结构化日志 / 可观测性 | 成熟服务标配 | **忽略** | 本地单机工具，stdout JSON 已是审计线索 |
| G10 | 语义化版本发布流程 | 各家都有 | **关闭** | 本项目有 CHANGELOG + 单一版本信源（`__init__.py` ↔ `pyproject.toml` 由测试断言） |

---

## 4. 本项目的独特组合（没有单一竞品同时具备）

1. **确定性规则内核** + **MCP 标准协议**：任何 Agent 可接入，不是某个前端的功能。
2. **零依赖** + **离线可用** + **可复现**：三个性质互相支撑，缺一个就不成立。
3. **世界自演化** 与 **玩家叙事** 解耦：世界不需要 LLM 也会变，LLM 只负责把变化讲成故事。
4. **设定包驱动到界面术语**：换世界不改一行代码，连"境界"两个字都不会漏。
5. **测试可被变异杀死**：32 个已知错误注入源码，测试必须变红，否则门禁失败。

---

## 5. 调研方法与可复现性

```bash
# 竞品数据（GitHub API，公开）
curl -s "https://api.github.com/repos/SillyTavern/SillyTavern" | jq '{stars:.stargazers_count,license:.license.spdx_id}'
curl -s "https://api.github.com/repos/4thfever/cultivation-world-simulator" | jq '.stargazers_count'
curl -s "https://api.github.com/repos/newideas99/open-dungeon" | jq '.stargazers_count'
curl -s "https://api.github.com/repos/joonspk-research/generative_agents" | jq '.stargazers_count'
```

**未核实的声明**（不写进结论）：
- AI Dungeon / NovelAI 的内部记忆与安全实现（闭源，只能引用官方文档措辞）；
- ACE OS v8 与修仙世界模拟器的"确定性"是否为工程保证（无公开回放/种子机制说明）。

这两类在正文里都标了 `[未确认]`，没有当作已证实事实使用。
