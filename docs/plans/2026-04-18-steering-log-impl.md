# Plan: Steering-Log Steal — Five Pattern Implementation (R78)

## Goal

Implement five stolen patterns from `hanlogy/steering-log` to close the following gaps: (1) add an env-var anti-recursion safeguard to all claude-spawning hooks, (2) port the brace-walking JSON extractor to `src/utils/extract_json.py` and wire it into all LLM-output parse paths, (3) add a two-stage LLM detector lane (Haiku classifier) alongside the existing regex in `correction-detector.sh`, (4) introduce a crash-resume 4-file disk-state machine for `.remember/` memory promotion, and (5) add episode self-sealing markdown under `.remember/episodes/`.

## Context

- Source: R78 steal report at `docs/steal/R78-steering-log-steal.md`
- Steal priority: P0 × 5 patterns (safeguard, brace-walker JSON extractor, two-stage LLM, crash-resume state machine, episode sealing)
- P1 patterns (negative-example prompts, placeholder substitution, spawn standardization, window-slice retry) deferred to follow-up session
- Implementation order: safeguard first (zero-dep, protects everything that follows), then JSON extractor (enables LLM paths), then LLM detector, then crash-resume state machine, then episodes

## ASSUMPTIONS

- `ASSUMPTION A1`: `claude --print --model haiku-3-5` (or `claude --print --model claude-haiku-3-5-20241022`) is available in the shell PATH where hooks execute — owner to verify model ID before step 7.
- `ASSUMPTION A2`: The `.remember/` directory write path used by existing hooks resolves to `$PROJECT_ROOT/.remember/` — confirmed by reading `correction-detector.sh` fallback paths.
- `ASSUMPTION A3`: `src/governance/audit/learnings.py::append_learning` is the authoritative write path for correction events — no parallel write path bypasses it.
- `ASSUMPTION A4`: `src/storage/events_db.py::EventsDB` constructor accepts an optional `db_path` arg; if not provided it defaults to `data/events.db` — owner to verify before step 12.
- `ASSUMPTION A5`: Hook scripts run with `$ORCHESTRATOR_ROOT` or equivalent set to the project root — confirmed by `correction-detector.sh` line 64.

## File Map

- `.claude/hooks/lib/safeguard.sh` — **Create** (4-line env-var anti-recursion guard)
- `.claude/hooks/correction-detector.sh` — **Modify** (source safeguard + add LLM slow-path detector)
- `.claude/hooks/session-start.sh` — **Modify** (source safeguard guard at top)
- `.claude/hooks/memory-save-hook.sh` — **Modify** (source safeguard guard at top)
- `src/utils/__init__.py` — **Create** (empty, makes `src/utils` a package)
- `src/utils/extract_json.py` — **Create** (brace-walking JSON extractor, ~40 LOC)
- `src/governance/audit/learnings.py` — **Modify** (replace bare `json.loads` on LLM output with `extract_json`)
- `.remember/buffer.jsonl` — **Create at runtime** (append-only raw conversation log; not committed)
- `.remember/pending.txt` — **Create at runtime** (work queue for promotion pipeline; not committed)
- `.remember/detector-context.json` — **Create at runtime** (detector window snapshot; not committed)
- `.remember/summarizer-context.json` — **Create at runtime** (summarizer window snapshot; not committed)
- `.claude/hooks/lib/remember_state.sh` — **Create** (helpers: `buffer_append`, `queue_push`, `context_snapshot`, `context_is_finished`, `context_resume`)
- `.claude/hooks/remember-pipeline.sh` — **Create** (SessionStart cleanup + resume logic reading the 4 state files)
- `.remember/episodes/` — **Create at runtime** (directory; not committed)
- `src/utils/episode.py` — **Create** (functions: `open_episode(slug)`, `append_moment(path, moment_md)`, `seal_episode(path, result)` where result in `{completed,paused,cancelled,failed}`)

## Steps

### Phase 0 — Safeguard (zero-dep, 1h)

1. Create `.claude/hooks/lib/safeguard.sh` with the following exact content:
   ```bash
   #!/usr/bin/env bash
   # Anti-recursion guard — source at the top of every hook that spawns a claude subprocess.
   # If ORCHESTRATOR_HOOK_INTERNAL=1 is set, this hook was invoked BY a spawned claude process.
   # Exit immediately to break the recursion loop.
   [ "${ORCHESTRATOR_HOOK_INTERNAL:-0}" = "1" ] && exit 0
   export ORCHESTRATOR_HOOK_INTERNAL=1
   ```
   → verify: `bash -c 'ORCHESTRATOR_HOOK_INTERNAL=1 source .claude/hooks/lib/safeguard.sh; echo "should not print"'` outputs nothing; `bash -c 'source .claude/hooks/lib/safeguard.sh; echo "ok"'` outputs `ok`

