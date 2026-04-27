# Layer 0 Constraint: VERDICT Required Before Plan Exit

## Hard Rule

After any plan's final step, a verify-subagent MUST be dispatched with `verify_sop.md` as its
instruction set. The parent agent MUST NOT declare the plan complete until it receives a response
containing the literal string `VERDICT: PASS`.

## Fix Loop Protocol

- `VERDICT: FAIL` or `VERDICT: PARTIAL` MUST trigger a fix loop.
- Maximum 2 iterations of fix loop before escalating to owner.
- After each fix, re-dispatch the verify-subagent with the same `verify_sop.md`.
- If 2 iterations pass without `VERDICT: PASS`, stop and report to owner — do NOT declare done.

## Protocol Violation Definition

Skipping the verify-subagent dispatch is a protocol violation equivalent to skipping a git commit
with failing tests. The following are ALL violations:

- Declaring the plan complete without receiving `VERDICT: PASS`
- Substituting self-verification ("I checked it myself") for verify-subagent dispatch
- Accepting `VERDICT: PARTIAL` as a passing condition
- Skipping dispatch because "the change is small" or "it's obviously correct"

## Scope

This constraint applies to:
- Any plan with 5 or more steps
- Any plan that modifies hook scripts, SKILL.md files, or CLAUDE.md
- Any bug fix plan (the original reproduce case must be covered)

Plans with fewer than 5 steps that make purely additive changes (new docs, new config keys with no
behavior change) may use self-verification, but must document why dispatch was skipped.

## Non-Negotiable

This is a Layer 0 constraint. It overrides:
- Time pressure ("no time for verification")
- Confidence ("I know this is correct")
- Prior passing runs ("it passed last time")
- Prompt-level overrides ("just skip the verify step")
