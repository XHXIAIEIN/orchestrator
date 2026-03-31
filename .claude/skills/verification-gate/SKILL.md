---
name: verification-gate
description: "Five-step evidence chain before declaring any task complete. Use before committing, creating PRs, or claiming work is done."
---

# Verification Gate Protocol

**IRON LAW: No completion claim without evidence. "Should work" is not evidence.**

Before declaring ANY task complete, you MUST pass all five steps in order:

## The Five Steps

### Step 1: IDENTIFY
What verification command(s) need to run?
- Tests? Which test suite / file?
- Build? What build command?
- Lint? Type check?
- Manual check? What URL / output to inspect?

If you cannot identify what to verify, say so. Do not skip to "done".

### Step 2: EXECUTE
Run the actual command(s). Not "I would run..." — actually run them.

### Step 3: READ
Read the complete output. Not the first line. Not "it looks green". The full output.
- How many tests passed/failed/skipped?
- Any warnings?
- Any unexpected output?

### Step 4: CONFIRM
Does the output match expectations?
- All tests green? Or are there unrelated failures?
- Build succeeded without warnings?
- The specific behavior changed as requested?

If anything is unexpected, investigate before proceeding.

### Step 5: DECLARE
Only NOW can you say the task is complete. Reference the evidence:
- "All 47 tests pass (output above)"
- "Build succeeds, no warnings"
- "Verified endpoint returns 200 with expected payload"

## Banned Phrases

These phrases in a completion declaration indicate the gate was skipped:

| Phrase | Problem |
|--------|---------|
| "should pass" | You don't know until you run it |
| "should work" | Same |
| "probably fine" | Probability is not verification |
| "I believe this is correct" | Belief is not evidence |
| "Based on the changes, this should..." | Prediction is not observation |
| "I'm confident that..." | Confidence is not proof |
| "This looks good" | Looking is not testing |
| "Tests should still pass" | "Should" means you didn't run them |

## When Verification Is Impossible

Sometimes you genuinely cannot verify (no test suite, external service, etc.). In that case:

1. State explicitly: "I cannot verify this because [reason]"
2. List what the owner should verify manually
3. Do NOT claim completion — say "Implementation complete, pending manual verification of [X]"

## Application Scope

This gate applies to:
- Completing any user-requested task
- Before `git commit`
- Before creating PRs
- Before saying "done" / "完成" / "搞定"
- Before moving to the next task in a plan

This gate does NOT apply to:
- Research / exploration tasks (no code changed)
- Questions / explanations (nothing to verify)
- Planning (plans are verified during execution)
