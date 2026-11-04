# World Games / world-walker 仓库全面检查报告

## 1. 审计范围与结论

审计对象：`https://gitcode.com/badhope/world-walker.git`。

本次已完成隔离克隆、仓库测绘、静态代码/配置/依赖/安全/工程卫生检查和关键证据复核；没有安装依赖、没有执行仓库脚本或构建、没有修改仓库文件、没有提交或发布。因此，文中“通过”主要指静态证据或元数据核验，不等于运行时门禁全绿。

**总判断：项目定位清晰、工程化程度较高，已从单一修仙文字游戏演进为可扩展的通用 AI 互动游戏框架；但当前 HEAD 仍不宜直接视为生产安全基线。P0 优先修复状态写入并发一致性、`play.sh` 参数拼接注入和审计修复门禁缺口，再做跨平台锁与外部文件入口加固。**

## 2. 克隆与环境基线

| 项目 | 证据 |
|---|---|
| 隔离克隆目录 | `C:/Users/Admin/Desktop/workspace/013/.audit/world-walker` |
| origin | `https://gitcode.com/badhope/world-walker.git` |
| HEAD | `99838e2103d8cd77f9301ba94691c638d6bac53e` |
| 分支 | `main` 与 `origin/main` 指向同一提交；当前检出为 detached HEAD |
| 状态 | `git status --short --branch`：`## HEAD (no branch)`；工作树 diff 为空 |
| 最近提交 | `fix(audit): 状态完整性与规则边界修复 — 快照穿越/并发RMW/NaN落盘/奖励与战斗边界`，2026-10-30 09:30:06 +08:00 |
| 本机验证环境 | Python 3.14.9、Git 2.47.1、Bash 5.2.37 |
| 规模 | 126 个 tracked 文件、57 个 Python 文件、68 个提交、17 个 `verify_*.py` 脚本、32 个 docs 文件、5 个 settings 文件 |

## 3. 项目真实意图与定位

### 3.1 真实意图

项目不是一款固定题材的游戏，而是“让宿主 Agent 负责叙事、让确定性引擎负责世界与规则”的通用互动游戏框架。核心闭环是：MCP/CLI 接收行动 → `rules/*` 计算确定性结果 → 状态 JSON 落盘 → 上下文台账与存档库维持长局连续性 → 本地只读网页面板展示真实状态。

证据：`README.md:5-9`、`README.md:25-45`、`ARCHITECTURE.md:7-23`。

### 3.2 服务对象与阶段

- 服务对象：通过 MCP 调用工具的 Claude Code、Codex、Cursor 或自建 Agent 宿主，以及进行本地互动的玩家。
- 核心问题：避免 LLM 即兴编数值、上下文遗忘和单 JSON 存档失控。
- 当前阶段：v1.4.0，已具备引擎、MCP、CLI、只读面板、设定包、验证脚本和 CI；仍是第一阶段，网页直接提交行动被明确放到第二阶段。
- 规模判断：不是一次性脚本，而是有版本、68 次提交、CI/门禁、路线图和扩展模型的长期小团队/可扩展框架。长期维护需要继续保持测试、跨平台和状态一致性门禁。

证据：`pyproject.toml:5-29`、`ARCHITECTURE.md:9-23`、`ROADMAP.md:31-64`、Git 提交统计。

## 4. 仓库地图

### 技术栈

- Python `>=3.10`，仓库根目录映射为 `game_engine` 包：`pyproject.toml:5-10,31-35`。
- 运行时以 Python 标准库为主；MCP 是可选依赖 `mcp>=2.3,<3`：`pyproject.toml:20-22`。
- HTTP/SSE 面板使用标准库 `http.server`；前端为原生 HTML/CSS/JS；状态和归档为 JSON/JSONL：`ARCHITECTURE.md:54-62`。
- 入口脚本：`world-games` / `world-walker` CLI 与 `world-games-mcp` / `world-walker-mcp` MCP：`pyproject.toml:24-29`。

### 目录职责

| 位置 | 职责 |
|---|---|
| `engine.py` | CLI 规则结算与调试入口 |
| `mcp_server.py` | MCP 工具入口、状态读写、行动结算 |
| `state_schema.py` | 状态结构、原子写、归档、种子、事务辅助函数 |
| `sessions.py` | 多局、快照、回收站 |
| `rules/` | 判定、战斗、经济、社交、上下文、玩法、事业线、世界书、体系等规则内核 |
| `settings_loader.py` / `settings/` | 设定包规范化与内置世界 |
| `panel.py` + `panel.html/css/js` | 本地只读面板与 SSE |
| `scripts/` | 17 个验证/演示/门禁辅助脚本 |
| `docs/` | 架构、玩法、基准、展示和演示材料 |

