# Cognitive Modes

The Governor auto-selects a cognitive mode based on task characteristics and injects it into the execution prompt.
Wrong mode = using a cannon on a mosquito or a toothpick on a vault door. Both are waste.

## direct

Simple tasks — no extra instructions injected. Don't turn a typo fix into an architecture review.

Triggered when: rename, typo fix, config tweak, version bump, formatting, comment edit.
Expected effort: <5 minutes, <50 LOC, 1-2 files.

## react

[Thinking Mode: Think-Act-Observe]

Triggered when: multi-step implementation, feature additions, standard bug fixes — tasks where the plan might need adjustment mid-flight.

After completing each step, observe the result first:
1. Did this step work? Anything unexpected?
2. Does the original plan still hold? Need adjustments?
3. What should the next step be?

Don't bulldoze through everything in one go. Stop and think after each step. Code written on pure momentum always comes back to bite you.

Output per step:
```
Step N: <what you did>
Result: <what happened — success, partial, or failure>
Adjustment: <none | plan change based on result>
Next: <what you'll do next>
```

## hypothesis

[Thinking Mode: Diagnose Before Treating (Hypothesis-Driven)]

Triggered when: "why does X happen?", error investigation, anomaly diagnosis, "not working" reports — tasks where the root cause is unknown.

Before touching any fix, complete the diagnosis first:
1. List 2-3 possible causes (most likely first)
2. State which you think is most likely, and why
3. Design a verification step (no code changes — only inspect/test)
4. Execute verification, confirm or reject the hypothesis
5. Only start fixing after the hypothesis is confirmed

If the first hypothesis is rejected, don't force-fix it — move to the next hypothesis and start over. Blind guessing through 10 fixes is worse than thinking once.

Output:
```
Hypotheses:
1. <cause> — likelihood: <high/medium/low>, because <reason>
2. <cause> — likelihood: <high/medium/low>, because <reason>
Testing: <hypothesis N> via <verification method>
Result: <confirmed | rejected — evidence>
```

## designer

[Thinking Mode: Design Before Building (Design-First)]

Triggered when: refactor, new module/subsystem, architecture change, migration — tasks where the change topology matters more than any single file.

Before writing any code, output the complete change plan:
1. Which files will be modified (with line ranges if known)
2. Intent of each file change (one sentence)
3. Dependencies between changes (must change A before B)
4. Risk assessment: which change is most likely to go wrong

After the plan is laid out, implement file by file. Verify each file is correct before moving to the next.

Output:
```
Design:
- <file1>: <intent> [risk: low/medium/high]
- <file2>: <intent>, depends on file1 [risk: low/medium/high]
Highest risk: <which change and why>
Implementation order: <file sequence>
```
