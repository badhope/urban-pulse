## 改了什么

<!-- 一到三句话。 -->

## 为什么

<!-- 问题是什么？不修会怎样？ -->

## 验证

- [ ] `bash scripts/pre_push_gate.sh` 全绿
- [ ] 新增/修改的逻辑有对应断言，并且能被 `verify_mutation.py` 的变异杀死
- [ ] 影响 `ARCHITECTURE.md` 的改动已同步更新该文档
- [ ] 没有提交 `*.bak` / `*.inbox.jsonl` / 运行时 `*.log.jsonl` / 密钥

## 不变量自查

- [ ] 确定性：同状态 + 同行动 → 同结果（未引入不受控随机/时间依赖）
- [ ] 面板只读：`panel.*` 不写状态文件
- [ ] 零依赖：未新增第三方运行时依赖（MCP 除外）

<details>
<summary>命令输出（可选）</summary>

```
粘贴门禁或相关自检的尾部输出
```

</details>
