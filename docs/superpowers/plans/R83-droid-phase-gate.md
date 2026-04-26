# Plan: R83 P0#2 — Factory DROID Phase-Gate Tool Guard

> **Source pattern**: `docs/steal/R83-cl4r1t4s-steal.md` P0 #2 (Factory DROID source-file tool refusal until env bootstrap is validated).
> **For executors**: follow `SOUL/public/prompts/plan_template.md` conventions. Every step has a copy-paste `verify` command.

## Goal

`Edit` and `Write` tool calls that target non-whitelisted files are blocked by a PreToolUse hook when `.claude/phase-state.json` does not contain `"phase": 1` or higher; running `scripts/phase-advance.sh` with a valid env fingerprint advances phase to 1 and unblocks normal file editing. **Done** = a `phase=0` Edit on `src/foo.py` is blocked; a `phase=0` Edit on `pyproject.toml` is allowed; a `phase=1` Edit on `src/foo.py` is allowed; all three cases verified by the test harness without starting a real Claude session.

## Why This Scope

Factory DROID's strongest moat is that the constraint lives at tool level, not prompt level. Our `dispatch-gate.sh` already enforces branch-level isolation (steal/* / round/*); this plan adds the orthogonal dimension: **phase-level isolation** within any session. The existing `Edit|Write|MultiEdit` PreToolUse matcher in `.claude/settings.json` is the correct mount point — we append one new hook entry to it rather than creating a new matcher.

Simplicity pre-check: minimum viable = 1 state schema doc + 1 hook script + 1 advance script + 1 settings entry + 2 fixture files + 1 test harness = 7 files. Plan below touches 8 files (adds 1 constraint doc). Within 2x simplest.

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `.claude/phase-state.json` | Runtime state file: `phase` (0–2), `validated_at` (ISO-8601), `env_fingerprint` (sha256 of lockfile+runtime marker) |
| Create | `.claude/hooks/phase-gate.sh` | PreToolUse(Edit\|Write\|MultiEdit) hook: reads phase-state.json, blocks non-whitelisted paths when phase < 1 |
| Create | `scripts/phase-advance.sh` | CLI tool: validates env markers, writes phase-state.json with new phase + fingerprint |
| Create | `SOUL/public/prompts/phase-gate.md` | Canonical spec: phase semantics, whitelist, fingerprint algorithm, agent-facing protocol |
| Create | `.claude/skills/steal/constraints/phase-gate.md` | Layer-0 hard rule for steal skill: steal agents must call phase-advance.sh before editing source files |
| Modify | `.claude/settings.json` | Append `phase-gate.sh` to the existing `Edit|Write|MultiEdit` PreToolUse hooks array |
| Create | `tests/hooks/fixtures/phase-gate-scenarios.json` | Three JSON payloads: (a) phase=0 + src/foo.py, (b) phase=0 + pyproject.toml, (c) phase=1 + src/foo.py |
| Create | `tests/hooks/test_phase_gate.sh` | Shell test harness: feeds each fixture through phase-gate.sh, asserts block/allow outcomes |

No files outside the repo root. No modifications to `dispatch-gate.sh`, `CLAUDE.md`, `boot.md`, `identity.md`, `hall-of-instances.md`, or any other R83 plan file.

---

## Phase 1: State Mechanism

### Task 1: Phase-state schema and runtime file