### 入口与命令

文档声明的入口和命令：

```text
pip install -e .
pip install -e ".[mcp]"
world-games / world-walker
world-games-mcp / world-walker-mcp
bash play.sh
bash scripts/pre_push_gate.sh
```

证据：`AGENTS.md:25-50`、`README.md:59-109`、`pyproject.toml:24-29`。

仓库没有常规 `tests/` 目录，也没有 pytest 测试套件；验证主要由 `scripts/verify_*.py` 完成，`AGENTS.md:40-50` 明确声明这一约定。

## 5. 已验证的静态质量事实

- 57/57 Python 文件可被 Python AST 解析；未执行其代码。
- 11 个 JSON 与 4 个 JSONL 文件均可用标准库 `json` 解析（合计 15 个文件）；未执行导入路径。
- AST 统计 `server.tool` 装饰器为 64 个，与 `README.md:7,113` 和 `ARCHITECTURE.md:33-49,68` 的声明一致。
- `scripts/verify_audit_fix.py` 本身定义 7 组修复、16 个断言：`scripts/verify_audit_fix.py:3-16,239-249`；但它未被 CI 或本地门禁调用。
- 当前工作树无 diff，审计过程没有污染仓库。
- 凭据模式扫描覆盖当前文件与 68 个历史提交的文本 blob，0 命中；这不是秘密不存在的绝对证明，但没有发现常见硬编码凭据模式。
- 依赖锁文件列出 10 个精确版本：`requirements-mcp.lock.txt:11-20`；对这 10 个精确版本做 OSV querybatch，返回 10 个空结果对象，未发现已知 OSV 命中。未做完整 SBOM、许可证和安装后行为审计。

## 6. 风险清单

### P0 / High：先修

#### P0-1：MCP 生产写路径没有接入事务式读改写，存在并发丢更新

`state_schema.py:172-193` 只定义了 `transact_state`；静态调用仅在 `scripts/verify_audit_fix.py:89,126`。生产 MCP 工具仍普遍执行 `_load()` → 原地修改 → `_finish()` → `save_state()`，例如 `mcp_server.py:727-749`、`752-772`、`775-811`、`814-859`、`1396-1465`、`1542-1596`。

影响：同一存档被多个 MCP 会话并发修改时，后写入者可能覆盖先写入者的事件、计数器或资源变化。该问题与最新提交标题声称修复的“并发 RMW”相矛盾。

证据强度：静态确定存在未接入；实际丢更新概率与具体宿主并发模型未运行验证。

修复方向：将所有状态变更工具统一包进事务式读改写；避免把普通查询工具混入事务；为 MCP 多进程场景增加 Linux `fcntl` 与 Windows `msvcrt` 双实现；把并发回归加入 CI 和本地 gate。

#### P0-2：`play.sh` 将 `STATE` 路径插入 Python 单行代码

`play.sh:35-39` 设置 `PYTHONPATH=.`，并把 `$STATE` 直接嵌入 `python -c "...open('$STATE')..."`。构造包含单引号的状态路径可破坏 Python 字面量，形成命令入口代码注入；`PYTHONPATH=.` 还扩大当前目录模块阴影风险。

影响：任何直接运行该脚本且路径来自不可信输入的场景，都可能执行非预期 Python 代码。即使用户通常只传本地路径，也不应以字符串拼代码。

证据强度：静态确定存在危险拼接；没有执行 PoC，避免执行不可信仓库脚本。

修复方向：改成 `python -c '...' -- "$STATE"`，在 Python 中从 `sys.argv` 读取路径；或直接调用已有 CLI，不再用 `-c` 拼接路径；必要时显式设置安全的模块搜索路径。

#### P0-3：审计修复回归未进入任何门禁

`README.md:486` 和 `README.en.md:388` 宣称 `verify_audit_fix.py` 存在；但 `.github/workflows/ci.yml:35-90,115-131`、`.workflow/ci.yml:30-156`、`scripts/pre_push_gate.sh:37-110` 均未调用它。该脚本锁定的 R1-R7（快照穿越、并发 RMW、NaN、奖励、战斗边界、等级倒退、fact ID）不会阻断 CI 或推送。

影响：最新修复可以在未来回归而不被门禁发现，且文档的“门禁项/自检数量”容易与实际不一致。

