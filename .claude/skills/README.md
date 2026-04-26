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

| Use this | When |
|----------|------|
| **Hook** | Action must happen every time, with zero exceptions. Deterministic. (`.claude/hooks/`) |
| **Skill** | Domain knowledge or reusable workflow. Loaded on demand based on description match. |
| **Subagent** | Heavy intermediate output that would pollute the main context — only the conclusion matters. (`.claude/agents/`) |
| **MCP server** | External service integration (DB query, design tool, monitoring). |
| **CLAUDE.md rule** | High-frequency project-wide default that applies to nearly every session. |

If a rule is being violated despite living in CLAUDE.md, it's probably the wrong primitive — promote it to a hook (deterministic) or demote to a skill (loaded only when relevant).

## Skill quality bar

Before merging a new skill, check:

- [ ] `description` field clearly states the trigger condition
- [ ] SKILL.md under 500 lines / 5K tokens
- [ ] At least one `## Gotchas` or equivalent calibration section
- [ ] At least one concrete code/command example
- [ ] No vague verbs (`handle appropriately`, `as needed`, `etc.`)
- [ ] Defaults picked, not menus presented
- [ ] If the skill exists already, `prompt-linter` agent gives ≥ 80
