## Parent

Parent: #2

## What to build

Add a review mode to status output that renders a compressed human decision packet from the current research state, audit report, evidence ledger, and decision proposal. The packet should show red, yellow, and green gate states plus down-drill references, so a user can decide whether to proceed, refine, pivot, promote, or stop without opening every underlying state file.

This slice should not weaken any gate. It only translates deterministic status into a lower-burden human review surface.

## Acceptance criteria

- [ ] Status has a review mode that prints a human-readable decision packet.
- [ ] The review packet includes red/yellow/green states for prior art, baseline, protocol integrity, validation gate, claim support, and spiral risk.
- [ ] The review packet includes a recommended decision summary based on current blockers and warnings.
- [ ] The review packet includes down-drill references to the source evidence artifacts.
- [ ] JSON status remains backward compatible.
- [ ] Tests exercise the behavior through public script invocations.

## Blocked by

- #3
- #4
- #5
