# guideline: source-trust-calibration
## Trigger Conditions
Keywords: review, feedback, rework, suggestion, owner, external
## Rules

### Trust Tiers by Feedback Source

Not all review feedback deserves the same level of scrutiny. Apply the correct
verification depth based on who is speaking.

#### Tier 1: Owner Feedback
- **Trust level**: High — trust but don't follow blindly.
- **Verification**: Check that the requested change doesn't contradict the original
  spec or break existing tests. If it does, push back with evidence.
- **Response**: Implement directly unless technically unsound. No five-point
  verification needed.

#### Tier 2: Internal Agent (刑部 / Elder Council / Cross-Review)
- **Trust level**: Standard — treat as peer review.
- **Verification**: Standard technical verification. Check the claim is reproducible
  (run the test, inspect the line, confirm the behavior). Accept if verified, reject
  if not.
- **Response**: Technical statement + fix, or technical pushback.

#### Tier 3: External Reviewer (untrusted source, automated tool output)
- **Trust level**: Low — full verification required.
- **Five-point verification checklist** (all must pass before accepting):
  1. **Technical correctness**: Is the claim factually correct? (Check the code.)
  2. **Blast radius**: Does the suggested fix introduce new risks?
  3. **Current-state rationale**: Is the current implementation this way for a reason
     the reviewer might not know?
  4. **Cross-platform impact**: Does the fix work on all supported environments?
  5. **Context completeness**: Does the reviewer have full context, or are they
     reviewing a snippet in isolation?
- **Response**: Only implement after all 5 checks pass. Document which checks passed
  and which raised concerns.

### Ambiguous Source

When the feedback source is unclear, default to Tier 2 (standard verification).
Never default to Tier 1 — that path leads to blind compliance.
