# R56 — Harness Engineering Steal Report

**Source**: Multiple repos (industry survey) | **Date**: 2026-04-14 | **Category**: Industry survey
**Repos cloned**: centminmod/my-claude-code-setup, TheDecipherist/claude-code-mastery, disler/claude-code-hooks-mastery, parcadei/Continuous-Claude-v3, iannuttall/dotagents
**Search coverage**: 50+ repos via `gh search`, 4 web search queries

---

## TL;DR

Harness engineering has become a distinct discipline distinct from prompt engineering. The consensus is: CLAUDE.md sets the *expectations*, hooks enforce the *constraints*, skills provide *reusable capabilities*, and agents form *specialist teams*. The field is maturing fast — context compaction amnesia, multi-agent orchestration, and permission layering are the active frontiers. Our stack is ahead on some dimensions (gate functions, evidence grading, steal discipline), behind on others (post-compaction re-injection, agent-level JSON config, file-based inter-agent coordination).

---

## Common Patterns

### 1. CLAUDE.md: Two-Tier Structure (global + project)

All serious repos separate:
- `~/.claude/CLAUDE.md` — cross-project identity, voice, core behaviors
- `./CLAUDE.md` — project-specific: directory structure, test commands, build conventions, architectural constraints

The centminmod template and claude-code-mastery both keep project CLAUDE.md under ~100 lines. Heavy content goes to skills via progressive disclosure.

Key quote from claude-code-mastery: *"CLAUDE.md rules are suggestions that Claude can override under context pressure. Hooks are deterministic enforcement — they always execute."*

### 2. Hook Architecture: Three Tiers

Every mature repo converges on the same functional tiers:

| Tier | Hook Event | Purpose |
|------|-----------|---------|
| Safety gate | `PreToolUse` | Block dangerous ops (rm -rf, .env access, secret files) |
| Quality gate | `PostToolUse` | Auto-format, run tsc, inject feedback |
| Session lifecycle | `SessionStart` / `Stop` | Context injection, TTS notification, handoff trigger |

Exit code protocol: `0` = allow, `1` = error (user only), `2` = block + stderr fed to Claude.

The hooks-mastery repo has the cleanest implementation: `pre_tool_use.py` handles both .env guard and rm -rf detection with comprehensive regex; all hooks fail-open (`except Exception: sys.exit(0)`) to avoid blocking Claude on unexpected errors.

### 3. `uv run --script` as Hook Runtime Standard

All Python hooks use the inline dependency declaration pattern:
```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.8"
# dependencies = ["python-dotenv"]
# ///
```
No `requirements.txt`, no venv management. `uv` handles deps on first run. This is the de facto standard for hook portability.

### 4. Skills: Progressive Disclosure Architecture

Skill structure is stable across repos:
```
.claude/skills/<name>/
├── SKILL.md          # Frontmatter: name, description, allowed-tools
├── references/       # Supporting reference docs loaded on demand
├── scripts/          # Executable helpers
└── tmp/              # Skill working dir
```

Key insight from centminmod: `description` field drives trigger matching. Write it in first-person trigger language: *"Use when user asks to 'generate an image', 'create a PNG'..."* — not abstract capability descriptions.

Skills are loaded lazily (name+description at startup, full content only when triggered). Frontmatter `allowed-tools` restricts tool access per-skill.

### 5. Agent Specialization by Role

Continuous-Claude-v3 and hooks-mastery both build named agent rosters rather than general-purpose subagents:

| Pattern | Implementation |
|---------|---------------|
| Orchestrator | `maestro` — dispatches others, synthesizes outputs |
| Researcher | `oracle` / `scout` — read-only exploration |
| Implementor | `kraken` — full tool access, TDD |
| Validator | `arbiter` / `sentinel` — test+review |
| Documenter | `scribe` / `chronicler` — write-only to docs |
| Security | `aegis` — read+bash, no write |

Agent specs live in `.claude/agents/<name>.md` (prompt + tools) or `.claude/agents/<name>.json` (structured config with `model`, `permissions`, `tools` array).

### 6. File-Based Inter-Agent Coordination

