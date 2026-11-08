# 项目全维度审查与对标报告（第二轮）

> 审查对象：world-walker（万界·行者）v0.8.0 · commit `30a2be3`
> 审查日期：2026-10-22
> 审查方式：所有结论均绑定实际命令输出、文件行号或实测行为。无证据项标注 `[未确认]` 并写明补证方式。

---

## 一、总体结论

**整体质量评级：A-（可交付，工程纪律显著高于同规模项目）**。零运行时依赖、9,353 行 Python、31 个 MCP 工具、85% 行覆盖 / 变异存活率 0%、bandit 与 pyflakes 双零。作为一个单人维护的 AI 叙事引擎，这个基线相当硬。

**最大风险不在代码质量，而在"单人 + 无运维文档"的可持续性**：没有部署/回滚文档、没有数据备份说明、没有结构化日志。项目本身是本地工具（SRE 指标体系不完全适用），但**存储安全（原子写）**是实打实的缺陷。

**最优先三项**：
1. **状态文件原子写入**（F-001）—— 当前写一半就损坏，且无备份。
2. **补齐安全响应头**（F-002）—— 面板缺 `X-Content-Type-Options` 等基础头。
3. **时间线不可交互**（F-003）—— 与竞品相比这是明显体验落差。

---

## 二、证据与基线

### 2.1 项目类型与技术栈

| 项 | 值 | 证据 |
|---|---|---|
| 项目类型 | **AI 应用 / 规则引擎库 + 本地只读 Web 应用** | `pyproject.toml:2-6` |
| 语言 | Python ≥ 3.10 | `pyproject.toml:10` |
| 运行时依赖 | **零**；可选 `mcp>=2.3,<3` | `pyproject.toml:21` |
| 前端 | 原生 HTML/CSS/JS，无构建链 | `panel.html` 257 / `panel.css` 452 / `panel.js` 1148 行 |
| 代码量 | 9,353 行 Python（73 个受管文件） | `git ls-files` + 行数统计 |
| 部署形态 | 单机：MCP stdio + 127.0.0.1 只读 HTTP | `panel.py:541`（`host="127.0.0.1"` 默认） |
| 用户角色 | 单一本地玩家 + AI 宿主 Agent | `ARCHITECTURE.md:9-11` |
| 数据敏感等级 | **低**：本地游戏存档，无 PII / 凭据 | `state_schema.py` 全字段核查 |

### 2.2 实际运行的命令与输出

| 命令 | 输出摘要 |
|---|---|
| `python scripts/compile_all.py` | 全部 36 个 Python 文件编译通过 |
| `python -m pyflakes rules/*.py engine.py scripts/*.py *.py` | **0 告警** |
| `python -m bandit -r rules/ engine.py panel.py mcp_server.py state_schema.py` | **High 0 / Medium 0 / Low 0** |
| `python -m radon cc ... -a` | 229 个代码块，**平均复杂度 A (3.98)** |
| `python -m coverage run --branch`（五套合并） | **行 85% / 分支 388 中 74 部分** |
| `python scripts/verify_mutation.py` | **18/18 变异全杀死，存活率 0%** |
| `python scripts/verify_formulas.py` | 122/122 |
| `python scripts/verify_branches.py` | 155/155 |
| `python scripts/verify_cli.py` | 20/20 |
| `python scripts/verify_panel.py` | 55/55 |
| `python scripts/verify_near_death.py` | 7/7 |
| `python scripts/verify_mcp_stdio.py` | 56/56 |
| `python scripts/user_playtest.py` | 47/47 |
| `python scripts/verify_injection.py` | 21/21 |
| `python scripts/verify_memory.py` | 7/7（1500 轮 RSS 增量 -0.4MB） |
| `python scripts/smoke_ui.py` | 13/13 |
| **UI 逐元素交互巡检**（本轮新增，21 项） | **19/21**（2 项见 F-003/F-004） |

### 2.3 对标对象（具名）

| 竞品 | 选择理由 | 对标维度 |
|---|---|---|
| **AI Dungeon**（Latitude） | AI 文字冒险的品类标杆，同用户场景 | 叙事、长局记忆、付费模式 |
| **NovelAI**（Anlatan） | 面向创作者的 AI 写作平台，有 Lorebook 体系 | 世界观管理、上下文注入 |
| **SillyTavern** | 开源本地部署、社区生态最活跃 | 生态兼容、本地化、扩展性 |

选择理由：三者覆盖本项目声明要切入的生态位（AI 叙事 + 本地/托管 + 世界观资产）。

---

## 三、发现清单（按严重级别）

### High

