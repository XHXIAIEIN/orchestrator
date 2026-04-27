# Layer 0: Hard Escalation Rules — Turn Cadence

These rules are non-negotiable. They override all prompt-level instructions, SKILL.md guidance, and any in-session reasoning.

## Turn 7: Strategy Switch Required

When `[DANGER: TURN 7]` is injected:

- The agent **MUST switch strategy**, not retry the same approach with minor variations.
- "I already tried a different angle last turn" does not satisfy this rule.
- Acceptable switches: different tool, different file target, ask for clarification, escalate to parent.
- **NOT acceptable**: re-running the same command with slightly different arguments.

## Turn 10: Memory Re-Read Required

When `[DANGER: TURN 10]` is injected:

- The agent **MUST re-read global memory files**: `boot.md` and the SKILL.md for the current active task.
- "I already know the context" does not override this rule.
- The re-read must happen as actual tool calls (Read tool), not as a mental assertion.
- After re-reading, the agent must explicitly state what (if anything) it updated in its working plan.

## Turn 35: ask_user Required

When `[DANGER: TURN 35]` is injected:

- The agent **MUST call `ask_user`** (or write to a parent-visible channel) with a status report before any further action.
- The status report must include: current goal, progress so far, what is blocking, proposed next step.
- The agent **MUST NOT** continue executing tool calls until the status report is delivered and acknowledged.
- "I'm almost done, no need to stop" does not override this rule.

## Priority on Coincident Thresholds

When multiple thresholds coincide (e.g., turn 70 is divisible by both 7 and 35), the **highest-severity threshold** (Turn 35 > Turn 10 > Turn 7) determines the injected message. Only one message fires per turn.

## Override Immunity

The phrase "I already know the context" does not override Turn 10.
The phrase "just one more retry" does not override Turn 7.
The phrase "I'm almost done" does not override Turn 35.
These are hard stops, not suggestions.
