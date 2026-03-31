# guideline: review-context-isolation
## Trigger Conditions
Keywords: review, dispatch, handoff, context, quality_review
## Rules

### What the Reviewer Gets

A reviewer (刑部 agent) receives exactly three things:

1. **Git SHA range** — the commit(s) to inspect via `git diff`
2. **Plan / requirements** — the original task spec (problem, expected result, constraints)
3. **One-line summary** — what was done, in one sentence

### What the Reviewer Does NOT Get

- **Session history** — the back-and-forth between dispatcher and executor is irrelevant.
  The reviewer judges the artifact, not the process.
- **Execution reasoning ("内心戏")** — the executor's internal deliberation, failed
  attempts, or alternative approaches considered. These bias the reviewer toward
  leniency ("they tried hard, let it slide").
- **Previous review feedback** — on first review. Rework reviews may include the
  specific findings from the prior review, but nothing more.

### Why This Matters

Context contamination is the #1 cause of rubber-stamp reviews. When a reviewer sees
the executor's struggle, empathy overrides judgment. The reviewer's job is to evaluate
the output against the spec — period.

### Implementation Notes

- `review_dispatch.py` constructs the review observation from artifact data only.
- The `scratchpad` path is passed for reference (the reviewer can read the file),
  but the scratchpad contains structured output, not session history.
- If `build_handoff_prompt` is used, it should produce a context-minimal handoff —
  summary + file path, not a replay of the execution session.
