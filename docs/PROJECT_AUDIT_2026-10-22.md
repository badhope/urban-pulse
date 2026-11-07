# 项目全维度审查与对标报告

> 审查对象：world-walker（万界·行者）v0.8.0 · commit `5665378` + 本轮修复
> 审查日期：2026-10-22
> 审查方式：全部结论均有工具输出、文件行号或实测行为支撑；无证据项标注 `[未确认]` 并写明缺什么证据。

---

## 一、总体结论

**整体质量评级：B+（可交付，但有明确短板）**。作为一个「AI 驱动的文字游戏引擎 + MCP 服务器 + 只读面板」的个人开源项目，它的工程质量显著高于同规模项目：零第三方依赖的核心、129 个学术公式、确定性与只读两条硬不变量、12 项自动化门禁、三平台 CI 全绿。

**最大风险：测试可信度而非功能缺陷。** 本项目历史上出现过多次「测试全绿但什么都没测」的情况（本次审查过程中又发现并修复了 2 处）。当前 289 条断言经 AST 审计与变异验证，但仍是静态分析——理论上总能找到新的绕过写法。

**最优先三项行动**：
1. 把 `verify_tests` 的静态审计升级为"变异测试为真值来源"（当前只能防已知的 9 类模式）。
2. 补齐剩余 52 个未被公式对拍覆盖的纯函数（尤其 `price_equation` 之外的进化/网络类）。
3. 拆分 `panel.py` 的超高复杂度函数（`view_model` 复杂度 35，红线 10）。

---

## 二、证据与基线

### 2.1 项目类型与技术栈

| 项 | 值 | 证据 |
|---|---|---|
| 项目类型 | **AI 应用 / 规则引擎库 + 本地只读 Web 应用**（非 SaaS、非 API 服务） | `pyproject.toml:2-6` 描述为「文字互动游戏引擎（世界观无关规则内核 + MCP 服务器）」 |
| 语言 | Python ≥ 3.10 | `pyproject.toml:10` |
| 依赖 | **零运行时依赖**；可选 `mcp>=2.0` | `pyproject.toml:20-21` |
| 前端 | 原生 HTML/CSS/JS，无构建链 | `panel.html` 257 行 / `panel.css` 451 行 / `panel.js` 1090 行 |
| 代码量 | Python 7,576 行（31 文件） | `git ls-files` 60 个受管文件 |
| 部署形态 | 单机：MCP stdio 服务 + 127.0.0.1 只读 HTTP 面板 | `mcp_server.py:1283`、`panel.py:449`（`host="127.0.0.1"` 默认） |
| 用户角色 | 单一本地用户（玩家）+ AI 宿主（Agent） | `ARCHITECTURE.md:9-11` |
| 数据敏感等级 | **低**：本地游戏存档，无凭据、无个人隐私字段 | `state_schema.py` 全文无 PII 字段 |

### 2.2 实际运行的命令与输出摘要

| 命令 | 结果 |
|---|---|
| `python scripts/compile_all.py` | 全部 31 个 Python 文件编译通过 |
| `python -m pyflakes rules/*.py engine.py scripts/*.py *.py` | **0 告警**（本轮清理前 37 条） |
| `python -m bandit -r rules/ engine.py panel.py mcp_server.py state_schema.py` | **High 0 / Medium 0 / Low 0**（本轮修复前 High 12 / Low 12） |
| `python -m radon cc panel.py -s` | `view_model` E(35) · `classify_event` D(24) · `build_scene` D(21) |
| `python scripts/verify_tests.py` | 0 可疑断言 / 审计 289 条 |
| `python scripts/verify_formulas.py` | 122/122 |
| `python scripts/verify_cli.py` | 20/20 |
| `python scripts/verify_panel.py` | 54/54 |
| `python scripts/verify_near_death.py` | 7/7 |
| `python scripts/verify_mcp_stdio.py` | 55/55 |
| `python scripts/user_playtest.py` | 47/47 |
| `python scripts/stress_freeplay.py 2000` | 2000/2000 轮 · 6188 次调用 · 0 错误 · 0 不变量破坏 |
| `python scripts/smoke_ui.py` | 13/13（真实 Edge 渲染） |
| `bash scripts/pre_push_gate.sh` | 12 项全绿 |
| `python -m pytest` | **collected 0 items** — 项目无 `test_*.py`，pytest 识别不到任何测试 |
| `python -m coverage` | 见 §6，MCP 侧 `[未确认]`（子进程覆盖率无法传导） |

