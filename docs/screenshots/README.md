# 界面截图（docs/screenshots）

本目录是 README 预览用的实况主舞台截图与演示视频，**非设计稿**——全部由真实面板在浏览器
（Edge / Chromium 内核，Playwright 驱动）中现场渲染后截取，并由 `scripts/shots.py`
逐项断言后入库。

## 截图清单

| 文件 | 内容 | 视口 |
|---|---|---|
| `stage-xuanshu.png` | 玄枢界（墨金）主舞台，第 500 回合真实存档 | 1500×950 |
| `stage-ink.png` | 折剑行（水墨）——同一引擎，武侠术语与品牌 | 1500×950 |
| `stage-neon.png` | 霓虹深渊（霓虹）——赛博朋克术语与品牌 | 1500×950 |
| `stage-neutral.png` | 雾港（石墨）——调查悬疑术语与品牌 | 1500×950 |
| `stage-768.png` | 768px 平板视口 | 768×900 |
| `stage-320.png` | 320px 窄屏，无横向滚动 | 320×800 |
| `drawer-codex.png` | 探索图鉴抽屉 | 1500×950 |
| `drawer-market.png` | 市场行情抽屉 | 1500×950 |
| `drawer-milestones.png` | 大事记抽屉 | 1500×950 |
| `drawer-world.png` | 势力与风向抽屉（世界脉搏） | 1500×950 |
| `help.png` | 帮助弹窗（术语表 / 数据路径 / 皮肤说明） | 1500×950 |
| `command-palette.png` | 命令面板（Ctrl/⌘+K） | 1500×950 |
| `character-card.png` | 在场角色卡详情（卡面文字） | 1500×950 |
| `action-queue.png` | 行动队列（浏览器排队 → 宿主结算） | 1500×950 |
| `share-mode.png` | 分享模式（隐藏操作区与路径，适合截图/直播） | 1500×950 |
| `first-visit.png` | 首次访问引导条（localStorage 记忆） | 1500×950 |
| `walkthrough.mp4` | 16 秒真实交互录屏（点击、展开、命令面板、排队） | 1280×800 |

## 截图用存档

- 均来自 `docs/demo/*.save.json`——由 `scripts/make_demo.py` 用设定包真跑出来，
  含真实的世界演化、因果台账、大事记、章节摘要与叙事正文。
- 玄枢界为 500 回合（沈砚 / 玄婴 / 临川城，8 势力，Phase K）；
  其余三套为 180 回合。详细参数见 [`docs/demo/README.md`](../demo/README.md)。

## 截图前逐项断言（`scripts/shots.py`）

每个世界都会检查：页签与品牌、`data-skin` 与设定包一致、回合号与主角名渲染、
世界脉搏卡片可见、图表 canvas 已绘制、四个抽屉可展开且滚入视口、帮助弹窗、
命令面板、时间线搜索、角色卡详情、行动排队成功且**状态文件字节不变**、
分享模式隐藏操作区、768/320 无横向溢出、零 JS 控制台错误、零失败网络请求。

全套 85 项断言，任一失败则不产出交付截图（脚本退出码 1）。

## 重新生成

```bash
python scripts/make_demo.py                      # 四套世界的演示存档 + 侧写
python scripts/shots.py                          # 断言 + 截图 + 录屏
python scripts/shots.py --only 玄枢界 --no-video  # 只重拍一套、不录视频
```

录屏依赖 `ffmpeg`（webm → mp4）。缺失时脚本会明确报告失败，而不是静默跳过。
