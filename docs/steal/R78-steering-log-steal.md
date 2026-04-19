# R78 — steering-log Steal Report

**Source**: https://github.com/hanlogy/steering-log | **Stars**: 1 (created 2026-03-27, very new) | **License**: MIT (Hanlgy AB)
**Date**: 2026-04-17 | **Category**: Skill-System (Claude Code Plugin)

## TL;DR

A Claude Code plugin that turns hook events into a **two-stage LLM pipeline** (Haiku-detector → Sonnet-summarizer) and persists user "steering moments" as **self-sealing markdown episodes**. The steal value isn't the feature — it's the **disk-state machine + env-var safeguard + episode abstraction** that lets async background agents survive crashes without polluting the host Claude Code session.

## Architecture Overview

```
Layer 0 — Claude Code Hooks (hooks.json)
    SessionStart → cleanup.js          (resume + truncate stale buffers)
    UserPromptSubmit → appendToBuffer.js (record human turn → spawn detector)
    Stop → appendToBuffer.js           (record assistant turn)
    PostCompact / SessionEnd → appendToBuffer.js  (record control events)

Layer 1 — Disk State (steering_log/.conversation/)
    buffer.jsonl              # raw conversation log, append-only
    triggers-queue.txt        # timestamps awaiting summarization
    detector-context.json     # current/last detector window {isFinished, messages}
    summarizer-context.json   # current/last summarizer window {isFinished, ...stats}

Layer 2 — Background Agents (spawn detached node)
    runDetector.ts:  Haiku — "is this a steering moment?" (binary)
    runSummarizer.ts: Sonnet — classify + structure + decide new-episode

Layer 3 — Episode Output (steering_log/{datetime}-{slug}.md)
    One file per task. Append moments. New episode → previous file gets
    `**Result**: completed|paused|cancelled|failed` line, never modified again.
```

**Key control flow** — `appendToBuffer` is the only write point; everything downstream is idempotent replay from disk state. `safeGuard()` env-var check (4-line module) prevents the spawned `claude --print` from re-triggering its own hooks (would cause infinite recursion).

## Steal Sheet

### P0 — Must Steal (5 patterns)

| Pattern | Mechanism | Our Current State | Adaptation | Effort |
|---------|-----------|------------------|------------|--------|
| **Two-stage LLM trigger (cheap classifier → expensive generator)** | Haiku decides `is_trigger:true/false` first; only on true does Sonnet run with full window. Both spawned via `spawn('claude', ['--print', '--model', model])` as detached background processes. | `correction-detector.sh` is regex-only (weight≥2). Catches literal phrases, misses semantic pushback ("we use JWT not sessions"), can't extend to `preference`/`scope-change`/`direction` types. | Add `.claude/hooks/steering-detector-llm.sh` running alongside regex. Regex = fast path for cheap obvious cases; LLM = slow path covering 5 semantic categories. Same buffer feeds both. | ~3h |
| **safeGuard env-var anti-recursion** | `STEERING_LOG_INTERNAL_RUN=1` set when spawning `claude --print`; every hook script calls `safeGuard()` first which checks the var and exits early. 4 lines, zero deps. | Our hooks have no explicit recursion guard. Today this works because hooks are bash, not spawning new claude processes. The moment any hook spawns a claude subprocess (already done in some experiments), we'd get unbounded recursion. | Add `.claude/hooks/lib/safeguard.sh` exporting `ORCHESTRATOR_HOOK_INTERNAL=1` env var pattern. Every hook that *might* spawn claude must source it. | ~1h |
| **Crash-resume disk-state machine (4-file separation of concerns)** | `buffer.jsonl` = raw log; `triggers-queue.txt` = work queue; `detector-context.json` / `summarizer-context.json` = current-window snapshots with `isFinished` flag. SessionStart `cleanup.js` reads context files: if `isFinished:true` → truncate buffer past that point; if `false` → resume from last queued trigger. | Hooks fire-and-forget, no on-disk continuation. If a hook crashes mid-write or claude crashes between hook and write, the event is lost. `.remember/now.md` is overwritten in-place, no replay. | Apply pattern to `.remember/`: split into `buffer.jsonl` (append) + `pending.txt` (queue) + a context snapshot. Memory promotion becomes resumable. | ~4h |
| **Episode self-sealing markdown** | One markdown file per task. New file = `{YYYYMMDDHHmmss}-{slug}.md`. New episode triggered by Sonnet decision auto-appends `\n\n---\n\n**Result**: {result}` to the previous file via `completeEpisode.ts`. Closed files are never reopened. | `.remember/today-*.md` is overwritten daily; no per-task boundaries. `docs/steal/` has per-round files but no termination semantic. `SOUL/public/skill_executions.jsonl` is raw events without task grouping. | Introduce `.remember/episodes/` directory using same scheme. Episode boundary detected by skill-router or explicit `/done` command. Result = `completed/paused/cancelled/failed`. | ~3h |
| **Brace-walking JSON extractor** | `extractJsonRecord.ts` (35 LOC): scan stdout for `{`, walk forward tracking depth + string-escape state, attempt `JSON.parse` on each balanced segment, return first that parses to a record. Survives any LLM preamble/postamble. | We `try: json.loads(...)` everywhere with no fallback. When LLM outputs `Sure, here's the JSON: {...}` we silently lose the entire decision. Affects `summarizer-skill.py`, plan parsers, agent orchestrators. | Port to `src/utils/extract_json.py`. Replace bare `json.loads` calls in LLM-output paths. | ~2h |

