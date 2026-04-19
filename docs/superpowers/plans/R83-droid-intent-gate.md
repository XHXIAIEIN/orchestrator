# Plan: R83 P0#4 — Factory DROID Per-Message Intent Gate

> **Source pattern**: `docs/steal/R83-cl4r1t4s-steal.md` P0 #4 (Factory DROID Phase 0 mandatory intent classification).
> **For executors**: follow `SOUL/public/prompts/plan_template.md` conventions. Every step has a copy-paste `verify` command.

## Goal

Every assistant turn declares its intent as `[INTENT: diagnostic | implementation | spec]` in the first 200 bytes of its response; a PreToolUse hook reads the intent from shared state and blocks Edit/Write/Bash-with-side-effects when intent is `diagnostic` or `spec` violates path constraints; after 3 consecutive turns with no intent declaration the hook escalates from warn to block. **Done** = (a) test case "diagnostic turn + Edit call" → hook blocks; (b) test case "implementation turn + Edit call" → hook allows; (c) test case "3 missing INTENT turns + Edit call" → hook blocks with escalation message.

## Why This Scope

DROID enforces the gate at the harness level, not the model level. We adopt the same approach: the agent declares intent explicitly; a hook enforces it against tool calls. The existing `state.sh` IPC mechanism (from R50 Caveman steal) provides cross-hook state without needing transcript access. The existing PreToolUse(Edit|Write) hook chain in `.claude/settings.json` is the correct mount point.

ASSUMPTION: PreToolUse hooks receive `tool_input` JSON only — they do NOT have direct access to the transcript or the preceding assistant message text. Therefore intent is communicated via state file written by a `UserPromptSubmit` hook that parses the assistant's last response. If the harness does not expose the prior assistant turn to UserPromptSubmit, the fallback is: agent writes intent to `.claude/hooks/state/intent.json` as a tool call (Bash echo) immediately before any Edit/Write. The plan covers both paths; Phase 2 Step 7 makes the explicit architectural decision.

Simplicity pre-check: minimum viable = 1 grammar doc + 1 constraint file + 1 state-writer hook + 1 intent-gate hook + 1 settings wire-up + 1 test file = 6 files. Plan below touches 7 files (adds warn-counter logic via state.sh). Within 2x simplest.

Execution-order coordination with P0#2 (Phase-gate tool guard): both hooks mount at PreToolUse(Edit|Write). Intent gate MUST run first (it can block immediately). Phase-gate runs second (it checks env-manifest state). Settings.json array order determines execution: intent-gate entry placed before phase-gate entry.

## File Map

| Action | Path | Responsibility |
|--------|------|---------------|
| Create | `SOUL/public/prompts/intent-gate.md` | Canonical intent grammar reference: three intent types, declaration syntax, when to switch |
| Create | `.claude/skills/claude-at/constraints/intent-declaration.md` | Layer-0 hard rule: every response turn MUST start with `[INTENT: ...]`; diagnostic forbids Edit/Write; spec forbids `src/` writes |
| Create | `.claude/hooks/intent-writer.sh` | UserPromptSubmit hook: parses the last assistant message for `[INTENT: ...]` tag, writes to state key `intent.current` + increments `intent.missing-streak` if absent |
| Create | `.claude/hooks/intent-gate.sh` | PreToolUse(Edit\|Write\|Bash) hook: reads `intent.current` from state, enforces per-intent tool constraints, escalates on missing-streak ≥ 3 |
| Modify | `.claude/settings.json` | Wire `intent-writer.sh` into `UserPromptSubmit`; wire `intent-gate.sh` into `PreToolUse(Edit\|Write\|Bash)` BEFORE the existing `guard.sh` entry |
| Create | `tests/hooks/test_intent_gate.sh` | Integration test: three cases (diagnostic+Edit→block; implementation+Edit→allow; 3×no-intent+Edit→block) using state.sh stubs |
| Create | `tests/hooks/fixtures/intent-state-diagnostic.sh` | State fixture: sets `intent.current=diagnostic` and `intent.missing-streak=0` via state_set for use by test harness |

