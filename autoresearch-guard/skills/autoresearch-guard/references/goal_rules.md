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

- 正式编译只允许从 `draft` 阶段执行。
- `hypothesis.yaml.iteration_id` 必须与 `state.yaml.iteration_id` 完全一致；goal、ledger、audit、decision 和 manifest 都使用这个 canonical id。
- 除非 `protocol.lock.yaml` 中 `locked: true`，否则拒绝正式编译。
- 未锁协议配合 `--allow-unlocked` 只写 `active_goal.draft.md`，保持 `draft/idle`，不会写正式 goal、protocol digest 或启动预算。
- 锁定后的正式编译写 `active_goal.md`、`protocol_digest`、`compiled_at` 和 `loop_budget`，然后迁移到 `execution/armed`。
- 包含 allowed work、forbidden work、blocked actions、论断边界与必填 closure 产物。
- 包含外层循环约定：一次一个有界实验、稳定 attempt id、每次结束前运行 `arx_loop.py check --json`、只有 `achieved` 算完成。
- 编译器不得发明 allowed 或 forbidden work。缺失字段视为错误或空列表。
- 编译器不得生成科学解读。

正式编译后修改 `protocol.lock.yaml` 会让 `arx_record.py`、`arx_audit.py` 和 closure readiness 拒绝继续。不要原地改锁定协议；需要改变实验约束时，归档或显式结束当前轮，再初始化新的 iteration。

## 好的 Goal

告诉 Codex 做什么、不做什么、复用哪个现有实现、如何验证、需要产出哪些 closure 产物，以及什么时候应该受控停止。Goal 模式负责跨 turn 运行，不负责提交科学 decision 或绕过 `.research` 门禁。
