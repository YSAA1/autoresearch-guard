# PRD: AutoResearch Guard 研究质量门禁增强

> 状态：2026-06-30 阶段的历史 PRD。它仍解释 prior art、baseline 和 claim gate 的来源，但不描述当前 loop runtime。当前实现契约见 `autoresearch-guard/skills/autoresearch-guard/references/loop_contract.md`。

## Problem Statement

用户希望 AutoResearch Guard 支持更可靠的自动研究循环。当前系统已经能初始化研究状态、编译受约束的 goal、记录证据、审计协议违规、检查决策、展示状态并归档，但研究质量门禁还不够硬。

主要风险是：agent 可以在 prior art 证据很弱、现有实现没有真正绑定、baseline 没复现、协议时间线不清、claim 证据越界的情况下继续推进研究。另一类风险是：为了补足证据约束而新增太多人工可见状态文件，导致用户在 review 过程中负担过重。

用户真正需要的是：研究门禁更硬，人工入口更轻。系统要能挡住自动研究里的假新颖、重复造轮子、弱 baseline、协议漂移、证据不足和结论越界，同时把这些结果压缩成一份可读的决策摘要。

## Solution

增强 AutoResearch Guard 的研究质量门禁，并通过单一 review packet 汇总门禁结果。

系统应在编译 goal 前要求研究假设绑定到 literature review 中的候选想法和现有实现证据；在审计阶段要求 baseline 证据存在并参与 promote 判断；要求实验记录发生在协议编译之后；要求 evidence review 中的 claim 明确证据等级和支持状态；在状态入口中输出红黄绿灯式 review packet，让用户只看决策摘要，必要时再下钻到底层证据。

这不是把人工 review 做成“少文件优先”，而是把低心智负担作为约束：底层门禁必须严格，默认人工入口必须压缩。

## User Stories

1. As a research operator, I want each hypothesis to point to a prior idea, so that I can tell where the research direction came from.
2. As a research operator, I want each hypothesis to point to an existing implementation or an explicit build-new rationale, so that the agent does not repeat work without justification.
3. As a research operator, I want the compiler to reject hypotheses whose evidence basis cannot be found in the literature review, so that unsupported ideas do not become active goals.
4. As a research operator, I want the compiler to reject reuse plans that cannot be found in the implementation review, so that reuse decisions stay auditable.
5. As a research operator, I want build-new decisions to require a clear reason, so that new code is created only when reuse is not appropriate.
6. As a research operator, I want the protocol to define baseline expectations, so that later results are compared against an explicit reference point.
7. As a research operator, I want audit to detect missing baseline evidence, so that promote is blocked until baseline is established.
8. As a research operator, I want audit to compare observed results with baseline where configured, so that the agent cannot promote weak improvements.
9. As a research operator, I want evidence records to be checked against the compiled protocol time, so that old or pre-protocol runs do not support a locked experiment.
10. As a research operator, I want protocol digest mismatches to remain visible in audit, so that protocol drift cannot be hidden.
11. As a research operator, I want forbidden split usage to remain a hard audit violation, so that test contamination blocks promotion.
12. As a research operator, I want validation gate failures to block promote but still allow refine, so that exploration can continue without overstating evidence.
13. As a research operator, I want each claim to declare its evidence level, so that exploratory, validation, and test claims are not confused.
14. As a research operator, I want unsupported claims to block promote, so that conclusions do not outrun evidence.
15. As a research operator, I want prohibited claims to block promote, so that claim boundaries are enforced.
16. As a research operator, I want claim support checks to read from the human evidence review, so that I do not need to maintain a separate claim file.
17. As a research operator, I want audit to report why promote is forbidden, so that I can decide whether to fix evidence, refine, pivot, or stop.
18. As a research operator, I want spiral risk to remain part of the decision gate, so that repeated low-information experiments do not continue silently.
19. As a research operator, I want status output to include a review mode, so that I can see a compressed decision packet without opening every state file.
20. As a research operator, I want the review packet to show red, yellow, and green gate states, so that I can distinguish blockers from acceptable risks.
21. As a research operator, I want the review packet to include down-drill references, so that I can inspect source evidence only when needed.
22. As a research operator, I want the review packet to avoid adding new manual review files, so that review remains focused on decision making rather than bookkeeping.
23. As a research operator, I want JSON status to remain available, so that automation can consume status without parsing human prose.
24. As a research operator, I want existing successful research lifecycle behavior to keep working, so that the enhanced gates do not break normal use.
25. As a research operator, I want tests to exercise the real CLI flow, so that the safety guarantees match actual usage.

## Implementation Decisions

- The public interface remains the existing script-based workflow rather than a new standalone CLI.
- The compile step becomes responsible for checking that hypothesis evidence and reuse decisions are traceable to the literature review.
- The literature review remains human-readable Markdown, with predictable structured sections that the compiler can parse.
- The audit step becomes responsible for baseline presence, baseline comparison where configured, protocol timing, claim support, and existing protocol/evidence checks.
- The evidence review remains the human-authored place for claim-level reasoning, with a predictable table for deterministic promote gating.
- The status step gains a review mode that renders a human decision packet from existing state and audit outputs.
- Promote remains the decision most aggressively guarded; refine and pivot can remain available when evidence is incomplete but useful.
- The implementation should avoid new manual YAML files unless a later stability issue proves that a generated machine index is necessary.
- Spiral risk remains a signal produced by deterministic audit and interpreted by the AI/human review phase.

## Testing Decisions

- Tests should exercise behavior through the public script interfaces, not private helper functions.
- The main seam is the existing lifecycle test harness that creates a temporary research root and invokes scripts as subprocesses.
- Tests should be added one vertical slice at a time: compile gate, audit baseline gate, claim support gate, and review packet output.
- Tests should verify observable outcomes: command exit codes, generated audit fields, forbidden decisions, and status/review output.
- Existing lifecycle, hook, spiral, escape gate, lessons, and subtraction regression tests should continue to pass.
- New tests should use small temporary fixtures rather than network calls or external research APIs.

## Out of Scope

- Building a standalone CLI platform.
- Adding a web UI.
- Automatically judging scientific novelty or scientific truth.
- Automatically choosing research direction, pivot strategy, or final claims.
- Creating a large new set of manual YAML files for users to review.
- Changing GitHub issue workflow or repository labels beyond what is needed to publish this work.
- Implementing full recovery planning or heartbeat tracking in this slice.

## Further Notes

The key design balance is strict machine-readable gates plus a lightweight human review surface. The system should make bad research states hard to promote, not make every intermediate artifact a manual approval burden.