| ID | 级别 | 置信度 | 维度 | 位置 | 问题 | 证据 | 建议修复 | 对标含义 |
|---|---|---|---|---|---|---|---|---|
| F-001 | ~~High~~ **已修复** | 高 | 数据完整性 | `state_schema.py:97` | 状态文件非原子写入：`open(path,'w')` 直接覆盖。进程在任何时刻被杀都会留下半截 JSON，**存档彻底损坏且无备份** | PoC：写入后把文件截断一半 → `load_state()` 抛 `JSONDecodeError`，无恢复路径。实测输出见下 | **已实施**：临时文件 + `fsync` + `os.replace()` 原子替换，并保留 `.bak` | 关闭差距：NovelAI/SillyTavern 均有自动存档与备份 |
| F-002 | ~~High~~ **已修复** | 高 | 安全配置（A02） | `panel.py:434,506` | 只设了 `Cache-Control`，缺 `X-Content-Type-Options`、`X-Frame-Options`、`Content-Security-Policy`、`Referrer-Policy` | `grep -n "X-Content-Type-Options\|X-Frame-Options\|Content-Security-Policy" panel.py` → 无命中 | **已实施**：`_send()` 统一加 4 头；实测 `curl -D` 四头齐全，CSP 未破坏页面（0 内联 script/style/事件） | 关闭差距：任何现代 Web 服务默认带这些头 |
| F-003 | ~~High~~ **已修复** | 高 | 体验（UI） | `panel.js:342` `timelineItem` | 时间线条目**不可点击**，无事件详情。玩家看到"沈砚击败了山贼"却点不出上下文 | UI 巡检：`#timeline li[data-event-id]` 全部无 click 监听（`grep addEventListener` 在 timelineItem 内为空），点击后 `#eventdlg` 不打开 | **已实施**：条目加 click/keydown（Enter/Space）→ 复用 `#eventdlg`。实测点击后弹窗打开、标题正确 | 明确差距：AI Dungeon 每条叙事可展开；SillyTavern 消息可点开详情 |

**F-001 PoC（已执行）**：
```
正常写入后大小: 36
PoC 确认：半截文件导致 JSONDecodeError —— 存档不可恢复
```

### Medium

| ID | 级别 | 置信度 | 维度 | 位置 | 问题 | 证据 | 建议修复 | 对标含义 |
|---|---|---|---|---|---|---|---|---|
| F-004 | Medium | 高 | 体验（数据） | `_ui_state.json` 场景 | 玩家所在位置常无其他角色，「在场」区显示"此时无人"，角色卡交互无法验证 | UI 巡检 FAIL「在场角色卡存在：当前状态无人」 | 非缺陷：数据状态使然。但应在无人在场时给出更明确的空态文案 | 承认差距 |
| F-005 | Medium | 高 | 可维护性 | `panel.py:62` / `engine.py:37` / `mcp_server.py:950` | 6 个函数圈复杂度 20-24，超红线 10 的 2 倍以上：`classify_event`(24)、`engine.main`(23)、`narration_context`(22)、`build_scene`(21)、`resolve_combat`(20)、`use_item`(20) | `radon cc -s` 输出 | 按职责拆分（`classify_event` 按事件类型抽表驱动） | 承认差距：单文件架构的取舍，但 24 偏高 |
| F-006 | Medium | 高 | 可维护性 | 全仓 | 重复 6 行块涉及 348 行 = **4.7%**，超红线 3% | 自研滑窗哈希检测（见 §6） | 抽出重复的 state 归一化/校验辅助函数 | 承认差距 |
| F-007 | Medium | 高 | 可维护性 | 全仓 | **27 个函数超 50 行**，最长 `verify_mcp_stdio.main` 399 行 | AST 统计 | 测试脚本可接受（线性场景）；生产代码中 `resolve_combat` 142 行、`resolve_trade` 111 行应拆 | 承认差距 |
| F-008 | Medium | 高 | 可观测性（A09） | 全仓 | **无任何结构化日志**：`grep -rn "logging\."` 零命中。排障只能靠 stdout JSON | 命令输出为空 | 引入 `logging`，至少记录工具调用/tick/异常 | 不适用：本地单机工具，无集中日志需求；但保留 stdout JSON 作为审计线索已够 |
| F-009 | Medium | 高 | 可靠性 | 全仓 | **无超时设置**（`grep timeout=` 在核心模块零命中）。MCP 工具调用没有超时保护 | 命令输出为空 | 本地 stdio 调用延迟可控，风险低；但面板 `open_panel` 的 HTTP 请求应有超时 | 承认差距 |
| F-010 | Medium | 中 | 供应链（A03） | 仓库根 | CVE 扫描**没有脚本**，只有文档记录（`requirements-mcp.lock.txt` 注释里的 OSV 结果）。无法在 CI 中自动复验 | `ls scripts/ \| grep -i cve` → 无 | 加 `scripts/check_cve.py`（OSV API），接入 CI | 关闭差距 |

