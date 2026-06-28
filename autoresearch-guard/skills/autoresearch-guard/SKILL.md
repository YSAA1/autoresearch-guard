---
name: autoresearch-guard
description: Use when Codex needs to run a research project as a guarded /goal loop with .research state, hypotheses, locked protocols, evidence ledgers, deterministic audits, AI evidence reviews, decision gate checks, lessons, and archives. Trigger when the user asks for AutoResearch Guard, evidence-bound research iteration, dead-end detection, pivot/refine loops, constrained Codex /goal generation, or research evidence auditing.
---

# AutoResearch Guard

## Overview

AutoResearch Guard organizes one research iteration as:

```text
Hypothesis -> Protocol -> /goal -> Experiment -> Evidence -> Audit -> AI Review -> Decision -> Next Goal or Archive
```

AI remains responsible for research judgement. Scripts and hooks only perform deterministic file, field, hash, metric, and rule checks.

## Hard Boundary

Do not let scripts or hooks make scientific decisions. They may:

- create `.research` files from templates
- validate required fields
- compute file hashes
- append evidence records
- check split contamination and blocked actions
- check locked protocol drift
- compare metrics against predeclared gates
- reject decisions that violate deterministic gates
- move completed iterations into archive

They must not:

- invent research ideas
- judge novelty
- explain scientific failure causes
- choose pivot/refine/promote by themselves
- rewrite experiment code
- write claim wording

## Workflow

1. Read `.research/lessons/retained_lessons.md` and `.research/lessons/anti_patterns.yaml` if they exist.
2. Let AI write or revise `.research/current/hypothesis.yaml`.
3. Let AI propose `.research/current/protocol.lock.yaml`, then require human confirmation by setting `locked: true`.
4. Run `scripts/arx_compile_goal.py` to render `.research/current/active_goal.md`.
5. Use the rendered file as the Codex `/goal` body.
6. Execute the research work in the main agent. Respect `allowed_work`, `forbidden_work`, and `blocked_actions.yaml`.
7. Run `scripts/arx_record.py` after each meaningful experiment to append deterministic evidence to `evidence_ledger.jsonl`.
8. Run `scripts/arx_audit.py` to produce `audit_report.yaml`.
9. AI writes `.research/current/ai_evidence_review.md` with failure attribution, residual risks, and allowed next actions.
10. AI writes `.research/current/decision.proposed.yaml`.
11. Run `scripts/arx_decide.py` to reject illegal decisions or commit the proposal to `decision.yaml`.
12. Generate `next_goal.md` manually from the decision, or run `scripts/arx_archive.py` to close the iteration.

## Script Map

- `scripts/arx_init.py`: create `.research/current`, lessons, archive folders, and initial state templates.
- `scripts/arx_compile_goal.py`: render `active_goal.md` from AI-authored YAML files after protocol lock.
- `scripts/arx_record.py`: append JSONL evidence with command, split, seed, file digests, and metrics.
- `scripts/arx_audit.py`: check evidence integrity, protocol drift, test contamination, blocked actions, required metrics, and validation gates.
- `scripts/arx_decide.py`: check `decision.proposed.yaml` against `audit_report.yaml` and commit legal decisions.
- `scripts/arx_status.py`: print current hypothesis, lock state, latest evidence, audit, blocked actions, claim boundary, and human gate status.
- `scripts/arx_archive.py`: move a completed `.research/current` into `.research/archive`.

## Hooks

Plugin hooks live in the plugin root `hooks/` folder. They are guardrails, not a research engine.

- `pre_tool_command_gate.py`: blocks deterministic violations before a command runs.
- `post_tool_capture.py`: records command metadata and reminds Codex to write evidence.
- `stop_goal_guard.py`: prevents ending a `/goal` while required evidence, audit, AI review, or decision artifacts are missing.

## References

Load only the relevant reference:

- `references/workflow.md`: end-to-end loop and file responsibilities.
- `references/failure_taxonomy.md`: terms for AI evidence review and dead-end detection.
- `references/claim_levels.md`: allowed claim strength and promotion boundaries.
- `references/goal_rules.md`: rules for compiling constrained `/goal` text.