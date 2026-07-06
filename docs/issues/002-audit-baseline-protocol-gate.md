## Parent

Parent: #2

## What to build

Add an end-to-end audit gate for baseline-first research and protocol timing. Audit should detect whether required baseline evidence exists, compare validation evidence against the configured baseline where possible, and reject evidence records that predate the compiled protocol timestamp.

This slice should keep refine possible for incomplete but useful evidence while making promote unavailable when baseline or protocol timing requirements are violated.

## Acceptance criteria

- [ ] Audit reports baseline status when the protocol requires a baseline.
- [ ] Promote is forbidden when required baseline evidence is missing.
- [ ] Promote is forbidden when configured baseline comparison is not satisfied.
- [ ] Audit reports protocol timing violations when evidence predates the compiled protocol.
- [ ] Existing validation gate, protocol digest, forbidden split, and spiral checks continue to work.
- [ ] Tests exercise the behavior through public script invocations.

## Blocked by

None - can start immediately