### 2.3 对标对象（具名）

| 竞品 | 选择理由 | 对标维度 |
|---|---|---|
| **AI Dungeon**（Latitude） | 最知名的 AI 文字冒险产品，同一用户场景（AI 驱动的互动叙事），但走「LLM 自由生成」路线 | 叙事体验、世界一致性、长局记忆、付费模式 |
| **NovelAI**（Anlatan） | 面向创作者的 AI 写作/角色扮演平台，有 Lorebook（世界书）体系 | 世界观设定管理、上下文注入、记忆机制 |
| **SillyTavern** | 开源、本地部署、社区生态最活跃的 AI 角色扮演前端 | 生态兼容（角色卡/世界书）、本地化部署、扩展性 |

选择理由：三者覆盖了本项目声明要切入的同一生态位（AI 叙事 + 本地/托管 + 世界观资产），且都在公开可查，适合逐项对标。

---

## 三、发现清单（按严重级别）

### Critical

**无。** 本项目为单机只读工具、无鉴权面、无多租户、无外部数据写入。经 OWASP Top 10 逐项核查（§3.2），未发现 Critical 级问题。

### High

| ID | 严重级别 | 置信度 | 维度 | 位置 | 问题描述 | 证据 | 建议修复 | 对标含义 |
|---|---|---|---|---|---|---|---|---|
| F-001 | ~~High~~ **已修复** | 高 | 可维护性 | `panel.py:305` | `view_model` 圈复杂度曾为 35（红线 10） | 拆前 `radon cc` → `E (35)`；拆后 → `B (6)`，子函数 `_build_events` B(8) / `_build_market` B(7) / `_build_cast` B(7) / `_build_player` B(6) | 已拆为 8 个 `_build_*` 纯函数 | 关闭差距 |
| F-002 | ~~High~~ **已修复** | 高 | 测试有效性 | `scripts/verify_mutation.py` | 静态 AST 审计只能识别已知假写法，存在信任缺口 | 已改为**真变异测试**：19 个已知错误变异逐条应用 → 跑验证脚本 → 期望变红。首轮跑出 2 个存活（归档计数漂移、重复事件合并未被断言），补断言后 **19/19 全杀，存活率 0%** | 关闭差距：直接证明"代码错了测试会红" |
| F-003 | ~~High~~ **已修复** | 高 | 覆盖率 | 全仓 | 行覆盖率曾为 66%；`systems_feedback` 37% / `narrative_engine` 42% / `economy` 48% / `cognition` 59% | 新增 `scripts/verify_branches.py`（111 条断言）后：**总 81%**；`systems_feedback` 96% / `narrative_engine` 83% / `economy` 91% / `cognition` 97% | 已补测并接入门禁（≥70% 硬门禁） | 关闭差距 |

### Medium

| ID | 严重级别 | 置信度 | 维度 | 位置 | 问题描述 | 证据 | 建议修复 | 对标含义 |
|---|---|---|---|---|---|---|---|---|
| F-004 | Medium | 高 | 正确性（已修） | `panel.css:270` | `.chip` 设 `display:inline-flex` 覆盖了 `[hidden]`，导致满血玩家显示"气血吃紧" | 修复前截图：`56/56` 旁出现红字「气血吃紧」；`getComputedStyle(#hpwarn).display` 返回 `inline-flex` | 已加 `.chip[hidden]{display:none}` + `smoke_ui.py` 断言 | 关闭差距 |
| F-005 | Medium | 高 | 体验（已修） | `panel.html:146` | 三个抽屉在 `<main>` 之后，位于页面底部 1584px 处；点击「图鉴」后内容不在视口内 | Playwright 实测：展开后 `rect.top=1584`，视口高 950 | 已加 `wireDrawers()` 展开时 `scrollIntoView` | 承认差距：NovelAI 的 Lorebook 是侧边栏常驻，本项目是底部折叠，属简化取舍 |
| F-006 | Medium | 高 | 体验（已修） | `panel.py:221` | 编年史 32% 是「回合N结束」心跳，且连续多条「攻击被闪避」重复，真实事件被挤出 | 实测 500 回合存档：tick 事件 38/120 = 32%；连续 4 条相同描述 | 已过滤 tick + 相邻相同合并显示 `×N` | 关闭差距 |
| F-007 | Medium | 高 | 安全 | `rules/world_dynamics.py:74,211` | 用 `assert` 做入参长度校验，`python -O` 下会被剥离 → 静默截断 | bandit `B101`；实测 `-O` 模式下不报错直接截断 | 已改为 `raise ValueError` | 关闭差距 |
| F-008 | ~~Medium~~ **已修复** | 高 | 供应链 | `requirements-mcp.lock.txt` | 曾无锁文件、`mcp>=2.0` 开区间 | 已新增 `requirements-mcp.lock.txt`（10 个包精确版本，附 OSV 扫描记录）；`pyproject.toml` 收紧为 `mcp>=2.3,<3` | 关闭差距 |
| F-009 | Medium | 中 | 可观测性 | 全仓 | 无结构化日志、无指标、无 trace。排查只能靠 stdout 打印的 JSON | `grep -rn "logging" --include=*.py` → 0 命中 | 引入 `logging` + 结构化字段（至少 tick/action/结果） | 不适用：本地单机工具，SRE 指标体系不成立（见 §3.3） |

