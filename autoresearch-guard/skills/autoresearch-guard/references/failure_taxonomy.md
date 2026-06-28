# Failure Taxonomy

Use these labels in `ai_evidence_review.md` when explaining research failure modes.

- `no_signal`: validation metrics do not move in the expected direction.
- `label_mismatch`: the training or ranking target does not match the measured objective.
- `proposal_headroom_low`: the candidate set cannot expose enough improvement.
- `baseline_too_strong`: the selected baseline already captures the available gain.
- `metric_misaligned`: the chosen metric rewards behavior that does not serve the research claim.
- `budget_insufficient`: the experiment is underpowered by seeds, training steps, data, or search budget.
- `implementation_bug`: observed evidence points to a code or data processing defect.
- `protocol_violation`: evidence cannot support a conclusion because the protocol was violated.
- `test_contamination`: test data or test labels were used before the human gate.
- `low_information_gain`: repeating the same action is unlikely to distinguish hypotheses.

Only AI and humans assign scientific failure labels. Scripts can only report deterministic violations.