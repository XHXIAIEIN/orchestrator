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

**Adversarial Probe Requirement**: At least one verification must be an adversarial probe — deliberately attempt to break the implementation. Examples:
- Invalid input (empty string, null, negative numbers, wrong types)
- Edge cases (zero items, max int, unicode, concurrent access)
- Race conditions (rapid repeated calls, out-of-order events)
- Boundary values (off-by-one, exactly-at-limit, one-past-limit)

If you cannot think of an adversarial probe, you haven't understood the change well enough.

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

## Change-Type Verification Strategies

Different change types demand different verification focus. Use this table to select probes:

| Change Type | Verification Focus |
|-------------|-------------------|
| Frontend | Visual regression + interaction test |
| Backend/API | Contract test + boundary input |
| CLI/Script | Argument combinations + error paths |
| DB Migration | Rollback test + data integrity |
| Refactoring | Behavioral equivalence proof |
| Config | All environments affected |
| Collector | Actual data retrieval check (not just status=OK) |
| Prompt/SOUL | Before/after comparison on representative inputs |

## FAIL Before Triple Check

Before declaring a verification FAIL, ask these three questions:

1. **Already handled by existing code?** The "failure" might be caught by upstream validation you haven't read yet.
2. **Intentional design decision?** What looks like a bug might be a deliberate tradeoff — check comments, commit history, docs.
3. **Not actionable (environmental/external)?** If the failure is caused by a missing service, network issue, or OS difference, flag it but don't block on it.

If all three answers are "no", it's a real failure. Report it.

## Known Failure Modes

Watch for these traps that cause you to skip or weaken verification:

- **Verification avoidance**: Finding excuses not to verify ("too small a change", "just a typo", "only touched comments"). Every change is a change.
- **80% trap**: Most tests pass so you skip edge cases. The edge case you skip is the one that ships the bug.
- **Confidence substitution**: You feel confident, so you treat that feeling as evidence. Confidence is not proof.
- **Fatigue shortcuts**: Late in a long task, you rush the final verification. The last step is where most bugs hide.

**When you feel the urge to skip verification, consult `SOUL/public/prompts/rationalization-immunity.md`.** The most relevant rationalizations:
1. "It's just a small change" → Small changes break large systems. A one-char typo took down CloudFlare.
2. "I know this will work" → Knowing is not verifying. Your mental model diverged from reality at least once today.
3. "There's no time" → Skipping verification never saves time. It converts a 5-minute check into a 2-hour debug session.

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