No files outside the repo root. No modifications to protected files (CLAUDE.md, boot.md, identity.md, hall-of-instances.md).

---

## Phase 1: Intent Grammar + Constraint Rule

### Task 1: Canonical grammar doc

- [ ] **Step 1.** Create `SOUL/public/prompts/intent-gate.md` with five sections:
  1. **Intent vocabulary**: three types with exact token spellings — `diagnostic` (read-only analysis; allowed tools: Read, Grep, Glob, Bash-read-only; forbidden: Edit, Write, Bash with state-modifying flags), `implementation` (full tool access; requires prior `diagnostic` turn unless the request is unambiguously a net-new creation), `spec` (write plan/doc files only; allowed paths: `docs/`, `SOUL/`, `plans/`; forbidden: `src/`, `.claude/hooks/`, any file in `.github/`).
  2. **Declaration syntax**: `[INTENT: diagnostic]` — square brackets, lowercase, first 200 bytes of assistant response. One declaration per turn; last one wins if multiple appear.
  3. **Switching rules**: `diagnostic` → `implementation` requires explicit re-declaration in the new turn; a turn that opens with `[INTENT: implementation]` resets the streak counter. "If unsure, ask one concise clarifying question and declare `[INTENT: diagnostic]`."
  4. **Missing-declaration behavior**: first two turns without declaration emit a systemMessage warning; third consecutive missing turn causes the gate to block Edit/Write until an explicit INTENT declaration appears.
  5. **Examples**: good (diagnostic response with Read calls), bad (implementation-level Edit without declaration), edge (spec turn that tries to write to `src/`).
  → verify: `test -f SOUL/public/prompts/intent-gate.md && grep -qc '\[INTENT:' SOUL/public/prompts/intent-gate.md | grep -qE '^[2-9]' && grep -q 'missing-streak' SOUL/public/prompts/intent-gate.md`

- [ ] **Step 2.** Create `.claude/skills/claude-at/constraints/intent-declaration.md` with front-matter `---\ntitle: intent-declaration\nrule_type: layer-0-hard\n---`. Body must contain three non-negotiable rules verbatim:
  - *"Rule 1 — Declaration required: Every assistant response turn MUST begin with `[INTENT: diagnostic | implementation | spec]` within the first 200 bytes. Responses without a declaration are treated as diagnostic (safe default) but increment the missing-streak counter."*
  - *"Rule 2 — Diagnostic lock: When intent is `diagnostic`, the following tool calls are forbidden: Edit, Write, MultiEdit, and any Bash command that contains `>`, `>>`, `tee`, `mv`, `cp`, `rm`, `git commit`, `git add`, `git push`, `mkdir`, `touch`. Violation causes the PreToolUse hook to block."*
  - *"Rule 3 — Spec path lock: When intent is `spec`, Edit/Write are allowed only on paths matching `^(docs/|SOUL/|plans/|\.claude/skills/.*SKILL\.md)`. Writes to `src/`, `.claude/hooks/`, or `.github/` are blocked."*
  → verify: `test -f .claude/skills/claude-at/constraints/intent-declaration.md && grep -q 'rule_type: layer-0-hard' .claude/skills/claude-at/constraints/intent-declaration.md && grep -c 'Rule [123]' .claude/skills/claude-at/constraints/intent-declaration.md | grep -q 3`

- [ ] **Step 3.** Create `.claude/skills/claude-at/` directory if absent, and verify the `constraints/` subdirectory exists.
  - depends on: step 2
  → verify: `test -d .claude/skills/claude-at/constraints && test -f .claude/skills/claude-at/constraints/intent-declaration.md`

---

## Phase 2: Hook Implementation

### Task 2: State-writer hook (UserPromptSubmit)

