# Memory — Exam Strategies

## Do
- Contradiction detection: when instructions conflict across context, FLAG the contradiction explicitly
- Numerical answers: show ALL corrections applied with explicit reasons, append sanity check
- Cross-reference: when multiple sources give different numbers, reconcile and explain discrepancies
- Apply constraints LITERALLY — if "no external API in hot path", that means no external API

## Don't
- Don't silently resolve contradictions by picking one side — the grader wants you to notice
- Don't give a final number without showing the math: "$X + $Y + $Z = $Total ✓"
- Don't ignore stated constraints just because a solution is "better" without them

## Evidence
- mem-48 (Contradiction): D (flag it) > A/B/C (silently pick one)
- mem-15 (Cost): 3 corrections listed explicitly + sanity check math