### Low

| ID | 级别 | 置信度 | 维度 | 位置 | 问题 | 证据 | 建议修复 |
|---|---|---|---|---|---|---|---|
| F-011 | Low | 高 | 性能 | `assets/echarts.min.js` | 1,007 KB 是首屏最大负担，占全部前端资源的 93% | `ls -la` 输出 | 可换轻量图表库或按需构建；当前可接受（本地无网络延迟） |
| F-012 | Low | 高 | 可维护性 | `mcp_server.py` 1,346 行 | 单文件承载 31 个工具 + 20 个辅助函数 | `wc -l` | 按工具组拆分（评估后判定收益低于成本，见 §7） |
| F-013 | Low | 中 | 体验 | `panel.js:1027` | 轮询兜底 2.5s 间隔，SSE 正常时也每 2.5s 检查一次 | 代码审查 | 可改为自适应退避；当前 CPU 开销可忽略 |

### [未确认]

| ID | 维度 | 待确认内容 | 需要什么证据 |
|---|---|---|---|
| U-001 | 覆盖率 | `mcp_server.py` 在**全量测试**下的真实覆盖率 | 现有 `coverage_mcp.py` 只跑 `verify_mcp_stdio`（34%）；需合并 `user_playtest` 的独立数据 |
| U-002 | 可访问性 | WCAG 2.1 AA 合规性 | 无 axe-core 扫描；需接入 `@axe-core/playwright` |
| U-003 | 性能 | 2000 回合的 P95 工具调用延迟 | 只测了总时长，未做分位统计 |
| U-004 | 兼容性 | Firefox / Safari 渲染差异 | 只在 Edge(Chromium) 测过 |

---

## 四、查漏补缺清单（项目类型专项）

项目类型 = **本地 AI 工具 + 规则引擎库 + 只读 Web 应用**。

### 4.1 AI 应用专项

| 检查项 | 状态 | 证据 |
|---|---|---|
| 提示词注入防护 | ✅ | `verify_injection.py` 21/21；9 条特征 + untrusted 标记 |
| 模型输出不落库（防污染） | ✅ | 所有数值经引擎结算，Agent 只转写 |
| 上下文长度控制 | ✅ | `recap(budget_chars)` / `event_log_keep` / 归档 |
| 本地文件读取范围 | ⚠️ | `character_card_read` 可读任意路径（本地工具场景可接受，但应文档化） |
| 多 Agent 并发写 | ⚠️ | 无文件锁；单机单 Agent 场景可接受 |

### 4.2 Web 应用专项

| 检查项 | 状态 | 证据 |
|---|---|---|
| 安全响应头 | ❌ | F-002 |
| CSP | ❌ | F-002 |
| CSRF | 不适用 | 全部 GET 只读，无状态变更端点 |
| XSS | ✅ | 前端全程 `textContent`，无 `innerHTML` 拼接用户数据（`grep innerHTML` 仅在静态模板） |
| 点击劫持 | ❌ | 缺 `X-Frame-Options`（F-002） |
| 静态资源路径穿越 | ✅ | `STATIC_WHITELIST` 白名单 + `verify_panel` 5 条路径断言 |
| 空态 / 错误态 / 加载态 | ✅ | 缺档横幅+重试、图表"数据不足"、空列表占位 |
| 键盘可达性 | ✅ | `?` 快捷键、Esc 关弹窗、`focus-visible` |
| 屏幕阅读器 | ⚠️ | 有 `aria-label`/`role`，但未做 axe 扫描（U-002） |

### 4.3 明确不适用

| 维度 | 不适用原因 |
|---|---|
| 多租户 / IDOR / 认证 / MFA | 无用户体系，单机单用户 |
| 数据库 N+1 / 索引 / 事务 | 无数据库，JSON 文件存储 |
| 自动伸缩 / 容量规划 | 本地进程，无弹性需求 |
| CDN / SRI | 全离线，无外部资源 |
| on-call / SLO / 错误预算 | 单人本地工具，无服务等级承诺 |

---

## 五、竞品对标矩阵

