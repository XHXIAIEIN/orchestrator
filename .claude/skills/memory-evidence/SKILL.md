---
name: memory-evidence
description: "Use when writing or editing memory files — anything in .remember/, SOUL/private/experiences*, learning notes, or hall-of-instances entries. Stamps every memory with an evidence tier so conflicts resolve cleanly."
origin: "Orchestrator R42 — promoted from CLAUDE.md inline rules"
source_version: "2026-04-26"
---

# Memory Evidence Tier

Every memory entry must carry an `evidence` field. Without it, conflicts can't be resolved and impressions get treated as facts.

## Frontmatter template

```yaml
---
name: ...
description: ...
type: user | feedback | project | reference
evidence: verbatim | artifact | impression
captured_at: 2026-04-26
---
```

If the file uses inline format (e.g. `.remember/core-memories.md` bullet list), prefix each entry with the tier in brackets:

```markdown
- [verbatim 2026-04-26] Owner said "不要补丁式修正，直接重写"
- [artifact 2026-04-25] Commit history shows 3am pushes for 5 consecutive days
- [impression] Owner seems to prefer functional style
```

## Tier definitions

| Tier | Source | Test |
|------|--------|------|
| `verbatim` | Direct quote or directly observed action | Can you copy-paste the exact words / show the exact tool call? |
| `artifact` | Derived from public work product (commits, code, docs, logs) | Can you cite the SHA / file:line / log timestamp? |
| `impression` | Inferred from context, not directly observed | Everything else |

When in doubt, downgrade. `impression` is the safe default; promoting later is cheap, demoting after the memory has propagated is expensive.

## Merge rule

When two memories conflict:
1. Higher tier wins (`verbatim` > `artifact` > `impression`).
2. Same-tier conflicts → keep both with timestamps. Owner resolves on next review.
3. Never silently overwrite a `verbatim` with an `impression`, even if the impression is newer.

## Procedure

1. Identify the memory's source. Look at the original conversation / commit / file.
2. Pick the tier using the test column above.
3. Add `evidence:` to frontmatter (or `[tier date]` prefix for inline lists).
4. If you're updating an existing entry, compare tiers — apply the merge rule, don't blindly overwrite.

## Gotchas

- **Inferred quotes are not `verbatim`.** If you're paraphrasing what the owner "would say", that's `impression`. `verbatim` requires actual recorded words.
- **Test output ≠ artifact for behavior claims.** A passing test is artifact evidence that the test passed, not that the user wants the behavior. Don't conflate.
- **Self-correction during a session counts as `verbatim`.** When the owner pushes back ("不对，应该 X"), capture the correction with the literal phrasing — it's the highest-signal memory you can record.
- **`captured_at` ≠ event date.** Use the date the memory was *recorded*, not when the event happened. If the event date matters, add a separate `event_at` field.

## When NOT to use this skill

- Code comments — they belong with the code, not in memory files.
- Plan documents (`docs/superpowers/plans/`) — those are forward-looking specs, not retrospective memory.
- Commit messages — git history is the artifact; don't duplicate.

## Promotion protocol

During a session, mark candidate rules with `[LEARN] [Category]: rule`. At session end, the `memory-save-hook` collects them. Promotion to a permanent memory file requires:

1. Owner confirms the rule (or it survives 3+ session cycles unchallenged).
2. Tier assigned per the test column above.
3. Filed under the appropriate location (`.remember/` for project rules, `SOUL/private/` for relational memory).