- [ ] **Step 1.** Create `SOUL/public/prompts/phase-gate.md` with five sections:
  1. **Phase semantics**: `0` = pre-bootstrap (no env validated), `1` = env validated (git sync + frozen install + tool check done), `2` = full review cycle complete (reserved for future auditing use).
  2. **Whitelist** (files Edit/Write are allowed at any phase): `*.md`, `*.lock`, `package.json`, `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `pyproject.toml`, `requirements*.txt`, `Pipfile`, `Pipfile.lock`, `uv.lock`, `.python-version`, `.nvmrc`, `.node-version`.
  3. **Fingerprint algorithm**: `sha256sum` of the concatenation of (a) contents of the first lockfile found by `ls *.lock pyproject.toml requirements*.txt 2>/dev/null | head -1` and (b) the literal string `phase1-validated`. Stored in `env_fingerprint` field of phase-state.json.
  4. **phase-state.json schema**: `{"phase": 0, "validated_at": null, "env_fingerprint": null}` when fresh; `{"phase": 1, "validated_at": "2026-04-19T10:00:00Z", "env_fingerprint": "abc123..."}` when advanced.
  5. **Agent-facing protocol**: "Before editing any source file in a new worktree or after a `git worktree add`, run `bash scripts/phase-advance.sh` to advance phase to 1. The hook will cite this doc in its block message."
  → verify: `test -f SOUL/public/prompts/phase-gate.md && grep -q 'phase.*semantics\|Phase semantics' SOUL/public/prompts/phase-gate.md && grep -q 'env_fingerprint' SOUL/public/prompts/phase-gate.md && grep -q '\.python-version' SOUL/public/prompts/phase-gate.md`

- [ ] **Step 2.** Create `.claude/phase-state.json` with initial content `{"phase": 0, "validated_at": null, "env_fingerprint": null}`. This file is runtime state and must NOT be committed to git; verify `.gitignore` already excludes `.claude/phase-state.json` or add the entry.
  - depends on: step 1
  → verify: `jq -e '.phase == 0 and .validated_at == null and .env_fingerprint == null' .claude/phase-state.json`

- [ ] **Step 3.** Add `.claude/phase-state.json` to `.gitignore` if not already present. Locate the existing `.gitignore` at repo root, append the line `.claude/phase-state.json` under a `# Runtime state` comment if the pattern is not already there.
  - depends on: step 2
  → verify: `grep -q 'phase-state\.json' .gitignore`

### Task 2: Phase-advance script

- [ ] **Step 4.** Create `scripts/phase-advance.sh` (executable, shebang `#!/bin/bash`). The script accepts one optional argument `--phase N` (default: 1). Logic:
  1. Read current `REPO_ROOT` via `git rev-parse --show-toplevel`.
  2. Locate the first lockfile by running `ls "$REPO_ROOT"/*.lock "$REPO_ROOT"/pyproject.toml "$REPO_ROOT"/requirements*.txt 2>/dev/null | head -1`. If none found, print `PHASE-ADVANCE: No lockfile found. Env fingerprint will be null.` and proceed with fingerprint `null`.
  3. If lockfile found: compute `FINGERPRINT=$(cat "$LOCKFILE" | sha256sum | awk '{print $1}')`. Append the string `phase1-validated` before hashing: `FINGERPRINT=$(printf '%s\nphase1-validated' "$(cat "$LOCKFILE")" | sha256sum | awk '{print $1}')`.
  4. Write `{"phase": N, "validated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)", "env_fingerprint": "$FINGERPRINT"}` to `.claude/phase-state.json` using `jq -n`.
  5. Print `PHASE-ADVANCE: phase advanced to N at <timestamp>. Fingerprint: <first 12 chars of fingerprint>...`.
  - depends on: steps 2, 3
  → verify: `bash scripts/phase-advance.sh && jq -e '.phase == 1 and .validated_at != null' .claude/phase-state.json`

- [ ] **Step 5.** Add a `--reset` flag to `scripts/phase-advance.sh` that writes `{"phase": 0, "validated_at": null, "env_fingerprint": null}` back to `.claude/phase-state.json` and prints `PHASE-ADVANCE: reset to phase 0.`. This flag is needed by the test harness (step 13) to restore state between test cases without manual file edits.
  - depends on: step 4
  → verify: `bash scripts/phase-advance.sh --reset && jq -e '.phase == 0' .claude/phase-state.json`

---

## Phase 2: Hook Implementation

### Task 3: Core phase-gate hook

