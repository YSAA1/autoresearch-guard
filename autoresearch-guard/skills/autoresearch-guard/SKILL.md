---
name: autoresearch-guard
description: 当 Codex 需要将研究项目作为受控的 /goal 循环运行时，使用 `.research` 状态、文献与现有实现搜索、假设、锁定协议、证据台账、确定性审计、死胡同检测、AI 证据审查、决策门禁检查、经验总结与归档。触发条件：用户请求 AutoResearch Guard、证据约束的研究迭代、死胡同检测、pivot/refine 循环、受约束的 Codex /goal 生成，或研究证据审计。
---

# AutoResearch Guard

## 概述

```text
Lessons -> Literature -> Hypothesis -> Protocol -> /goal -> Ledger -> Audit -> Review -> Decision -> Closure
```

AI 负责研究判断与 closure 中的 lessons 更新。脚本与 hook 只做确定性检查。文件职责、closure 清单、迭代衔接、强制边界与 MCP 配置见 `references/workflow.md`。

## 核心原则：不重复造轮子

任何方法在写实验代码前，必须先调查 prior art：论文（Semantic Scholar MCP）+ 现有实现（WebSearch）。复用优先；重写必须在 `hypothesis.yaml.reuse_plan.build_new_reason` 给理由。`arx_compile_goal.py` 用确定性字段检查强制本原则。详见 `references/prior_art.md`。

## 硬性边界

脚本与 hook **可以**：初始化文件、校验字段、哈希、追加 ledger、检查划分污染与 blocked actions、比较 validation gates、报告 `spiral_risk`、拒绝非法 `promote`、拒绝缺 `spiral_response` 的 critical 决策、归档。

脚本与 hook **不得**：发明研究思路、解释科学失败、判断是否真死胡同（只报信号，AI 决定）、选择 pivot/refine/promote、重写实验代码、撰写论断措辞、评新颖性。

## 依赖

- **Semantic Scholar MCP**（`s2-mcp-server`）：Literature 阶段搜论文与引用图。配置见 `references/workflow.md` 附录。MCP 不可用时降级为 WebSearch。
- **WebSearch**（内置）：搜现有实现/仓库。

## 工作流

1. **Lessons** — 若存在，阅读 `.research/lessons/`。完成：已吸收或确认不存在。
2. **Literature** — AI 用 S2 MCP 搜论文 + WebSearch 搜现有实现，编写 `literature_review.md`（见 `references/prior_art.md`）。完成：≥1 candidate_idea + ≥1 existing_implementation，每个有证据链接。
3. **Hypothesis** — AI 编写或修订 `hypothesis.yaml`，含 `evidence_basis` 与 `reuse_plan`。完成：必填字段已填。
4. **Protocol** — AI 编写 `protocol.lock.yaml`（含 `spiral_budget`）；人工设 `locked: true`。完成：协议已锁定。
5. **Compile** — `scripts/arx_compile_goal.py` 校验 `evidence_basis` + `reuse_plan` 并渲染 `active_goal.md`。完成：goal 已生成。
6. **Goal** — 将 `active_goal.md` 作为 Codex `/goal` 正文。
7. **Research** — 在 `/goal` 内执行，优先复用 `reuse_plan.base` 指定的现有实现；遵守 allowed/forbidden work 与 `blocked_actions.yaml`。
8. **Ledger** — 每次有意义实验后 `scripts/arx_record.py`。完成：ledger 有记录。
9. **Audit** — `scripts/arx_audit.py` 生成 `audit_report.yaml`（含 `spiral_risk`）。完成：报告已写出（有违规时 exit 1，报告仍生成）。
10. **Review** — AI 编写 `ai_evidence_review.md`（失败归因见 `references/failure_taxonomy.md`）。若 `spiral_risk` 非 none，必须含「死胡同评估」节。完成：无 `TBD by AI`。
11. **Propose** — AI 编写 `decision.proposed.yaml`；若 `spiral_risk=critical`，必含 `spiral_response`。
12. **Decide** — `scripts/arx_decide.py`（critical 时拒绝无 `spiral_response` 的 proceed）。完成：`decision.yaml` 已提交。
13. **Closure** — 更新 `lessons/`（有失败时强制）；编写 `next_goal.md`（若继续）；`scripts/arx_archive.py`；若继续则 `arx_init.py --archive-existing`。分支见 `references/workflow.md`「Closure 与迭代衔接」。

## 脚本

| 脚本 | 用途 |
|------|------|
| `arx_init.py` | 创建 `current/`、`lessons/`、`archive/` 及初始模板（含 literature_review.md 与 ai_evidence_review.md） |
| `arx_compile_goal.py` | 锁定后校验 reuse 字段并渲染 `active_goal.md` |
| `arx_record.py` | 追加 ledger 证据 |
| `arx_audit.py` | 确定性审计 + `spiral_risk` 信号 |
| `arx_decide.py` | 检查并提交决策；escape gate |
| `arx_status.py` | 打印当前状态 |
| `arx_archive.py` | 归档 `current/` |

## Hooks

护栏，非研究引擎。

- `pre_tool_command_gate.py` — 拦截确定性命令违规
- `post_tool_capture.py` — 检测类实验命令，提醒写入 ledger（不写日志文件）
- `stop_goal_guard.py` — 缺少 closure 产物或失败时未写 lessons → 阻止结束 `/goal`

## 参考

- `references/workflow.md` — 目录、文件职责、closure、迭代衔接、强制边界、MCP 配置附录
- `references/prior_art.md` — 不重复造轮子：论文 + 现有实现调查方法
- `references/spiral_detection.md` — 死胡同信号、阈值、等级定义
- `references/failure_taxonomy.md` — 审查用失败标签（AI 侧，脚本不校验）
- `references/claim_levels.md` — 论断等级；脚本仅强制 `promote` 门禁
- `references/goal_rules.md` — goal 编译规则与 reuse 字段校验