- [ ] **Step 4.** Create `.claude/hooks/intent-writer.sh` with shebang `#!/bin/bash`. Reads UserPromptSubmit JSON from stdin via `INPUT=$(head -c 65536)`. Logic:
  1. Extract last assistant message text: `LAST_ASSISTANT=$(echo "$INPUT" | jq -r '.messages // [] | map(select(.role == "assistant")) | last | .content // ""' 2>/dev/null)`.
  2. If `LAST_ASSISTANT` is empty (no prior assistant turn exists — first turn of session): source `lib/state.sh`, set `intent.current=unknown`, set `intent.missing-streak=0`, exit 0 silently.
  3. Extract INTENT tag: `INTENT_TAG=$(echo "$LAST_ASSISTANT" | head -c 200 | grep -oiP '(?<=\[INTENT: )(diagnostic|implementation|spec)(?=\])' | head -1 | tr '[:upper:]' '[:lower:]')`.
  4. If `INTENT_TAG` is non-empty: source `lib/state.sh`, run `state_set "intent.current" "$INTENT_TAG"`, run `state_set "intent.missing-streak" "0"`, exit 0.
  5. If `INTENT_TAG` is empty: source `lib/state.sh`, run `state_set "intent.current" "unknown"`, increment missing-streak via `state_incr "intent.missing-streak"`. If new streak value is 1 or 2, emit `{"systemMessage":"[INTENT-GATE] No INTENT declaration found (streak: N). Declare [INTENT: diagnostic | implementation | spec] at the start of your next response. Third consecutive missing declaration will block Edit/Write."}`. Exit 0.
  - depends on: step 1
  → verify: `bash -n .claude/hooks/intent-writer.sh && grep -q 'intent.current' .claude/hooks/intent-writer.sh && grep -q 'intent.missing-streak' .claude/hooks/intent-writer.sh`

- [ ] **Step 5.** Make `intent-writer.sh` executable and add a `--selftest` branch that (a) feeds a synthetic JSON payload with an assistant message containing `[INTENT: diagnostic]` through the logic and (b) asserts `state_get "intent.current"` returns `diagnostic` after processing.
  - depends on: step 4
  → verify: `chmod +x .claude/hooks/intent-writer.sh && bash .claude/hooks/intent-writer.sh --selftest | grep -q 'SELFTEST OK'`

### Task 3: Intent-gate hook (PreToolUse)

ASSUMPTION verified in step 4: UserPromptSubmit receives full message history in `.messages[]`. If `jq` path above returns empty in production, fallback is step 7 below.

- [ ] **Step 6.** Create `.claude/hooks/intent-gate.sh` with shebang `#!/bin/bash`. Reads PreToolUse JSON from stdin via `INPUT=$(head -c 65536)`. Logic:
  1. Extract: `TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // ""')`, `FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // ""')`, `BASH_CMD=$(echo "$INPUT" | jq -r '.tool_input.command // ""')`.
  2. Fast-pass: if `TOOL_NAME` is not in `(Edit|Write|MultiEdit|Bash)` → exit 0.
  3. Source `lib/state.sh`. Read `INTENT=$(state_get "intent.current")` and `STREAK=$(state_get "intent.missing-streak")`.
  4. Missing-streak escalation: if `STREAK` ≥ 3, emit `{"decision":"block","reason":"[INTENT-GATE] 3 consecutive turns without INTENT declaration. Declare [INTENT: diagnostic | implementation | spec] at the start of your response before calling Edit/Write/Bash."}` and exit 0.
  5. Diagnostic enforcement: if `INTENT` = `diagnostic` AND `TOOL_NAME` is `Edit|Write|MultiEdit` → block with reason `[INTENT-GATE] Intent is diagnostic — Edit/Write forbidden. Switch to [INTENT: implementation] if you need to modify files.`
  6. Diagnostic Bash filter: if `INTENT` = `diagnostic` AND `TOOL_NAME` = `Bash` AND `BASH_CMD` matches `(>|>>|\btee\b|\bmv\b|\bcp\b|\brm\b|git commit|git add|git push|\bmkdir\b|\btouch\b)` → block with reason `[INTENT-GATE] Intent is diagnostic — state-modifying Bash forbidden.`
  7. Spec path enforcement: if `INTENT` = `spec` AND `TOOL_NAME` is `Edit|Write|MultiEdit` AND `FILE_PATH` does NOT match `^(docs/|SOUL/|plans/|\.claude/skills/.*SKILL\.md)` → block with reason `[INTENT-GATE] Intent is spec — writes outside docs/SOUL/plans/ forbidden. Declare [INTENT: implementation] to write to src/.`
  8. All other cases → exit 0 (allow implicitly).
  - depends on: step 4
  → verify: `bash -n .claude/hooks/intent-gate.sh && grep -q 'INTENT-GATE' .claude/hooks/intent-gate.sh && grep -c '"decision":"block"' .claude/hooks/intent-gate.sh | grep -qE '^[3-9]'`

