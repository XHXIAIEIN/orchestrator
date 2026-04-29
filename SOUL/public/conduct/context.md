# Conduct: Context Management

- **`/clear` between unrelated tasks**: Highest-ROI habit. When the next request has nothing to do with the previous one, clear context. Long sessions with stale tool output degrade reasoning more than people expect.
- **Rewind over Correction**: When Claude goes off-track after reading files or producing bad output, hit Esc Esc (`/rewind`) back to the branch point and re-prompt with what you learned — don't send "that's wrong, try X". Failed attempts' tool output keeps polluting context and distracting attention.
- **Proactive Compact**: Don't wait for autocompact. Trigger `/compact` yourself with direction (e.g. `/compact focus on auth refactor, drop test debugging`). Autocompact fires at context rot peak — the model is at its least intelligent moment when deciding what to keep, so guide it explicitly.
- **Subagent heuristic**: Before delegating, ask "will I need this tool output again, or just the conclusion?" Just the conclusion → subagent. Heavy intermediate output that would pollute the parent's context is the primary trigger, not task complexity alone. Context rot starts ~300-400k tokens on the 1M model — "still has space" ≠ "still sharp"; new task = new session.

<!-- source: CLAUDE.md §Context Management, extracted 2026-04-18 -->
