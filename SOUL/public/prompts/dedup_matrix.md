# Deduplication Decision Matrix

> **Who consults this**: Any agent creating or updating skills, memory files, experience entries, or learnings. **When**: Before writing any persistent knowledge entry.

Source: Claudeception (Round 36c steal)

## Identity

This is a reference document that prevents knowledge bloat from unchecked accumulation. It defines the lookup-before-write protocol for all persistent storage.

## How You Work

### Decision Table

Before creating a new entry, search existing entries and match against this table:

| Scenario | Match Signal | Action |
|----------|-------------|--------|
| **No overlap** | No existing entry covers this topic | Create new entry |
| **Same trigger, same fix** | Existing entry solves the exact same problem | Update existing entry (bump version/date) |
| **Same trigger, different root cause** | Same symptom, different solution | Create new entry + add bidirectional `See also:` links |
| **Partial overlap (60-80%)** | Existing entry covers most of this | Update existing entry, add "Variant" subsection |
| **Same domain, different problem** | Related topic but distinct issue | Create new entry + add `See also:` link |
| **Outdated** | Existing entry is stale or factually wrong | Mark existing as `deprecated` + create replacement with backlink |

### Quality Gate (all 4 must pass before saving)

| Check | Test | If fail |
|-------|------|---------|
| **Reusable** | Will this help in a future conversation (not just this one)? | Skip — ephemeral knowledge does not belong in persistent storage |
| **Non-trivial** | Can this be derived from `git log`, `grep`, or reading the code? | Skip — don't duplicate what existing tools provide |
| **Specific** | Does it have a precise trigger condition (not "when debugging")? | Rewrite with exact trigger: error message, file pattern, or symptom |
| **Verified** | Was the solution tested and confirmed working? | Defer — tag as `unverified` and revisit. Unverified knowledge misleads. |

### Application Scope

This matrix applies to:
- Memory files (`MEMORY.md` index + individual memory files)
- Skill files (`.claude/skills/*/SKILL.md`)
- Experience entries (`experiences.jsonl`)
- Learnings (`.claude/context/learnings.md`)
- Steal patterns (`docs/steal/` — dedup against existing patterns before adding)

## Output Format

N/A — reference document. This matrix governs the write decision; it does not produce standalone output. The agent applies the decision table silently and proceeds with the chosen action (create / update / skip / defer).

## Quality Bar

- Every new entry must pass all 4 quality gate checks. No exceptions.
- Every update must include a date bump in frontmatter.
- `See also:` links must be bidirectional — if A links to B, B must link to A.

## Boundaries

- **Stop** if you cannot find the existing entries to search against (e.g., memory index is missing or corrupt) — report the issue rather than writing a potentially duplicate entry.
- **Stop** if an entry fails the "Verified" check and the fix involves security-sensitive operations — do not persist unverified security guidance.

### Anti-Patterns (self-check before saving)

- **Append-only accumulation**: Adding without searching for overlap → index grows unbounded
- **Stale entries**: Never updating outdated information → misleading retrievals
- **Vague descriptions**: Generic entries matching too many queries → noise drowns signal
- **Duplicate with drift**: Same knowledge saved twice with different wording → inconsistent advice
