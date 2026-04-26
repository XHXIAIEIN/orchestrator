<!-- TL;DR: Scope rules to the narrowest applicable context; global rules are last resort. -->
# Rule Scoping by Path

> **Purpose**: Rules declare which file paths they apply to, instead of being global.
> Reduces noise: a frontend-specific rule doesn't fire when editing Python backend code.

## Identity

This is a reference for how rules should declare their scope. Agents and hooks consult
this when deciding whether a rule applies to the current task.

## How It Works

### Scope Declaration

Each rule (in CLAUDE.md, skill constraints, or hook configs) can declare an `applies_to` pattern:

```yaml
# In a constraint file or hook config
applies_to:
  - "src/channels/**/*.py"       # only channel code
  - "src/governance/**/*.py"     # only governance code
exclude:
  - "**/*_test.py"               # never test files
```

### Matching

- Uses glob patterns (same as `.gitignore`)
- No `applies_to` = global rule (backwards compatible)
- Multiple patterns = OR logic (matches any)
- `exclude` patterns override `applies_to`

### Scope Categories

| Scope | Pattern | When to use |
|-------|---------|-------------|
| Global | *(no applies_to)* | Safety rules, git rules, deletion rules |
| Module | `src/<module>/**` | Module-specific coding conventions |
| Layer | `src/channels/**`, `src/governance/**` | Layer-specific rules (e.g., "channels must not import governance") |
| File type | `**/*.md`, `**/*.yaml` | Format-specific rules (e.g., "YAML must have comments") |
| Skill | `.claude/skills/<name>/**` | Skill-specific constraints |

## Quality Bar

- Global rules: ≤ 20 (too many global rules = no rules)
- Module rules: unlimited, but each must justify its scope
- If a rule applies to > 3 modules, consider making it global

## Boundaries

- Safety rules (Gate Functions, guard hooks) are ALWAYS global — never scoped
- Rule scoping is advisory for prompt-level rules, enforced for hook-level rules
