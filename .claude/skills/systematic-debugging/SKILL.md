---
name: systematic-debugging
description: "Structured root-cause debugging protocol. Use when encountering any bug, test failure, or unexpected behavior."
---

# Systematic Debugging Protocol

**IRON LAW: NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST.**

You MUST complete Phase 1 before proposing any fix. If you catch yourself wanting to "just try something" — STOP. That impulse is the problem this protocol exists to solve.

## Phase 1: Root Cause Investigation (MANDATORY GATE)

Complete ALL of these before moving to Phase 2:

1. **Read the full error** — every line of the stack trace, every warning. Don't skim.
2. **Reproduce reliably** — run the failing command yourself. If it can't be reproduced, collect more data. Do NOT guess.
3. **Check recent changes** — `git diff`, `git log --oneline -10`, env changes. The bug is usually in what changed.
4. **Add diagnostic logging** — at every component boundary: input/output/state. Run once. Find where the chain breaks.
5. **Backward trace (5 levels)** — from the error, trace backwards through the call chain. At each level ask: "Is the input to this function correct?" Find where the bad value was introduced.

**Gate check**: Can you state the root cause in one sentence? If not, you're not done with Phase 1.

## Phase 2: Pattern Analysis

1. Find a **working example** of similar functionality
2. **Line-by-line comparison** — list every difference between working and broken
3. Identify **hidden assumptions** and **implicit dependencies**

## Phase 3: Hypothesis & Testing

1. Write down **one hypothesis** — be specific ("X is null because Y doesn't initialize before Z")
2. Design the **smallest possible test** for that hypothesis
3. Run the test
4. If falsified → **new hypothesis from scratch**. Do NOT stack fixes. Do NOT combine "maybe this AND that".

## Phase 4: Implementation

1. **Write a failing test** that reproduces the bug
2. **Make the minimal fix** — change as few lines as possible
3. **Run all tests** — verify no regressions
4. If the fix exposes a new problem in a different location → see 3-Attempt Rule below

## 3-Attempt Architectural Escalation

Track your fix attempts:
- **Attempt 1** fails → OK, revise hypothesis, try again
- **Attempt 2** fails → Slow down. Re-read Phase 1 notes. Is the root cause actually identified?
- **Attempt 3** fails → **STOP IMMEDIATELY**. This is likely an architectural issue, not a local bug.

On the third failure, output this report to the user:

```
## Debugging Escalation Report
**Bug**: [description]
**Root cause hypothesis**: [your best guess]
**3 attempts tried**: [what each attempt changed and why it failed]
**Why this might be architectural**: [what pattern you're seeing]
**Recommendation**: [what the user should consider]
```

Do NOT attempt a 4th fix. The user decides the next step.

## Rationalization Immunity

These thoughts mean you're about to violate the protocol:

| Thought | Reality |
|---------|---------|
| "I already know what's wrong" | Then Phase 1 should take 30 seconds. Do it anyway. |
| "This is a simple typo" | Typos don't need 3 attempts. If it's simple, Phase 1 is fast. |
| "Let me just try this quick fix" | Quick fixes that skip investigation cause 80% of debugging spirals. |
| "The error message is clear enough" | Read the FULL trace. The obvious line is often not the root cause. |
| "I don't need to reproduce it" | If you can't reproduce it, you can't verify the fix. |
| "I'll add the test after fixing" | That's not TDD, that's confirmation bias. Test first. |
| "This is taking too long, let me just..." | Impatience is the #1 cause of debugging spirals. Slow down. |
| "The third attempt is different enough" | Three failures = wrong mental model. Stop and escalate. |

## Post-Fix Hardening

After a successful fix, add ONE layer of defense:
- A validation at the function entry point, OR
- A type check where the bad value was introduced, OR
- A test case that catches this category of bug

Goal: make this class of bug structurally impossible, not just fixed in this instance.