- [ ] **Step 6.** Create `.claude/hooks/phase-gate.sh` (executable, shebang `#!/bin/bash`). Reads PreToolUse JSON from stdin. Extract fields with a single `jq` call:
  ```
  PARSED=$(echo "$INPUT" | jq -r '[.tool_name // "", .tool_input.file_path // ""] | @tsv')
  TOOL_NAME=$(echo "$PARSED" | cut -f1)
  FILE_PATH=$(echo "$PARSED" | cut -f2)
  ```
  Fast-pass: if `TOOL_NAME` is not `Edit`, `Write`, or `MultiEdit` → `exit 0`.
  - depends on: step 1
  → verify: `test -x .claude/hooks/phase-gate.sh && bash -n .claude/hooks/phase-gate.sh`

- [ ] **Step 7.** Add the whitelist check inside `phase-gate.sh`. After extracting `FILE_PATH`, derive `BASENAME=$(basename "$FILE_PATH")` and `EXT="${FILE_PATH##*.}"`. Build a bash function `is_whitelisted` that returns 0 (allow) if any of the following match:
  - Extension match: `md` (any `.md` file).
  - Basename exact match against: `package.json`, `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `pyproject.toml`, `.python-version`, `.nvmrc`, `.node-version`, `Pipfile`, `Pipfile.lock`, `uv.lock`.
  - Basename glob match against: `requirements*.txt` (check with `case "$BASENAME" in requirements*.txt) ... esac`).
  - Basename glob match against: `*.lock` (any file ending in `.lock`).
  If none match, function returns 1 (not whitelisted).
  - depends on: step 6
  → verify: `bash -c 'source .claude/hooks/phase-gate.sh 2>/dev/null; echo "whitelist function defined"' || bash .claude/hooks/phase-gate.sh --selftest-whitelist 2>&1 | grep -q "pyproject.toml:allow"` (add `--selftest-whitelist` mode that prints `<filename>:allow|block` for a hardcoded list including `pyproject.toml`, `src/foo.py`, `README.md`, `requirements.txt`, `yarn.lock`; exits 0)

- [ ] **Step 8.** Add the phase check inside `phase-gate.sh`. After the whitelist function, main logic:
  1. Call `is_whitelisted "$FILE_PATH"` — if returns 0, `exit 0` (allow).
  2. Locate `PHASE_STATE="$(git rev-parse --show-toplevel)/.claude/phase-state.json"`. If file does not exist, treat as `phase=0`.
  3. Read `CURRENT_PHASE=$(jq -r '.phase // 0' "$PHASE_STATE" 2>/dev/null || echo 0)`.
  4. If `CURRENT_PHASE` >= 1, `exit 0` (allow).
  5. Otherwise: emit `{"decision":"block","reason":"[PHASE-GATE] Edit/Write blocked: phase=0 (env not bootstrapped). File '$FILE_PATH' is not on the pre-bootstrap whitelist. Run 'bash scripts/phase-advance.sh' to advance to phase 1. Protocol: SOUL/public/prompts/phase-gate.md"}` and `exit 0`.
  - depends on: steps 7, 5
  → verify: `echo '{"tool_name":"Edit","tool_input":{"file_path":"src/foo.py"}}' | bash .claude/hooks/phase-gate.sh | jq -e '.decision == "block"'`

- [ ] **Step 9.** Add `--selftest` mode to `phase-gate.sh` (gated by `[ "$1" = "--selftest" ]`). Runs three inline assertions without touching the real phase-state.json:
  1. Phase=0 + `src/foo.py` → expect `decision:block`.
  2. Phase=0 + `pyproject.toml` → expect `exit 0` (no output / allow).
  3. Phase=0 + `README.md` → expect `exit 0`.
  Each assertion uses a temp file at `$(mktemp)` to fake phase-state.json via the `PHASE_STATE` env override, feeds the payload through the hook logic inline, and prints `PASS: <case>` or `FAIL: <case>: <actual>`. Exits 1 if any FAIL.
  - depends on: step 8
  → verify: `bash .claude/hooks/phase-gate.sh --selftest | grep -v FAIL | grep -q 'PASS'`

### Task 4: Settings wire-up

- [ ] **Step 10.** Read `.claude/settings.json` in full. Locate the `PreToolUse` array entry whose `matcher` is `"Edit|Write|MultiEdit"`. It currently contains `config-protect.sh` and `block-protect.sh check`. Append a third hook entry to its `hooks` array:
  ```json
  {"type": "command", "command": "bash .claude/hooks/phase-gate.sh", "timeout": 3}
  ```
  Use `jq` to merge: identify the array index of the `Edit|Write|MultiEdit` entry, then use `jq '(.hooks.PreToolUse[] | select(.matcher == "Edit|Write|MultiEdit") | .hooks) += [{"type":"command","command":"bash .claude/hooks/phase-gate.sh","timeout":3}]'`.
  - depends on: steps 8, 9
  → verify: `jq -e '.hooks.PreToolUse[] | select(.matcher == "Edit|Write|MultiEdit") | .hooks | map(select(.command | contains("phase-gate.sh"))) | length >= 1' .claude/settings.json`

---

## Phase 3: Whitelist Config and Integration Tests

### Task 5: Layer-0 constraint for steal skill

- [ ] **Step 11.** Create `.claude/skills/steal/constraints/phase-gate.md`. Use the same front-matter structure as sibling constraints (`depth-before-breadth.md`, `worktree-isolation.md`): `---\ntitle: Phase Gate Enforcement\nrule_type: layer-0-hard\n---`. Body: one non-negotiable rule — *"After `git worktree add` for a steal task, the first action MUST be `bash scripts/phase-advance.sh` before reading or editing any source file outside the pre-bootstrap whitelist (*.md, *.lock, package.json, pyproject.toml, .python-version, requirements*.txt, Pipfile*, uv.lock, .nvmrc). Attempting to Edit/Write a non-whitelisted file before phase-advance will be blocked by the hook."* Include a 6-line example showing the correct sequence: worktree add → phase-advance → edit source.
  → verify: `test -f .claude/skills/steal/constraints/phase-gate.md && grep -q 'rule_type: layer-0-hard' .claude/skills/steal/constraints/phase-gate.md && grep -q 'phase-advance' .claude/skills/steal/constraints/phase-gate.md`

### Task 6: Test fixtures and harness

- [ ] **Step 12.** Create `tests/hooks/fixtures/phase-gate-scenarios.json` containing a JSON array of three scenario objects, each with fields `label`, `phase_state` (the full phase-state.json object to inject), and `tool_payload` (the PreToolUse JSON):
  1. `{"label":"block-src","phase_state":{"phase":0,"validated_at":null,"env_fingerprint":null},"tool_payload":{"tool_name":"Edit","tool_input":{"file_path":"src/foo.py","old_string":"x","new_string":"y"}}}` → expected decision: `block`.
  2. `{"label":"allow-pyproject","phase_state":{"phase":0,"validated_at":null,"env_fingerprint":null},"tool_payload":{"tool_name":"Edit","tool_input":{"file_path":"pyproject.toml","old_string":"a","new_string":"b"}}}` → expected decision: `allow` (no output or empty).
  3. `{"label":"allow-after-advance","phase_state":{"phase":1,"validated_at":"2026-04-19T10:00:00Z","env_fingerprint":"abc123"},"tool_payload":{"tool_name":"Write","tool_input":{"file_path":"src/foo.py","content":"print(1)"}}}` → expected decision: `allow`.
  → verify: `jq -e 'length == 3 and .[0].label == "block-src" and .[1].label == "allow-pyproject" and .[2].label == "allow-after-advance"' tests/hooks/fixtures/phase-gate-scenarios.json`

- [ ] **Step 13.** Create `tests/hooks/test_phase_gate.sh` (executable bash). For each of the three scenarios in the fixture:
  1. Write `scenario.phase_state` to a temp file `$(mktemp --suffix=.json)`.
  2. Set `PHASE_STATE=<tempfile>` env var (phase-gate.sh must respect this override — add the override to step 8's implementation: `PHASE_STATE="${PHASE_STATE:-$(git rev-parse --show-toplevel)/.claude/phase-state.json}"`).
  3. Pipe `scenario.tool_payload` through `PHASE_STATE=<tempfile> bash .claude/hooks/phase-gate.sh`.
  4. For `block-src`: assert output contains `"decision":"block"` — print `PASS: block-src` or `FAIL: block-src: <actual>`.
  5. For `allow-pyproject` and `allow-after-advance`: assert output is empty (hook exited 0 with no JSON) — print `PASS: <label>` or `FAIL: <label>: <actual>`.
  6. Clean up temp file after each case.
  Exit 1 if any case fails.
  - depends on: steps 9, 12
  → verify: `chmod +x tests/hooks/test_phase_gate.sh && bash tests/hooks/test_phase_gate.sh | tee /dev/stderr | grep -c 'PASS' | grep -qE '^3$'`

### Task 7: End-to-end rehearsal and cross-links

- [ ] **Step 14.** Run the full integration: reset state, attempt a blocked edit, advance phase, attempt the same edit allowed.
  ```
  bash scripts/phase-advance.sh --reset
  echo '{"tool_name":"Edit","tool_input":{"file_path":"src/orchestrator/core.py"}}' | bash .claude/hooks/phase-gate.sh | jq -e '.decision == "block"'
  bash scripts/phase-advance.sh
  echo '{"tool_name":"Edit","tool_input":{"file_path":"src/orchestrator/core.py"}}' | bash .claude/hooks/phase-gate.sh
  bash scripts/phase-advance.sh --reset
  ```
  - depends on: steps 8, 13
  → verify: `bash -c 'bash scripts/phase-advance.sh --reset && echo '\''{"tool_name":"Edit","tool_input":{"file_path":"src/orchestrator/core.py"}}'\'' | bash .claude/hooks/phase-gate.sh | jq -e ".decision == \"block\"" && bash scripts/phase-advance.sh && out=$(echo '\''{"tool_name":"Edit","tool_input":{"file_path":"src/orchestrator/core.py"}}'\'' | bash .claude/hooks/phase-gate.sh) && [ -z "$out" ] && echo end-to-end-PASS'`

