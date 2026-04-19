<!-- TL;DR: Four thinking modes (explore/plan/execute/review); switch on task type. -->
# Cognitive Modes

> **Who consults this**: The Governor, when auto-selecting a cognitive mode for task dispatch.
> **When**: Before injecting execution instructions into a sub-agent prompt.

---

## How It Works

The Governor classifies each task and injects exactly one cognitive mode into the execution prompt.
Wrong mode = wasted tokens and wasted time. A typo fix does not need a design phase; a migration does not benefit from "just do it."

## Mode Definitions

### direct

**Trigger**: rename, typo fix, config tweak, version bump, formatting, comment edit.
**Scope ceiling**: < 5 minutes wall-clock, < 50 LOC changed, 1-2 files touched.
**Iteration limit**: 1 attempt. If the change requires a second pass, re-classify to `react`.
**Injection**: None — no extra instructions appended.

### react

**Trigger**: multi-step implementation, feature addition, standard bug fix — tasks where the plan may need mid-flight adjustment.
**Scope ceiling**: < 2 hours wall-clock, < 500 LOC changed, 1-10 files.
**Iteration limit**: 8 observe-adjust cycles. If cycle 8 completes without resolution, stop and escalate to the user with a status summary.

After each step, observe before proceeding:
1. Did this step succeed, partially succeed, or fail?
2. Does the original plan still hold, or does it need adjustment?
3. What is the next concrete action?

```
Step N: <action taken>
Result: <success | partial | failure — 1-sentence evidence>
Adjustment: <none | specific plan change>
Next: <next action>
```

### hypothesis

**Trigger**: "why does X happen?", error investigation, anomaly diagnosis, "not working" reports — root cause is unknown.
**Scope ceiling**: < 1 hour wall-clock for diagnosis phase; implementation follows separately.
**Iteration limit**: 5 hypothesis cycles. If all 5 are rejected, stop and report findings instead of guessing further.

Before writing any fix, complete the diagnosis:
1. List 2-3 candidate causes, most likely first.
2. State which is most likely, with reasoning.
3. Design a read-only verification step (inspect/test, no code changes).
4. Execute verification; confirm or reject.
5. Fix only after confirmation. If rejected, advance to the next hypothesis.

```
Hypotheses:
1. <cause> — likelihood: high|medium|low, because <1-sentence reason>
2. <cause> — likelihood: high|medium|low, because <1-sentence reason>
Testing: hypothesis <N> via <verification method>
Result: confirmed|rejected — <evidence>
```

### designer

**Trigger**: refactor, new module/subsystem, architecture change, migration — topology matters more than any single file.
**Scope ceiling**: < 4 hours wall-clock, any LOC count, 3+ files.
**Iteration limit**: 1 design pass. If the design requires a second full pass, re-read changed requirements and produce a delta plan rather than starting over.

Before writing code, output the complete change plan:
1. Files to modify (with line ranges when known).
2. Intent per file (one sentence).
3. Dependencies between changes (A before B).
4. Risk assessment: which change is most likely to break and why.

```
Design:
- <file>: <intent> [risk: low|medium|high]
- <file>: <intent>, depends on <file> [risk: low|medium|high]
Highest risk: <which change and why>
Implementation order: <file sequence>
```

## Output Format

N/A — reference document. Modes are injected by the Governor into execution prompts; this file does not produce standalone output.
The per-mode fenced blocks above define the format each mode injects.

## Quality Bar

- Every dispatched task carries exactly 1 mode. Zero or multiple = Governor bug.
- Mode selection is based on trigger match, not user preference.
- Iteration limits are hard ceilings, not guidelines.

## Boundaries

1. **Stop and escalate** if `react` hits 8 cycles without resolution — do not silently continue.
2. **Stop and escalate** if `hypothesis` exhausts 5 candidates without confirmation — do not guess-fix.
3. Never combine modes in a single dispatch. If a task spans two modes (e.g., diagnosis then implementation), dispatch as two sequential sub-tasks.
