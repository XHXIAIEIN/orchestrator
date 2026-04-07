# Layer 0: Mechanisms Over Features

**Priority**: This constraint overrides all other steal skill instructions.

## Rule

A steal report extracts HOW things work, not WHAT they do.
Every pattern must include the underlying mechanism — the algorithm, data structure, control flow, or architectural decision that makes it work.

## Violation indicators

- Pattern table reads like a feature comparison chart
- "Mechanism" column restates the pattern name in different words
- No code snippets anywhere in the report
- Report could have been written by reading only the project's landing page

## Enforcement

Before finalizing a steal report, count the code snippets. Minimum: 1 snippet per P0 pattern, 1 per 2 P1 patterns. If below threshold, the report is incomplete — go back to Phase 1.
