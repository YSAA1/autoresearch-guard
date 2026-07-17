# Loop Engineering 重构执行计划

## 目标

把 AutoResearch Guard 从“靠文件是否存在和 Stop hook 反复催促”的流程，改成一套可恢复、可审计、有硬预算的研究循环：Codex 原生 Goal 模式负责跨 turn 续跑，插件负责研究 campaign 的状态、证据、门禁、闭环和熔断。

## Active slice

先建立唯一的状态机与 readiness 判定，再让现有脚本和 hooks 全部通过这一层工作。当前实现阶段不增加第二套宿主协议。

## Non-goals

- 不把插件改成 Claude Code 插件；Claude 文档只作为 loop/hook 设计先例。
- 不实现新的 Web UI、独立服务或常驻 daemon。
- 不让脚本判断科学真伪、自动选择研究方向或替代人工 checkpoint。
- 不把 Stop hook 当成完整的 loop runner 或安全边界。
- 不在本轮实现宿主未提供的 token/cost 精确计量；先用持久 turn、attempt、无进展和 wall-clock 预算。

## 成功标准

1. `.research/current/state.yaml` 明确记录 canonical iteration、revision、phase、loop status、owner session 和预算；非法逆序调用会被拒绝。
2. 未锁协议不能进入正式 execution；失败、错误、其他 iteration 的 evidence 不能支撑 validation gate 或 promote。
3. audit 绑定最新 protocol、hypothesis、ledger、review 与 policy digest；decision、Stop 和 archive 都拒绝陈旧 snapshot。
4. decision 后 evidence 冻结；继续型 decision 必须带有效 `next_goal.md` 才能归档并进入下一轮。
5. Stop 仅作用于 owner session；`stop_hook_active=true` 时绝不再次 block；预算耗尽、无进展、等待人工、后台任务和异常均走明确的非循环终态。
6. hook 输入统一解析，Pre/Post/Stop 的 fail policy、幂等键和可观测字段明确；hook 只做快速 adapter。
7. 状态写入采用同目录临时文件、fsync、原子 replace；ledger 追加有跨进程锁与 attempt id 幂等。
8. 安全归档与 `--archive-existing` 共用同一 closure 判定和 manifest，不再静默搬走未完成状态或残留旧文件。
9. README、Skill 和工作流文档与真实命令一致；README smoke flow 可执行。
10. 新旧回归测试、Skill validator、Plugin validator 全部通过，并有独立 reviewer 检查稳定 diff。

## Verification path

Verification path status: `runnable`

- `ARX_TEST_TMP=/tmp python -m unittest discover -s autoresearch-guard/tests -v`
- `python /home/ssy/.codex/skills/.system/skill-creator/scripts/quick_validate.py autoresearch-guard/skills/autoresearch-guard`
- `python /home/ssy/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py autoresearch-guard`
- 用真实 Codex hook stdin JSON 手工检查 PreToolUse、PostToolUse、SessionStart、Stop 的 stdout/exit code。
- 将插件复制到含空格和中文的临时“安装副本”目录，从副本执行 hook 命令，确认不依赖源码路径；本轮不改用户的全局插件缓存。

## Required capabilities

- Python 标准库、现有可选 PyYAML/Jinja2。
- Codex plugin hooks、Goal 模式和插件级 MCP；不新增依赖。
- Git 分支/worktree、独立 subagent review 和本地插件 validator。

## Fallback evidence

真实跨平台 CI 当前不可用。Windows 的 `commandWindows` 保留并做结构检查；Linux 上用含空格和中文的安装路径执行相同脚本作为路径回归。最终报告会明确未在 Windows 宿主实际运行。

## Final integration claim

从初始化到 locked compile、session 认领、实验记录、两阶段 audit/review、decision、closure、archive/rollover 的完整路径可执行；任一 stale snapshot、预算熔断、Stop 重入或非法阶段调用都不能伪装成成功闭环，也不会靠 hook 无限续跑。

## 调研依据

