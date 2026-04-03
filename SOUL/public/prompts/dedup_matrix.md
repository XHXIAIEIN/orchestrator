# Deduplication Decision Matrix

When creating or updating skills, memory files, or knowledge entries, use this matrix to decide the correct action. Prevents knowledge bloat from unchecked accumulation.

Source: Claudeception (Round 36c steal)

## Decision Table

| Scenario | Match Signal | Action | Example |
|----------|-------------|--------|---------|
| **No overlap** | No existing entry covers this topic | **Create new** | New debugging pattern never seen before |
| **Same trigger, same fix** | Existing entry solves the exact same problem | **Update existing** (bump version/date) | Same error, better wording |
| **Same trigger, different root cause** | Same symptom leads to different solution | **Create new** + add bidirectional `See also:` | "Connection refused" — firewall vs service down |
| **Partial overlap** | Existing entry covers 60-80% of this | **Update existing**, add "Variant" subsection | Same pattern, different framework |
| **Same domain, different problem** | Related topic but distinct issue | **Create new** + add `See also:` | Both about Docker, but networking vs volumes |
| **Outdated** | Existing entry is stale or wrong | **Mark deprecated** + create replacement with link | API changed, old approach broken |

## Quality Gate (4 checks before saving)

Every new entry must pass ALL four:

| Check | Question | Fail → Action |
|-------|----------|---------------|
| **Reusable** | Will this help in future conversations? | Skip — ephemeral knowledge doesn't belong in persistent storage |
| **Non-trivial** | Can this be derived from reading the code or docs? | Skip — don't duplicate what `git log` or `grep` already provides |
| **Specific** | Does it have a precise trigger condition? | Rewrite — vague entries are never retrieved |
| **Verified** | Was the solution actually tested and confirmed? | Defer — unverified knowledge is worse than no knowledge |

## Application Scope

This matrix applies to:
- **Memory files** (`MEMORY.md` index + individual memory files)
- **Skill files** (`.claude/skills/*/SKILL.md`)
- **Experience entries** (`experiences.jsonl`)
- **Learnings** (`.claude/context/learnings.md`)
- **Steal patterns** (docs/steal/ — dedup against existing patterns before adding)

## Anti-Patterns

- **Append-only accumulation**: Adding entries without checking for overlap → index grows unbounded
- **Stale entries**: Never updating or removing outdated information → misleading retrievals
- **Vague descriptions**: Generic entries that match too many queries → noise drowns signal
- **Duplicate with drift**: Same knowledge saved twice with slightly different wording → inconsistent advice
