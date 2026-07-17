---
name: autoresearch-guard
description: 当 Codex 需要把研究项目作为有证据、有预算、可恢复的 Goal 循环运行时使用。覆盖 prior art、假设、锁定协议、实验台账、确定性审计、死胡同信号、AI 证据审查、决策门禁、经验总结和归档。触发条件：用户请求 AutoResearch Guard、受约束的研究迭代、死胡同检测、pivot/refine 循环、研究证据审计，或为 Codex Goal 模式生成受控研究任务。
---

# AutoResearch Guard

## 它负责什么

```text
Lessons -> Literature -> Hypothesis -> Protocol -> Goal
  -> Evidence -> Audit -> Review -> Decision -> Closure
```

Codex 负责研究判断。脚本负责确定性事实：状态能否迁移、协议是否漂移、证据是否属于本轮、`research.yaml` 门禁是否满足、`verified` 证据路径是否可解析、audit 是否陈旧、预算是否触发，以及当前轮能否归档。

不要把 Stop hook 当成循环引擎。Codex Goal 模式负责跨 turn 继续执行，`.research` 保存外层 campaign 状态，Stop 只做一次有界纠偏。完整边界见 `references/loop_contract.md`。

## 先选最简 loop（防过工程）

| 场景 | 选用 | 不要 |
|---|---|---|
| ≤1 次检索、无归档需求 | turn + 本地笔记 | 全量 campaign |
| 有可检成功条件、需要证据台账 | Goal + `.research` campaign | 靠对话记忆宣称完成 |
| 定时跟进外部源 | 人工或外部 cron | 本插件不做 time/proactive runner |

默认路径是 Goal + campaign。本插件不实现定时器，也不把 Stop 改成无限 runner。

## 研究语义产物

初始化后维护单一文件 `research.yaml`（问题、非目标、`claim_level_target`、成功标准、claims、gaps、sources、conflicts、adversary）。另有 `outcome.yaml` 做结果门禁。

论断等级见 `references/claim_levels.md`。`verified` 要求证据路径可解析且 adversary 为 `survived`；脚本不做科学真伪判断。`promote` 额外要求同会话 review subagent 写出绑定当前 audit 的 `subagent_review.yaml`（主 agent 自填 review 不能替代）。

## 先调查，再写实验代码

每个新方法都要先调查 prior art（Semantic Scholar / arXiv MCP + WebSearch）。优先复用；必须重写时在 `hypothesis.yaml.reuse_plan.build_new_reason` 写清原因。`arx_compile_goal.py` 会检查 `evidence_basis` 与 `reuse_plan.base` 能回指 `literature_review.md`。详见 `references/prior_art.md`。

## 固定流程

1. 阅读 `.research/lessons/`，吸收上一轮经验。
2. 填写 `research.yaml` 与 `outcome.yaml`。
3. 调查论文与现有实现，填写 `literature_review.md`。
4. 填写 `protocol.lock.yaml`（含 `loop_budget`），人工确认后设 `locked: true`；写 `hypothesis.yaml`。
5. 运行 `arx_compile_goal.py`。未锁协议配合 `--allow-unlocked` 只能生成草稿；正式编译进入 `execution/armed`。
6. `arx_loop.py start`，把 `active_goal.md` 交给 Codex Goal 模式。
7. 优先复用 `reuse_plan.base`，遵守 allowed/forbidden work 与 blocked actions。
8. 每次有意义实验后运行 `arx_record.py`（稳定 `--attempt-id`；baseline 用 `--role baseline`）。
9. 运行 `arx_audit.py`，填写 `ai_evidence_review.md`。若准备 `promote`：`arx_loop.py prepare-review` 后 spawn review subagent。
10. 再 audit，再 `arx_decide.py`。critical spiral 下的 `proceed` 需先 `pause`，再 `resume --human-approved`。
11. 失败时更新 `lessons/anti_patterns.yaml`；继续型决策填写 `next_goal.md`。`arx_loop.py check --require-ready` 通过后 `arx_archive.py`。

若 review 后要补实验：

```bash
python scripts/arx_loop.py resume --research-root .research --reason "补充缺失证据" --reopen-execution
```

## 硬性边界

脚本与 hooks 可以：初始化/迁移状态；校验 prior art、reuse、协议摘要、attempt id；校验 `research.yaml` 格式与计数门禁；校验 `verified` 证据可解析性；串行化写入；检查划分污染、blocked actions、baseline、validation gates、claim support；计算预算与 `spiral_risk`；锚定 audit/decision digest；为 owner session 提供恢复上下文和一次 Stop 纠偏。

脚本与 hooks 不能：发明研究方向、解释科学失败、判断假设是否死亡、自动选择 pivot/refine/promote、把 tool exit 0 当实验成功、靠 hook 正则提供安全隔离。

## 状态和停止规则

阶段固定为 `draft -> execution -> review -> closure -> archived`。

```bash
python scripts/arx_loop.py check --research-root .research --json
```

- `achieved`：可归档。
- `incomplete`：预算内可继续。
- `blocked_requires_human` / `budget_exhausted` / `no_progress` / `aborted`：停止或等待人工。

只有 `achieved` 算成功。

## 脚本

| 脚本 | 用途 |
| --- | --- |
| `arx_init.py` | 初始化 iteration；安全归档或 `--force` recovery |
| `arx_compile_goal.py` | 校验 prior art / reuse；草稿或正式 `active_goal.md` |
| `arx_loop.py` | `check/start/pause/resume/abort/hooks/prepare-review` |
| `arx_record.py` | 幂等追加 evidence |
| `arx_audit.py` | 确定性审计、research gates、spiral 信号 |
| `arx_decide.py` | 检查并提交 decision |
| `arx_status.py` | 状态与人类 review packet |
| `arx_archive.py` | readiness 归档 |
| `arx_lifecycle.py` | 内部深模块（状态、readiness、预算、digest、锁） |

## Hooks

Hooks 默认关闭。`arx_init.py --enable-hooks` 打开；`arx_loop.py hooks --on|--off` 切换。只保留：

- `session_recovery.py`（SessionStart）：注入恢复上下文
- `stop_goal_guard.py`（Stop）：owner session 一次 closure 纠偏

审计、决策、归档必须在 hooks 关闭时仍能 fail closed。

## 参考

- `references/loop_contract.md`：三层 loop、状态机、预算、Stop、digest
- `references/workflow.md`：目录、文件职责、closure、MCP
- `references/prior_art.md` / `goal_rules.md` / `spiral_detection.md` / `failure_taxonomy.md` / `claim_levels.md`