### P1 — Worth Doing (4 patterns)

| Pattern | Mechanism | Adaptation | Effort |
|---------|-----------|------------|--------|
| **Negative-example-driven classifier prompt** | `momentRules.md` dedicates a whole section to "Do NOT classify as a moment" with 7 concrete categories (vague disagreement, social ack, follow-up Q, additive request, option-selection, weak signal). Raises precision dramatically vs positive-only prompts. | Audit our skill prompts (especially `correction-detector`, `summarizer`, `skill_routing`) — most are positive-only. Add explicit "Do NOT" sections. | ~2h |
| **Shared rules placeholder + dual-template substitution** | `{{QUALIFICATION_RULES}}` placeholder in both `detector.md` and `summarizer.md`, replaced at runtime with `momentRules.md` content. Single source of truth for what counts. Also `{{PREVIOUS_RESULT_INSTRUCTION}}` / `{{PREVIOUS_RESULT_JSON}}` for conditional sections. | `SOUL/public/prompts/` already has shared modules but no formal placeholder substitution. Add `{{INCLUDE: skill_routing.md}}` convention to `prompt_template_loader.py`. | ~2h |
| **Detached + unref background spawn** | `spawn(node, [script, cwd], { detached: true, stdio: 'ignore' }); child.unref()` — hook returns instantly, child outlives parent. | Some Python hooks already use `subprocess.Popen(... stdout=DEVNULL)` but inconsistent. Standardize on `nohup`-equivalent helper. | ~1h |
| **Window slice + retry parser** | Detector window = exactly 2 messages (last assistant + current human). `AGENT_MAX_RETRIES=2` retries on JSON parse failure. Tiny prompt + retry beats large prompt one-shot. | Our LLM-summary hooks pass full conversation. Cap window. Add `RETRY_ON_PARSE_FAIL` to llm helpers. | ~2h |

### P2 — Reference Only (3 patterns)

| Pattern | Mechanism | Why ref-only |
|---------|-----------|-------------|
| **esbuild + path-alias + .md-as-text loader** | `build.mjs` uses `loader: { '.md': 'text' }` to inline prompt files at build time, single executable bundle. | We're Python-first; only relevant if we ship a Node Claude Code plugin. |
| **`declare module '*.md'` TS shim** | `declarations.d.ts` (3 lines) lets TS treat `.md` imports as `string` defaults. | Same — Node-only. |
| **Sortable timestamp filename = sortable history** | `{YYYYMMDDHHmmss}-{slug}.md` so `readdirSync().sort()` returns chronological order without parsing. | Already doing this in `docs/steal/Rxx-`. |

