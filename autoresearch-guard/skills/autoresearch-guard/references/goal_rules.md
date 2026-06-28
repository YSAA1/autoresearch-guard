# Goal Compilation Rules

`active_goal.md` is generated from AI-authored files and deterministic state.

## Required Inputs

- `.research/current/hypothesis.yaml`
- `.research/current/protocol.lock.yaml`
- `.research/current/blocked_actions.yaml`
- `.research/current/claim_boundary.yaml`

## Rules

- Refuse to compile unless `protocol.lock.yaml` has `locked: true`, unless `--allow-unlocked` is passed for local draft work.
- Include allowed work, forbidden work, blocked actions, claim boundary, and required artifacts.
- Include the protocol digest so later audit can detect drift.
- Do not invent allowed or forbidden work in the compiler. Missing fields are treated as errors or empty lists.
- Do not generate scientific interpretation in the goal compiler.

## Good Goal

A good goal tells Codex what to do, what not to do, what evidence to produce, and when it is not allowed to stop.