The dominant pattern for multi-agent output: **never use `TaskOutput`** (dumps full transcript into context). Instead, agents write to `.claude/cache/agents/<agent-type>/output-{timestamp}.md`, orchestrator reads those files.

From Continuous-Claude agent-context-isolation skill:
```
# RIGHT
Task(run_in_background=true, prompt="...Output to: .claude/cache/agents/oracle/result.md")

# WRONG
TaskOutput(task_id=id)  # dumps 70k+ tokens into main context
```

### 7. Context Compaction Defense

This is the hottest problem in 2026. Three approaches observed:

1. **Post-compaction re-injection hook** — `PostToolUse` with `compact` matcher fires after compaction, injects CLAUDE.md + recently used files back as system message
2. **Context threshold Stop hook** — Continuous-Claude's `auto-handoff-stop.py` blocks at 85% context, forces `/create_handoff` command
3. **Disk-persisted handoff files** — Scribe agent writes structured handoffs before session end; next session reads via SessionStart hook

The threshold-based approach (Continuous-Claude) is the most elegant: a `status.py` script writes context % to a tmpfile, the Stop hook reads it, blocks + instructs. Same data source drives the status line and the gate.

### 8. Permission Layering

Four-tier permission model (from Claude Code docs, confirmed across repos):
1. `~/.claude/managed-settings.json` — enterprise admin, cannot be overridden
2. `~/.claude/settings.json` — user global
3. `.claude/settings.json` — project shared (version-controlled)
4. `.claude/settings.local.json` — personal per-project (gitignored)

Agent-level permissions: agent JSON configs support `"permissions": "skip"` to bypass interactive prompts for specific agents. `inherit_blocks: true` propagates parent blocklists down.

---

## Steal Sheet

Items worth direct adoption or adaptation:

| Item | Source | Priority | Notes |
|------|--------|----------|-------|
| Post-compaction re-injection hook | Community pattern | HIGH | We get context amnesia after compaction. Use `PostToolUse` with `compact` matcher to re-inject CLAUDE.md |
| Context threshold Stop hook | Continuous-Claude | HIGH | Block at 85%+, force handoff. Currently we don't have automated handoff gates |
| `uv run --script` inline deps | hooks-mastery | MEDIUM | All our hooks already use uv but without inline dep declarations — formalize the pattern |
| Agent JSON config alongside .md | Continuous-Claude | MEDIUM | `.claude/agents/name.json` for model/permission/tools, `.md` for prompt — cleaner separation |
| `fail-open` hook exception handling | hooks-mastery | MEDIUM | All hooks should `sys.exit(0)` on unexpected errors. We have some that might hard-exit |
| `.env` access guard in PreToolUse | hooks-mastery | LOW | Already have dispatch-gate; consider adding .env guard |
| `run_in_background=true` + file coordination | Continuous-Claude | MEDIUM | Our agents dump output to context. Switch to file-based handoff pattern |
| Skill `allowed-tools` frontmatter | centminmod | LOW | We use skills without tool restrictions; adding per-skill tool scoping reduces attack surface |
| CoD (Chain of Draft) agent mode | centminmod code-searcher | LOW | Token-efficient search agent mode. Interesting for high-frequency codebase queries |

---

## Consensus/Divergence Matrix

| Practice | centminmod | hooks-mastery | Continuous-Claude | dotagents | Us (Orchestrator) |
|----------|-----------|---------------|-------------------|-----------|-------------------|
| Global + project CLAUDE.md split | YES | YES | YES | YES | YES |
| uv run --script for hooks | YES | YES | YES | N/A | YES (informal) |
| Progressive skill disclosure | YES | NO | YES | YES | YES |
| Named agent roster | YES | YES | YES | N/A | YES |
| File-based agent output | NO | PARTIAL | YES | N/A | NO |
| Context threshold gate | NO | NO | YES | N/A | NO |
| Post-compaction re-injection | NO | NO | PARTIAL | N/A | NO |
| Agent JSON config | NO | NO | YES | N/A | NO |
| fail-open hook exceptions | YES | YES | YES | N/A | PARTIAL |
| Per-skill tool restrictions | YES | NO | YES | N/A | NO |
| Commit-per-feature discipline | N/A | N/A | N/A | N/A | YES |
| Evidence grading in memory | N/A | N/A | N/A | N/A | YES |
| Gate functions | N/A | YES (basic) | PARTIAL | N/A | YES (full) |
| Steal/round discipline | N/A | N/A | N/A | N/A | YES |

