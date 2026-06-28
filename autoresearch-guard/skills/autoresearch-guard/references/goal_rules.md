# Goal 编译规则

`active_goal.md` 由 AI 编写的 YAML 与确定性状态生成。文件归属见 `workflow.md`。

## 必填输入

- `.research/current/literature_review.md`
- `.research/current/hypothesis.yaml`
- `.research/current/protocol.lock.yaml`
- `.research/current/blocked_actions.yaml`
- `.research/current/claim_boundary.yaml`

## hypothesis 必填字段

- `iteration_id`、`objective`、`hypothesis`
- `evidence_basis`：引用 `literature_review.md` 中的 candidate_idea id（非空）
- `reuse_plan.base`：复用的 repo url 或 `build_new`（非空）
- `reuse_plan.build_new_reason`：仅当 `base == build_new` 时必填（非空）

校验在 `arx_compile_goal.py`，确定性查字段，不评科学性。

## 规则

- 除非 `protocol.lock.yaml` 中 `locked: true`，否则拒绝编译；本地草稿可传 `--allow-unlocked`。
- 包含 allowed work、forbidden work、blocked actions、论断边界与必填 closure 产物。
- 写入 `state.yaml` 的 `protocol_digest`，供后续审计检测协议漂移。
- 编译器不得发明 allowed 或 forbidden work。缺失字段视为错误或空列表。
- 编译器不得生成科学解读。

## 好的 Goal

告诉 Codex 做什么、不做什么、复用哪个现有实现、需产出哪些 closure 产物，以及何时不允许停止。
