# 论断等级

使用证据所能支持的最弱论断。等级定义供 AI 在 `ai_evidence_review.md` 与人工审查中使用。

## 等级（由弱到强）

- `exploratory`：早期信号、单源或未完成对抗；可探索，不可当强结论。
- `supported`：多源覆盖、冲突已处理或显式降级、对抗未驳倒；可支撑 refine/proceed。
- `verified`：在 `supported` 之上，证据路径可解析（文件存在或 http(s) URL）、对抗 verdict=`survived`、research gates 全绿。脚本只做存在性/格式与绑定检查，不判断科学真伪。

兼容旧表：`validation` 视为 `supported`，`test` 视为 `verified`。

## Promotion / verified 规则

- 若 research gates 失败（缺 brief/claims/gaps、关键 gap 源类型不足、对抗表缺失等），禁止 `promote`，也禁止 review 表出现 `verified`。
- 若 `audit_report.yaml` 列出 `test_contamination: true`，或 validation 门禁缺失/失败，禁止 `promote`。
- 若证据不完整，论断至多保持 `exploratory`。
- 若 `ai_evidence_review.md` 的「结论与证据」表含 `unsupported`、`prohibited`、缺证据的 supported claim，或 claim 等级超过 `claim_boundary.yaml.max_claim_level`，禁止 `promote`。
- 若 `audit_report.yaml.spiral_risk.level == critical`，禁止 `promote`。
- 若存在 `unresolved` 冲突且目标等级 ≥ `supported`，research gate 失败。

## 脚本强制范围

`arx_audit` 通过 `forbidden_decisions` 与 `verified_claim_status` 禁止非法 `promote` / 伪 `verified`。`arx_research.evaluate_research_gates` 只计数与格式校验：多源类型、对抗表完整性、证据路径可解析性、claim id 绑定。越界论断的科学语义仍由 AI 与人工在 review 阶段负责。