修复方向：把 `verify_audit_fix.py` 接入 GitHub/Gitee/pre-push 同一套门禁，更新脚本计数和 `verify_docs` 基线；在 Linux 与 Windows CI 都执行跨进程回归。

### P1 / Medium：应在同一迭代加固

#### P1-1：跨平台文件锁实现与项目声明不一致

`state_schema.py:144-161,188-193` 仅导入 `msvcrt`，没有 `fcntl` 分支；但 docstring 声称 Windows/POSIX 双平台，`pyproject.toml:15-18` 声明 OS Independent，`ARCHITECTURE.md:19` 写 Python >=3.10。

影响：Linux/macOS 调用 `transact_state` 会因 `msvcrt` 不存在而失败。当前 CI 未运行 `verify_audit_fix.py`，所以缺陷未暴露。

修复方向：按 `os.name` 分支实现 `msvcrt`/`fcntl.flock`，并在 Linux/macOS/Windows 矩阵执行事务回归。

#### P1-2：`restore` 和 `session_import` 接受任意本地路径

`mcp_server.py:1639-1662` 的 `restore(snapshot_path)` 只检查 `exists` 后直接 `load_state` 并覆盖当前状态；`mcp_server.py:1933-1952` 的 `session_import(path, ...)` 也直接读取调用者提供的路径。相比之下，`snapshot(label)` 已在 `mcp_server.py:1628-1636` 对标签做 `safe_name` 清洗。

影响：在本地 Agent 输入不可信或宿主被提示词注入时，可读取任意可读 JSON；`restore` 还可用合法 JSON 覆盖当前对局。SECURITY.md:13 对外部角色卡路径做了设计声明，但没有覆盖 restore/import 的最小权限边界。

修复方向：限制到当前状态目录/存档目录和快照白名单；校验扩展名、规范化路径、文件大小和状态 schema；导入前使用临时状态并显式确认覆盖语义。

#### P1-3：角色卡/世界书导入无文件大小上限

`mcp_server.py:274-293` 对 PNG 做全量 `read()`，`mcp_server.py:296-305` 和 `mcp_server.py:359-376` 对 JSON 直接 `json.load()`；`settings_loader.py:277-349` 对 `content` 没有长度上限。`character_card_read`/`import_lorebook`/`add_character` 入口位于 `mcp_server.py:1056-1129`。

影响：恶意或误选超大文件可造成内存和 CPU 消耗，形成本地 DoS；世界书正文还会进入状态与 Agent 上下文。

修复方向：打开前 `stat` 上限；PNG 分块解析并限制 chunk/解码大小；JSON 深度、条目数和单字段长度限额；导入后继续保留 `untrusted` 标记并限制上下文预算。

#### P1-4：CI 与 lock 文件脱节，构建不可完全复现

`requirements-mcp.lock.txt:11-20` 钉住 10 个版本，但 `.github/workflows/ci.yml:115-116` 和 `.workflow/ci.yml:126-132` 仍执行 `pip install -e ".[mcp]"`，而 `pyproject.toml:20-22` 只给区间 `mcp>=2.3,<3`。

影响：上游依赖漂移可能带来行为变化、供应链风险或 CI 不一致。OSV 查询只证明当前锁定版本无已知漏洞，不能证明区间安装结果。

修复方向：CI 使用 lock 文件安装，并增加 lock 与 pyproject 兼容性校验；按更新流程重新跑 MCP/界面验证和漏洞扫描。

### P2 / Low：维护性与可观测性改进

- `mcp_server.py` 约 2151 行、`panel.py` 约 1563 行、`templates.py` 约 976 行、`rules/systems.py` 约 845 行；模块职责虽有边界，但长期维护成本高。建议按工具域拆分并保持公共状态契约不变。
- `scripts/pre_push_gate.sh:13` 使用 `set -uo pipefail` 而非 `set -euo pipefail`，虽通过 `step()` 显式累计失败，但未来新增未包装命令容易产生失败后继续执行的假绿风险。
- 失败吞噬点较多；`mcp_server.py:410-416` 对侧写异常静默容错是有意设计，但应确保指标或日志能表明观测数据缺失。
- 项目没有常规 pytest 层；当前脚本式验证覆盖了大量行为，但建议逐步增加最小单元/属性测试以缩短定位时间。

## 7. 五方案对比：下一步开发优先级

