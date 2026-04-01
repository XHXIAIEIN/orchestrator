# Session Boundary Check

When receiving a new task mid-conversation, evaluate whether it should be handled here or in a new session.

## Quick Check (do this mentally, don't output unless recommending new session)

1. **Topic overlap**: Does the new task share files/modules/domain with what we've been doing?
2. **Phase**: Are we staying in the same phase (all implementation, all review, etc.)?
3. **Context health**: How many tool calls so far? Has compaction happened?
4. **Scope**: Is this a tweak/fix (stay) or a full feature/research (new session)?

## Decision Matrix

| Hard trigger hit? | Soft triggers (2+)? | Action |
|---|---|---|
| Yes | — | Recommend new session |
| No | Yes | Recommend new session |
| No | No | Continue here |

## Rules for session-boundary.yaml

Read `config/session-boundary.yaml` for the full trigger definitions. The config is the source of truth — this prompt explains how to apply it.

## How to Recommend

Don't ask "should I open a new session?" (that's a stall violation). Instead:

1. State the assessment: "This task needs a fresh session — different domain, and we're 40+ tool calls deep."
2. Write the handoff immediately (per `session_handoff.md` protocol)
3. Give the startup prompt for the new session
4. Then stop — don't start the work

## When NOT to Trigger

- User explicitly says "just do it here" or "顺手" or "顺便" — respect the override
- Task is trivially small (<5 min, <50 LOC) even if topic is different
- You're just answering a question, not executing a task