- [ ] **Step 15.** Add a one-line reference to `phase-gate.md` in `SOUL/public/prompts/skill_routing.md` under the "env setup / bootstrap" route: append `→ Phase gating: SOUL/public/prompts/phase-gate.md` as a bullet under whichever section handles environment or worktree setup tasks.
  - depends on: step 1
  → verify: `grep -q 'phase-gate' SOUL/public/prompts/skill_routing.md`

- [ ] **Step 16.** Append a one-line entry to `docs/steal/R83-cl4r1t4s-steal.md`'s P0 table marking pattern #2 as landed: locate the row `| 2 | **Phase-Gate Tool Guard**` and change its `Effort` cell from `~4h` to `~4h — shipped <commit-sha>` after the implementation commit.
  - depends on: step 14
  → verify: `grep -q 'Phase-Gate Tool Guard' docs/steal/R83-cl4r1t4s-steal.md`

---

## Phase Gates

### Gate 1: Plan → Implement

- [ ] Every step has action verb + specific target + verify command (16 steps, all satisfy this)
- [ ] No banned placeholder phrases (verified against Iron Rule table: no "implement the logic", "update as needed", "etc.", "similar to X", "refactor", "clean up", "optimize" in isolation)
- [ ] Dependencies explicit on every multi-step task
- [ ] Total steps: 16 (within 5–30 range)
- [ ] Simplicity pre-check documented (see "Why This Scope" above: 8 files, within 2x simplest)
- [ ] Owner review: **not required** (task is reversible; phase-state.json is gitignored; hook appended to existing matcher; script is additive)