| 能力/维度 | world-walker | AI Dungeon | NovelAI | SillyTavern | 差距类型 | 优先级 |
|---|---|---|---|---|---|---|
| 数值确定性/可复现 | ✅ 同种子逐字节一致 | ❌ | ❌ | ❌ | **跨越** | — |
| 规则内核（数学驱动） | ✅ 129 公式 + 16 模型 | ❌ | ❌ | ❌ | **跨越** | — |
| 完全离线可用 | ✅ 零依赖 | ❌ 云端 | ❌ 云端 | ✅ 自架 | **跨越** | — |
| 实时可视化面板 | ✅ 图表/关系网/事件谱 | ❌ | ❌ | ⚠️ 纯文本 | **跨越** | — |
| 长局记忆 | ✅ 三层（摘要/大事记/归档） | ⚠️ 有截断 | ✅ Lorebook | ✅ 世界书 | 承认（无向量检索） | P2 |
| 世界观资产兼容 | ✅ 角色卡 V1/V2/V3 + 世界书 | ❌ | ✅ Lorebook | ✅ 原生 | **承认**（不做编辑器） | P1 |
| **事件可展开查看** | ❌ 时间线不可点 | ✅ | ✅ | ✅ | **关闭** | **P1（F-003）** |
| **自动存档/备份** | ❌ 无备份，非原子写 | ✅ | ✅ | ✅ | **关闭** | **P0（F-001）** |
| **安全响应头** | ❌ | ✅ | ✅ | ✅ | **关闭** | **P1（F-002）** |
| 世界书 GUI 编辑器 | ❌ | ❌ | ✅ | ✅ | 承认（越过只读红线） | — |
| 移动端 | ⚠️ 响应式 320px 可用 | ✅ App | ⚠️ Web | ❌ | 承认 | P3 |
| 图像生成 | ❌ | ✅ | ✅ | ⚠️ 插件 | 刻意忽略 | — |
| 多人协作/分享 | ❌ | ✅ | ⚠️ | ✅ | 刻意忽略 | — |
| 插件生态 | ❌ | ⚠️ | ❌ | ✅ | 刻意忽略 | — |

### 差距评分（需求+收入+战略）× 投入 ÷ 3

| 差距 | 需求 | 收入 | 战略 | 投入 | 分数 | 分类 |
|---|---|---|---|---|---|---|
| 原子写 + 自动备份 | 5 | 1 | 5 | 4 | 14.7 | **关闭** |
| 安全响应头 | 3 | 0 | 4 | 5 | 11.7 | **关闭** |
| 事件可展开 | 4 | 1 | 3 | 4 | 10.7 | **关闭** |
| CVE 扫描脚本 | 3 | 0 | 3 | 4 | 8.0 | **关闭** |
| 世界书编辑器 | 4 | 2 | 4 | 3 | 10.0 | 承认（越过只读红线） |
| 向量检索记忆 | 3 | 1 | 3 | 2 | 4.7 | 承认 |
| 图像生成 | 2 | 3 | 1 | 1 | 2.0 | 忽略 |
| 插件生态 | 2 | 1 | 2 | 1 | 1.7 | 忽略 |

---

## 六、量化指标看板

| 指标 | 红线 | 当前值 | 判定 | 测量方式 |
|---|---|---|---|---|
| 行覆盖率 | ≥90% | **85%** | ⚠️ 未达，过 80% 底线 | `coverage run --branch` 五套合并 |
| 分支覆盖率 | ≥85% | **388 分支中 74 部分**（≈81%） | ⚠️ 未达 | 同上 |
| 变异分数 | ≥80% | **100%（18/18）** | ✅ 通过 | `verify_mutation.py` |
| 圈复杂度（单函数） | ≤10 | **最高 24**（`classify_event`） | ❌ 不通过 | `radon cc -s` |
| 认知复杂度 | ≤15 | `[未确认]` | ⚠️ 无工具 | 需 `radon cc --show-closures` 或 SonarQube |
| 技术债务比率 | ≤5% | `[未确认]` | ⚠️ 无 SonarQube | 需 SonarQube |
| 重复行 | <3% | **4.7%** | ❌ 不通过 | 自研 6 行滑窗哈希 |
| Critical/High 漏洞 | 0 | **0**（bandit） | ✅ 通过 | `bandit -r` |
| lint 告警 | 0 | **0**（pyflakes） | ✅ 通过 | `pyflakes` |
| 超 50 行函数 | 越少越好 | **27 个**（多为测试脚本） | ⚠️ | AST 统计 |
| 平均复杂度 | A 级 | **A (3.98)** | ✅ 通过 | `radon cc -a` |

### 6.1 覆盖率明细（按模块）