2. Add `source "$(dirname "$0")/lib/safeguard.sh"` as the second executable line (after the shebang/comment block) in `.claude/hooks/correction-detector.sh` — insert after line 8 (`SCRIPT_DIR=...`), before line 10 (`INPUT=$(head...`)
   → verify: `bash -c 'ORCHESTRATOR_HOOK_INTERNAL=1 echo "{\"prompt\":\"no wrong\"}" | bash .claude/hooks/correction-detector.sh'` exits with code 0 and prints nothing

3. Add `source "$(dirname "$0")/lib/safeguard.sh"` as the second executable line in `.claude/hooks/session-start.sh` — after the shebang/comment block, before `PROJECT_DIR=...` line
   → verify: `grep -n "safeguard" .claude/hooks/session-start.sh` returns a match

4. Add `source "$(dirname "$0")/lib/safeguard.sh"` as the second executable line in `.claude/hooks/memory-save-hook.sh`
   → verify: `grep -n "safeguard" .claude/hooks/memory-save-hook.sh` returns a match

### Phase 1 — Brace-Walking JSON Extractor (2h)

5. Create `src/utils/__init__.py` as an empty file (zero bytes)
   → verify: `python3 -c "import src.utils"` exits 0

   - depends on: nothing (standalone)

6. Create `src/utils/extract_json.py` with function `extract_json_record(text: str) -> dict | None` that:
   - Scans `text` left-to-right for the first `{` character
   - Tracks brace depth, increments on `{`, decrements on `}`, handles string-escape state (`"..."` and `\'...'` with backslash escape tracking)
   - On each depth-0 `}` (i.e., depth decrements to 0), slices the candidate substring from the opening `{` to current position inclusive
   - Attempts `json.loads(candidate)` — on success, returns the parsed dict immediately
   - If the parsed result is not a `dict`, continues scanning for the next `{`
   - Returns `None` if no balanced `{}` segment parses to a dict
   - Also exports `extract_json_list(text: str) -> list | None` using same logic for `[`/`]` delimiters
   → verify: `python3 -c "from src.utils.extract_json import extract_json_record; assert extract_json_record('Sure, here is the JSON: {\"k\": 1} done') == {'k': 1}; assert extract_json_record('no json here') is None; print('ok')"` prints `ok`

   - depends on: step 5

7. Open `src/governance/audit/learnings.py`, find every `json.loads(` call on LLM-generated text (not on file reads or DB rows), and replace each with `extract_json_record(...)` from `src.utils.extract_json` — import added at top of file
   → verify: `python3 -c "import src.governance.audit.learnings"` exits 0 (no import errors); `grep -n "extract_json_record" src/governance/audit/learnings.py` returns at least one match

   - depends on: step 6

### Phase 2 — Two-Stage LLM Correction Detector (3h)

8. Read `.claude/hooks/correction-detector.sh` in full to confirm current structure before modifying
   → verify: Read tool confirms file content matches what was read in session setup

9. Append to `.claude/hooks/correction-detector.sh` a new bash section after the existing regex block (after line 113 `exit 0` is removed and replaced) that:
   - Runs only when `total_weight == 0` (regex found nothing — slow path only)
   - Extracts the last 2 messages from `.remember/buffer.jsonl` (last assistant turn + current human turn) using `tail -2`
   - Constructs a JSON prompt string: `{"model":"claude-haiku-3-5-20241022","messages":[...],"system":"<contents of SOUL/public/prompts/correction-detector-llm.md>"}` — but at this step the system prompt file does not exist yet (created in step 10), so use a placeholder constant: `"Classify the human message. Reply with JSON only: {\"is_trigger\": true|false, \"category\": \"correction|pushback|scope-change|direction|preference\"}"`
   - Spawns `ORCHESTRATOR_HOOK_INTERNAL=1 claude --print --model claude-haiku-3-5-20241022 "$prompt_json"` via `bash -c "... &"` (detached, output captured to `/tmp/steering-detector-$$.out`)
   - Does NOT wait for the subprocess (fire-and-forget at this phase; result integration is P1)
   → verify: `bash -c 'echo "{\"prompt\":\"we use JWT not sessions\"}" | ORCHESTRATOR_HOOK_INTERNAL=0 bash .claude/hooks/correction-detector.sh'` exits 0 within 1 second (does not block on LLM call)

   - depends on: steps 2, 8

