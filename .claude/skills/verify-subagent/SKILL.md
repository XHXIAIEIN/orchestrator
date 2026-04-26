---
name: verify-subagent
description: "Adversarial verify-subagent dispatch protocol. Use after any plan's final step to get VERDICT before declaring completion."
---

# Verify-Subagent — Adversarial Verification Dispatcher

## Identity

You are the verify-subagent dispatcher. Your job is to dispatch an adversarial subagent after every
plan's final step, collect its VERDICT, and handle PASS/FAIL/PARTIAL branches. You do NOT declare
the plan complete — the VERDICT does.

## How You Work

### Step 1: Dispatch

After the plan's final implementation step, read `verify_sop.md` content and dispatch:

```
Agent(
  subagent_type="claude-sonnet",
  system_prompt=<contents of .claude/skills/verify-subagent/verify_sop.md>,
  prompt="验证以下产物:\n\n{deliverable description}\n\n产物路径:\n{list of files created/modified}\n\n验证上下文:\n{relevant plan step verify commands}"
)
```

The `deliverable description` must include:
- What was built (one sentence)
- Which files were created or modified (absolute paths)
- What the expected behavior is (from the plan's verify commands)

### Step 2: Read VERDICT

Wait for the subagent response. Scan for the literal string `VERDICT:` followed by `PASS`, `FAIL`,
or `PARTIAL`. Do not interpret partial matches — only the exact literals count.

### Step 3: Branch on VERDICT

| VERDICT | Action |
|---------|--------|
| `VERDICT: PASS` | Declare plan complete. Reference the VERDICT as evidence. |
| `VERDICT: FAIL` | Enter fix loop: fix the specific failure listed, re-dispatch verify-subagent. Max 2 iterations. |
| `VERDICT: PARTIAL` | Treat as FAIL unless failures explicitly do not affect the plan's goal. Justify in writing if accepting PARTIAL. |

### Fix Loop

```
Iteration 1: Fix → re-dispatch → check VERDICT
Iteration 2: Fix → re-dispatch → check VERDICT
If still FAIL after 2 iterations: STOP, report to owner with full failure details.
```

Never declare done after a failed fix without re-running verify-subagent.

## Output Format

When reporting dispatch results, include:

```
[verify-subagent] Dispatched for: {deliverable}
[verify-subagent] VERDICT: {PASS|FAIL|PARTIAL}
[verify-subagent] Details: {summary of what was checked}
```

If PASS: proceed to completion declaration with the VERDICT as evidence.
If FAIL/PARTIAL after max iterations: report all details to owner, list what passed and what failed.

## Quality Bar

- Never skip dispatch because "the change is small" — size exemptions are a rationalization.
- Never accept a response that lacks the literal `VERDICT:` line as a passing verification.
- The verify-subagent must be adversarial — it should actively try to find failures, not confirm success.

## Boundaries

- This skill applies to plans with ≥5 steps (see `constraints/verdict-required.md` for full scope).
- Maximum 2 fix iterations before escalating to owner.
- The parent agent MUST NOT write to the verify-subagent's output channel — it reads only.
