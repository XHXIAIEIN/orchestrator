# Skills — Layout & Authoring Rules

This directory holds per-skill capability bundles. Each skill is a self-contained unit with its own SKILL.md, optional constraints, and reference material.

## Layout

```
.claude/skills/<skill-name>/
├── SKILL.md            # Main skill definition (required, < 500 lines / < 5K tokens)
├── constraints/        # Layer 0 hard rules (optional)
│   └── *.md            # One file per inviolable constraint
├── references/         # Detail loaded on demand (optional)
│   └── *.md            # Long examples, edge case catalogs, etc.
├── scripts/            # Bundled tested scripts (optional)
└── assets/             # Templates, fixtures (optional)
```

## Priority order

When a skill is active, its rules win in this order:

1. **`constraints/*.md`** — non-negotiable. Override SKILL.md and CLAUDE.md.
2. **`SKILL.md`** — main instructions. Override CLAUDE.md general rules.
3. **`CLAUDE.md`** — project-wide defaults.

Constraints exist for failure modes that prompt-level "don't do X" cannot prevent (e.g. steal-work worktree isolation). Soft preferences stay in SKILL.md.

## Authoring SKILL.md

Follow [Anthropic skill best practices](https://agentskills.io/skill-creation/best-practices). Key rules:

- **Frontmatter is required**: `name`, `description`. Optional: `disable-model-invocation`, `tools`, `model`, `origin`, `source_version`.
- **Description is the trigger**: write it so the model knows *when* to load this skill. Bad: "Helper for X". Good: "Use when the owner asks to debug failing tests, reproduce a bug, or trace an unexpected exception."
- **Procedures over declarations**: teach the agent *how to approach* a class of problems, not what to produce for one instance.
- **Defaults not menus**: pick a default tool/approach, mention alternatives briefly. Don't list 5 equal options.
- **Calibrate specificity**: be prescriptive for fragile/destructive ops, give freedom where multiple approaches are valid.
- **Add gotchas**: environment-specific facts that defy reasonable assumptions. Highest-value section in most skills.
- **Provide templates** for output formats — agents pattern-match better against concrete structures than prose descriptions.
- **Progressive disclosure**: keep SKILL.md to core instructions. Move detail to `references/` and tell the agent *when* to load each ref file.
- **Cut what the agent already knows**: don't explain what HTTP is, what a PDF is, etc. Add only what's project-specific.

## Authoring constraints/

A constraint file is one rule, one page max. Format:

```markdown
# <Rule name>

**When this applies**: <trigger condition>

**The rule**: <imperative statement>

**Why**: <one sentence — the failure mode this prevents>

**Verify**: <command or check that proves compliance>
```

Example: `.claude/skills/steal/constraints/worktree-isolation.md`.

## When to create a skill vs other primitives

| Use this | When | Example |
|----------|------|---------|
| **Hook** | Action must happen every time, with zero exceptions. Deterministic. (`.claude/hooks/`) | `block-protect` enforcing identity iron rules; `dispatch-gate` blocking `[STEAL]` work outside `steal/*` branches |
| **Skill** | Domain knowledge or reusable workflow. Loaded on demand based on description match. | `verification-spec`, `memory-evidence`, `steal` |
| **Subagent** | Heavy intermediate output that would pollute the main context — only the conclusion matters. (`.claude/agents/`) | `reviewer` returning ranked findings; `engineer` dispatched into a worktree, main thread reads only the final commits |
| **MCP server** | External service integration (DB query, design tool, monitoring). | Future: SQLite query gateway, Qdrant inspector |
| **CLAUDE.md rule** | High-frequency project-wide default that applies to nearly every session. | Git Safety, Surgical Changes, Skill Routing pointer |

If a rule is being violated despite living in CLAUDE.md, it's probably the wrong primitive — promote it to a hook (deterministic) or demote to a skill (loaded only when relevant).

### Subagent dispatch test

Before calling `Agent(subagent_type=...)`, ask:

1. **Will the main thread need the intermediate output later?** Yes → don't dispatch, do it directly. The conversation context is the working memory.
2. **Is the work read-only research (audit, scan, review)?** Yes → dispatch makes sense (`analyst`/`inspector`/`reviewer`/`sentinel`/`verifier`).
3. **Is the work execution (writes/edits)?** Only dispatch if it runs in an isolated workspace (e.g. `isolation: "worktree"`) and the main thread truly only needs the final conclusion. Otherwise the main thread should execute and keep context coherent.

A subagent is **not** a way to offload "I don't feel like reading these files" — that just relocates the same work and adds a serialization round-trip.

## Subagent roster

Six project-local subagents live in `.claude/agents/`. Three out-of-the-box agents (`Plan`, `Explore`, `general-purpose`) and plugin agents (`codex:codex-rescue`, `prompt-maker:prompt-linter`) are also available.

| Agent | Type | Tools | When to dispatch |
|-------|------|-------|------------------|
| `analyst` | research, READ-ONLY | Read/Glob/Grep/Bash | Metrics scan, anomaly triage, baseline comparisons |
| `inspector` | research, READ-ONLY | Read/Glob/Grep | Doc rot, config drift, stale TODO sweeps |
| `reviewer` | research, READ-ONLY | Read/Glob/Grep | Code review with confidence-scored findings |
| `sentinel` | research, READ-ONLY | Read/Glob/Grep/Bash | Security audit (OWASP top 10 against this codebase) |
| `verifier` | research, runs tests but does not modify | Read/Glob/Grep/Bash | 5-step evidence chain before declaring completion |
| `engineer` | execution, **worktree-isolated only** | Read/Write/Edit/Bash/Glob/Grep/Agent | Steal pilots, worktree pipeline impl runs — see `SOUL/public/prompts/steal_pilot_dispatch.md` |

Retired (moved to `.trash/2026-04-26-gap3/`):
- `architect` — superseded by Plan Mode (Shift+Tab) for multi-file structural work; see `SOUL/public/prompts/skill_routing.md`.
- `operator` — infra ops belong on the main thread; the dispatcher needs the live state (container, DB, GPU) to make follow-up decisions, so isolation is a net loss.

## Skill quality bar

Before merging a new skill, check:

- [ ] `description` field clearly states the trigger condition
- [ ] SKILL.md under 500 lines / 5K tokens
- [ ] At least one `## Gotchas` or equivalent calibration section
- [ ] At least one concrete code/command example
- [ ] No vague verbs (`handle appropriately`, `as needed`, `etc.`)
- [ ] Defaults picked, not menus presented
- [ ] If the skill exists already, `prompt-linter` agent gives ≥ 80
