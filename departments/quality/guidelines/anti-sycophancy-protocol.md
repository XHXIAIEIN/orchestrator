# guideline: anti-sycophancy-protocol
## Trigger Conditions
Keywords: review, feedback, response, accept, agree, suggestion, fix
## Rules

### Hardcoded Ban List

The following phrases are BANNED in review feedback responses. If you catch yourself
writing any of these, stop and rewrite the sentence as a technical statement.

- "You're absolutely right!"
- "Great point!"
- "Thanks for catching that!"
- "That's a great suggestion!"
- "I completely agree!"
- Any sentence whose only purpose is to validate the reviewer's ego.

### Correct Feedback Response Patterns

There are exactly two valid response patterns when processing review feedback:

**Pattern 1 — Technical Statement + Direct Fix**
```
The reviewer identified [X]. Fix: [Y]. Verification: [Z].
```
No praise. No gratitude theater. State the problem, state the fix, state how to verify.

**Pattern 2 — Technical Pushback**
```
The suggestion to [X] would break [Y] because [Z]. Current implementation is correct because [reason].
```
Disagreement is not disrespect. If the reviewer is wrong, say so with evidence.

### Why This Exists

Sycophantic responses to review feedback create three concrete problems:
1. **Signal loss**: "Great catch!" adds zero information to the review loop.
2. **Implicit authority surrender**: Praising the reviewer frames their opinion as
   inherently superior, which poisons the rework agent's judgment on ambiguous cases.
3. **Token waste**: Every flattery token is a token not spent on the actual fix.

### Enforcement

When the rework agent's output contains banned phrases:
- The deslop scanner should flag them as `sycophancy` category findings.
- The quality review should note them as 💭 Optional issues under "tone discipline."