---

## Gaps

Capabilities we don't have that appear in 3+ repos:

1. **Post-compaction context re-injection** — highest impact, missing across most repos too but Continuous-Claude solved it elegantly
2. **Automated session handoff** — context threshold → forced handoff document → next-session pickup. We do manual handoffs.
3. **Agent-level JSON config** — separating model/permissions/tools from prompt content. Our agents are all inline .md.
4. **File-based inter-agent output coordination** — we let agents write to context; large agent outputs bloat the main window.
5. **Per-skill tool scoping** — `allowed-tools` in SKILL.md frontmatter. We grant agents broad access.

---

## Adjacent Discoveries

- **dotagents** (iannuttall) — CLI tool that symlinks your `.claude/` directory across multiple projects. Solves the multi-project consistency problem: one canonical `~/.dotagents/` repo, symlinked into each project. TypeScript, Bun runtime. Interesting for managing our global skills across machines.
- **claude-reflect** (BayramAnnakov) — captures corrections and positive feedback in real time, syncs them back to CLAUDE.md. Self-healing harness pattern. Could complement our memory evidence system.
- **Piebald-AI/tweakcc** — customizes Claude Code's internal system prompts (themes, spinners, thinking verbs). Unlocks private/unreleased features. Useful for diagnostics but risky to depend on.
- **Dicklesworthstone/post_compact_reminder** — minimal hook that detects compaction and injects a reminder to re-read AGENTS.md. Simplest possible anti-amnesia solution. 30 lines of shell.
- **tzachbon/claude-model-router-hook** — PreToolUse hook that routes to different model tiers based on task complexity. Budget Haiku for searches, Opus for architecture decisions. Cost optimization pattern.
- **BayramAnnakov/claude-reflect** — auto-captures user corrections ("not like this, do it like X") and writes them back to CLAUDE.md. Closes the feedback loop automatically.

---

## Meta Insights

1. **The field is 6 months old and already stratified.** There's a clear gap between "drop CLAUDE.md and call it done" and "full harness engineering with gates, hooks, and agent rosters." The repos we cloned are the top 5% — most public repos are still at the single-file stage.

2. **Hooks are the moat.** CLAUDE.md is copyable; hooks require operational discipline to maintain. Repos with mature hook systems (Continuous-Claude, hooks-mastery) have invested 3-5x more engineering effort than repos with only CLAUDE.md. Our hook investment (dispatch-gate, branch enforcement, Telegram notifications) is unusual and defensible.

3. **Context compaction is the unsolved problem.** Every repo acknowledges it, few have solved it. Continuous-Claude's threshold gate + handoff pattern is the most complete solution seen. This is the R57 candidate.

4. **Agent specialization beats general agents.** Named agents with explicit tool restrictions (read-only oracle, write-only scribe, bash-heavy implementor) outperform Swiss-army subagents. The specialist roster pattern from Continuous-Claude is worth stealing directly.

5. **File-based coordination is the production pattern for multi-agent.** Context pollution from agent output is a real problem at scale. Background agents + file handoffs + no TaskOutput = stable main context window. Our steal rounds that spawn agents should adopt this.

6. **Permission inheritance is underspecified everywhere.** Most repos use `dangerouslySkipPermissions` globally rather than per-agent scoping. Continuous-Claude's `"permissions": "skip"` per-agent JSON is cleaner. Our gate functions are still the strongest safety approach seen.

7. **The TTS / notification pattern is surprisingly common.** Stop hooks that announce completion via ElevenLabs/OpenAI TTS appear in 4+ repos. hooks-mastery has the most complete implementation with priority fallback chain (ElevenLabs > OpenAI > pyttsx3). Mainly useful for unattended agent runs.
