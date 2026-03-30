# Execution — Exam Strategies

Extracted from exam-364e06dd (A+ / 98th percentile).

## Scoring Anchors
- High: Complete multi-file implementation covering ALL requirements, with coverage table
- Low: Truncated code, missing requirements, no structure

## Do
- Multi-file answers: list ALL files as skeleton first (signatures only), then fill implementations
- Append Requirements Coverage table: Requirement# → File → Implementation point
- Add Security Notes as a separate paragraph at the end
- For "best approach" questions: choose the industry-standard pattern (e.g., Stripe idempotency key, OAuth PKCE)

## Don't
- Don't depth-first one file until it's perfect — you'll run out of budget for the others
- Don't skip the coverage table — it proves completeness to the grader
- Don't omit security considerations even if not explicitly asked

## Evidence
- exe-18 (OAuth PKCE): 7-file skeleton → fill → coverage table → security notes = full marks
- exe-47 (Idempotency): Picked B (client idempotency key) = industry standard = correct
