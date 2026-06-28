# AutoResearch Guard Workflow

AutoResearch Guard uses a single source of live state: `.research/current/`.

## Loop

1. AI writes the hypothesis.
2. AI writes a protocol.
3. Human locks the protocol by setting `locked: true`.
4. `arx_compile_goal.py` renders `active_goal.md`.
5. Codex uses `active_goal.md` as the `/goal`.
6. Codex runs experiments.
7. `arx_record.py` appends evidence from result files and metrics.
8. `arx_audit.py` checks deterministic facts.
9. AI writes evidence review and failure attribution.
10. AI proposes a decision.
11. `arx_decide.py` checks whether the proposed decision violates hard gates.
12. The iteration either produces `next_goal.md` or is archived.

## File Roles

- `state.yaml`: lifecycle state and protocol digest.
- `hypothesis.yaml`: AI-authored research intent and scoped work.
- `protocol.lock.yaml`: human-locked evaluation protocol.
- `active_goal.md`: generated `/goal` text.
- `evidence_ledger.jsonl`: append-only deterministic evidence.
- `audit_report.yaml`: deterministic audit output.
- `ai_evidence_review.md`: AI-authored scientific review.
- `decision.proposed.yaml`: AI-authored proposed decision.
- `decision.yaml`: gate-checked committed decision.
- `next_goal.md`: AI-authored next iteration input.
- `claim_boundary.yaml`: maximum supported claim level.
- `blocked_actions.yaml`: deterministic blocked actions.

## Invariant

Scripts may reject illegal states. They must not choose the research direction.