- [ ] **Step 7.** Add fallback detection to `intent-gate.sh`: after step 6's logic 3 (state read), if `INTENT` = `unknown` AND a file `.claude/hooks/state/intent.json` exists (the explicit file-write fallback path), parse it with `jq -r '.intent // "unknown"'` and override the `INTENT` variable. Add a comment block:
  ```
  # ARCHITECTURAL NOTE: Two paths for intent propagation:
  # Path A (preferred): intent-writer.sh parses UserPromptSubmit .messages[] and writes to state.sh.
  # Path B (fallback): Agent explicitly runs `bash .claude/hooks/set-intent.sh diagnostic`
  #   before any Edit/Write call. Used when harness does not expose message history to hooks.
  # If both paths produce conflicting values, Path A wins (most recent hook run).
  ```
  - depends on: step 6
  → verify: `grep -q 'ARCHITECTURAL NOTE' .claude/hooks/intent-gate.sh && grep -q 'intent.json' .claude/hooks/intent-gate.sh`

- [ ] **Step 8.** Create `.claude/hooks/set-intent.sh` as the Path B fallback helper: accepts one argument (`diagnostic`, `implementation`, or `spec`), validates it against the allowed set, writes `{"intent": "<value>", "ts": "<epoch>"}` to `.claude/hooks/state/intent.json` using `jq -n`, and exits 0. Rejects unknown values with exit 1 and a message to stderr.
  - depends on: step 7
  → verify: `bash .claude/hooks/set-intent.sh diagnostic && jq -e '.intent == "diagnostic"' .claude/hooks/state/intent.json`

- [ ] **Step 9.** Make `intent-gate.sh` and `set-intent.sh` executable.
  - depends on: steps 6, 8
  → verify: `test -x .claude/hooks/intent-gate.sh && test -x .claude/hooks/set-intent.sh`

### Task 4: Settings wire-up

- [ ] **Step 10.** Read `.claude/settings.json` fully. Add `intent-writer.sh` to `hooks.UserPromptSubmit[0].hooks` array (append after existing `correction-detector.sh` entry — UserPromptSubmit order matters less). Add `intent-gate.sh` as a NEW entry at the START of the `hooks.PreToolUse` array with matcher `Edit|Write|MultiEdit|Bash`, using `jq` to prepend rather than append, so it executes before `guard.sh`. Verify the resulting JSON is valid before writing back.
  - depends on: steps 5, 9
  → verify: `jq -e '.hooks.UserPromptSubmit[0].hooks | map(select(.command | contains("intent-writer"))) | length >= 1' .claude/settings.json && jq -e '.hooks.PreToolUse[0].hooks[0].command | contains("intent-gate")' .claude/settings.json`

---

## Phase 3: Integration Testing

### Task 5: Test fixtures + harness

- [ ] **Step 11.** Create `tests/hooks/fixtures/intent-state-diagnostic.sh` as a sourceable bash file that sets state to a known diagnostic baseline:
  ```bash
  source .claude/hooks/lib/state.sh
  state_set "intent.current" "diagnostic"
  state_set "intent.missing-streak" "0"
  ```
  And a second fixture function `intent_state_implementation()` that sets `intent.current=implementation` + streak=0. And a third `intent_state_missing_streak_3()` that sets `intent.current=unknown` + streak=3.
  → verify: `bash -c 'source tests/hooks/fixtures/intent-state-diagnostic.sh; source .claude/hooks/lib/state.sh; [ "$(state_get intent.current)" = "diagnostic" ] && echo OK' | grep -q OK`

