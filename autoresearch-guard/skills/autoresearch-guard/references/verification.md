# 验证契约参考

`arx verify lock --file FILE` 只接受 JSON：

```json
{
  "claim": "明确、可检查的结论",
  "checks": [
    {
      "id": "stable-id",
      "criterion": "通过条件",
      "method": "检查方式",
      "evidence_required": "所需证据"
    }
  ]
}
```

顶层和每条 check 都不能有额外字段。字符串不能为空，`checks` 不能为空，ID 不能重复。

锁定后，CLI 会把契约写入 `.research/current/verifications/vNNN.json`，并保存内容摘要。`--revise` 创建下一个版本，旧版本继续留在目录中，但旧记录不会支撑新版本。

结果按追加顺序保存。每条记录绑定 check ID 和当前契约摘要；内容完全相同的记录不会重复写入。某条 check 的最新记录决定它现在的 verdict。

```bash
arx verify record --check stable-id --verdict pass \
  --evidence reports/check.txt https://example.test/source \
  --reason "报告和来源都满足契约要求"
```

`pass` 需要至少一条非空 evidence。三个 verdict 都需要非空 reason。CLI 不验证 URL、文件是否真实存在，也不判断领域语义。

`verified` 需要当前版本每个 check 的最新 verdict 都是 `pass`。其他 outcome 不读取验证门禁，只要求非空 summary。