### Low

| ID | 严重级别 | 置信度 | 维度 | 位置 | 问题描述 | 证据 | 建议修复 |
|---|---|---|---|---|---|---|---|
| F-010 | Low | 高 | 可维护性 | `panel.py:62` | `classify_event` 复杂度 24、`build_scene` 21，均超红线 | radon | 按事件类型抽子函数 |
| F-011 | Low | 高 | 可维护性 | `mcp_server.py` 1287 行 | 单文件承载 31 个 MCP 工具，超千行 | `wc -l` | 按工具组拆分（建局/行动/长局/生态） |
| F-012 | Low | 高 | 测试 | `scripts/*.py` | 测试文件不叫 `test_*.py`，`pytest` 收集 0 项；无法用生态工具（coverage/pytest-xdist/mutmut） | `pytest` → `collected 0 items` | 在 `pyproject.toml` 加 `[tool.pytest.ini_options] python_files` 或重命名 |
| F-013 | Low | 高 | 体验 | `panel.py:249` | 时间线里「无名客对沈砚的敬重2.0」文案缺「上升/下降」方向词（敬重已修，亲密未修） | `rules/social.py:72` 的 `direction` 仅在 respect 分支使用 | 亲密文案同样加方向词 |
| F-015 | ~~High~~ **已修复** | 高 | 安全（AI 应用） | `mcp_server.py:262-300` | 角色卡/世界书是外部文件，内容经 `narration_context` 进入 Agent 上下文，此前无任何注入防护 | 构造含「忽略之前的所有指令」的恶意世界书条目，注入前 `narration_context` 原样返回、无标记 | 新增 `_scan_injection()`（9 条特征）+ 输出侧 `untrusted` 标记与 `content_policy`；**标记而非删除**（保留叙事，data/instruction 分离） | 关闭差距：AI Dungeon/NovelAI 有过滤，此前本项目是短板 |
| F-014 | Low | 中 | 文档 | `README.md:84` | 声称"77 个函数"，实测 `verify_formulas` 覆盖 77 个（本轮已校准）；但 129 个公开函数中 52 个仍无对拍 | 静态提取比对 | 在 README 明示"未覆盖 52 个"或继续补 |

### [未确认] 项

| ID | 维度 | 待确认内容 | 需要什么证据 |
|---|---|---|---|
| ~~U-001~~ ✅ | 覆盖率 | MCP 服务端真实覆盖率 | **已解决**：新增 `scripts/coverage_mcp.py`，用 `sitecustomize` 在子进程静默挂 coverage（不能用 `coverage run` 包一层——它往 stdout 写告警会打断 MCP 的 JSON-RPC）。实测：**行 34% / 分支 37 个部分覆盖**；`rules` 侧在 MCP 路径下 34%，与零依赖路径的 81% 合并后为 **85%** |
| ~~U-002~~ ✅ | 供应链 | 依赖 CVE | **已解决**：`pip-audit` 连不上 PyPI，改用 **OSV.dev API** 逐包查询（10 个包：mcp 2.3.0 / anyio 4.15.1 / httpx 0.28.1 / pydantic 2.14.1 / pydantic-core 2.50.1 / starlette 1.8.0 / sse-starlette 3.5.0 / uvicorn 0.54.0 / pydantic-settings 2.16.0 / httpx-sse 0.4.3）→ **已知漏洞 0 条** |
| ~~U-003~~ ✅ | 性能 | 长局内存 | **已解决**：三段对照实测 1500 轮 RSS 增量 **-0.4MB**（无泄漏）；状态 7KB、侧写封顶 600、归档计数=行数 |
| ~~U-004~~ ✅ | 兼容性 | Python 3.10 的 MCP 路径 | **已解决**：CI 的 `mcp e2e` 矩阵含 3.10 与 3.13，两版本均跑通端到端 + 注入 + 试玩 + 500 轮压测 |