### Gate 2: Implement → Verify

- [ ] All 16 verify commands executed and passing
- [ ] `git diff` contains only the 8 files in the File Map (no collateral edits to `dispatch-gate.sh` or other hooks)
- [ ] End-to-end rehearsal (step 14) produces visible `end-to-end-PASS` output
- [ ] `phase-gate.sh --selftest` exits 0 with no FAIL lines
- [ ] `test_phase_gate.sh` exits 0 with exactly 3 PASS lines

### Gate 3: Verify → Commit

- [ ] Pre-commit hook clean (no protected-file edits — `git diff --stat` matches File Map)
- [ ] Commit message: `feat(hooks): R83 P0#2 — DROID-style phase-gate tool guard blocking Edit/Write before env bootstrap`
- [ ] Cross-reference in commit body: `Refs: docs/steal/R83-cl4r1t4s-steal.md:46` (the P0 row)

---

## Dependencies on Other R83 Plans

- **P0#1 `R83-dia-trust-tagging`** (independent, can ship first): creates `.claude/hooks/lib/injection-sigils.sh`. Phase-gate.sh can optionally source this library in a future hardening pass to scan for injection attempts in file paths, but it is not required for the current implementation. The `EXTERNAL_CONTENT` tag grammar from P0#1 applies to content read during pre-bootstrap; phase-gate enforces that editing is blocked until after that read-phase completes.

