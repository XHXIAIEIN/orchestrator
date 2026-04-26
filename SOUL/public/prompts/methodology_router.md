<!-- TL;DR: Route to correct methodology (debug/plan/audit/ship) by task type. -->
# Methodology Router

> **Who consults this**: The Governor, when selecting a thinking framework for task dispatch.
> **When**: After cognitive mode selection, before injecting methodology into the execution prompt.

Source: tanweai/pua Flavor-Based Methodology Router (Round 35 steal)

---

## How It Works

Different task types benefit from different mental models.
The Governor auto-selects methodology based on task classification, then appends a compact injection block (< 100 tokens) to the execution prompt.

## Task Type to Methodology Map

| Task Type | Methodology | Core Principle | Steps |
|---|---|---|---|
| Debug / Fix bug | RCA (Root Cause Analysis) | Diagnose before treating | 1. Reproduce 2. Hypothesize (2-3 causes) 3. Verify each 4. Fix confirmed cause 5. Regression test |
| Build new feature | First Principles | Question every assumption | 1. Simplest version? 2. Constraints? 3. Build minimal 4. Iterate |
| Code review | Subtraction | Less is more | 1. What can be removed? 2. What can be simplified? 3. Blast radius? 4. One clear owner per decision |
| Research / Investigation | Search First | Don't reinvent | 1. Search codebase 2. Search docs 3. Search web 4. Synthesize 5. Form opinion |
| Architecture / Design | Working Backwards | Start from the user | 1. Write ideal usage 2. Define interface 3. Design implementation 4. Identify risks |
| Performance | Measure First | No premature optimization | 1. Profile/benchmark 2. Identify bottleneck 3. Hypothesize fix 4. Implement 5. Measure again |
| Deploy / Ops | Closed Loop | Every action has verification | 1. Pre-check 2. Execute 3. Verify 4. Monitor 5. Rollback plan ready |
| Refactor | Preserve Behavior | Tests are the contract | 1. Ensure tests pass 2. Refactor one thing 3. Tests pass again 4. Repeat |

## Failure-Mode Switch Table

When the current approach stalls, switch methodology based on the failure pattern:

| Failure Pattern | Detection Signal | Switch To |
|---|---|---|
| Same error repeating | 3+ identical errors in sequence | RCA — root cause misidentified |
| Different error each time | Error type changes per attempt | First Principles — isolate 1 variable, change 1 thing |
| No progress, going in circles | 3+ attempts with no measurable change | Working Backwards — re-derive "done" state |
| Giving up, deflecting | "I can't", "environment issue", "probably needs X" | Search First — missing information |
| Code works but wrong approach | Passes but fragile/complex | Subtraction — what can be removed? |
| Performance issue | "It's slow" without profiling data | Measure First — profile before guessing |

### Concrete Examples

**Same error repeating**: 3 different fixes for `KeyError: 'user_id'` but error persists. You are fixing the symptom. Switch to RCA: trace where `user_id` gets set, work backward from the error.

**Different error each time**: `ImportError` then `TypeError` then `AttributeError`. Cascading changes without isolation. Switch to First Principles: revert all changes, modify 1 thing, observe.

**Going in circles**: Config restructured twice, considering a third layout. Lost sight of the goal. Switch to Working Backwards: write the ideal usage first, derive implementation.

**Giving up**: "This probably needs a different library." You have not searched. Switch to Search First: check actual docs, search issues, read examples.

## Integration with Cognitive Modes

| Cognitive Mode | Methodology Behavior |
|---|---|
| `direct` | No methodology injection (task is trivial) |
| `react` | Inject methodology matching task type from the map above |
| `hypothesis` | Always use RCA |
| `designer` | Always use Working Backwards |

## Dispatch Injection Format

When the Governor dispatches a task, append:

```
[Methodology: {name}]
{Core Principle}
Steps: {numbered steps from map}
Failure switch: if {failure signal}, switch to {methodology}.
```

Keep injection under 100 tokens. The methodology is a compass, not a manual.

### Injection Example

```
[Methodology: RCA]
Diagnose before treating.
Steps: 1. Reproduce 2. Hypothesize (2-3 causes) 3. Verify each 4. Fix confirmed cause 5. Regression test
Failure switch: if 3+ identical errors persist after fix, re-examine hypothesis list.
```

## Output Format

N/A — reference document. The Governor reads this to select and inject methodologies; it does not produce standalone output.

## Boundaries

1. **Stop and re-classify** if the failure-mode switch table triggers twice for the same task — the task type classification itself is likely wrong.
2. **Never stack methodologies** — exactly 1 methodology per dispatch. If a task spans two (e.g., debug then build), split into two dispatches.
