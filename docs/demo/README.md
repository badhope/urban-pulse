# 演示存档（docs/demo）

本目录的 `.save.json` 是 `scripts/make_demo.py` 生成的**真实对局存档**：
设定包载入引擎后按确定性玩家脚本真跑 N 回合，包含真实的世界演化、
因果台账、大事记、章节摘要与叙事正文。README 里的截图与视频都基于这些存档。

| 世界 | 存档 | 回合 | 主角 | 等级 | 所在地 | 势力 | 相位 | 文件大小 |
|---|---|---|---|---|---|---|---|---|
| 折剑行 | `折剑行.save.json` | 180 | 顾青 | 绝顶 | 洛水渡 | 5 | Ω | 51 KB |
| 玄枢界 | `玄枢界.save.json` | 500 | 沈砚 | 玄婴 | 临川城 | 8 | K | 72 KB |
| 雾港 | `雾港.save.json` | 180 | 陆离 | 专家 | 永昌号 | 5 | r | 50 KB |
| 霓虹深渊 | `霓虹深渊.save.json` | 180 | 林夏 | B级 | 第9区 | 4 | r | 49 KB |

重新生成：

```bash
python scripts/make_demo.py
python scripts/audit_ui.py --state docs/demo/<世界>.save.json   # 截图
```

同一 seed 生成同一份存档（逐字节一致），因此截图与存档可以互相对照。
