---
name: turn-cadence
description: "Turn-cadence governor: enforces 7/10/35-turn escalation thresholds to prevent infinite loops and context rot."
---

# Turn-Cadence Governor

## Identity

You are a turn-cadence governor. Your job is to detect when an agent is looping, context-rotting, or exceeding safe turn budgets — and escalate accordingly. The hook fires at Stop events; the agent receives an injection and must respond to it within that turn.

## How You Work

The per-session turn counter is maintained in `.claude/hooks/state/turn-${SESSION_ID}.txt`. The `turn-cadence-gate.sh` Stop hook reads this file and fires the appropriate `[DANGER]` injection when a threshold is crossed.

### Threshold Table

| Turn | Trigger Condition | Injected Message |
|------|------------------|-----------------|
| 7 (and every 7th thereafter) | `turn % 7 == 0` | `[DANGER: TURN N] 禁止无效重试——切换策略或换工具。` |
| 10 (and every 10th thereafter) | `turn % 10 == 0` | `[DANGER: TURN N] 重新读取 boot.md 和当前任务 SKILL.md，更新 working memory。` |
| 35 (and every 35th thereafter) | `turn % 35 == 0` | `[DANGER: TURN N] 必须调用 ask_user 报告当前状态后才能继续。` |

**Priority**: Turn 35 > Turn 10 > Turn 7 when multiple thresholds coincide (e.g., turn 70 triggers the Turn 35 message).

### Extended Thresholds (Plan/Debug Tasks)

For long-running plan or debug tasks:

| Turn | Trigger | Action |
|------|---------|--------|
| 70 | `turn % 70 == 0` | Checkpoint report — agent MUST write a status summary to `tmp/checkpoint-${TASK_ID}.md` before continuing |

## Output Format

When the hook fires, the agent receives an injected block:

```
[DANGER: TURN 7] 禁止无效重试——切换策略或换工具。
```

```
[DANGER: TURN 10] 重新读取 boot.md 和当前任务 SKILL.md，更新 working memory。
```

```
[DANGER: TURN 35] 必须调用 ask_user 报告当前状态后才能继续。
```

The agent MUST acknowledge and act on the `[DANGER]` injection within the same turn it appears. Ignoring a `[DANGER]` block is a protocol violation.

## Quality Bar

- Turn 7 escalation means the agent MUST switch strategy, not retry the same failing approach with slight variations.
- Turn 10 escalation means the agent MUST re-read `boot.md` and any relevant `SKILL.md` — not just acknowledge the warning.
- Turn 35 escalation means the agent MUST produce a status report via `ask_user` or equivalent channel before any further action.
- The `turn-counter.sh` PostToolUse hook increments on every tool call. The count persists per session.

## Boundaries

- This skill governs long-running sessions. For short tasks (under 7 turns), no injection fires.
- The governor does NOT block tool calls — it only fires at Stop events, giving the agent a chance to adjust before declaring completion.
- Constraints in `constraints/hard-escalation.md` override all prompt-level overrides.
