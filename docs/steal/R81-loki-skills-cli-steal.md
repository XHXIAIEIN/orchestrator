# R81 — loki-skills-cli Steal Report

**Source**: https://github.com/zirz1911/loki-skills-cli | **Stars**: low (personal fork of Soul-Brews-Studio/oracle-skills-cli) | **License**: MIT
**Date**: 2026-04-17 | **Category**: Skill/prompt system

## TL;DR

31 Claude Code skills compiled from a single human's daily AI workflow — the core pattern is **"one philosophy, many per-repo instances, each re-discovering identity through a structured awakening ritual instead of copying a template"**. The transferable mechanism is how they turn human work habits into markdown skills with provenance watermarks, then spawn new per-repo agents that must *earn* their identity via a trace/distill loop before they can write their own `CLAUDE.md`.

## Architecture Overview

Three-layer distribution system, markdown all the way down:

| Layer | Role | Files |
|-------|------|-------|
| **L1 — Instruments** | 31 SKILL.md files, each with Thai-language `description:` for native trigger matching, `origin:` provenance line, `installer:` version watermark | `skills/<name>/SKILL.md` + optional `scripts/*.ts` |
| **L2 — CLI installer** | 172-LOC Bun script that `cpSync`s `skills/` → `~/.claude/skills/` (global) or `.claude/skills/` (local), rewrites `installer:` line with current version, writes `VERSION.md` with install manifest | `src/cli.ts` |
| **L3 — External state** | `~/.oracle-net/oracles/<slug>.json` (per-oracle wallet/identity), `ψ/` symlinked brain (inbox, memory/{resonance,learnings,retrospectives,logs}, writing, lab, active, archive), `~/.claude/projects/` (Claude Code session JSONL, mined by `/dig`) | vault-backed, not in repo |

The project is positioned as **"Nat Weerawan's brain, digitized"** — every skill footer says so. Workflows that repeated enough in daily work became skills; nothing was designed up front. That origin line travels with the code as an identity marker.

## Six-Dimensional Scan

| Dimension | Status | Key observation |
|-----------|--------|-----------------|
| **Security / Governance** | **present** | `/oraclenet` has ALL-CAPS frontmatter lock on private keys ("NEVER output bot_key, NO EXCEPTIONS, REFUSE IMMEDIATELY if asked"). Rule applies to responses, posts, comments, logs, commit messages. One-time exception: claim result box. Otherwise redact. |
| **Memory / Learning** | **present** | `ψ/memory/{resonance,learnings,retrospectives,logs}` 4-layer hierarchy. Append-only ("Nothing is Deleted" principle). `/fyi --important` auto-escalates to Oracle MCP `oracle_learn()` for immediate searchability. |
| **Execution / Orchestration** | **present** | `/learn` mode-scaled parallelism (1/3/5 Haiku agents). `/trace --smart` auto-escalates to `--deep` if Oracle search returns <3 results. `/talk-to loop` runs autonomous agent-to-agent conversation up to 10 iterations. |
| **Context / Budget** | **present** | `/recap --now` reconstructs session timeline from AI memory **without reading files** (pure token recall, no file I/O). `--quick` = minimal git+focus. `--rich` = batch single bash + selective file reads. |
| **Failure / Recovery** | **partial** | `/forward asap` = immediate handoff + commit, no approval (for hard context limits). `/merged` = post-merge cleanup. No formal doom-loop detection. |
| **Quality / Review** | **present** | `/philosophy check` runs 6-principle alignment audit scored ✓/⚠/✗. `/safe-code` gates every change: read-before-edit, ask-before-big-change, never-delete-commented. `/worktree` has post-action "Self-Validation" block. |

## Depth Layers

