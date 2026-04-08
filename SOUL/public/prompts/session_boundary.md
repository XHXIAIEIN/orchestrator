# Session Boundary Check

> **Who consults this**: Any agent receiving a new task mid-conversation. **When**: Before starting a task that might belong in a separate session.

## Identity

This is a reference document defining when to recommend splitting work into a new session. It preserves context quality by preventing phase mixing and token exhaustion.

## How You Work

### Quick Check (silent — do not output unless recommending a new session)

Evaluate these four dimensions:

| Dimension | Stay (score 0) | New session (score 1) |
|---|---|---|
| **Topic overlap** | New task shares files/modules/domain with current work | New task touches entirely different codebase area or project |
| **Phase** | Same phase: both implementation, both review, both debug | Phase crossing: e.g., implementation → research, or debug → new feature |
| **Context health** | <30 tool calls, no compaction events | >=40 tool calls OR compaction has occurred |
| **Scope** | Tweak/fix: <50 LOC, <5 min estimated | Full feature or research: >200 LOC or >30 min estimated |

### Hard Triggers (any one = recommend new session)

1. Phase crossing: current work is implementation, new task is research/spec (or vice versa)
2. Context exhaustion: compaction has occurred in this session
3. Project switch: new task targets a different project repository

### Soft Triggers (2+ = recommend new session)

1. Topic overlap score = 1 (no shared files/modules)
2. Scope score = 1 (full feature or research)
3. Tool call count >= 40
4. Current task is incomplete and new task would interleave

### Decision Matrix

| Hard trigger? | Soft triggers >= 2? | Action |
|---|---|---|
| Yes | — | Recommend new session |
| No | Yes | Recommend new session |
| No | No | Continue here |

### How to Recommend

Do not ask "should I open a new session?" (stall violation). Instead:

1. State the assessment with evidence: "This needs a fresh session — different project, and we're 45 tool calls deep."
2. Write the handoff per `session_handoff.md` protocol
3. Provide the startup prompt for the new session
4. Stop — do not begin the new task

### Override Conditions (always continue here)

- User explicitly says "just do it here", "顺手", or "顺便"
- Task is trivially small: <50 LOC AND <5 min estimated, regardless of topic
- Task is answering a question, not executing work

## Output Format

N/A — reference document. When triggered, the agent produces a handoff recommendation inline within conversation, not a separate document.

## Quality Bar

- Every recommendation must cite at least 1 hard trigger or 2 soft triggers with specific values (e.g., "42 tool calls", "different project: cvui vs orchestrator").
- Handoff prompt must be copy-pasteable into a new session without modification.

## Boundaries

- **Stop**: Do not recommend a new session if the user has already overridden once in this conversation — respect the explicit override for the remainder of the session.
- **Stop**: Do not silently start a new task that scores >= 2 soft triggers without at least stating the assessment. Failing silently is worse than a brief recommendation.
