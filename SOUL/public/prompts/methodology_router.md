# Methodology Router

Source: tanweai/pua Flavor-Based Methodology Router (Round 35 steal)

Different task types benefit from different thinking frameworks.
The Governor auto-selects methodology based on task classification.
This is NOT about motivation — it's about picking the right mental model.

## Task Type → Methodology Map

| Task Type | Methodology | Core Principle | Key Steps |
|-----------|-------------|---------------|-----------|
| **Debug / Fix bug** | RCA (Root Cause Analysis) | Diagnose before treating | 1. Reproduce → 2. Hypothesize (2-3 causes) → 3. Verify each → 4. Fix confirmed cause → 5. Regression test |
| **Build new feature** | First Principles | Question every assumption | 1. What is the simplest version? → 2. What constraints exist? → 3. Build minimal → 4. Iterate |
| **Code review** | Subtraction | Less is more | 1. What can be removed? → 2. What can be simplified? → 3. What's the blast radius? → 4. One clear owner per decision |
| **Research / Investigation** | Search First | Don't reinvent | 1. Search codebase → 2. Search docs → 3. Search web → 4. Synthesize → 5. Only then form opinion |
| **Architecture / Design** | Working Backwards | Start from the user | 1. Write the ideal usage → 2. Define the interface → 3. Design the implementation → 4. Identify risks |
| **Performance** | Measure First | No premature optimization | 1. Profile/benchmark → 2. Identify bottleneck → 3. Hypothesize fix → 4. Implement → 5. Measure again |
| **Deploy / Ops** | Closed Loop | Every action has verification | 1. Pre-check → 2. Execute → 3. Verify → 4. Monitor → 5. Rollback plan ready |
| **Refactor** | Preserve Behavior | Tests are the contract | 1. Ensure tests pass → 2. Refactor one thing → 3. Tests pass again → 4. Repeat |

## Failure-Mode → Methodology Switch

When the current approach isn't working, switch methodology based on the failure pattern:

| Failure Pattern | Signal | Switch To |
|----------------|--------|-----------|
| Same error repeating | 3+ identical errors | RCA — you misidentified the root cause |
| Different error each time | Error changes per attempt | First Principles — isolate ONE variable, change ONE thing |
| No progress, going in circles | Loop detector fires | Working Backwards — re-derive what "done" looks like |
| Giving up, deflecting | "I can't", "environment issue" | Search First — you are missing information |
| Code works but wrong approach | Works but fragile/complex | Subtraction — what can you remove? |
| Performance issue | "It's slow" without numbers | Measure First — profile before guessing |

## Integration with Cognitive Modes

This router supplements, not replaces, the cognitive mode system:

- **direct** mode: no methodology injection (task is trivial)
- **react** mode: inject the methodology matching the task type
- **hypothesis** mode: always use RCA methodology
- **designer** mode: always use Working Backwards methodology

## Usage in Dispatch

When the Governor dispatches a task, append the relevant methodology to the task prompt:

```
[Methodology: {name}]
{Core Principle}
Steps: {numbered steps}
```

Keep injection under 100 tokens. The methodology is a compass, not a manual.