10. Create `SOUL/public/prompts/correction-detector-llm.md` with exact content:
    ```markdown
    You are a correction classifier. Given the last two turns of a conversation (assistant then human), classify the human message.

    Reply with JSON only — no preamble, no explanation:
    {"is_trigger": true|false, "category": "correction|pushback|scope-change|direction|preference|none"}

    category definitions:
    - correction: user says the agent produced wrong output (factual error, wrong code, wrong approach)
    - pushback: user disagrees with agent's choice without stating a factual error ("we use JWT, not sessions")
    - scope-change: user narrows or expands the task mid-flight
    - direction: user redirects the approach ("do it differently — use X instead")
    - preference: user states a personal/project preference that should be remembered

    Do NOT classify as a trigger:
    - Vague agreement ("ok", "sounds good", "yes please")
    - Social acknowledgement ("thanks", "great", "perfect")
    - Follow-up questions that extend rather than correct
    - Additive requests ("also add X") with no correction of existing output
    - Option selections ("option 2 please") with no correction signal
    - Short affirmatives under 5 characters
    ```
    → verify: `wc -l SOUL/public/prompts/correction-detector-llm.md` returns 20+; `grep "Do NOT" SOUL/public/prompts/correction-detector-llm.md` matches

    - depends on: nothing (standalone)

### Phase 3 — Crash-Resume 4-File State Machine (4h)

11. Create `.claude/hooks/lib/remember_state.sh` with the following five functions:
    - `buffer_append(role, content)` — appends `{"ts":"$(date -u +%Y-%m-%dT%H:%M:%SZ)","role":"$1","content":"$2"}` to `.remember/buffer.jsonl` atomically (write to `.remember/buffer.jsonl.tmp`, then `mv`)
    - `queue_push(timestamp)` — appends `$timestamp` as a line to `.remember/pending.txt`
    - `context_snapshot(file, is_finished, payload_json)` — writes `{"isFinished":$is_finished,"ts":"$(date -u ...)","payload":$payload_json}` to `.remember/$file` atomically
    - `context_is_finished(file)` — reads `.remember/$file`, uses `python3 -c "import sys,json; d=json.load(open(sys.argv[1])); print(d.get('isFinished','false'))"` to return `true`/`false`
    - `context_resume(file)` — reads `.remember/$file` and echoes the `payload` field as JSON
    → verify: `bash -c 'source .claude/hooks/lib/remember_state.sh; buffer_append "human" "test message"; grep -q "test message" .remember/buffer.jsonl && echo ok'` prints `ok`

    - depends on: step 1 (safeguard exists so remember_state.sh can source it if needed)

12. Create `.claude/hooks/remember-pipeline.sh` as the SessionStart cleanup script that:
    - Sources `.claude/hooks/lib/safeguard.sh` and `.claude/hooks/lib/remember_state.sh`
    - Reads `.remember/detector-context.json` — if it exists and `isFinished=true`, truncates `.remember/buffer.jsonl` at the line number matching the `ts` field in the context snapshot (lines after that timestamp are replayed; lines before are committed and can be dropped — use `grep -n` to find line, then `tail -n +N` to slice)
    - If `isFinished=false`, reads the last queued timestamp from `.remember/pending.txt` and echoes `[remember-pipeline] resuming from $ts` to stderr (actual re-dispatch to summarizer is P1)
    - If neither context file exists, creates empty `.remember/buffer.jsonl` and `.remember/pending.txt` (idempotent `touch`)
    - Creates `.remember/episodes/` directory if it does not exist (`mkdir -p`)
    → verify: `bash .claude/hooks/remember-pipeline.sh` exits 0; `ls .remember/` shows `buffer.jsonl`, `pending.txt`, `episodes/`

    - depends on: step 11

13. Register `remember-pipeline.sh` as a SessionStart hook by adding it to `.claude/hooks.json` under the `SessionStart` array — append `{"matcher":"","hooks":[{"type":"command","command":".claude/hooks/remember-pipeline.sh"}]}` as an additional entry (or add to existing SessionStart array depending on current structure)
    → verify: `python3 -c "import json; d=json.load(open('.claude/hooks.json')); starts=[h for ev in d.get('hooks',[]) if ev.get('event')=='SessionStart' for h in ev.get('hooks',[])] ; assert any('remember-pipeline' in str(h) for h in starts), starts"` exits 0

    - depends on: step 12

14. Modify `.claude/hooks/correction-detector.sh` to call `buffer_append "human" "$prompt"` (from `remember_state.sh`) immediately after `INPUT=$(head -c 65536)` — this makes correction-detector the write point for human turns in the buffer
    → verify: `bash -c 'echo "{\"prompt\":\"test human turn\"}" | bash .claude/hooks/correction-detector.sh'; grep -q "test human turn" .remember/buffer.jsonl && echo ok'` prints `ok`

    - depends on: steps 11, 9

### Phase 4 — Episode Self-Sealing (3h)