| 方案 | 核心思路 | 优点 | 缺点 | 成本 | 本需求适配评分 |
|---|---|---|---|---|---|
| A. 继续堆玩法/模板 | 先扩充世界、体系和面板功能 | 用户可见功能增长快 | 并发、路径和门禁缺口继续扩大 | 中；低依赖；高回归风险 | 2/5 |
| B. 只补 CI 门禁 | 把 `verify_audit_fix` 接入现有 CI/pre-push | 快速阻断回归，改动小 | 不能修复生产并发/路径问题；Linux 锁仍坏 | 低；低依赖；中风险 | 3/5 |
| C. 先做状态写入一致性基线（推荐） | 统一事务式写入，补跨平台锁，接入并发回归，再修 `play.sh` | 直接解决数据丢失与本地入口风险；支撑长期扩展 | 触及核心写路径，需逐工具回归 | 中高；无新增运行时依赖；中风险 | **5/5** |
| D. 先做外部文件导入沙箱 | 限制 restore/import/角色卡/世界书大小和路径 | 缩小本地 Agent 输入攻击面 | 不能解决并发状态损坏；需调整兼容语义 | 中；低依赖；中风险 | 4/5 |
| E. 先做 schema/插件生态 | JSON Schema、版本号、迁移和第三方世界包规范 | 长期扩展价值高 | 建立在当前状态写入可靠的前提上；周期长 | 高；可能需要新工具；高风险 | 3/5 |

**选择 C。** 用户要的是“开发全面检查”，最重要的不是再列玩法，而是先确认可持续开发基线；C 同时覆盖数据一致性、跨平台和命令入口，且不引入第三方运行时依赖。推荐实施顺序：C 的事务/锁与 `play.sh` → B 的门禁接入 → D 的路径/大小限制 → E 的 schema/插件化 → A 的功能扩展。

## 8. 测试与运行验证边界

本次实际执行的验证：

- Git remote/HEAD/status/log/branch/diff：通过元数据核验。
- Python 3.14.9、Bash 5.2.37 可用。
- AST：57/57 Python 解析成功。
- JSON：11 个 JSON 文件解析成功。
- MCP 工具装饰器静态计数：64。
- 文件/提交/验证脚本数量统计。
- OSV 对锁定 10 个版本的查询：0 个已知命中（网络查询结果由 lead 提供）。

本次明确未执行：

- `pip install -e .` 或 `pip install -e ".[mcp]"`；
- `bash scripts/pre_push_gate.sh`、任何 `verify_*.py`、`play.sh`、`engine.py`、`mcp_server.py`；
- 打包/wheel 安装、MCP stdio、Playwright/UI、500 轮压测、覆盖率门禁；
- Linux/macOS/Windows 跨平台运行对照；
- 依赖安装后的 SBOM、许可证和传递依赖完整审计。

因此不能声称仓库“测试全绿”“构建通过”或“运行正常”。只能说静态结构和元数据检查达到上述结果。

## 9. 交付质检门禁

| 维度 | 结果 | 说明 |
|---|---|---|
| 完整性 | 通过（静态审计范围） | 覆盖克隆、地图、意图、质量、依赖、安全、测试边界和优先级 |
| 一致性 | 有条件通过 | 文档和代码大体一致；`verify_audit_fix` 接入门禁和计数存在缺口 |
| 可追溯 | 通过 | 关键结论均给出文件路径/行号或命令证据 |
| 可复现 | 有条件通过 | 克隆和静态命令可复现；仓库运行门禁因安全边界未执行 |
| 合规/敏感信息 | 通过 | 未在报告输出凭据值；未发现常见凭据模式 |
| 版权 | 未完整验证 | 仅确认 `LICENSE`/仓库资源存在，未逐项审查截图、视频和前端素材授权链 |
| 格式 | 通过 | Markdown 报告，中文结论、风险分级、三清单齐全 |

## 10. 三清单

### 改了什么

- 在当前工作区新增本报告：`world-walker-audit.md`。
- 更新会话记忆文件以记录目标、克隆事实、审计进度和未验证边界。

### 没动什么

- 未修改 `.audit/world-walker` 内任何代码、配置、文档或资源。
- 未修改远程仓库、分支、提交或 CI。
- 未安装依赖、未执行仓库脚本、未提交、未推送、未发布。

### 未验证什么

- 真实运行时测试、构建、MCP stdio、UI、压测、覆盖率和 wheel 安装。
- P0/P1 静态疑点的具体运行时复现与利用条件。
- 非 Windows 平台实际行为。
- 传递依赖完整 SBOM/许可证/安装后行为。
- 截图、视频和其他展示素材的版权授权链。
