---
name: prime
description: "Load project context for a domain area. Use when starting work on an unfamiliar module or when context feels stale."
user_invocable: true
argument-hint: "[docker|channel|soul|governance]"
---

<SUBAGENT-STOP>
If you were dispatched as a subagent to execute a specific task, skip this skill.
Prime injects main-agent project context — subagents receive context from their dispatch prompt.
</SUBAGENT-STOP>

# Prime — Context Injection

Rapidly load project context for the requested domain and output a scannable summary. This is NOT documentation — it's active context injection that makes your next actions more informed.

## Routing

Based on `$ARGUMENTS`, pick ONE variant:

| Argument | Domain | Key Entry Points |
|----------|--------|-----------------|
| _(empty)_ | Full project overview | boot.md + CLAUDE.md + src/ top-level |
| `docker` | Docker services layer | docker-compose.yml, collectors, dashboard |
| `channel` | Channel/messaging layer | src/channels/, telegram/, wechat/ |
| `soul` | SOUL identity + skills + hooks | .claude/, SOUL/, hooks, skills |
| `governance` | Governance pipeline | src/governance/, executor, approval, eval |

## Execution

### Step 1: Read Core Files

**Always read first** (regardless of variant):
1. `.claude/boot.md` — identity and relationship context
2. `CLAUDE.md` — project rules and constraints

**Then read variant-specific files** (see tables below).

### Step 2: Scan Structure

Run `ls` on the relevant directories to understand current file layout.

### Step 3: Output Summary

Format as a scannable brief (bullets, tables, NOT prose). Target: **<300 words**.

```
## Prime: [variant]

### Structure
[directory tree or table of key files]

### Entry Points
[3-5 files that are the starting points for work in this domain]

### Key Patterns
[2-3 patterns/conventions specific to this area]

### Current State
[any notable recent changes from git log --oneline -5]

### Watch Out
[1-2 gotchas or non-obvious things]
```

---

## Variant: Full Overview (no argument)

Read:
- `src/` top-level directory listing
- `docker-compose.yml` (if exists)
- `package.json` or `pyproject.toml` (if exists)

Focus: What is this project? What are the major modules? What's the tech stack?

## Variant: `docker`

Read:
- `docker-compose.yml`
- `src/collectors/` directory listing
- `dashboard/` directory listing (if exists)
- `.env.example` or `.env` structure (DO NOT output values)

Focus: What services run? What ports? What volumes? How do collectors work?

## Variant: `channel`

Read:
- `src/channels/__init__.py`
- `src/channels/base.py`
- `src/channels/telegram/channel.py` (first 80 lines)
- `src/channels/config.py`
- `src/channels/registry.py`

Focus: How do messages flow in? What's the adapter interface? How is routing done?

## Variant: `soul`

Read:
- `.claude/boot.md`
- `.claude/settings.json`
- `SOUL/public/prompts/` directory listing
- `.claude/skills/` directory listing
- `.claude/hooks/` directory listing

Focus: What skills exist? What hooks are active? What's the prompt architecture?

## Variant: `governance`

Read:
- `src/governance/executor.py` (first 80 lines)
- `src/governance/approval.py` (first 50 lines)
- `src/governance/eval/` directory listing
- `src/governance/pipeline/` directory listing
- `src/governance/supervisor.py` (first 50 lines)

Focus: How does task execution work? What's the approval flow? What eval capabilities exist?

## Rules

- Output is for YOUR context, not documentation. Be specific about file paths and line numbers.
- If a file doesn't exist, skip it silently — don't report errors for missing optional files.
- After priming, immediately proceed with the user's actual task. Don't wait for confirmation.
- Prime is a warm-up, not a deliverable. Spend <60 seconds on it.