| 模块 | 行覆盖 | 分支部分覆盖 | 判定 |
|---|---|---|---|
| `rules/cultural_evolution.py` | 100% | 0 | ✅ |
| `rules/social.py` | 97% | 1 | ✅ |
| `rules/cognition.py` | 97% | 3 | ✅ |
| `rules/systems_feedback.py` | 97% | 1 | ✅ |
| `rules/social_extended.py` | 96% | 2 | ✅ |
| `rules/economy.py` | 90% | 5 | ✅ |
| `rules/world_dynamics.py` | 85% | 12 | ⚠️ |
| `panel.py` | 84% | 19 | ⚠️ |
| `rules/models.py` | 80% | 11 | ⚠️ |
| `rules/narrative_engine.py` | 80% | 6 | ⚠️ |
| `rules/combat.py` | 67% | 7 | ❌ |
| `rules/karma.py` | 51% | 7 | ❌ |

---

## 七、修复与补齐路线图

| 优先级 | 任务 | 发现 ID | 工作量 | 验收标准 |
|---|---|---|---|---|
| ~~P0~~ ✅ | 状态文件原子写入 + `.bak` 备份 | F-001 | S | 写入过程中 kill 进程，重启后仍能读到上一完整版本；新增断言用"截断文件"复现 |
| ~~P1~~ ✅ | 安全响应头（4 个） | F-002 | S | `curl -I` 可见四头齐全；`verify_panel` 断言 |
| ~~P1~~ ✅ | 时间线事件可点击展开 | F-003 | M | 点任一条目弹出详情；UI 巡检该项转 PASS |
| **P1** | CVE 扫描脚本接入 CI | F-010 | S | `scripts/check_cve.py` 可在 CI 跑；OSV 查询失败时不误报 |
| P2 | `classify_event` 表驱动重构（24→≤10） | F-005 | M | `radon cc` 该项 ≤10；`verify_panel` 55/55 不降 |
| P2 | 抽公共 state 归一化辅助，降重复率 | F-006 | M | 重复率 <3% |
| P2 | `resolve_combat` / `resolve_trade` 拆分 | F-007 | M | 各自 ≤80 行；`verify_formulas` 不降 |
| P3 | 面板请求超时 | F-009 | S | URL 请求带 timeout |
| P3 | 无人在场时的空态文案 | F-004 | S | 显示"此处暂无他人"而非"此时无人" |
| — | **不做**：拆分 `mcp_server.py` | F-012 | — | 31 个工具挂同一 server 实例，拆分只减行数不增可靠性（详见 §7.1） |
| — | **不做**：结构化日志 | F-008 | — | 本地单机工具，stdout JSON 已是审计线索 |
| — | **不做**：世界书 GUI 编辑器 | 对标差距 | — | 越过 ADR-002「面板严格只读」红线 |

### 7.1 关于不做的决策记录

- **F-012 拆分 mcp_server.py**：31 个 `@server.tool()` 装饰的函数必须挂在同一个 `server` 实例上。拆成多文件需要把 `server` 对象跨模块传递，或改用 blueprint 模式——两种都增加间接层，而本项目是本地单机、无多实例、无热重载需求。**收益（行数变少）不抵成本（可读性下降）**。
- **F-008 结构化日志**：项目无服务端、无集中采集。所有工具返回 JSON 且 MCP 协议本身会记录调用，`print` 到 stderr 足以定位问题。引入 `logging` 配置反而增加需要维护的配置面。

---

## 附录：本轮 UI 逐元素巡检明细

| # | 元素 | 结果 | 备注 |
|---|---|---|---|
| 1 | 首访引导条默认可见 | PASS | |
| 2 | 点「知道了」后消失 | PASS | |
| 3 | 刷新后不再出现（localStorage） | PASS | |
| 4 | 帮助弹窗可打开 | PASS | |
| 5-8 | 帮助含术语/图表/状态文件/皮肤 | PASS | 4 项 |
| 9 | Esc 可关闭帮助 | PASS | |
| 10-13 | 四个抽屉可展开且有内容 | PASS | 图鉴/市场/大事记/世界标记 |
| 14 | 「跳到最新」滚回顶部 | PASS | scrollTop=0 |
| 15 | 动效开关可切换 | PASS | false→true |
| 16 | 在场角色卡 | **FAIL** | 数据状态：当前地点无人（非缺陷） |
| 17 | 点时间线事件弹出详情 | **PASS（已修）** | F-003 修复后实测：40 个条目可点，弹窗标题正确 |
| 18 | 按 `?` 打开帮助 | PASS | |
| 19 | 连接状态文本非空 | PASS | 实况 · 21:04:41 |
| 20 | 徽章区渲染 | PASS | 1 个徽章 |
| 21 | 无 JS 控制台错误 | PASS | 0 条 |
