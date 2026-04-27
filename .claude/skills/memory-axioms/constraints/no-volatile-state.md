# Constraint: No Volatile State in Memory Writes

**Layer**: 0 — non-negotiable. Overrides SKILL.md and CLAUDE.md when memory-axioms skill is active.

## HARD BLOCK Rule

Any memory write whose content matches the following regex MUST be rejected:

```
\b(PID|pid|\d{5,}|session[-_]id|/tmp/|localhost:\d{4,}|127\.0\.0\.1:\d{4,}|0\.0\.0\.0:\d{4,}|[A-Z]:\\Users\\[^\\]+\\AppData\\Local\\Temp)\b
```

### Pattern breakdown

| Pattern | What it catches | Why it's volatile |
|---------|-----------------|-------------------|
| `\b(PID\|pid)\b` | Process ID labels | Reassigned every process start |
| `\b\d{5,}\b` | 5+ digit numbers | Likely PIDs, ports, sequence IDs |
| `\bsession[-_]id\b` | Session ID labels | Per-CLI-invocation identifier |
| `/tmp/` | Unix temp paths | Cleared on reboot |
| `localhost:\d{4,}`, `127\.0\.0\.1:\d{4,}`, `0\.0\.0\.0:\d{4,}` | Ephemeral local services | Port reassignment, machine-specific |
| `[A-Z]:\\Users\\...\\Temp` | Windows temp paths | User-scoped, ephemeral |

## Enforcement

The agent must remove volatile references before retrying the write.

**This is not a prompt suggestion — it is a pre-write validation rule.**

- No "just this once" exceptions.
- No "the user will know what I mean" reasoning.
- No "I'll clean it up later" deferrals.

## Allowed alternatives

| Volatile | Replace with |
|----------|--------------|
| `PID 47291` | `orchestrator container` (service role) |
| `session-cli-1745719847-12345` | `current session` (or omit — sessions are ephemeral by definition) |
| `/tmp/foo.json` | `temp/foo.json` (project-relative) or skip |
| `localhost:5432` | `the postgres service in docker-compose.yml` |
| `2026-04-27 03:14:07` (as identifier) | commit hash or feature name |

## Bypass paths

There is **one** legitimate bypass: when the volatile string is the actual subject of the memory entry.

Example:
- ❌ "Bug: server keeps crashing on PID 47291" — the PID is incidental
- ✅ "Hook output included literal `[session-id: abc-123]` in stderr — verified by `grep` on hook log file `data/hooks.log`" — the session ID is the artifact under discussion, AND the entry has artifact-level evidence.

The bypass only applies when:
1. The volatile string is verbatim quoted (in `code` formatting), AND
2. The entry has `evidence: verbatim` or `evidence: artifact` frontmatter, AND
3. The verbatim source persists (committed log file, not in-memory output).

If any of the three fails → no bypass → reject.