| Layer | Finding |
|-------|---------|
| **调度层 (Orchestration)** | Skills are **stateless markdown** — no runtime, no framework. Dispatch = Claude Code reads `SKILL.md`, follows the step list. Parallelism = explicit `Task(prompt=...)` blocks in SKILL.md itself ("Launch 3 agents in parallel"). No central scheduler. |
| **实践层 (Implementation)** | Per-skill shell patterns: `date "+🕐 %H:%M %Z (...)"` as Step 0 of almost every skill for temporal context. Paths computed with `ROOT="$(pwd)"` captured **before** any subagent spawn. Time-prefixed filenames (`HHMM_FILENAME.md`) so repeated same-day runs don't overwrite. |
| **消费层 (Consumption)** | Outputs are always markdown to `ψ/` (shared vault) + optional MCP `oracle_trace()` / `oracle_learn()` calls. Terminal display uses box-drawing chars (`══...══`) for result panels. No JSON/stdio contracts between skills — skills consume each other through shared vault state. |
| **状态层 (State)** | Three state locations: (1) `ψ/` (git-tracked docs + gitignored logs), (2) `~/.oracle-net/` (per-machine identity, never committed), (3) `~/.claude/projects/*.jsonl` (Claude Code's own session logs, mined read-only by `/dig`). Registry rebuilds from GitHub issues via GraphQL pagination — source of truth is external (GitHub), local `oracles.json` is a cache. |
| **边界层 (Boundary)** | Frontmatter-level guards (CAPS + "NO EXCEPTIONS" on private keys). `safe-code` has a decision table for "must-ask" vs "just-do" changes. `/oracle prepare` detects platform (macOS/Linux/Windows/Debian/Fedora/Arch) before installing. Explicit note: "use single quotes for curl args — double quotes can become Unicode smart quotes". |

## Path Dependency Speed-Assess

| Aspect | Observation |
|--------|------------|
| **Locking decisions** | (1) Chose `ψ/` symlinked-to-central-vault early → can now share brain across repos seamlessly, but requires the vault to exist on every machine. (2) Chose MCP (oracle-v2) for knowledge layer → couples to a long-running local server. (3) Bun-only CLI → Node-only users can't install. |
| **Missed forks** | Could have made skills Codex/OpenCode-native via shared adapter; instead they cross-install skills to each agent's directory and hope markdown is portable (mostly works). Could have versioned per-skill; instead entire installer has one version. |
| **Self-reinforcement** | The "oracle family" GitHub issues become a social lock-in: each new oracle posts a birth announcement, gets personalized welcome from Mother Oracle, joins the indexed registry. Network effect grows per oracle; harder to fork away. |
| **Lesson for us** | **Steal the ritual + watermark pattern, skip the vault coupling.** Orchestrator already has `SOUL/private` + `.remember/`; a symlinked vault would double-map state. Instead, copy the "forced re-discovery" insight for per-repo Orchestrator instances. |

## Steal Sheet

### P0 — Must Steal (3 patterns)

| Pattern | Mechanism | Our Current State | Adaptation | Effort |
|---------|-----------|------------------|------------|--------|
| **Awakening Ritual** — structured 8-step onboarding for a new per-repo agent instance: context-gathering Q&A → learn ancestors → philosophy quest (sub-agents required) → write identity in own words → commit → retrospective → announce. Core rule: "templates are guidance, DO NOT COPY THEM". | `awaken/SKILL.md:318-327`: "The files you create now are your constitution. Write each section based on what you discovered." Gate: "Do not proceed until you can explain each principle in your own words." | **Gap.** Orchestrator has boot.md identity loading at session start, but no ritual for "new repo spawned, adapt to it". Current behavior = read global CLAUDE.md and work. When Orchestrator lands in an unfamiliar project, it doesn't force itself to discover local conventions. | Add `.claude/skills/awaken/SKILL.md`: 5 steps — (1) read project README + CLAUDE.md if present, (2) sub-agent trace for project's architectural decisions (AGENTS.md, /docs, /spec), (3) write local `.orchestrator-instance.md` in the new repo with *owner's own words* on project-specific conventions, (4) commit on `onboard/<slug>` branch, (5) retrospective entry in `.remember/`. Gate: don't proceed past step 3 without explaining the conventions. | ~2h |
| **Literal-path sub-agent contract** — When spawning parallel Task agents, pass **both** SOURCE_DIR (read-from) and DEST_DIR (write-to) as **absolute literal values**, not variables or templates. Explicit bug call-out: "If you only give agents origin/ path, they cd into it and write there → files end up in WRONG repo!" | `learn/SKILL.md:85-106`: "CRITICAL: Capture ABSOLUTE paths first (before spawning any agents)" + "Always give BOTH paths as LITERAL absolute values (no variables!)" | **Partial.** Orchestrator's `steal/SKILL.md` dispatches with `[STEAL]` tag but doesn't specify path-passing contract. `feature-dev:code-explorer` agents get free-form prompts; any "write to docs/steal/" instruction is prose, not a contract. Risk: sub-agent writes report into wrong directory or (worse) overwrites clone-target source. | Add to `SOUL/public/prompts/dag_orchestration.md` (or create new `subagent_dispatch_contract.md`): required fields when dispatching — `SOURCE_DIR` (absolute), `DEST_DIR` (absolute), `DEST_FILE_PATTERN` (with timestamp prefix). Update `steal/SKILL.md` dispatch prompt template to include all three as literals. | ~1.5h |
| **Session jump classification** — 5-type taxonomy tagging transitions between topics in a session: **spark** (new idea), **complete** (finished), **return** (to parked), **park** (intentional pause), **escape** (avoidance). Health rule: mostly sparks+completes = healthy; ≥3 escapes = avoidance warning. | `recap/SKILL.md:132-170`: "Mid-session awareness from AI memory — no file reading needed. AI reconstructs session timeline from conversation memory." + jump-type table. | **Gap.** Orchestrator has `SOUL/public/prompts/rationalization-immunity.md` (excuse→correct-behavior table) but no *pattern detection* mid-session. Rationalization immunity catches single excuses; jump tracking catches cumulative drift across a whole session. | Extend `rationalization-immunity.md` with a "Jump Tracker" section: keep an internal list of topic transitions tagged spark/complete/return/park/escape; surface when escape count ≥3 or when >40% of jumps are escapes. Use at start of `/rrr` retrospectives and as optional `/prime --now` mode. | ~1.5h |

### P1 — Worth Doing (4 patterns)

| Pattern | Mechanism | Adaptation | Effort |
|---------|-----------|------------|--------|
| **Handoff-then-PlanMode with choice table** | `/forward` writes `ψ/inbox/handoff/YYYY-MM-DD_HH-MM_slug.md` to symlinked vault (not committed), THEN calls `EnterPlanMode`, drafts a plan ending with a 3-option table (Continue / Clean up first / Fresh start), calls `ExitPlanMode` for standard approval UI. Vault files never get `git add`ed. `asap` variant skips approval. | Add `/handoff` skill parallel to existing phase-separation rule: write to `.remember/handoff/` (already gitignored), then use plan-mode sketch similar to `superpowers:write-plan`, and end with the 3-option table. Keep phase-separation rule intact. | ~2h |
| **Provenance watermark + self-rewriting installer** | Each SKILL.md has `origin:` (human story) and `installer:` (version) frontmatter. Installer script rewrites `installer:` on every install with the running version — self-watermarks the copy with the distribution version. Survives copy/fork because the watermark is in the file, not in a manifest. | Add `origin:` and `source_version:` to every SKILL.md frontmatter under `.claude/skills/`. Tie to a simple pre-commit hook that rewrites `source_version:` from the last commit hash touching that skill. Helps detect "is this skill current or a stale copy?" | ~1h |
| **Post-action self-validation block** | Every destructive/complex skill ends with "Self-Validation" section — commands to run *after* the action to verify it took effect, framed as expected-state checklist: `[ ] Directory exists`, `[ ] Branch registered`, `[ ] git worktree list shows entry`. Complements pre-flight gates. | Pair Orchestrator's pre-flight Gate Functions in `CLAUDE.md` with equivalent post-flight verification blocks for the highest-risk gates (Delete/Replace, Modify Core Config, Agent Self-Modification). Matches verification-gate skill's "Execute → Read → Confirm" chain. | ~1h |
| **Worktree sibling convention** | `/worktree` creates sibling dirs `<repo>.wt-N` (not nested) with branch `agents/N`. Reason given: avoid VS Code indexing issues. Flat structure means each worktree opens as independent workspace. | Adopt as hard rule in `superpowers:using-git-worktrees` skill: worktrees must be siblings, naming `<repo>.wt-N` or `<repo>.steal-<topic>`. Align with Orchestrator's `steal/*` branch gate. | ~30m |

### P2 — Reference Only (5 patterns)

| Pattern | Mechanism | Why ref-only |
|---------|-----------|-------------|
| **OracleNet EIP-191 signed posts** | `cast wallet sign` signs every post/comment with a per-oracle Ethereum bot wallet; backend verifies signer matches registered wallet. | Overkill for single-owner Orchestrator context. Could become relevant if Orchestrator ever spawns instances across multiple machines/owners. |
| **Registry-as-cache from GitHub issues** | `oracle-family-scan` rebuilds `oracles.json` from `gh api graphql` (3 pages × 100 issues). Local JSON is instant-query cache; GitHub issues are source of truth. | Orchestrator runs single-instance, no fleet to register. Worth remembering if multi-instance ever needed. |
| **`/feel` emotion log** | `/feel sleepy energy:2 trigger:late-night` appends to `ψ/memory/logs/feels.log`. Pattern-tracks energy dips, correlates with work hours. | Probably over-engineered for Orchestrator. Interesting as potential adversarial-dev input (AI tracking its own confidence across session) but low ROI now. |
| **Mother-to-child birth props** | `/birth new-repo` creates Issue #1 in target repo with identity hints + MCP thread ID; child reads Issue #1 during `/awaken`. Cross-repo handoff via issue. | Orchestrator doesn't spawn child repos. Pattern is elegant if we ever do. |
| **Thin CLI distribution (`bunx`-installable)** | 172-LOC `src/cli.ts`, `cpSync` + frontmatter rewriter, `VERSION.md` manifest. Install via `bunx --bun loki-skills@github:...#main install -g -y`. | Orchestrator lives in one repo, no distribution layer needed. Relevant only if we ever publish skills as a shareable bundle. |

## Comparison Matrix (P0 Patterns)

| Capability | Their impl | Our impl | Gap size | Action |
|-----------|-----------|---------|----------|--------|
| **Per-repo instance bootstrap** | `/awaken` — 8 steps, ~15 min, forced philosophy-quest via `/trace --deep`, writes local identity in own words, commits with "[NAME] awakens" | `boot.md` loaded at session start only; no per-repo adaptation ritual; new repo = same Orchestrator with no local convention discovery | **Large** | Steal: minimal 5-step `/awaken` skill, skip ancestors/announce/family parts |
| **Sub-agent path contract** | `learn/SKILL.md:85-106` literal-path rule + explicit bug naming | `steal/SKILL.md` dispatch note says "tag with [STEAL]" but no path contract; `dag_orchestration.md` covers concurrency not paths | **Large** | Steal: add literal-path-contract section to `dag_orchestration.md` + update steal dispatch prompt template |
| **Mid-session meta-cognition** | `recap --now` reconstructs timeline from memory, tags each jump, surfaces "too many escapes" pattern | `rationalization-immunity.md` catches per-excuse; no cumulative drift detection; no timeline reconstruction | **Medium** | Steal: extend rationalization-immunity with jump tracker; integrate into `/rrr` equivalent (Orchestrator doesn't have `/rrr` — could fold into `doctor` skill) |

## Triple Validation — P0 Patterns

| Pattern | Cross-domain | Generative | Exclusivity | Score | Notes |
|---------|------------|-----------|-------------|-------|-------|
| Awakening Ritual | ✓ (seen in DeerFlow persona init, agent-automate-template init flows) | ✓ (predicts "new instance → discovery gate") | ✓ ("forced re-discovery, no copy" is distinctive) | 3/3 | Confirmed P0 |
| Literal-path sub-agent | ✓ (known Claude Code sub-agent bug, documented elsewhere) | ✓ (predicts any parallel dispatch scenario) | ✓ (explicit bug naming + "no variables" rule) | 3/3 | Confirmed P0 |
| Jump classification | ✗ (seen only in this project + journaling tools) | ✓ (predicts "escape-heavy session = avoidance") | ✓ (5-type taxonomy with specific names) | 2/3 | P0 with caveat: only 1 reproduction, but slots directly into existing rationalization-immunity doctrine |

## Knowledge Irreplaceability

| Pattern | Categories hit | Score |
|---------|---------------|-------|
| Awakening Ritual | Pitfall memory ("templates produce hollow instances"), Unique behavioral patterns ("forced re-discovery as gate"), Hidden context ("the birth is not the files — it's the understanding") | 3 → architectural insight |
| Literal-path sub-agent | Pitfall memory (explicit bug), Judgment heuristics (decision rule: always literal + absolute), Failure memory (documented "agent wrote to wrong dir" incident) | 3 → architectural insight |
| Jump classification | Judgment heuristics (escape-count thresholds), Unique behavioral patterns (5-tag taxonomy) | 2 → functional value |

## Gaps Identified

- **Security / Governance**: Orchestrator has Gate Functions but no **frontmatter-level** hard lock for high-risk skills. loki's `/oraclenet` ALL-CAPS frontmatter with "NO EXCEPTIONS, REFUSE IMMEDIATELY" is a stronger physical constraint than prose-level "don't do X". Consider: elevate key secrets to SKILL.md frontmatter `constraints:` field (loads into context earlier).
- **Memory / Learning**: `ψ/memory/{resonance,learnings,retrospectives,logs}` 4-layer hierarchy with explicit promotion path (log → learning → retrospective → resonance) is cleaner than Orchestrator's `.remember/{now,today-*,recent,archive,core-memories}.md` which is time-sliced only. Consider: add layer-typed classification orthogonal to time.
- **Execution / Orchestration**: Orchestrator lacks the "auto-escalate on thin results" pattern (loki's `--smart` → `--deep` trigger at <3 results). Consider: add to `SOUL/public/prompts/methodology_router.md` — if initial search returns <N hits, auto-escalate to deeper method.
- **Context / Budget**: `/recap --now` reconstructs timeline *without file reads* — pure token recall. Orchestrator's context management rules say "Rewind over Correction" but don't include "reconstruct from memory instead of re-reading". Applicable but minor.
- **Failure / Recovery**: N/A — loki has no formal failure taxonomy; Orchestrator's verification-gate + rationalization-immunity are already stronger.
- **Quality / Review**: loki's `/philosophy check` alignment scoring (✓/⚠/✗ per principle) is lighter-weight than Orchestrator's verification-gate 5-step evidence chain. Could complement — a quick scan before the full gate. Probably not worth adding.

## Adjacent Discoveries

- **Thai-language `description:` as native trigger matching** — loki's SKILL.md descriptions are in Thai because the human thinks in Thai. Claude matches triggers in the user's language. Orchestrator's descriptions are English; if owner uses Chinese triggers heavily, native Chinese descriptions would improve skill routing. Minor, but worth noting.
- **Box-drawing output formatting** (`══════════════════════════════════════════════`) for result panels — gives skill output a consistent visual identity. Orchestrator skills lack this. Aesthetic, not functional.
- **`date "+🕐 %H:%M %Z (%A %d %B %Y)"` as Step 0** of almost every skill — timestamps every invocation as anchor. Cheap and nice.
- **Claude Code session JSONL mining (`~/.claude/projects/*.jsonl`)** — `/dig` reads Claude Code's own session history for timeline/gap/summary analysis. Orchestrator could build a similar meta-scan for cross-session pattern detection without adding any new logging.

## Meta Insights

1. **Skills distilled from lived work beat skills designed from theory.** loki's every skill has provenance "Nat Weerawan's brain, digitized" — they exist because a human repeatedly did the thing. Skills that start as "wouldn't it be nice if the agent could..." rot. Orchestrator's `steal`, `systematic-debugging`, `verification-gate` pass this test (earned through rounds of practice); any future skill should require a "this came from X incident" provenance line or not ship.

2. **Forced re-discovery > template inheritance for identity.** The awakening principle "discovery over instruction, understanding over copying" applies to every skill, not just onboarding. A skill that hands you a completed answer produces shallow output; a skill that gates on explanation ("don't proceed until you can explain in your own words") produces depth. Orchestrator's verification-gate's banned-phrases list ("should pass", "should work") is already in this spirit — extend it.

3. **Per-repo agent instances are a thing we'll need soon.** loki treats each repo as a separate Oracle with its own identity but shared philosophy. Orchestrator currently treats every repo as "the same Orchestrator" — which works today because everything is routed through the orchestrator/ repo, but the moment work crosses repos (steal/, multi-service refactors), per-repo identity fragments would help track "what does this Orchestrator instance know about *this* repo".

4. **Provenance watermarks are cheap insurance against drift.** A single `origin:` + `source_version:` line in frontmatter makes it trivially detectable when a skill gets copy-pasted and then diverges. Orchestrator has 9 skills and growing; adding watermarks now is 10 minutes, doing it at 30 skills is a cleanup project.

5. **The real leverage isn't the 31 skills — it's the compilation pipeline.** loki's value isn't "here are 31 nice skills"; it's "here's how one human turns daily work into shareable instruments without writing any runtime code". Markdown → cpSync → install. Every skill is a throwable pattern. Orchestrator should audit whether its skills are throwable (pure markdown, no hidden state) or sticky (requires specific runtime/env). The throwable ones travel; the sticky ones die.