## Comparison Matrix

| Capability | Their impl | Our impl | Gap | Action |
|-----------|-----------|---------|-----|--------|
| User-pushback detection trigger | Haiku LLM, semantic, 5 categories | Regex weight≥2, 2 categories | **Large** (semantic recall) | **Steal** as parallel slow-path |
| Hook recursion safety | `STEERING_LOG_INTERNAL_RUN=1` env var | Implicit (bash hooks don't spawn claude today) | **Medium** (latent risk) | **Steal** before next agent-spawning hook |
| Async work persistence | 4-file disk state machine + cleanup-on-resume | Fire-and-forget, no replay | **Large** (data loss on crash) | **Steal** for `.remember/` and learnings DB |
| Task-boundary in event log | Episode = file, sealed with Result line | None — flat events | **Large** (no narrative grouping) | **Steal** with `.remember/episodes/` |
| Robust LLM JSON extraction | `extractJsonRecord` brace-walker (no regex) | `json.loads` only | **Medium** (silent drops) | **Steal** as `utils/extract_json.py` |
| Cheap-classifier-then-expensive-generator | Built-in pipeline | Not used (we always Sonnet/Opus) | **Medium** (cost + latency) | **Enhance** — adopt for high-frequency hooks |
| Negative-example prompts | Explicit "Do NOT" section per classifier | Mostly positive instructions | **Small** | **Enhance** existing prompts |
| Sub-agent spawn pattern | Node spawn detached + unref | Bash `nohup &` ad-hoc | **Small** | **Enhance** — standardize helper |
| Episode result taxonomy | 4 states (completed/paused/cancelled/failed) | None | **Small** | **Steal** when adding episodes |
| LLM call retry on parse fail | `AGENT_MAX_RETRIES=2` in pipeline | Inconsistent across helpers | **Medium** | **Enhance** — unify in llm wrapper |

## Gaps Identified

Mapped to the six-dimensional scan:

- **Memory / Learning** — biggest gap. We have eventless flat memory (`now.md` overwritten, `today-*.md` daily snapshot). Episode abstraction would let us query "show me everything from the auth refactor task" instead of date-windowed grep. Their `findLatestEpisode` + `completeEpisode` is the minimum viable narrative grouping.
- **Failure / Recovery** — second-biggest gap. Their cleanup.js on SessionStart is the resume mechanism we lack. If our hook crashes mid-write to learnings DB, the event is gone. Their `isFinished` flag is the contract: detector/summarizer can crash anywhere, the next session resumes from the last queued trigger.
- **Quality / Review** — gap on classifier precision. Regex catches "no, that's wrong" but misses "we're using JWT, not session auth" (no negation keyword). LLM detector with negative-example prompt catches the latter while filtering "yes option 2" / "can you add a comment?" weak signals.
- **Security / Governance** — minor latent gap. We don't have hook-spawning-claude scenarios *today*, but the moment we add one (e.g. autonomous learning promotion via subagent), we need the env-var safeguard already in place.
- **Execution / Orchestration** — small gap. Our agent dispatch (parallel agents skill) is more sophisticated than theirs; their value is just the disk-state contract for *single* background agents.
- **Context / Budget** — N/A in their architecture. They use 2-message detector windows by design (cheap), no token budgeting because each call is pre-bounded by the buffer slice.

## Adjacent Discoveries

- **`.md` as build-time string asset** — `loader: { '.md': 'text' }` esbuild plugin. Useful pattern for any tool shipping prompts as bundled assets (avoids runtime file I/O, simplifies distribution).
- **Jest `.md` transform** (`jest.mdTransform.cjs`, 8 lines) — turns `.md` imports into `module.exports = JSON.stringify(content)`. Lets prompt files be unit-tested for placeholder presence. Could apply to our `prompt-linter` agent test suite.
- **`spawnSync('claude', ['--print', '--model', model])` as a programmable Claude API** — shows that Claude Code's `--print` mode is effectively a local LLM call. Cheaper than going to api.anthropic.com when you already have Claude Code installed. Worth knowing for offline-friendly tooling.
- **Hanlgy's plugin pattern** (`hanlogy/claude-plugins` is the parent) — single-purpose plugins that do one thing via hooks. Our skill ecosystem is heavier; lighter plugin form factor might be useful for "always-on" passive captures.

## Path Dependency Speed-Assess

- **Locking decisions**: Markdown-file-per-episode locks them out of fast structured queries. They can grep, can't `SELECT WHERE type='pushback' AND topic LIKE '%auth%'`. For their use case (human-readable history) this is fine — for ours (memory feeding back into agents) it's a deal-breaker. We should keep markdown for narrative, SQL for query.
- **Missed forks**: Could have stored episodes in SQLite — would gain queryability, lose `git diff` / `cat` / cross-tool readability. Could have used WebSocket for real-time hooks instead of file-based — would gain liveness, lose crash-resume.
- **Self-reinforcement**: Plugin is tightly coupled to Claude Code hooks API; rewriting for another CLI is a full port. Hanlogy's whole product strategy assumes Claude Code lock-in.
- **Lesson for us**: Steal the *contracts* (4-file state machine, isFinished flag, episode result enum), avoid the *coupling* (don't tie our memory to markdown-only — keep `events_db` SQL primary, episodes as derived markdown view).

## Meta Insights

1. **Same hook event, two routing strategies, both valuable**. Regex-classify is zero-cost & precise on literals; LLM-classify is cents-per-call & semantic. They don't compete — regex handles fast path (instant additionalContext injection), LLM handles slow path (background structured capture). Our `correction-detector.sh` should keep its regex precision but gain a parallel LLM lane for everything regex misses. The mistake would be replacing one with the other.

2. **Episode = the atomic unit of agent memory worth saving**. Both flat event streams (our `.remember/`) and SQL event tables fail to capture *task narrative*. An episode has clear start (new topic), middle (moments append), and termination (Result line). This is the same shape as a traditional agent's "task" but with a key twist — episodes self-seal. Once `**Result**: completed` is appended, the file is immutable. That immutability is what makes episodes safely cacheable, indexable, and shareable across sessions.

3. **The minimum viable Crash-Resume contract is two flags and four files**. `isFinished:true|false` on each context file is the entire recovery protocol. SessionStart reads them, decides truncate-or-resume, deletes them. No WAL, no transaction log, no PID files. The whole disk-state machine fits in 80 LOC (`cleanup.ts` + `advance{Detector,Summarizer}.ts`). Most "checkpoint/restart" implementations over-engineer this 10x.

4. **Physical safeguards beat prompt safeguards every time**. `STEERING_LOG_INTERNAL_RUN=1` is 4 lines and *cannot* be talked out of. A prompt instruction "don't trigger yourself" can be ignored, hallucinated past, or forgotten on context compaction. Env-var guards, file-system checks, and exit codes are the real defense. We've seen this repeatedly across 78 rounds — every time we relied on prompt-level "please don't", it eventually broke; every time we used a hard gate (hook block, file mode, env check), it held.

5. **A 1-star repo can outperform a 1000-star repo on architecture clarity**. This project is 3 commits old, 1 star, but every file does one thing, the names tell the story (`advanceDetector`, `findLatestEpisode`, `completeEpisode`, `safeGuard`), and the disk contracts are explicit. The lesson: stars measure adoption, not design quality. When stealing, optimize for code-to-concept ratio, not popularity.
