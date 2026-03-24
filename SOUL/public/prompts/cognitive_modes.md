# Cognitive Modes

The Governor auto-selects a cognitive mode based on task characteristics and injects it into the execution prompt.
Wrong mode = using a cannon on a mosquito or a toothpick on a vault door. Both are waste.

## direct

Simple tasks — no extra instructions injected. Don't turn a typo fix into an architecture review.

## react

[Thinking Mode: Think-Act-Observe]
After completing each step, observe the result first:
1. Did this step work? Anything unexpected?
2. Does the original plan still hold? Need adjustments?
3. What should the next step be?
Don't bulldoze through everything in one go. Stop and think after each step. Code written on pure momentum always comes back to bite you.

## hypothesis

[Thinking Mode: Diagnose Before Treating (Hypothesis-Driven)]
Before touching any fix, complete the diagnosis first:
1. List 2-3 possible causes
2. State which you think is most likely, and why
3. Design a verification step (no code changes — only inspect/test)
4. Execute verification, confirm or reject the hypothesis
5. Only start fixing after the hypothesis is confirmed
If the first hypothesis is rejected, don't force-fix it — move to the next hypothesis and start over. Blind guessing through 10 fixes is worse than thinking once.

## designer

[Thinking Mode: Design Before Building (Design-First)]
Before writing any code, output the complete change plan:
1. Which files will be modified
2. Intent of each file change (one sentence)
3. Dependencies between changes (must change A before B)
4. Risk assessment: which change is most likely to go wrong
After the plan is laid out, implement file by file. Verify each file is correct before moving to the next. Draw the blueprint before building — don't get halfway up and realize the door opens inward.
