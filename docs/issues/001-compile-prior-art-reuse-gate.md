## Parent

Parent: #2

## What to build

Add an end-to-end compile-time gate that requires each active research hypothesis to trace back to the literature review. A hypothesis must reference a candidate idea, and its reuse plan must reference an existing implementation unless it explicitly chooses build-new with a reason.

This slice should preserve the script-based workflow: a user initializes a research root, writes the literature review and hypothesis, locks the protocol, runs compile, and either receives an active goal or a deterministic rejection explaining the missing trace.

## Acceptance criteria

- [ ] Compile succeeds when the hypothesis evidence basis matches a candidate idea and the reuse base matches an existing implementation.
- [ ] Compile fails when the hypothesis evidence basis is missing from the literature review.
- [ ] Compile fails when the reuse base is missing from the implementation review and is not build-new.
- [ ] Compile still allows build-new only when a non-empty build-new reason is present.
- [ ] Tests exercise the behavior through public script invocations.

## Blocked by

None - can start immediately
