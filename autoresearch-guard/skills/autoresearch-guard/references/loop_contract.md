# AutoResearch Guard 循环契约

本文记录当前实现真正提供的保证。它用于约束状态机、hooks、审计和归档，也明确哪些能力尚未实现。

## 适用范围

插件只支持 Codex。宿主字段和输出格式以 Codex 官方的 [Hooks](https://learn.chatgpt.com/docs/hooks) 与 [Build plugins](https://learn.chatgpt.com/docs/build-plugins) 为准。

Claude 的 [Getting started with loops](https://claude.com/blog/getting-started-with-loops)、[Keep Claude working toward a goal](https://code.claude.com/docs/en/goal) 和 [Hooks reference](https://code.claude.com/docs/en/hooks) 是设计参考，不是兼容性承诺。Claude 和 Codex 字段相似时也不能直接假设语义相同。

## 三层循环

| 层 | 谁负责 | 持久状态 | AutoResearch Guard 的边界 |
|---|---|---|---|
| Agent turn | Codex 宿主 | 会话上下文 | 插件不重写模型与工具循环。 |
| Native Goal | Codex Goal 模式 | 宿主 Goal 状态 | 负责跨 turn 续跑 `active_goal.md`，不提交研究决策。 |
| Research campaign | 本插件和用户 | `.research` | 负责 iteration、协议、evidence、预算、审计、decision、lessons 和归档。 |

一次 tool call 不是一个研究 attempt，一次 turn 结束也不等于 iteration 完成。Goal 模式可以被关闭或中断，`.research` 仍应足以解释当前研究走到哪一步。

Anthropic 的 [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) 建议用结构化进度和小步工作跨上下文恢复。本插件采用这条工程原则，但状态格式和运行协议由自己定义。

## Codex hook adapter

`hooks/hook_runtime.py` 统一处理 Codex hook stdin：

- 读取 `session_id`、`turn_id`、`tool_use_id`、`tool_name`、`cwd` 和 `stop_hook_active`。
- 从 Bash 的 `command`，以及 apply_patch/Edit/Write 的路径、patch、replacement 或 content 字段构造检查文本。
- 把领域结果转换成 Codex 支持的 `permissionDecision: deny`、`decision: block`、`additionalContext` 或 `continue: false`。
- 使用插件安装副本中的 `${PLUGIN_ROOT}`，不依赖源码 checkout 路径。

Hook adapter 不解释科研结果，不推进审计或 decision，也不在回调中运行长任务。

## Canonical state

`.research/current/state.yaml` 是当前 iteration 的控制状态。版本 2 包含：

- `iteration_id`：本轮稳定 id。
- `phase`：`draft`、`execution`、`review`、`closure` 或 `archived`。
- `revision`：领域迁移时递增。
- `created_at`、`updated_at`、`compiled_at`。
- `protocol_digest`：正式编译时锁定的协议摘要。
- `audit_digest`、`decision_digest`：最近一次正式 audit/decision 文件的 canonical 锚点。
- `hooks_enabled` 和 `human_gate_required`。
- `loop.status`、`owner_session_id`、`started_at`、暂停原因和人工批准时间。
- turn、Stop continuation、连续无进展、最近 turn、progress digest、hook tool id 去重和 loop budget。
- 人工批准时间及其绑定的 audit digest。

阶段固定为：

```text
draft -> execution -> review -> closure -> archived
```

循环状态为：

| 状态 | 含义 |
|---|---|
| `idle` | 仍在准备草稿。 |
| `armed` | 正式 goal 已编译，等待执行或重新认领 owner。 |
| `running` | owner session 正在 execution。 |
| `closing` | audit/review/decision/closure 正在收口。 |
| `waiting_human` | 人工暂停或预算熔断，自动续跑停止。 |
| `aborted` | 用户或恢复流程终止当前轮。 |
| `complete` | 已满足正常归档，归档中的 state 使用该状态。 |

`decision.yaml` 中的科研决策和上表不是一回事。`refine` 不等于 `running`，`promote` 也不会自动归档。

生产脚本共用 `arx_lifecycle.py` 的 phase 检查和迁移。典型顺序是：

```text
init
  -> locked compile
  -> loop start / session claim
  -> record attempts
  -> audit
  -> AI review
  -> re-audit
  -> decision
  -> readiness check
  -> archive
```

未锁协议不能进入 execution。review 后要补 evidence，必须运行 `arx_loop.py resume --reopen-execution`。decision 后 evidence 已冻结。

## Owner session

Owner 用来防止 Codex 的无关会话被研究 hook 困住。

- `arx_loop.py start --session-id` 可以显式认领。
- 启用 hooks 时，首次实验类 Bash 命令或 loop start 命令可通过 Pre/Post hook 认领空 owner。
- 已有 owner 时，另一个 session 的实验类 Bash 命令会被 Pre hook 拒绝。
- 非 owner 的 Stop 直接放行。
- pause、abort 和预算熔断会释放 owner。

Owner 不是权限边界。直接从 hooks 之外运行 Python 脚本时，脚本拿不到 Codex session id，因此不能验证调用者身份。防止伪闭环的最终手段是 phase、协议 digest、attempt id、audit digest、readiness 和文件锁，不是 session 字符串。

## Readiness

`arx_lifecycle.evaluate_readiness()` 是 `arx_loop check`、`arx_status`、Stop 和正常 archive 共用的 closure 判定。

输出拆分：

| 字段 | 含义 |
|---|---|
| `process_ready` | 流程产物、digest、decision、research gates、promote 时的 subagent 门禁齐备 |
| `outcome_ready` | `outcome.yaml` 检查 + success_criteria 可检陈述通过 |
| `goal_ready` / `ready` | 两者同时为真；只有这时 outcome 才是 `achieved` |

`process_ready` 但 `outcome_ready=false` 必须视为 incomplete，不得结束 Goal。

正常归档需要同时满足：

1. phase 是 `closure`。
2. 当前 iteration 至少有一条 evidence。
3. `audit_report.yaml`、`ai_evidence_review.md` 和 `decision.yaml` 有意义且不含初始化占位。
4. `protocol.lock.yaml` 仍是 locked，摘要与 compile 时一致。
5. audit 保存的输入 digests 与当前研究输入一致（protocol、hypothesis、blocked actions、claim boundary、research brief/claims/gaps/sources/conflicts/adversary、ledger、AI review）；audit 文件 digest 与 state 锚点一致。
6. research gates 通过：brief 非空、≥1 可证伪 claim、gap 覆盖、关键 critical gap ≥2 种 `source_type`、冲突已处理、对抗表完整。
7. 若 review 含 `verified` 论断，audit 的 `verified_claim_status` 必须为 pass（证据路径可解析 + 对抗 survived + claim 绑定）。
8. decision 的 `audit_digest`、`input_digests`、forbidden decision 与 critical gate 仍合法；decision 文件 digest 与 state 锚点一致。
9. 有失败 evidence 时，`lessons/anti_patterns.yaml` 有当前 iteration 的条目。
10. decision 为 `proceed`、`refine` 或 `pivot` 时，`next_goal.md` 已填写。
11. 若 decision 为 `promote`：`subagent_review.yaml` 必须 `verdict=pass` 且 `bound_audit_digest` 等于当前 audit（主 agent 自填 review 不能替代）。`verified` 只走 audit 格式门禁，不强制 subagent。

插件是 campaign 控制面，不是「自由探索 + 可选自报 verify」。Hook 只是快速 adapter，不是安全边界。

### Promote 审查包

- `prepare-review` 打包证据到 `review_pack/`（禁止塞 transcript）；仅 `promote` 强制同会话 subagent 验收。
- SessionStart 只注入恢复上下文（phase/status/next action），不做 smoke/queue 仪式。

readiness 输出：

| Outcome | 是否成功 | 自动续跑 |
|---|---:|---:|
| `achieved` | 是 | 否；可以归档。 |
| `incomplete` | 否 | 可以，但仍受预算和 Stop 一次纠偏限制。 |
| `blocked_requires_human` | 否 | 否。 |
| `budget_exhausted` | 否 | 否。 |
| `no_progress` | 否 | 否。 |
| `aborted` | 否 | 否。 |

每份报告还带 phase、status、owner、state digest、缺项、stale 输入、下一步和预算快照。文件存在不等于文件有效。

`arx_decide.py` 在提交前检查 fresh audit、state 中的 audit digest、完整 claim 表和 decision policy；它不会因为旧报告仍在磁盘上就接受 decision。Readiness 会再次执行同一 decision policy，因此修改已提交的 decision 不能绕过 archive。

## 持久预算和无进展

正式编译把 `protocol.lock.yaml.loop_budget` 写入 state。当前字段是：

| 字段 | 默认值 | 计算方式 |
|---|---:|---|
| `max_turns` | 20 | owner 的新 Stop turn 数。 |
| `max_attempts` | 12 | 当前 iteration 的非 baseline evidence 数。 |
| `max_consecutive_failures` | 3 | ledger 尾部连续失败的非 baseline attempt 数。 |
| `max_flatline_count` | 3 | validation gate（没有 gate 时用 expected metrics）的同一 metric/split 在尾部连续不变的最大长度。 |
| `max_no_progress_turns` | 2 | 相邻 Stop turn 的 progress digest 不变次数。 |
| `max_stop_continuations` | 1 | 当前 iteration 允许的 Stop 纠偏总数；只有正式 compile 新轮时重置，pause/resume 不补额度。 |
| `max_wall_time_minutes` | 240 | 从正式 compile/start 时间计算的墙钟时间。 |

兼容旧 `spiral_budget.max_failed_attempts` 和 `max_total_attempts`。所有值必须是正整数。

progress digest 来自当前研究产物摘要，不使用 mtime。只重复同一失败命令、改时间戳或重排文字，不会凭空形成新的 metric evidence。达到 attempt/turn/wall-clock 等硬上限时，outcome 为 `budget_exhausted`；只触发连续失败、平线或无进展类条件时，outcome 为 `no_progress`。`arx_loop.py check` 会在这两种 outcome 下把状态置为 `waiting_human` 并释放 owner，即使 hooks 已关闭也一样。

[Building Effective AI Agents](https://www.anthropic.com/engineering/building-effective-agents) 建议只在反馈清楚且能衡量改进时使用 evaluator-optimizer，并设置停止条件。这里的 ledger、metric 和预算就是对应的确定性反馈面。

## Stop contract

Stop hook 是一次纠偏，不是 loop runner。

它只有在以下条件同时成立时才返回 `decision: block`：

- hooks 已启用；
- 当前 status 是 `running` 或 `closing`；
- Stop 来自 owner session；
- readiness 尚未完成；
- 没有后台任务或 scheduled wakeup；
- budget 没有触发；
- `stop_hook_active` 为 false；
- Stop continuation 额度仍有剩余。

返回 block 后，Codex 可能用新的用户 prompt 续跑。重入时 `stop_hook_active: true`，hook 必须放行，不能再次 block。若之后的新 turn 再次 Stop，而 continuation 总额已经用完，hook 会转入 `waiting_human` 并返回 `continue: false`。非 owner、未绑定 owner、armed/idle、等待人工、aborted、complete 和后台任务会放行。

预算触发时，hook 把状态改为 `waiting_human`、释放 owner，并返回 `continue: false`。内部状态无法安全读取时也返回 `continue: false`，避免错误情况下继续盲跑。

Stop 不会写科研 decision、自动记录实验、归档或启动测试。

## Hooks 不是安全边界

Codex command hooks 需要用户 trust，匹配的 hooks 可能并发运行，且 hook 不能覆盖全部工具路径。因此：

- SessionStart 只补充恢复上下文。
- Stop 只做一次 closure 纠偏。
- audit、decision 和 archive 必须在没有 hook 帮助时仍能拒绝非法状态。
- 不提供 PreToolUse / PostToolUse；确定性拦截完全由脚本侧完成。

当前实现无法从项目状态判断 Codex UI 中某个 hook 是否已 trust，也不会把 sandbox 或权限策略替换成正则拦截。

`find_research_root` 从 cwd 向上查找 `.research/current`。若某层没有 campaign，但存在独立项目边界标记（`.git`、`package.json`、`pyproject.toml`、`.arx-boundary` 等），则停止上溯，避免 monorepo 子包继承祖先 campaign 的 hooks。可用 `arx_loop.py hooks --on|--off` 切换当前 `.research` 的 `hooks_enabled`。

## Digest 链

Audit 保存输入摘要：

```text
protocol + hypothesis + blocked_actions + claim_boundary + research.yaml + ledger + AI review
                               |
                               v
                         audit_report.yaml
                               |
                         audit_digest
                               v
                          decision.yaml
                               |
                               v
                       archive_manifest.yaml
```

任一 audit 输入变化都会让旧 audit stale。Audit 文件本身的 digest 写入 state，防止报告被改后继续使用。Decision 保存 audit digest 和 audit 输入 digests，decision 文件 digest 也写入 state。Archive 重新检查 policy，并保存 readiness、当前产物 snapshot digests、audit digest、decision digest 和 outcome。

当前 audit snapshot 不包含 conversation、Codex Goal 内部计数或文献全文。`literature_review.md` 通过 compile 时的 idea/reuse 绑定参与前置门禁，但不属于 post-execution audit digest；正式执行后不应原地改写 prior art 或假设边界。

## Attempt id、锁和写入

`arx_record.py` 把 canonical iteration、protocol digest、state revision 和实验字段一起计算成 `record_digest`。调用者可以提供稳定的 `--attempt-id`；未提供时使用语义摘要派生 id。

- 同 id、同 digest：返回已有记录，不重复追加。
- 同 id、不同 digest：拒绝冲突。
- iteration 不匹配、phase 不在 execution、协议摘要漂移或 attempt 预算耗尽：拒绝写入。
- baseline 不占 experiment attempt 预算，但仍进入审计。

所有 canonical state、ledger、event 和 archive 操作使用 `.research/.arx.lock` 做进程间互斥。Audit 在一把锁内完成 ledger 读取、门禁计算、输入 digest、报告写入和 phase 迁移，避免晚到 evidence 被摘要覆盖却没被分析。Compile、record 和 decide 也会在提交点重查状态。单文件重写使用同目录临时文件、flush、fsync 和原子 replace；JSONL append 在锁内 flush 和 fsync。锁在同一线程内可重入。

当前锁文件不保存持有者元数据，也没有跨机器租约。它适用于同一文件系统上的本地 Codex 工作流。

## 归档和恢复

正常 archive 在锁内重新计算 readiness，更新归档状态，写 `archive_manifest.yaml`，再把 current 移到带时间戳和随机后缀的唯一目录。`arx_init.py --archive-existing` 复用同一入口，不会绕过 closure。

`arx_init.py --force --force-reason ...` 是恢复入口。它先把未完成 current 保存为 recovery archive，再创建干净的新轮；它不会静默覆盖旧文件。`state.yaml` 缺失或损坏时，raw recovery manifest 会记录解析错误和原始文件 digests。

当前实现保证每次归档使用唯一目标；目录移动在进程内报错时会恢复原 closure state，未完成 archive 仍可重试。它还没有多文件 transaction journal、自动 reconcile、强杀故障注入恢复或跨文件系统原子 rollover。进程若在 manifest 写入和目录移动之间被强杀，需要人工查看 current、archive、state 和 events，再用带理由的 recovery archive 处理。

## 可观测性

`events.jsonl` 记录状态迁移、session claim、evidence、hook deny/reminder/Stop 和熔断事件。每条事件带 event id、时间、iteration、revision 和细节。它不会记录完整 prompt、密钥或论文全文。

`arx_loop.py check --json` 是控制流的主要诊断入口。`arx_status.py --json` 额外汇总协议、证据、audit 和 decision；`--review` 生成人类门禁摘要。

## 已验证的场景

集成测试覆盖：

- draft compile 不能启动 execution；
- state/hypothesis identity split、非法 phase、foreign iteration、decision 后 evidence、修改后的 audit/decision 和 stale 输入被拒绝；
- 失败 evidence 不能通过 validation gate；
- attempt id 幂等、并发 JSONL 写入，以及 audit/record 的快照互斥；
- owner Stop、非 owner Stop、Stop 重入、continuation 总额和后台任务；
- hooks 关闭时的连续失败终态、声明 metric 的平线和无进展预算熔断；
- Bash、apply_patch、Edit 对锁定协议的修改，同时允许只读 `sed -n`；
- `--archive-existing`、缺失 state 的 `--force` recovery archive，以及 move 失败后的 closure 恢复；
- v1 compiled state、无 PyYAML fallback、SessionStart 和含空格/中文的插件安装副本。

尚未在真实 Windows Codex 宿主上执行 hooks，也没有故障注入测试多文件归档中断。Windows hook command 目前只做 manifest 结构和常规回归检查。

## 调研资料

- [Claude：Getting started with loops](https://claude.com/blog/getting-started-with-loops)
- [Claude Code：Keep Claude working toward a goal](https://code.claude.com/docs/en/goal)
- [Claude Code：Hooks reference](https://code.claude.com/docs/en/hooks)
- [Anthropic：Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- [Anthropic：Building Effective AI Agents](https://www.anthropic.com/engineering/building-effective-agents)
- [Anthropic：Scaling Managed Agents](https://www.anthropic.com/engineering/managed-agents)
- [OpenAI Codex：Hooks](https://learn.chatgpt.com/docs/hooks)
- [OpenAI Codex：Build plugins](https://learn.chatgpt.com/docs/build-plugins)
- [ClaudeFast：Claude Code Loops](https://claudefa.st/blog/guide/mechanics/claude-code-loops)
- [Simon Willison：Designing agentic loops](https://simonwillison.net/2025/Sep/30/designing-agentic-loops/)