- **P0#2 `R83-droid-phase-gate`** (this plan): no inbound dependencies. Can ship independently of P0#3–P0#5.

- **P0#3 `R83-manus-typed-events`**: typed event frontmatter will eventually include `event_type: env_bootstrap` events. When P0#3 ships, `scripts/phase-advance.sh` should emit an `env_bootstrap` event to the memory compiler instead of (or in addition to) writing plain JSON. This is a forward compatibility note only — P0#2 does not block on P0#3.

- **P0#4 `R83-droid-intent-gate`**: both P0#2 and P0#4 install PreToolUse hooks that can emit `decision:block`. Execution order matters: in `.claude/settings.json`, `phase-gate.sh` MUST appear before `intent-gate.sh` in the `Edit|Write|MultiEdit` hooks array, because phase-gate is a harder prerequisite (no env = no editing regardless of intent). When P0#4 is implemented, the plan author must verify the array order and document it in `SOUL/public/prompts/phase-gate.md` section 5.

- **P0#5 `R83-anti-fabrication`**: no execution dependency. Anti-fabrication targets the `rationalization-immunity.md` and verification-gate layers; phase-gate targets the hook layer. Orthogonal.

---

## Known Limits / Deferred Items

- `ASSUMPTION: The phase-state.json path resolution via 'git rev-parse --show-toplevel' correctly identifies the worktree root (not the main repo root) when the hook runs inside a worktree. If git rev-parse returns the main repo root in some worktree configurations, phase-state.json must be read from the worktree's own .git/.. path. Resolve empirically in step 14's end-to-end rehearsal.`

- Scope excludes the `Read` and `Bash` tools: phase-gate only blocks Edit/Write/MultiEdit. A future hardening pass could extend to block `Bash` commands that write files (e.g., `tee`, `>` redirection) when phase < 1. Deferred — the shell-command pattern space is large and the Edit/Write/MultiEdit coverage catches the primary Claude Code file-mutation path.

- Scope excludes phase 2 semantics. The `"phase": 2` reserved value in the schema is a placeholder for a future "full review cycle complete" gate. `scripts/phase-advance.sh --phase 2` will write it but no hook acts on it in this plan.

- Windows path compatibility: `git rev-parse --show-toplevel` returns Unix-style paths on Windows when run inside Git Bash (the project shell). Verify in step 14 that paths like `/d/Users/...` are correctly resolved; if `jq` path comparison fails due to mixed separators, normalize with `sed 's|\\\\|/|g'` in phase-gate.sh.

---

## Effort Estimate

- Task 1 (phase schema doc + phase-state.json + .gitignore): 30 min
- Task 2 (phase-advance.sh + --reset flag): 40 min
- Task 3 (phase-gate.sh core + whitelist + selftest): 60 min
- Task 4 (settings wire-up): 10 min
- Task 5 (steal constraint doc): 15 min
- Task 6 (fixtures + test harness): 35 min
- Task 7 (end-to-end rehearsal + cross-links + R83 mark): 30 min
- **Total: ~3h 40min** (rounds to ~4h, matches steal report estimate)
