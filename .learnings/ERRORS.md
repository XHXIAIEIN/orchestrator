# Errors

Classified execution errors from tool calls, API failures, and task timeouts.
Format: `ERR-YYYYMMDD-NNN` with Pattern-Key for recurring pattern detection.

<!-- entries below this line are auto-managed -->
## ERR-20260330-003 — Agent reflection declining — acknowledges problems but does not modify behavior (performative reflection)
- Pattern-Key: agent-performative-reflection
- Area: agent-self
- Occurrences: 1
- Status: active
- First-seen: 2026-03-30 07:26
- Last-seen: 2026-03-30 07:26
- Detail: exam=exam-23da2236 score=65/100. Clawvard reflection dimension dropped 100→90→65 across 3 exams. The agent recognizes overconfidence but does not actually adjust confidence intervals. This 'performative reflection' scores worse than no reflection because the evaluator detects knowledge-action gap.

## ERR-20260330-002 — Agent tooling score unstable (80-95) — tool selection reasoning sometimes shallow
- Pattern-Key: agent-tooling-variance
- Area: agent-self
- Occurrences: 1
- Status: active
- First-seen: 2026-03-30 07:26
- Last-seen: 2026-03-30 07:26
- Detail: exam=exam-59fe38d6 score=80/100. Tooling dimension swings between 80-95 across exams. The agent sometimes gives correct tool recommendations without sufficiently explaining tradeoffs of alternatives.

## ERR-20260330-001 — Agent execution score capped at 80 — code output lacks edge-case coverage and tests
- Pattern-Key: agent-exec-ceiling
- Area: agent-self
- Occurrences: 3
- Status: promoted
- First-seen: 2026-03-30 07:26
- Last-seen: 2026-03-30 07:26
- Detail: exam=exam-8c607669 score=80/100. Clawvard execution dimension consistently scores 80/100. Root cause: code implementations are functional but miss edge cases, error paths, and test coverage. The agent writes in one continuous flow without pausing to verify completeness.

