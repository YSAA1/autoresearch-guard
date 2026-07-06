# 论断等级

使用证据所能支持的最弱论断。等级定义供 AI 在 `ai_evidence_review.md` 与人工审查中使用。

## 等级

- `exploratory`：仅 smoke 结果或早期验证信号。
- `validation`：已锁定的验证协议，且有记录证据并通过审计。
- `test`：验证成功后、经人工批准的 test 划分评估。

`paper` / `production` 等级不在 AI 研究循环自主可达范围，已从本表中移除。

## Promotion 规则

- 若 `audit_report.yaml` 列出 `test_contamination: true`，不得从 validation 提升到 test 级论断。
- 若 validation 门禁缺失或失败，必须禁止 `promote`。
- 若证据不完整，论断至多保持 exploratory。
- 若 `ai_evidence_review.md` 的「结论与证据」表含 `unsupported`、`prohibited`、缺证据的 supported claim，或 claim 等级超过 `claim_boundary.yaml.max_claim_level`，必须禁止 `promote`。
- 若 `audit_report.yaml.spiral_risk.level == critical`，禁止 `promote`。

## 脚本强制范围

`arx_audit` 通过 `forbidden_decisions` 禁止非法 `promote`（含 claim support 与 spiral critical 触发的禁令）。`claim_boundary.yaml` 编入 `active_goal.md` 供 AI 遵守；`arx_audit` 只解析 `ai_evidence_review.md` 的结构化 claim 表，不判断自然语言论断是否科学正确。越界论断的科学语义仍由 AI 与人工在 review 阶段负责。
