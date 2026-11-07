# 贡献指南

## 先读这三份

1. `ARCHITECTURE.md` —— 唯一真理源（数据模型、不变量、ADR）
2. `AGENTS.md` —— 仓库级硬约束（零依赖、面板只读、确定性）
3. `docs/BENCHMARK.md` —— 我们和谁比、哪些差距是"承认"而不是"没发现"

发布流程见 `docs/RELEASING.md`；对外文档英文主版是 `README.md`，中文版是 `README.zh-CN.md`。

## 开发环境

```bash
git clone <repo> && cd world-walker
pip install -e ".[mcp]"          # MCP 门禁需要；版本基线见 requirements-mcp.lock.txt
pip install -r requirements-mcp.lock.txt
pip install coverage pyflakes bandit radon playwright   # 门禁所需工具
python -m pip check
python -m playwright install msedge                     # 界面巡检所需浏览器
```

## 修改前

**任何影响架构、接口、数据模型、依赖或目录结构的改动，必须同步更新 `ARCHITECTURE.md`。**
这不是建议，是仓库约定：文档漂移在本项目里被当作缺陷处理。

## 验证

```bash
bash scripts/pre_push_gate.sh    # 含行为回归；缺 MCP/Playwright 时 fail-closed
```

单项：

```bash
python scripts/run_behavior_regressions.py  # 判定、tick、变异、MCP stub、归档中断回归
python scripts/verify_cli.py         # CLI 通道
python scripts/verify_panel.py       # 视图模型 / 行动队列
python scripts/verify_world.py       # 世界演化
python scripts/verify_settings.py    # 四套设定包
python scripts/verify_generic.py     # 通用游戏层（判定/档案/上下文/存档库）
python scripts/metrics.py --check    # 文档引用的数字必须与源码一致
python scripts/verify_mutation.py    # 44 个变异必须全杀
```

## 写测试的硬规则

本项目**没有 pytest**。测试包括 `scripts/verify_*.py` 和行为回归套件；断言应满足：

1. **精确到值**：`check('trade 扣款', gold_before - gold_after == result['total_cost'])`
   而不是 `check('trade 扣款', gold_after < gold_before)`。
2. **不得恒真**：`verify_tests.py` 会静态拒绝 `x >= 0`、`bool(1==1)`、`check(name, True)`、
   `os.path.exists(p) or True` 这类写法。
3. **必须能被变异杀死**：新断言要配一条 `verify_mutation.py` 的变异条目
   （把实现改坏 → 该断言必须 FAIL）。做不到就说明断言不够强。
4. **前提必须成立**：需要确定性的用例要在临时状态里显式关掉随机源（如 `config.market_jitter = False`），
   否则手算复算永远对不上。

## 新增设定包

1. 复制 `settings/玄枢界.setting.json`，替换 world / player / entities / market / relations / lore。
2. `terms` 必须覆盖所有界面词（对照 `panel.py::DEFAULT_TERMS` 的键）。
3. `level_tiers` 从低到高，`advance` 会逐阶校验。
4. 人物、势力、地名**必须原创**——借结构，不搬名字。
5. 跑 `python scripts/verify_settings.py`，它会对新包做全部断言。
6. 跑 `python scripts/make_demo.py --only <世界名>` 生成演示存档。

## 新增 MCP 工具

1. 在 `mcp_server.py` 用 `@server.tool()` 装饰器声明，docstring 写清中英文用途。
2. 如果工具**只读**，用 `_read()` 包装返回，**不要** `_finish()`（后者会 `save_state`）。
3. 在 `world_schema()` 的 `action_tools` 里登记。
4. 在 `scripts/verify_mcp_stdio.py` 的 `EXPECTED_TOOLS` 里加名字，并写至少一条行为断言。
5. 更新 `README.md` 的工具表与 `GAME_MASTER_PROTOCOL.md`。

## 代码风格

- Python 3.10+，仅标准库（MCP 是可选 extra）。
- 不写行内注释解释"是什么"，只在**为什么这么写**不显然时写注释。
- 异常处理要么明确容错（带 `# nosec B110` 与理由），要么不要 `except`。
- 禁止 `assert` 做入参校验（`python -O` 会剥离）。
- 前端：原生三件套，状态值一律 `textContent`，不拼 HTML。

## 提交

- 一个 commit 一件事；提交信息写"为什么"而不只是"改了什么"。
- 不提交：`*.bak`、`*.inbox.jsonl`、`*.log.jsonl`（除 `docs/demo` 的演示侧写）、`.aqg/`、`__pycache__/`。
- 不提交任何密钥；凭据只从本机凭据库读。

## 报告问题

请附：
- 复现命令（最小）
- 期望 vs 实际
- `python scripts/verify_*.py` 的相关输出
- 如果是界面问题，附截图与视口宽度