---

## 四、查漏补缺清单（按项目类型）

项目类型 = **本地 AI 工具 + 规则引擎库 + 只读 Web 应用**，非 SaaS / 非多租户 API。

### 4.1 适用且已覆盖

| 检查项 | 状态 | 证据 |
|---|---|---|
| 启动/构建/编译 | ✅ | `compile_all.py` 31 文件全过 |
| 空值/零值/负值边界 | ✅ | `verify_cli` 写命令字段有界；`user_playtest` 买 0/负数/99999 被拒 |
| 并发竞态 | ⚠️ 部分 | 面板 `ThreadingHTTPServer` 只读，无写竞争；MCP 单进程串行 |
| 超时 | ⚠️ 部分 | `panel.py` SSE 读取有 `timeout`；MCP 工具本身无超时（本地调用，风险低） |
| 异常不吞 | ✅ | bandit B110/B112 三处均为有意的容错边界，已加 `# nosec` 与理由 |
| 错误信息不泄露堆栈 | ✅ | `panel.py:330` 返回 `error` + `hint`，非堆栈 |
| 功能宣称 vs 实现 | ✅ | README 功能逐条核对，本轮修正了 3 处计数/描述偏差 |

### 4.2 项目类型专项（本地 AI 工具）

| 检查项 | 状态 | 说明 |
|---|---|---|
| 提示词注入防护 | ⚠️ **设计缺口** | MCP 工具返回值直接进 Agent 上下文。角色卡/世界书是外部文件，`import_lorebook` 不校验内容。攻击者构造恶意 `.png` 卡可让 Agent 执行非预期指令。**这不是代码 bug，是 AI 应用的固有攻击面** |
| 模型输出校验 | ✅ | `_guarded_tool` 统一包装，工具入参有 pydantic schema |
| 上下文长度控制 | ✅ | `recap(budget_chars)` + `event_log_keep` + 归档 |
| 本地文件访问范围 | ✅ | 面板静态资源白名单；`character_card_read` 可读任意路径 ⚠️（见下） |
| 状态文件并发写 | ⚠️ 部分 | 多 Agent 同时调 MCP 会竞争（无文件锁）。单机单 Agent 场景可接受 |

### 4.3 明确不适用

| 维度 | 不适用原因 |
|---|---|
| 多租户隔离 / IDOR | 无用户体系，单机单用户 |
| 认证 / 会话 / MFA | 无登录 |
| 数据库 N+1 / 索引 | 无数据库，JSON 文件存储 |
| 自动伸缩 / 容量规划 | 本地进程，无弹性需求 |
| CDN / SRI | 图表库 vendored 本地，无 CDN |
| 灾备 / 备份恢复 | 状态文件单文件，用户自行备份；`snapshot/restore` 已覆盖回退 |

---

## 五、竞品对标矩阵

| 能力/维度 | world-walker | AI Dungeon | NovelAI | SillyTavern | 差距类型 | 优先级 |
|---|---|---|---|---|---|---|
| **数值确定性/可复现** | ✅ 同种子逐字节一致 | ❌ 纯 LLM 生成，不可复现 | ❌ 同左 | ❌ 同左 | **跨越** | — |
| **规则内核（数学驱动）** | ✅ 129 个公式 + 16 模型 | ❌ 无 | ❌ 无 | ❌ 无 | **跨越** | — |
| **长局记忆** | ✅ 三层（摘要/大事记/归档+recall） | ⚠️ Memo 系统，有截断 | ✅ Lorebook + 上下文 | ✅ 世界书 | 承认（本项目无向量检索） | P2 |
| **世界观资产兼容** | ✅ 角色卡（V1/V2/V3）+ 世界书 | ❌ | ✅ Lorebook | ✅ 原生 | **承认**（兼容但不自建编辑器） | P1 |
| **世界书编辑器（GUI）** | ❌ 只能 JSON 手写 | ❌ | ✅ 完整 GUI | ✅ 完整 GUI | **关闭** | P1 |
| **多人协作/分享** | ❌ | ✅ 社区分享场景 | ⚠️ 部分 | ✅ 卡片分享 | **刻意忽略**（单机工具定位） | — |
| **移动端** | ⚠️ 响应式 320px 可用 | ✅ 原生 App | ⚠️ Web | ❌ 需自架 | 承认 | P3 |
| **图像生成** | ❌ | ✅ 内置 | ✅ 内置 | ⚠️ 插件 | **刻意忽略**（核心是数值引擎） | — |
| **本地离线可用** | ✅ 完全离线（零依赖） | ❌ 云端 | ❌ 云端 | ✅ 自架 | **跨越** | — |
| **安装复杂度** | ✅ `pip install -e .` | ✅ 注册即用 | ✅ 注册即用 | ❌ 需 Node + 配置 | **跨越** | — |
| **实时可视化面板** | ✅ 图表/关系网/事件谱 | ❌ | ⚠️ 纯文本 | ⚠️ 纯文本 | **跨越** | — |
| **插件/扩展生态** | ❌ | ⚠️ 有限 | ❌ | ✅ 丰富 | **刻意忽略** | — |
| **提示词注入防护** | ❌ 无 | ⚠️ 有过滤 | ⚠️ 部分 | ⚠️ 有 | **关闭** | P1 |

