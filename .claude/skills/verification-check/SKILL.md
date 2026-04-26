---
name: verification-check
description: "Evidence-gated completion check. Use before committing, creating PRs, or claiming work is done. Pairs with verification-spec at task start."
origin: "Orchestrator — split from verification-gate (2026-04-26)"
source_version: "2026-04-26"
---

# Verification Check Protocol

<!-- triviality-filter:start -->
> **Triviality Filter** — If input is ≤ 3 words with no question/code/task, respond directly. Skip full protocol.
> Full spec: `SOUL/public/prompts/triviality_filter.md`
<!-- triviality-filter:end -->

## Pre-Read Discipline

Before reading any reviewer output or review file:
1. Read `SOUL/public/prompts/rationalization-immunity.md` (specifically the "Review Dismissal" and "Pre-Load Rule" sections).
2. Only then open the review file.

Skipping step 1 means you have already formed rationalizations. The review is worthless.

```
IRON LAW: NO COMPLETION CLAIM WITHOUT EVIDENCE. "Should work" IS NOT EVIDENCE.
```

This is the post-implementation gate. It pairs with `verification-spec` (task-start gate that produces the Goal/Verify/Assume block). If you skipped `verification-spec`, you do not have a `Verify:` command yet — go state one before running this gate.

Before declaring ANY task complete, pass all five steps in order.

## The Five Steps

### Step 1: IDENTIFY
Pull the `Verify:` line from the spec block emitted at task start. If the task surfaced new verification needs (e.g. an adversarial probe revealed a sub-feature), add them here.

If you somehow have no spec, name the verification commands now:
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
Does the output match the goal stated in the spec block?
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

## Common Rationalizations

These thoughts mean you're about to skip or weaken verification:

| Rationalization | Reality | Correct Behavior |
|---|---|---|
| "It's just a small change" | Small changes break large systems. A one-char typo took down CloudFlare. | Same verification process. No size exemptions. |
| "I know this will work" | Knowing is not verifying. Your mental model diverged from reality at least once today. | Run it and prove it. |
| "There's no time" | Skipping verification never saves time. It converts a 5-minute check into a 2-hour debug session. | The fastest path is the verified path. |
| "Only touched comments/docs" | Comment changes can break parsers, configs, and tools. A stray `*/` has killed builds. | Verify cosmetic changes the same as functional ones. |
| "Most tests pass, the rest are unrelated" | The 80% trap. The edge case you skip is the one that ships the bug. | Run ALL tests. Investigate every failure. |
| "I feel confident about this" | Confidence is a feeling, not evidence. Substituting emotion for verification is the #1 gate bypass. | Convert confidence into proof. Run the command. |
| "I'm tired, this is the last task" | Fatigue shortcuts cause the majority of late-stage bugs. The last step is where most bugs hide. | Slow down. The gate doesn't have a fatigue exemption. |
| "The adversarial probe isn't needed here" | If you can't think of how to break it, you don't understand the change well enough. | Find at least one adversarial input. Always. |
| "I already verified something similar earlier" | "Similar" ≠ "same". Different code, different state, different result. | Verify THIS change specifically. |

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

## Pairs With

- `verification-spec` — emits the Goal/Verify/Assume block at task start; this gate consumes the `Verify:` command