- [ ] **Step 12.** Create `tests/hooks/test_intent_gate.sh` (executable bash) with exactly three test cases. Each case: (a) loads the appropriate state fixture, (b) builds a JSON payload with `jq -n`, (c) pipes to `intent-gate.sh`, (d) captures stdout and asserts. Print `PASS: <case>` or `FAIL: <case>: got=<actual>` per case. Exit 1 if any case fails.
  - **Case 1** — diagnostic + Edit → block: Load `intent_state_diagnostic`. Payload: `{"tool_name":"Edit","tool_input":{"file_path":"src/main.py","old_string":"x","new_string":"y"}}`. Assert stdout contains `"decision":"block"` and `INTENT-GATE`.
  - **Case 2** — implementation + Edit → allow: Load `intent_state_implementation`. Same payload. Assert stdout does NOT contain `"decision":"block"` (empty or `"decision":"allow"`).
  - **Case 3** — missing-streak=3 + Write → block: Load `intent_state_missing_streak_3`. Payload: `{"tool_name":"Write","tool_input":{"file_path":"src/foo.ts","content":"x"}}`. Assert stdout contains `"decision":"block"` and `consecutive turns`.
  - depends on: steps 9, 11
  → verify: `chmod +x tests/hooks/test_intent_gate.sh && bash tests/hooks/test_intent_gate.sh`

- [ ] **Step 13.** Extend `tests/hooks/test_intent_gate.sh` with two additional edge cases (append to the file, do not rewrite):
  - **Case 4** — spec + write to `docs/` → allow: Set intent=spec, streak=0. Payload: `{"tool_name":"Write","tool_input":{"file_path":"docs/my-plan.md","content":"x"}}`. Assert: no block.
  - **Case 5** — spec + write to `src/main.py` → block: Same state. Payload file_path=`src/main.py`. Assert: block with `writes outside docs/SOUL/plans/`.
  - depends on: step 12
  → verify: `bash tests/hooks/test_intent_gate.sh | grep -E 'PASS|FAIL' | wc -l | grep -qE '^5$' && bash tests/hooks/test_intent_gate.sh | grep -qv FAIL`

- [ ] **Step 14.** Run `bash -n .claude/hooks/intent-writer.sh && bash -n .claude/hooks/intent-gate.sh && bash -n .claude/hooks/set-intent.sh` to confirm all three hooks parse cleanly as bash, then run the full test suite one final time and confirm all 5 cases pass.
  - depends on: step 13
  → verify: `bash -n .claude/hooks/intent-writer.sh && bash -n .claude/hooks/intent-gate.sh && bash -n .claude/hooks/set-intent.sh && bash tests/hooks/test_intent_gate.sh | grep -c PASS | grep -q 5`

- [ ] **Step 15.** Validate that `.claude/settings.json` remains valid JSON after all edits by running `jq empty .claude/settings.json` and confirm the PreToolUse array order still places `intent-gate` before `guard.sh` by checking array index 0 vs the guard.sh entry.
  - depends on: step 10
  → verify: `jq empty .claude/settings.json && jq -r '.hooks.PreToolUse | to_entries[] | select(.value.hooks[0].command | contains("guard.sh")) | .key' .claude/settings.json | grep -qvE '^0$'`

---

## Phase Gates

### Gate 1: Plan → Implement

- [ ] Every step has action verb + specific target + verify command
- [ ] No banned placeholder phrases (checked against Iron Rule table)
- [ ] Dependencies explicit on every multi-step task
- [ ] Total steps: 15 (within 5–30 range)
- [ ] Simplicity pre-check documented (see "Why This Scope" above)
- [ ] Both ASSUMPTION blocks are explicitly labeled and will be resolved empirically at Steps 4 and 7
- [ ] Execution-order conflict with P0#2 resolved: intent-gate placed first in PreToolUse array (Step 10)
- [ ] Owner review: **not required** (all changes are new files except settings.json append; reversible; no production impact until first agent turn)

### Gate 2: Implement → Verify

- [ ] All 15 verify commands executed and passing
- [ ] `git diff --stat` shows only files in the File Map (no collateral edits)
- [ ] 5/5 test cases pass in `tests/hooks/test_intent_gate.sh`
- [ ] `jq empty .claude/settings.json` passes (valid JSON)
- [ ] No orphaned imports or dead state keys introduced by the changes

