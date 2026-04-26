---
name: memto
description: "Query dormant past sessions as expert collaborators. Use when: need to recall a past decision or debate, want to ask 'what did we conclude about X in the R38 session', or want to compare answers across multiple historical sessions."
---

# memto — Session Expert Protocol

memto treats past Claude Code sessions as dormant collaborators. Instead of distilling facts, you fork the original session non-destructively, ask your question in the fork, then the fork is auto-cleaned up.

## When to Use

- User asks "what did we decide about X" and `.remember/` doesn't have it
- Need to verify a past architectural decision (e.g., "the R38 AutoAgent boundary debate")
- Want to ask the same question across N past sessions and surface disagreements

## Commands

List recent sessions matching a keyword:
```
memto list [--keyword <term>] [--top 10]
```

Ask a question across matching sessions (returns JSON for agent consumption):
```
memto ask "<keyword>" --question "<your question>" --top 3 --json
```

Ask a specific session by ID:
```
memto ask --session-id <id> --question "<your question>"
```

## Constraints

- Never modify original sessions — memto forks before querying
- Use `--json` when consuming output in code; omit for human-readable output
- `memto ask` spawns subprocesses and may take 30-120s per session; plan accordingly
- If `memto` is not installed: `npm install -g memto`