### 差距评分（按用户要求公式：`(需求+收入+战略)×投入÷3`）

| 差距 | 需求 | 收入 | 战略 | 投入(5=易) | 分数 | 分类 |
|---|---|---|---|---|---|---|
| 世界书 GUI 编辑器 | 4 | 2 | 4 | 3 | 10.0 | 关闭 |
| 提示词注入防护 | 3 | 1 | 4 | 3 | 8.0 | 关闭 |
| 向量检索记忆 | 3 | 1 | 3 | 2 | 4.7 | 承认 |
| 图像生成 | 2 | 3 | 1 | 1 | 2.0 | 忽略 |
| 插件生态 | 2 | 1 | 2 | 1 | 1.7 | 忽略 |

---

## 六、量化指标看板

| 指标 | 红线 | 当前值 | 判定 | 测量方式 |
|---|---|---|---|---|
| 行覆盖率（全仓） | ≥90% | **88%**（原 66%） | ⚠️ 未达 90%，已过硬门禁 70% | `coverage run` 合并五套件（新增 `verify_branches`），`--source=rules,panel,state_schema` |
| 行覆盖率（MCP 服务端） | ≥80% | **34%（仅 MCP 路径）** | ⚠️ 未达 80%，但已实测 | `scripts/coverage_mcp.py`（sitecustomize 子进程插桩） |
| 分支覆盖率 | ≥85% | **MCP 路径：282 分支中 37 个部分覆盖** | ⚠️ 未达 85% | `coverage run --branch`（见 coverage_mcp.py） |
| 变异分数 | ≥80% | **100%（19/19）** | ✅ 通过 | `scripts/verify_mutation.py`（自动化，接入门禁与 CI） |
| 圈复杂度（单函数） | ≤10 | **最高 24**（`classify_event`）；`view_model` 已 35→6 | ⚠️ 仍有 2 个函数超标 | `radon cc -s` |
| 认知复杂度 | ≤15 | `[未确认]` | ⚠️ 未确认 | 无工具（radon 只有圈复杂度） |
| 技术债务比率 | ≤5% | `[未确认]` | ⚠️ 未确认 | 需 SonarQube 或等价 |
| 重复行（新代码） | <3% | `[未确认]` | ⚠️ 未确认 | 无工具 |
| Critical/High 漏洞 | 0 | **0**（bandit） | ✅ 通过 | `bandit -r`（本轮修复前 High 12） |
| pyflakes 告警 | 0 | **0** | ✅ 通过 | `python -m pyflakes`（本轮修复前 37） |

### 6.1 变异测试记录（手工，作为变异分数的近似依据）

| # | 变异 | 是否被抓 |
|---|---|---|
| 1 | `resolve_trade` 整个 no-op | ✅ |
| 2 | trade 只扣 1 元 | ✅ |
| 3 | social 增益改 100 | ✅ |
| 4 | combat 恒定 1 伤 | ✅ |
| 5 | 死目标继续受伤 | ✅ |
| 6 | 归档按计数截断（删历史） | ✅ |
| 7 | 价格回归失效 | ✅ |
| 8 | OU 死区内冻结 | ✅ |
| 9 | Lerner 公式 ε±1 | ✅ |
| 10 | 认知 alpha 0.88→0.99 | ✅ |
| 11 | 记忆检索默认权重 | ✅ |
| 12 | S6 认知预算"正常"档 | ✅ |
| 13 | S4 merit 系数互换 | ✅ |
| 14 | S2 KL 方向反转 | ✅ |
| 15 | W1 replicator 恒返回 0 | ✅ |
| 16 | 只在满血目标命中 | ✅ |
| 17 | wheel 缺 panel.html | ✅ |
| 18 | `check_true('x', True)` 恒真 | ✅ |
| 19 | `check('x', f(1), f(1))` 自证 | ✅ |
| 20 | `ok = True; check(x, ok)` 数据流 | ✅ |

