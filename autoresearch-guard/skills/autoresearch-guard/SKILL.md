---
name: autoresearch-guard
description: 当 Codex 需要把研究项目作为有证据、有预算、可恢复的 Goal 循环运行时使用。覆盖 prior art、假设、锁定协议、session owner、实验台账、确定性审计、死胡同信号、AI 证据审查、决策门禁、经验总结和归档。触发条件：用户请求 AutoResearch Guard、受约束的研究迭代、死胡同检测、pivot/refine 循环、研究证据审计，或为 Codex Goal 模式生成受控研究任务。
---

# AutoResearch Guard

## 它负责什么

```text
Lessons -> Literature -> Hypothesis -> Protocol -> Goal -> Evidence -> Audit -> Review -> Decision -> Closure
```

Codex 负责研究判断。脚本负责确定性事实：状态能否迁移、协议是否漂移、证据是否属于本轮、门禁是否通过、audit 是否陈旧、预算是否触发，以及当前轮能否归档。

不要把 Stop hook 当成循环引擎。Codex Goal 模式负责跨 turn 继续执行，`.research` 保存外层 campaign 状态，Stop 只做一次有界纠偏。完整边界见 `references/loop_contract.md`。

## 先调查，再写实验代码

每个新方法都要先调查 prior art：

- 用 Semantic Scholar MCP 查论文、引用和相关工作。
- 需要 arXiv 原文时用 arXiv MCP。
- 用 Web 搜索现有实现和仓库。
- 优先复用；必须重写时，在 `hypothesis.yaml.reuse_plan.build_new_reason` 写清原因。

`arx_compile_goal.py` 会检查：

- `hypothesis.yaml.evidence_basis` 能回指 `literature_review.md` 中的 `idea_id`。
- `reuse_plan.base` 能回指现有实现表中的 `impl_id` 或 `url`；也可以是带理由的 `build_new`。

详见 `references/prior_art.md`。

## 固定流程

1. 阅读 `.research/lessons/`，吸收上一轮保留的经验和反模式。
2. 调查论文与现有实现，填写 `literature_review.md`。
3. 填写 `hypothesis.yaml`，包括 `evidence_basis` 和 `reuse_plan`。
4. 填写 `protocol.lock.yaml` 的划分、指标、门禁、baseline 和 `loop_budget`。人工确认后设 `locked: true`。
5. 运行 `arx_compile_goal.py`。未锁协议配合 `--allow-unlocked` 只能生成 `active_goal.draft.md`；正式编译才会进入 `execution/armed`。
6. 运行 `arx_loop.py start`，再把 `active_goal.md` 交给 Codex Goal 模式。启用 hooks 时，首次 loop 或实验命令会绑定当前 Codex session。
7. 一次只做一个有界实验。优先复用 `reuse_plan.base` 指定的实现，不得越过 allowed/forbidden work、划分和 blocked actions。
8. 每次有意义实验后运行 `arx_record.py`。给重试复用稳定的 `--attempt-id`；baseline 使用 `--role baseline`；失败使用 `--status fail|error` 和结构化 `--failure-tag`。记录会绑定 canonical iteration、protocol digest 和 state revision。
9. 运行 `arx_audit.py`。它会过滤失败、foreign iteration 和错误协议证据，并生成 `audit_report.yaml`，随后进入 review。
10. 填写 `ai_evidence_review.md` 的「结论与证据」表。解释科学结果和失败原因；有 spiral 信号时写「死胡同评估」。
11. 再运行一次 `arx_audit.py`，让报告绑定最新 review 和 ledger。然后填写 `decision.proposed.yaml`，或用 `arx_decide.py` 的命令行参数提交。
12. 运行 `arx_decide.py`。脚本要求最新 audit、已完成的 claim 表和合法 proposal。critical spiral 下的 `proceed` 需要先在 review 阶段 `pause`，再运行 `resume --human-approved`；批准会绑定当前 audit digest。
13. 处理 closure：失败时更新 `lessons/anti_patterns.yaml`；继续型决策还要填写 `next_goal.md`。`arx_loop.py check --require-ready` 通过后再运行 `arx_archive.py`，或用下一次 `arx_init.py --archive-existing` 完成归档并初始化新轮。

如果 review 后要补实验，先显式执行：

```bash
python scripts/arx_loop.py resume \
  --research-root .research \
  --reason "补充缺失证据" \
  --reopen-execution
```

