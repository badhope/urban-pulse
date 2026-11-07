# 设定包（settings/）

一个「设定包」= 一局游戏的全部开局素材，一个 JSON 文件就够。MCP 里一句话开局：

```
load_setting(path="settings/玄枢界.setting.json")     # 世界 + 人物 + 市场 + 关系 + 世界书，一次到位
```

载入后建议紧接着 `open_panel`，给玩家一块可一直看的实况主舞台（叙事/HUD/长局图表/皮肤）。

**换世界只需换这个包**：世界观词、等级阶梯、地点描写、货币、皮肤与品牌全在里面；
引擎侧不需要改一行代码。

## 格式

| 字段 | 必填 | 说明 |
|---|---|---|
| `world` | ✓ | `{name, era, location_desc}` |
| `player` | ✓ | 实体形状（见 `world_schema` 工具的 entity_shape） |
| `entities` | | NPC 数组，每项要有 `id`；可带 `desc` / `personality` / `speech`（叙事层文字） |
| `market` | | `[{location, items:[{key, name, price, supply, base_price, type, desc}]}]` |
| `relations` | | `[{a, b, affinity, respect}]`（键序由引擎生成） |
| `world_flags` | | 字符串数组（世界状态标记） |
| `currency` | | 货币名（默认「灵石」；示例设定用「玄晶」，交易文案会跟着变） |
| `ui` | | 面板皮肤与品牌：`{skin: xuanshu\|neutral\|ink\|neon, accent: '#rrggbb', motif: '风格文案', brand: '字标', tagline: '标语'}`；让本世界在主舞台上自带视觉风格与自己的名字（未知 skin 回退 neutral；规范见 `BRAND.md`） |
| `level_tiers` | | 本世界的等级阶梯（数组，低→高），如 `["淬体","引元",...]`。配了它，`advance` 只能逐阶递进（同阶内可递段），跳阶/倒退会被拒；战斗按阶梯给战力加成。不配则退回旧行为（不校验） |
| `terms` | | 面板术语覆盖 `{level:"等级", track:"进化轨", ...}`（键见 `panel.py::DEFAULT_TERMS`）。让非修真世界观不必看到「境界/修行轨」 |
| `places` | | 地点描写 `{地名: {desc}}` 或 `{地名: "描写"}`。走到该地时面板主舞台显示它，而不是开场那句 |
| `lore` | | 世界书条目，**与酒馆 character_book 同形**：`keys` / `secondary_keys` / `selective` / `constant` / `insertion_order` / `content` / `comment`。`narration_context` 按关键词触发它们 |
| `playbook` | | 玩法剧本 `{loop, input, progress, failure, beat, settlement, context}`；决定这一局"怎么玩"（详见 `docs/GAMEPLAY.md`）。缺省为自由推进 + 气血失败 |
| `questlines` | | 事业线数组（stage DAG + 谓词 + 奖励）。载入时校验环与幽灵 next；未满足 `visibility` 的线保持 dormant，不占面板 |
| `seed` | | 随机种子（可复现） |
| `state_path_hint` | | 默认状态文件名 |

## 已有设定（四套，全部可直接开玩）

| 文件 | 世界观 | 等级阶梯 | 货币 | 世界书 | 适合看什么 |
|---|---|---|---|---|---|
| `玄枢界.setting.json` | 东方玄幻 | 十阶（淬体→登枢） | 玄晶 | 21 条 | 完整的长线范式：入学试炼 / 秘境名额 / 拍卖暗斗 / 追杀赌斗 / 渡厄突破 / 墟界长线 |
| `折剑行.setting.json` | 武侠 | 七阶（不入流→大宗师） | 银两 | 10 条 | 克制的冷叙事：断剑主线、当铺经济、三方立场 |
| `霓虹深渊.setting.json` | 赛博朋克 | 七级（F级→S级） | 信用点 | 9 条 | 义体与记忆题材、阶级隐喻、AI 角色 ECHO |
| `雾港.setting.json` | 调查悬疑 | 六阶（外行→传奇） | 法币 | 9 条 | 线索链与理智消耗、克苏鲁式"越查越冷" |

四套共用同一套规则内核：战斗、交易、社交、因果、势力演化、长局记忆全部一致，
差别在**叙事词汇、等级阶梯、经济规模、玩法循环（playbook）与事业线结构**：

| 设定包 | 玩法循环 | 进度轴 | 失败条件 |
|---|---|---|---|
| 玄枢界 | 自由推进（freeform） | 修行阶 0–10 | 重伤退场（hp） |
| 折剑行 | 声明→判定→后果（ttrpg） | 身手 0–7 | 债主上门（clock 12） |
| 霓虹深渊 | 地点与命令（mud） | 评级 0–7 | 被盯上（clock 10） |
| 雾港 | 选项推进（choice） | 线索 0–24 | 理智（sanity） |
`scripts/verify_settings.py` 会逐包断言载入完整、术语无泄漏、连跑 15 回合后世界仍在演化。

每个包都配了 `places`（地点描写）与 `ui`（皮肤 + 品牌），载入后 `open_panel` 就能看到
该世界自己的名字、标语与视觉风格。

## 版权与原创性

框架层——长阶梯修炼体系、资源与品阶、势力交错、事件推进节奏——属于类型文学的**公共范式**，可以自由借鉴；
本仓的示例设定里，人物、势力、地名、物名**全部原创**，没有复用任何已有作品的名词。
往这里加新设定时请守住同一条线：**借结构，不搬名字**。
