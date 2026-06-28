# Claim Levels

Use the weakest claim supported by evidence.

## Levels

- `exploratory`: smoke results or early validation signals only.
- `validation`: locked validation protocol with recorded evidence and audit pass.
- `test`: human-approved test split evaluation after validation success.
- `paper`: replicated results, baselines, ablations, and claim boundary review.
- `production`: operational deployment evidence and monitoring.

## Promotion Rules

- Never promote from validation to test-level claims if `audit_report.yaml` lists `test_contamination: true`.
- Never claim `paper` or `production` from validation-only evidence.
- If validation gates are missing or failed, `promote` must be forbidden.
- If evidence is incomplete, claims stay exploratory at most.