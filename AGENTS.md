# AGENTS.md — World Games

通用 AI 互动游戏框架：规则结算内核（Python）+ 上下文台账 + 存档库 + MCP 服务器 + 只读网页主舞台。
任何题材都能用；内置四套设定包只是示例。零第三方运行时依赖（MCP 为可选 extra）。

**`ARCHITECTURE.md` 是本项目唯一真理源**——凡影响架构/接口/数据模型/依赖/目录结构的变更，必须同步更新它。

## 结构

- 仓库根即 `game_engine` 包（`pyproject.toml` 中 `package-dir = { "game_engine" = "." }`，内部统一 `import game_engine.*`）
- `bootstrap.py` — 入口引导（仓库根 → `game_engine` 包，幂等；三个入口共用，别再复制粘贴）
- `engine.py` — 规则结算内核
- `mcp_server.py` — MCP 工具入口（64 工具；兼容 mcp 1.x `fastmcp` 与 2.x `mcpserver` 两种布局）
- `panel.py` / `panel.html` / `panel.css` / `panel.js` — 只读主舞台（面板不许写状态；
  行动队列只写 `<state>.inbox.jsonl` 侧写，状态仍由 MCP 单点写入）
- `state_schema.py` — 状态模型（原子写 / 世代归档 / 种子）
- `sessions.py` — 存档库（多局/快照/回收站；只碰文件系统，不写状态内容）
- `rules/checks.py` — 通用判定（d20/2d6/d100/4dF/骰池、对抗、成功等级）
- `rules/gamesystem.py` — 游戏档案（自定义属性/资源/进度轨/标签/表格；旧存档自动回退）
- `rules/context.py` — 上下文台账（事实/线索/承诺 + 预算打包）
- `rules/systems.py` — 七类可插拔体系（时间/掉落/制造/声望/成就/成长/自定义）
- `templates.py` — 八套完整游戏模板（开箱即用，可 overrides 覆盖）
- `settings_loader.py` — 设定包 → 状态（**纯标准库**；MCP 与零依赖自检共用，不要在这里引 mcp）
- `rules/` — 规则数据；`settings/` — 四套设定包；`scripts/` — 验证脚本（17 个 `verify_*.py` + `metrics.py` + 素材流水线）
- `docs/metrics.json` — 唯一数字信源（`scripts/metrics.py --write` 生成，禁止手改；文档只许引用这里）

## 运行

```bash
pip install -e .            # 或 pip install -e '.[mcp]' 装 MCP 依赖
world-games                 # CLI（兼容别名 world-walker）
world-games-mcp             # MCP 服务器（兼容别名 world-walker-mcp）
bash play.sh                # 快速开局
```

## 验证（改完必须跑）

```bash
bash scripts/pre_push_gate.sh   # 推送前门禁，与 GitHub Actions 同判据
```

分项可跑：`verify_formulas.py`、`verify_memory.py`、`verify_mcp_stdio.py`、`verify_panel.py`、
`verify_injection.py`、`verify_branches.py`、`verify_cli.py`、`verify_near_death.py`、
`verify_world.py`、`verify_settings.py`、`verify_docs.py`、`verify_generic.py`、`verify_systems.py`、`verify_mutation.py`、`smoke_ui.py`。

**CI 的 core 作业不装 mcp**：任何要在 core 里跑的脚本都不得 import `mcp_server`（会 ModuleNotFoundError）。
设定包相关逻辑一律走 `settings_loader.py`。

素材流水线（不进门禁）：`python scripts/make_demo.py` 生成四套世界的演示存档，
`python scripts/shots.py` 断言后截图并录制 `docs/screenshots/walkthrough.mp4`。

**没有 pytest 测试套件**——验证靠上述脚本，不要假设 `pytest` 可用。

## 体系与模板（v1.4）

- `rules/systems.py` 的七类 kind（time/loot/craft/reputation/achievement/progression/custom）
  共用 `system_run(sid, action, params)`；新增能力时在 `KINDS` 与 `_CONFIG_NORMALIZERS` 同处扩展。
- `custom` 的效果 op 必须先在 `EFFECT_OPS` 白名单登记，**定义期** `normalize_system` 就会拒绝非法 op。
- `templates.py` 的模板必须通过 `validate()`：缺件、`places[].market` 悬空、
  事业线 `visited` 指向不存在地点都会被拦下。
- 成就/模板谓词的 `counter_gte` 依赖 `state["counters"]`；新增计数器必须在
  `state_schema.bump()` 的调用点登记（当前：图鉴/线索/判定/击杀），否则是死条件。
- 改体系或模板后跑 `python scripts/verify_systems.py`（161 项）+ `verify_mutation.py`。

## 硬约束

- 数值确定性优先：同样的输入 + 随机种子必须复现同样结果，禁止引入不受控随机/时间依赖
- 面板严格只读：`panel.*` 不得写 `game_state.json`
- 零依赖原则：新增第三方依赖前必须先说明必要性（MCP 之外）
- 改数据模型必须同步 `ARCHITECTURE.md` 与 `state_schema.py`
- `game_state.json` / `demo_state.json` / `audit_state.json` 是演示与审计快照；`demo_state.json` 被 `verify_cli.py` 当作 CLI 基准存档，改动会让断言失真

## 不要碰

- `__pycache__/`、`*.egg-info/`、`.venv/`
- `docs/screenshots/` 里的截图（由 `scripts/shots.py` 断言后入库）
- `requirements-mcp.lock.txt`（经 OSV 扫描，加依赖需重扫）
- `game_state.json` 的真实存档（调试请用副本）