不要在 review 或 closure 阶段直接追加 evidence。

## 硬性边界

脚本与 hooks 可以：

- 初始化和迁移状态；
- 校验 prior art、reuse、协议摘要、iteration id 和 attempt id；
- 串行化写入并原子替换单个状态文件；
- 检查划分污染、blocked actions、baseline、validation gates 和 claim support；
- 计算预算与 `spiral_risk` 信号；
- 把 audit/decision digest 固定到 canonical state，拒绝修改后的报告、非法 decision 和未闭环 archive；
- 为 owner session 提供恢复上下文和一次 Stop 纠偏。

脚本与 hooks 不能：

- 发明研究方向或解释科学失败；
- 判断某个假设是否真的死亡；
- 自动选择 pivot、refine、promote 或 stop；
- 把 tool exit 0 当成实验成功；
- 依靠 hook 正则提供安全隔离；
- 在没有人工 checkpoint 的情况下越过 critical spiral gate。

## 状态和停止规则

阶段固定为 `draft -> execution -> review -> closure -> archived`。控制状态与 `decision.yaml` 分开。

每次准备结束前运行：

```bash
python scripts/arx_loop.py check --research-root .research --json
```

- `achieved`：闭环完成，可以归档。
- `incomplete`：还有确定性缺项；Goal 可以在预算内继续。
- `blocked_requires_human`：显式暂停，等待人工。
- `budget_exhausted`：attempt、turn 或 wall-clock 等硬预算耗尽。
- `no_progress`：连续失败、指标平线或连续无进展触发熔断。
- `aborted`：用户或上层控制器终止。

只有 `achieved` 算成功。其余结果都要保留原因、预算和下一条可执行动作，然后停止或等待人工。

## 脚本

| 脚本 | 用途 |
|---|---|
| `arx_init.py` | 初始化新 iteration；安全归档 ready 状态；用 recovery archive 处理缺失或损坏 state 的 `--force`。 |
| `arx_compile_goal.py` | 校验 prior art / reuse；生成草稿或正式 `active_goal.md`；正式编译进入 execution。 |
| `arx_loop.py` | `check/start/pause/resume/abort`，输出统一 readiness 和预算。 |
| `arx_record.py` | 用稳定 attempt id 幂等追加 evidence；检查 iteration、phase 和 protocol digest。 |
| `arx_audit.py` | 在 root lock 内审计同一快照的证据、baseline、门禁、claim support、协议违规和 spiral 信号。 |
| `arx_decide.py` | 检查 state 锚定的 fresh audit、完整 review、forbidden decision 和 critical escape gate，再提交并锚定 decision。 |
| `arx_status.py` | 输出状态、owner、预算和人类 review packet。 |
| `arx_archive.py` | 用统一 readiness 归档当前轮；未完成恢复归档必须写理由。 |
| `arx_lifecycle.py` | 内部深模块；脚本和 hooks 共用状态、readiness、预算、digest、锁和归档逻辑。 |

## Hooks

Hooks 默认关闭。用 `arx_init.py --enable-hooks` 为当前 `.research` 打开；Codex 侧还需要 trust hook 配置。

- `session_recovery.py`：SessionStart 时读取状态，告诉 Codex 当前 phase、owner 关系和下一步。
- `pre_tool_command_gate.py`：提前拦截禁用划分、blocked action、锁定协议修改和非 owner 实验。
- `post_tool_capture.py`：实验类 Bash 命令后提醒写 evidence；不自动记录结果。
- `stop_goal_guard.py`：只对 owner session 处理 closure。最多 block 一次；重入、非 owner、后台任务和等待人工直接放行；熔断时 `continue: false`。

Hooks 可能未启用、未 trust、超时或漏掉执行路径。决定和归档脚本必须独立 fail closed。

## 参考

- `references/loop_contract.md`：三层 loop、真实状态机、owner、预算、Stop、digest、原子写和已知限制。
- `references/workflow.md`：目录、文件职责、closure 分支、恢复命令和 MCP 配置。
- `references/prior_art.md`：论文与现有实现调查方法。
- `references/goal_rules.md`：Goal 编译输入和 draft/formal 规则。
- `references/spiral_detection.md`：连续失败、平线、无信号与 blocked action 的确定性算法。
- `references/failure_taxonomy.md`：AI 证据审查使用的失败标签。
- `references/claim_levels.md`：claim 等级和 promote 门禁。