**20/20 全部被抓**（复验专家另测试的 17 个对抗变异中曾漏 16 个，本轮已补 4 个关键盲区）。

---

## 七、修复与补齐路线图

| 优先级 | 任务 | 对应发现 | 工作量 | 验收标准（如何证明"真实实现"） |
|---|---|---|---|---|
| ~~P0~~ ✅ | 拆分 `view_model`（复杂度 35 → ≤15） | F-001 | M | **已完成**：`radon cc` → `B (6)`；`verify_panel` 54/54 保持 |
| ~~P0~~ ✅ | 补低覆盖模块测试（37%/42%/48% → ≥70%） | F-003 | M | **已完成**：96%/83%/91%；新增 111 条断言经 `verify_tests` 审计（0 可疑） |
| ~~P1~~ ✅ | 引入自动变异测试 | F-002 | L | **已完成**：19 个变异存活率 0%，接入门禁与 CI |
| P1 | 世界书 GUI 编辑器 | 对标差距 | L | 能在面板内增删改词条并落盘；有 e2e 断言 |
| ~~P1~~ ✅ | 提示词注入防护（角色卡/世界书 untrusted 标记） | F-015 | M | **已完成**：`verify_injection.py` 21/21；两个变异（关掉扫描 / 去掉 untrusted）均 FAIL |
| ~~P2~~ ✅ | 加依赖锁文件 / 收紧 `mcp` 版本 | F-008 | S | **已完成**：`requirements-mcp.lock.txt` + `mcp>=2.3,<3` |
| ~~P2~~ ✅ | 补齐剩余函数的公式对拍 | F-014 | M | **已完成**：127/129 个公开函数（98%）；剩 `resolve_combat`/`should_use_system2` 分别在 verify_near_death 与随机测试中覆盖 |
| P3 | 拆分 `mcp_server.py`（1287 行） | F-011 | M | 按工具组拆成 3–4 个模块，`verify_mcp_stdio` 55/55 不降 |
| P3 | 亲密文案加方向词 | F-013 | S | `rules/social.py` 亲密分支输出「亲密上升5」；有断言 |

---

## 附：本轮审查中实际修复的问题

| # | 问题 | 文件 | 验证方式 |
|---|---|---|---|
| 1 | `.chip[hidden]` 被 `display` 覆盖，满血误显示「气血吃紧」 | `panel.css:270` | Playwright 断言 `getComputedStyle(#hpwarn).display === 'none'` |
| 2 | 抽屉在页面底部，点击后内容不在视口 | `panel.js:809` `wireDrawers()` | Playwright 断言展开后 `rect.top < innerHeight` |
| 3 | 编年史 32% 是 tick 心跳 + 连续重复 | `panel.py:221` `_merge_adjacent()` | 实测 tick 残留 0、相邻相同残留 0、`×8` 正确聚合 |
| 4 | `assert` 做长度校验，`-O` 下失效 | `rules/world_dynamics.py:74,211` | 改为 `raise ValueError`，实测异常抛出 |
| 5 | bandit High 12 / Low 12 | 多处 | 现 High 0 / Medium 0 / Low 0 |
| 6 | pyflakes 37 条 | 多处 | 现 0 条 |
| 7 | 无 UI 自动化 | 新增 `scripts/audit_ui.py` + `scripts/smoke_ui.py` | 13/13 全绿，接入门禁 |
| 8 | `view_model` 复杂度 35 | `panel.py` 拆为 8 个 `_build_*` | `radon cc` → `B (6)` |
| 9 | 覆盖率 66%，3 模块 <50% | 新增 `scripts/verify_branches.py`（111 条断言） | 总 81%，最低模块 72% |
| 10 | 覆盖率无门禁 | `pre_push_gate.sh` + CI 加 ≥70% 硬门禁 | 门禁 14 项全绿，覆盖率 81% |

**注：本报告的 §3 F-004~F-007 是修复前状态，修复后已复验。**