### Gate 3: Verify → Commit

- [ ] Pre-commit hook clean (guard-rules.conf unchanged; block-protect.sh scan passes)
- [ ] Commit message: `feat(hooks): R83 P0#4 — DROID per-message intent gate (diagnostic/implementation/spec enforcement)`
- [ ] Cross-reference in commit body: `Refs: docs/steal/R83-cl4r1t4s-steal.md:48`

---

## Dependencies on Other R83 Plans

| Slug | Plan | Coupling |
|------|------|----------|
| P0#1 `R83-dia-trust-tagging` | Trusted/Untrusted Data Classification | Independent. Ships first. Provides `injection-sigils.sh` library; no overlap with intent-gate. |
| P0#2 `R83-droid-phase-gate` | Phase-Gate Tool Guard (`phase-gate.sh`, PreToolUse Edit\|Write) | **Execution-order conflict**: both hooks mount at PreToolUse(Edit\|Write). Resolution: intent-gate MUST precede phase-gate in the `settings.json` PreToolUse array — diagnostic blocks immediately, phase-gate is redundant if already blocked. When implementing P0#2, the implementor MUST insert `phase-gate` after the `intent-gate` entry, not before. This plan's Step 10 establishes the slot; P0#2's settings.json edit must not displace it. |
| P0#3 `R83-manus-typed-events` | Typed Event Stream Architecture | No direct coupling. Typed frontmatter on memory files does not interact with per-message intent classification. If event type `plan` is adopted, `spec` intent maps cleanly to it. |
| P0#4 `R83-droid-intent-gate` | This plan | — |
| P0#5 `R83-anti-fabrication` | Data Integrity Anti-Fabrication Rule | Additive. Anti-fabrication adds a grep-check for `mock`/`TODO`/`stub` in newly-written code at verification time. This check is downstream of intent-gate: it fires only after implementation-intent writes succeed. No ordering constraint. |

---

## Known Limits / Deferred Items

- `ASSUMPTION A: UserPromptSubmit hook receives full message history in .messages[].` If the harness only passes the current user message (not prior turns), `intent-writer.sh` will always see empty `LAST_ASSISTANT` and can never parse intent from the response. Fallback: Path B (`set-intent.sh` explicit call). Resolve empirically at Step 4 selftest by inspecting the raw INPUT JSON. If Path A fails, add a note to `SOUL/public/prompts/intent-gate.md` and the constraint file that Path B is the active mechanism.

- `ASSUMPTION B: The grep-oiP Perl-compatible lookbehind in intent-writer.sh (Step 4) is available in the bash environment.` If `grep -P` is unavailable (macOS ships POSIX grep), replace with `sed -n 's/.*\[INTENT: \([a-z]*\)\].*/\1/p'`. The verify command in Step 5 (selftest) will surface this failure immediately.

- Scope excludes the `ask` intent type (DROID also classifies "ambiguous" requests). We use `diagnostic` as the safe-default for ambiguous turns — no third terminal state needed.

- Scope excludes per-tool allowlist expansion. If `spec` intent needs to write to additional path prefixes (e.g., `.claude/skills/*/SKILL.md` or `SOUL/private/`), extend the regex in Step 6 logic 7 — do not create a new hook.

- The missing-streak counter resets on any valid INTENT declaration (step 4 logic 4). It does NOT reset on session start automatically — `session-start.sh` should call `state_del "intent.missing-streak"` and `state_del "intent.current"` to avoid leaking state between sessions. That modification to `session-start.sh` is out of scope for this plan; log as a follow-up.

---

## Effort Estimate

| Task | Content | Time |
|------|---------|------|
| Task 1 (grammar doc + constraint file + directory check) | Steps 1–3 | 30 min |
| Task 2 (state-writer hook + selftest) | Steps 4–5 | 40 min |
| Task 3 (intent-gate hook + fallback + set-intent helper + chmod) | Steps 6–9 | 60 min |
| Task 4 (settings wire-up) | Step 10 | 15 min |
| Task 5 (fixtures + 5-case test suite + final validation) | Steps 11–15 | 35 min |
| **Total** | | **~3h** |
