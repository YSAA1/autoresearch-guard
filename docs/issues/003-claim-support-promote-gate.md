## Parent

Parent: #2

## What to build

Add an end-to-end claim support gate that reads structured claim rows from the evidence review and prevents promote when claims are unsupported, prohibited, or exceed the allowed evidence boundary.

The evidence review remains human-readable; deterministic audit only reads the predictable claim table and turns unsafe claims into promote blockers.

## Acceptance criteria

- [ ] Audit recognizes supported claims from the evidence review table.
- [ ] Promote is forbidden when any claim is unsupported.
- [ ] Promote is forbidden when any claim is prohibited.
- [ ] Promote is forbidden when a claim exceeds the configured evidence boundary.
- [ ] Missing or malformed claim tables produce an explicit audit unknown or violation rather than a silent pass.
- [ ] Tests exercise the behavior through public script invocations.

## Blocked by

None - can start immediately