- [Claude 官方：Getting started with loops](https://claude.com/blog/getting-started-with-loops)
- [Claude Code：Keep Claude working toward a goal](https://code.claude.com/docs/en/goal)
- [Claude Code：Hooks reference](https://code.claude.com/docs/en/hooks)
- [Anthropic：Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- [Anthropic：Building Effective AI Agents](https://www.anthropic.com/engineering/building-effective-agents)
- [Anthropic：Scaling Managed Agents](https://www.anthropic.com/engineering/managed-agents)
- [Codex：Hooks](https://learn.chatgpt.com/docs/hooks)
- [Codex：Build plugins](https://learn.chatgpt.com/docs/build-plugins)
- [ClaudeFast：Claude Code Loops](https://claudefa.st/blog/guide/mechanics/claude-code-loops)
- [Simon Willison：Designing agentic loops](https://simonwillison.net/2025/Sep/30/designing-agentic-loops/)

## Confidence Loop

### 第一轮

- Target：原生 goal loop 与插件 campaign 状态机分层，任何自动重试都有预算和可观察进展。
- Evidence-backed assumptions：Codex Stop 会产生新的 continuation prompt；hook 有 `session_id`、`turn_id`、`stop_hook_active`；插件 hooks 并行且不是完整拦截边界；当前插件默认发现 `hooks/hooks.json`。
- Inferred assumption：本轮只支持 Codex。证据是现有 `.codex-plugin`、marketplace、MCP 和用户前序要求均指向 Codex 插件。
- Loopholes：仅修 Stop 重入仍会留下乱序脚本、陈旧 audit、未锁协议 promote、并发写损坏和 archive 绕过。
- Fixes：把 closure、transition、digest、预算和锁放进一个 host-agnostic 深模块；hook 仅适配事件。
- Confidence：中。

### 第二轮

- Loopholes：owner session 若靠目录或首次 Stop 推断，会接管无关对话；把 `/goal` 的 turn cap 当硬预算会在 resume 后重置；强制所有未完成状态继续会卡住人工和外部依赖。
- Fixes：显式 start/首次实验认领 session；预算持久化到 `.research`；终态至少区分 achieved、waiting_human、budget_exhausted、no_progress、aborted；Stop 重入直接放行，硬熔断用 `continue:false`。
- Revised confidence：高，但不是 100%。剩余风险主要是未在真实 Windows 宿主运行，以及 Codex 对部分 unified exec 的 hook 拦截仍不完整；最终 archive/decide 的确定性门禁负责兜底。

## 工作项

- [x] 阶段 0：核对基线、官方资料与真实失败路径
  - acceptance_criteria: 现有 17 个测试和两个 validator 的基线已记录；Stop 重入、乱序状态、stale audit、archive 绕过已有可复现证据。
  - verification_commands: `ARX_TEST_TMP=/tmp python -m unittest discover -s autoresearch-guard/tests -v`
  - success_definition: 能从代码、探针和官方文档解释为何当前系统不是闭环。
- [x] 阶段 1：落地状态机、readiness、预算、原子状态和 hook adapter
  - acceptance_criteria: 所有生产脚本和 hooks 通过单一 transition/readiness seam；新 contract 测试转绿。
  - verification_commands: `ARX_TEST_TMP=/tmp python -m unittest discover -s autoresearch-guard/tests -v`
  - success_definition: 研究迭代不能乱序、伪闭环或无限自动续跑。
- [x] 阶段 2：同步中文文档、插件 manifest 与可执行 smoke
  - acceptance_criteria: README/SKILL/references/manifest 描述与实际命令、状态和 hook 语义一致。
  - verification_commands: `python /home/ssy/.codex/skills/.system/skill-creator/scripts/quick_validate.py autoresearch-guard/skills/autoresearch-guard && python /home/ssy/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py autoresearch-guard`
  - success_definition: 新用户能按文档走完一轮且知道如何暂停、恢复和 rollover。
- [x] 阶段 3：独立 review、fresh verify、安装副本验证和提交
  - acceptance_criteria: reviewer 无 Critical；完整测试与 validator 在最后改动后通过；安装副本 hook smoke 通过；工作树只含本任务文件。
  - verification_commands: `git diff --check && ARX_TEST_TMP=/tmp python -m unittest discover -s autoresearch-guard/tests -v`
  - success_definition: `feature/loop-engineering-redesign` 上存在可审查提交，完成声明逐项有 fresh evidence。

## Commit units

1. `refactor: rebuild autoresearch loop control`：状态机、hooks、脚本、模板和测试；前置条件是 review 无 Critical 且 verify PASS。
2. `docs: document bounded research loops`：仅在文档可独立审查时拆分；否则并入第一个提交，避免行为与文档短暂分离。

## 已知风险

- Codex hooks 当前不能覆盖所有 unified exec/WebSearch 路径，Pre hook 只能早反馈，最终 digest/audit/decision/archive 必须继续 fail closed。
- 真实 token/cost 数据不在当前 hook payload 中，先不伪造精确预算。
- 跨多文件原子提交只能做到锁、原子单文件写和可恢复归档顺序，不能承诺文件系统级事务。

## Review 记录

第一次独立 adversarial review 结论为 `BLOCK`。它在绿测之外复现了三条闭环绕过：audit 计算期间插入 evidence 会让错误报告仍显得 fresh、修改 `decision.yaml` 可绕过 forbidden decision、state 与 hypothesis 可使用不同 iteration id。还发现 hooks 关闭时预算 outcome 不落地、损坏 state 无法 force recovery、v1 compiled 状态迁移成不可启动、人工批准不绑定 audit，以及安装副本缺测试。

修复已经进入当前 diff：audit/compile/record/decide 在 root lock 内提交；state 锚定 audit 和 decision digest；compile 强制唯一 iteration；`arx_loop check` 独立触发预算熔断；force 支持 raw recovery；v1 compiled 迁移到 `execution/armed`；critical approval 需要 review pause 并绑定当前 audit；新增中文空格安装副本、SessionStart、archive move 失败和无 PyYAML 回归测试。

这部分完成后仍需第二次独立 review。第一次 review 的修复不能自行替代复审。

第二次 review 找到一个打包 blocker：本地 plugin validator 不接受 manifest 的显式 `hooks` 字段；同时发现 resume 会重置 Stop continuation 总额，flatline 会混入同名但错误 split 的 metric。修复后，第三次独立短审为 `PASS`：hooks 改用约定路径，Stop 额度只在新 iteration 编译时重置，flatline 按 gate 的 `(metric, split)` 计算。

## Verification 记录

Claim：当前 feature 分支已经满足 loop-engineering 重构的成功标准，可以进入提交。

Fresh evidence（均晚于最后一次行为改动）：

- `PYTHONDONTWRITEBYTECODE=1 ARX_TEST_TMP=/tmp python -m unittest discover -s autoresearch-guard/tests -v`：38/38 通过。
- `ruff check autoresearch-guard/hooks autoresearch-guard/skills/autoresearch-guard/scripts autoresearch-guard/tests`：通过。
- `python -m py_compile autoresearch-guard/hooks/*.py autoresearch-guard/skills/autoresearch-guard/scripts/*.py`：通过。
- Skill validator：通过。
- Plugin validator：通过。
- `git diff --check`：通过。
- Direct-writer probe：在 audit 计算中绕过 `.arx.lock` 直接修改 ledger，audit 检测到输入变化并拒绝写报告。
- 安装副本 smoke：在含空格和中文的副本中执行 SessionStart、PreToolUse、PostToolUse 和 Stop payload，全部符合契约。

Verification verdict：`PASS`。第三次 review 为 `PASS`，commit eligibility 为 `eligible`。

未验证项：没有真实 Windows Codex 宿主，也没有对进程 hard-kill 或跨文件系统 move 做故障注入。替代证据是 Windows command 结构校验、Linux 中文/空格安装副本、进程内 move 失败恢复测试和 raw recovery 测试。

Next：提交 milestone，然后运行 `cleanup` 做最终知识与 git 状态检查。