15. Create `src/utils/episode.py` with three functions:
    - `open_episode(slug: str, episodes_dir: str = ".remember/episodes") -> str` — creates `{episodes_dir}/{YYYYMMDDHHmmss}-{slug}.md` with header `# Episode: {slug}\n\n_Started: {ISO timestamp}_\n\n` and returns the absolute path
    - `append_moment(episode_path: str, moment_md: str) -> None` — appends `\n---\n\n{moment_md}\n` to the file atomically (open in append mode, write, flush, fsync)
    - `seal_episode(episode_path: str, result: str) -> None` — validates `result` is one of `{"completed", "paused", "cancelled", "failed"}`, raises `ValueError` otherwise; appends `\n\n---\n\n**Result**: {result}\n` then sets the file to read-only (`chmod 0o444`) so it cannot be reopened
    → verify: `python3 -c "from src.utils.episode import open_episode, append_moment, seal_episode; import tempfile, os; d=tempfile.mkdtemp(); p=open_episode('auth-refactor', d); append_moment(p, 'User pushed back on session auth'); seal_episode(p, 'completed'); assert not os.access(p, os.W_OK); print('ok')"` prints `ok`

    - depends on: step 5 (src/utils package exists)

16. Add a CLI trigger for episode sealing: modify `.claude/hooks/correction-detector.sh` to detect when `prompt` starts with `/done` (exact match after strip) and, if so, call `seal_episode(find_latest_episode(".remember/episodes"), "completed")` via `python3 -c "from src.utils.episode import seal_episode; ..."` — this provides the manual episode-close command
    → verify: `bash -c 'echo "{\"prompt\":\"/done\"}" | bash .claude/hooks/correction-detector.sh'` exits 0 and does not crash; if an episode file exists in `.remember/episodes/` it becomes read-only

    - depends on: steps 15, 14

17. Add `find_latest_episode(episodes_dir: str) -> str | None` to `src/utils/episode.py` — reads `os.listdir(episodes_dir)`, filters `*.md` files, sorts lexicographically (timestamp prefix ensures chronological), returns the last entry's absolute path, or `None` if directory is empty
    → verify: `python3 -c "from src.utils.episode import find_latest_episode, open_episode; import tempfile; d=tempfile.mkdtemp(); open_episode('t1', d); open_episode('t2', d); p=find_latest_episode(d); assert 't2' in p, p; print('ok')"` prints `ok`

    - depends on: step 15

--- PHASE GATE: Implementation → Verify ---
[ ] Deliverable exists: all 7 new/modified files present (`safeguard.sh`, `extract_json.py`, `remember_state.sh`, `remember-pipeline.sh`, `correction-detector-llm.md`, `episode.py`, updated `correction-detector.sh`)
[ ] Acceptance criteria met: verify commands for steps 1, 6, 11, 12, 15, 17 all pass
[ ] No open questions: ASSUMPTION A1 (haiku model ID) verified by owner before step 9 goes live
[ ] Owner review: not required (plan is approval)

## Non-Goals

- P1 patterns (negative-example prompt sections, `{{INCLUDE:}}` placeholder substitution, detached-spawn standardization, window-slice + retry) — deferred to a follow-up session
- P2 patterns (esbuild `.md` loader, TS shims) — Node-only, not applicable
- Replacing existing `EventsDB` SQL layer with markdown-only storage — steal report explicitly warns against this (R78 §Path Dependency)
- Migrating existing `.remember/today-*.md` daily snapshots to episode format — out of scope; episodes are additive new files in `.remember/episodes/`
- Pushing to remote or modifying any branch other than `steal/steering-log`

## Rollback

Each phase is independently rollback-able:

- **Phase 0 (safeguard)**: Delete `.claude/hooks/lib/safeguard.sh`; remove the single `source safeguard.sh` line from each modified hook — 3 targeted line removals, no data loss
- **Phase 1 (extract_json)**: Delete `src/utils/extract_json.py` and `src/utils/__init__.py`; revert `learnings.py` to bare `json.loads` — `git checkout src/governance/audit/learnings.py`
- **Phase 2 (LLM detector)**: Remove the appended bash section from `correction-detector.sh` (identifiable by comment `# ── LLM slow-path ──`); delete `SOUL/public/prompts/correction-detector-llm.md`
- **Phase 3 (crash-resume)**: Delete `.claude/hooks/lib/remember_state.sh` and `.claude/hooks/remember-pipeline.sh`; revert `.claude/hooks.json` SessionStart entry; remove `buffer_append` call from `correction-detector.sh`
- **Phase 4 (episodes)**: Delete `src/utils/episode.py`; remove `/done` handler from `correction-detector.sh`

All rollbacks are `git checkout <file>` or `rm` — no database migrations, no schema changes.
