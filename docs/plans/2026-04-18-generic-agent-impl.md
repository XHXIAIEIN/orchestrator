# Plan: GenericAgent Runtime Constraints — P0+P1 Implementation

## Goal

Ship five P0 runtime governance patterns from GenericAgent (turn-cadence escalation, no-tool interception, out-of-band subagent intervention, adversarial verify-subagent, memory axioms) and three P1 patterns (paste-by-reference guard, fuzzy-match file read, subagent IO protocol) as new skills and hooks in `.claude/`, with every constraint living at engine level (hooks / SKILL.md constraints), not prompt level.

## Context

Source: R82 GenericAgent steal report (`docs/steal/R82-generic-agent-steal.md`).
Key finding: GenericAgent's `sys_prompt.txt` is 7 lines; all real constraints are runtime hooks. Our current system inverts this — CLAUDE.md is large, hooks are thin. The steal is about moving our existing soft constraints to engine-level enforcement and adding the three patterns we lack entirely (turn-cadence, live intervention, adversarial verifier).

## ASSUMPTIONS

- `ASSUMPTION-1`: Claude Code hook schema uses `exit_code != 0` + JSON `{"decision": "block", "reason": "..."}` to stdout to block the Stop event and inject a continue prompt. (Evidence: stall-detector.sh pattern; confirm against `.claude/settings.json` hook config before step 10.)
- `ASSUMPTION-2`: The `stop` hook receives `last_assistant_message` in stdin JSON — same field stall-detector.sh reads.
- `ASSUMPTION-3`: Turn counter is not natively available in hook stdin; we will derive it from a state file written by session-start and incremented by post-tool-use hook.
- `ASSUMPTION-4`: `Monitor` tool in Claude Code can tail a file by path — used for P0-3 subagent IO. If not available, owner must confirm alternative.
- `ASSUMPTION-5`: `.claude/settings.json` already wires `PostToolUse` and `Stop` hooks; if not, step 1 must add the wiring before any hook script is written.
- `ASSUMPTION-6`: All new skills target the main repo path (`D:/Users/Administrator/Documents/GitHub/orchestrator/`) since plans are implementation instructions, not code written in the worktree.

## File Map

### New files — Create

| File | Purpose |
|------|---------|
| `.claude/skills/turn-cadence/SKILL.md` | P0-1: Documents the 7/10/35-turn escalation rules agents must follow |
| `.claude/skills/turn-cadence/constraints/hard-escalation.md` | Layer 0: Non-negotiable turn-gate rules |
| `.claude/hooks/turn-counter.sh` | PostToolUse hook: increments per-session turn counter in `.claude/hooks/state/turn-{SESSION_ID}.txt` |
| `.claude/hooks/turn-cadence-gate.sh` | Stop hook: reads turn counter, injects [DANGER] escalation block if threshold hit |
| `.claude/skills/no-tool-interception/SKILL.md` | P0-2: Stop-hook interception rules for non-tool responses |
| `.claude/skills/no-tool-interception/constraints/block-patterns.md` | Layer 0: Exact regex patterns that trigger block |
| `.claude/hooks/no-tool-gate.sh` | Stop hook: intercepts "complete/完成/搞定" without `[VERIFY]`/`VERDICT` token |
| `.claude/skills/subagent-intervention/SKILL.md` | P0-3: File-channel protocol for live parent→subagent intervention |
| `.claude/skills/subagent-intervention/constraints/channel-contract.md` | Layer 0: `_stop`/`_keyinfo`/`_intervene` file semantics |
| `.claude/hooks/subagent-channel.sh` | PostToolUse hook: checks `temp/{task}/_stop|_keyinfo|_intervene.txt` each turn, injects content |
| `.claude/skills/verify-subagent/SKILL.md` | P0-4: Adversarial verify subagent dispatch protocol |
| `.claude/skills/verify-subagent/verify_sop.md` | Forked + adapted verify_sop — 65-line adversarial checklist with two-failure-modes header |
| `.claude/skills/verify-subagent/constraints/verdict-required.md` | Layer 0: `VERDICT: PASS/FAIL/PARTIAL` literal required before plan exit |
| `SOUL/public/prompts/memory_axioms.md` | P0-5: Four memory axioms gate (Action-Verified / Sanctity / No Volatile / Minimum Pointer) |
| `.claude/skills/memory-axioms/SKILL.md` | P0-5: Skill wrapper that routes to memory_axioms.md |
| `.claude/skills/memory-axioms/constraints/no-volatile-state.md` | Layer 0: Hard ban on PID/timestamp/session-ID in memory writes |
| `SOUL/public/memory/file_access_stats.json` | P0-5: Access frequency tracker (bootstrapped as `{}`) |
| `.claude/skills/paste-ref/SKILL.md` | P1: `{{file:path:start:end}}` expansion guard documentation |
| `.claude/skills/fuzzy-read/SKILL.md` | P1: FileNotFound fuzzy-match "Did you mean" protocol |
| `.claude/skills/subagent-io/SKILL.md` | P1: `input.txt`/`output.txt`/`[ROUND END]` sentinel IO protocol |

### Modified files — Modify

| File | Change |
|------|--------|
| `.claude/skills/verification-gate/SKILL.md` | Add "Two Failure Modes" header + rationalization-immunity list forked from GenericAgent verify_sop; add `[VERIFY]` step as mandatory last plan step |
| `SOUL/public/prompts/plan_template.md` | Add mandatory `[VERIFY]` final step requirement and adversarial-verify-subagent gate at Implement → Done transition |
| `.claude/hooks/session-start.sh` | Initialize `SOUL/public/memory/file_access_stats.json` if missing; write session turn-state file |
| `.claude/hooks/session-stop.sh` | Clean up per-session turn-state file; run file_access_stats GC candidate report |

## Steps

### Phase 1 — Foundation: Turn Counter Infrastructure

**1.** Read `.claude/settings.json` (or `.claude/config.json`) to confirm PostToolUse and Stop hook wiring exists; if missing, add `"hooks": {"PostToolUse": [".claude/hooks/turn-counter.sh"], "Stop": [".claude/hooks/turn-cadence-gate.sh", ".claude/hooks/no-tool-gate.sh"]}` to the config  
→ verify: `cat .claude/settings.json | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('hooks',{}))"` shows PostToolUse and Stop keys

**2.** Create `.claude/hooks/turn-counter.sh` — PostToolUse hook that reads `SESSION_ID` from env (or derives it as `$$`-based fallback), increments integer in `.claude/hooks/state/turn-${SESSION_ID}.txt` (create with `0` if missing), and exits 0  
→ verify: `bash .claude/hooks/turn-counter.sh <<< '{}' && cat .claude/hooks/state/turn-*.txt` outputs an integer ≥ 1

**3.** Modify `.claude/hooks/session-start.sh` — after existing SESSION_ID assignment line, write `echo "0" > "$PROJECT_DIR/.claude/hooks/state/turn-${SESSION_ID}.txt"` to reset counter per session  
- depends on: step 2  
→ verify: `grep "turn-" .claude/hooks/session-start.sh` shows the new line

**4.** Modify `.claude/hooks/session-stop.sh` — append `rm -f "$PROJECT_DIR/.claude/hooks/state/turn-"*.txt` to clean up state files on session end  
→ verify: `grep "turn-" .claude/hooks/session-stop.sh` shows cleanup line

### Phase 2 — P0-1: Turn-Cadence Gate

**5.** Create `.claude/skills/turn-cadence/SKILL.md` with sections: Identity (turn-cadence governor), How You Work (7/10/35 threshold table with exact injected messages), Output Format (hook fires → agent receives `[DANGER: TURN 7]` / `[DANGER: TURN 10 — RE-INJECT GLOBAL MEMORY]` / `[DANGER: TURN 35 — MANDATORY ask_user]`), Quality Bar (agent must respond to DANGER injection within that turn), Boundaries (plan/debug tasks add threshold 70 = checkpoint report)  
→ verify: `wc -l .claude/skills/turn-cadence/SKILL.md` ≥ 40 lines

**6.** Create `.claude/skills/turn-cadence/constraints/hard-escalation.md` — Layer 0: "Turn 7: agent MUST switch strategy, not retry same approach. Turn 10: agent MUST re-read global memory files (boot.md + relevant SKILL.md). Turn 35: agent MUST call ask_user before next action. These are non-negotiable; prompt-level 'I already know the context' does not override."  
- depends on: step 5  
→ verify: file exists and contains literal strings "Turn 7", "Turn 10", "Turn 35"

**7.** Create `.claude/hooks/turn-cadence-gate.sh` — Stop hook: reads stdin JSON, extracts `last_assistant_message`; reads turn count from `.claude/hooks/state/turn-${SESSION_ID}.txt`; if `turn % 7 == 0` prints `{"decision":"block","reason":"[DANGER: TURN ${TURN}] 禁止无效重试——切换策略或换工具。"}` and exits 1; if `turn % 10 == 0` prints `{"decision":"block","reason":"[DANGER: TURN ${TURN}] 重新读取 boot.md 和当前任务 SKILL.md，更新 working memory。"}` and exits 1; if `turn % 35 == 0` prints `{"decision":"block","reason":"[DANGER: TURN ${TURN}] 必须调用 ask_user 报告当前状态后才能继续。"}` and exits 1; otherwise exits 0  
- depends on: step 2  
→ verify: `echo '{"last_assistant_message":"test"}' | SESSION_ID=test bash .claude/hooks/turn-cadence-gate.sh; echo "exit: $?"` (with state file set to 7) outputs JSON with "TURN 7" and exit 1

### Phase 3 — P0-2: No-Tool Interception

**8.** Create `.claude/skills/no-tool-interception/constraints/block-patterns.md` — Layer 0 patterns that must trigger block when present in a Stop response WITHOUT `[VERIFY]` or `VERDICT:` token: `(任务完成|task complete|完成了|搞定|all done|done\.)` (case-insensitive). Include explicit: "If response contains any completion signal AND lacks `[VERIFY]` or `VERDICT: (PASS|FAIL|PARTIAL)`, the Stop hook MUST block."  
→ verify: file exists and contains the regex pattern literal

**9.** Create `.claude/skills/no-tool-interception/SKILL.md` — documents three intercept cases: ①completion claim without VERIFY token → block; ②response is >200 chars code block with <30 chars natural language → block with "请补充 tool call 或说明下一步"; ③empty/max_tokens response → block with "响应不完整，请重新生成"  
→ verify: file exists, contains three numbered cases

**10.** Create `.claude/hooks/no-tool-gate.sh` — Stop hook: reads `last_assistant_message` from stdin JSON; checks if message matches completion pattern from step 8 AND lacks `[VERIFY]`/`VERDICT:` token; if both conditions met, prints `{"decision":"block","reason":"[no-tool-gate] 检测到完成声明但缺少 [VERIFY] 或 VERDICT token。请运行验证命令后再声明完成。"}` and exits 1; otherwise exits 0  
- depends on: step 8, step 9  
→ verify: `echo '{"last_assistant_message":"任务完成，代码已写好。"}' | bash .claude/hooks/no-tool-gate.sh` outputs JSON block and exits 1; `echo '{"last_assistant_message":"任务完成。[VERIFY] all tests pass."}' | bash .claude/hooks/no-tool-gate.sh` exits 0

### Phase 4 — P0-3: Out-of-Band Subagent Intervention

**11.** Create `.claude/skills/subagent-intervention/constraints/channel-contract.md` — Layer 0 file-channel contract: `temp/{task}/` directory is the IPC root; `_stop.txt` presence → subagent MUST exit after current turn; `_keyinfo.txt` content → injected verbatim into next turn's prompt prefix; `_intervene.txt` content → injected as `[PARENT INTERVENTION]` block in next turn; all three files are consume-once (read + delete); parent writes, subagent reads; subagent MUST NOT write to these files  
→ verify: file exists and contains all four filenames literally

**12.** Create `.claude/skills/subagent-intervention/SKILL.md` — documents: how parent sets up temp dir; how to pass `task_id` to subagent; how parent uses Monitor tool to observe `output.txt`; how parent writes `_intervene.txt` when drift detected; subagent's obligation to call `consume_intervention_files` turn-end hook  
- depends on: step 11  
→ verify: file exists and contains "Monitor" and "_intervene.txt" literals

**13.** Create `.claude/hooks/subagent-channel.sh` — PostToolUse hook: if env var `TASK_ID` is set, checks `temp/${TASK_ID}/_stop.txt`; if exists, reads content, deletes file, prints `{"decision":"block","reason":"[parent-stop] ${CONTENT}"}` and exits 1; checks `temp/${TASK_ID}/_keyinfo.txt`; if exists, reads content, deletes file, appends to `.claude/hooks/state/keyinfo-${TASK_ID}.txt`; checks `temp/${TASK_ID}/_intervene.txt`; if exists, reads content, deletes file, prints `{"decision":"block","reason":"[PARENT INTERVENTION] ${CONTENT}"}` and exits 1; if none present, exits 0  
- depends on: step 11  
→ verify: `mkdir -p temp/test-task && echo "switch to plan B" > temp/test-task/_intervene.txt && TASK_ID=test-task bash .claude/hooks/subagent-channel.sh <<< '{}'` outputs JSON with "PARENT INTERVENTION" and exits 1; confirm file is deleted after run

### Phase 5 — P0-4: Adversarial Verify-Subagent

**14.** Create `.claude/skills/verify-subagent/verify_sop.md` — 65-line adversarial verifier script (forked from GenericAgent, adapted to our stack): Header "你的两个失败模式：①验证回避（默认 PASS 因为懒）②被前80%迷惑（大部分对就说全对）"; Per-deliverable checklists: 脚本（幂等性/边界输入/缺失依赖）、API（合约测试/错误路径）、配置（所有环境受影响）、Bug修复（原始 reproduce case 仍触发 FAIL 则修复失败）; 必须至少一项对抗探测（边界值/负输入/并发/孤儿引用）; 输出格式严格为 `VERDICT: PASS` / `VERDICT: FAIL — [具体失败项]` / `VERDICT: PARTIAL — [通过项] / [失败项]`  
→ verify: `wc -l .claude/skills/verify-subagent/verify_sop.md` between 55 and 75

**15.** Create `.claude/skills/verify-subagent/constraints/verdict-required.md` — Layer 0: "After any plan's final step, a verify-subagent MUST be dispatched with verify_sop.md as its instruction set. The parent agent MUST NOT declare the plan complete until it receives a response containing literal `VERDICT: PASS`. `VERDICT: FAIL` or `VERDICT: PARTIAL` must trigger a fix loop (max 2 iterations). Skipping the verify-subagent dispatch is a protocol violation equivalent to skipping a git commit with failing tests."  
- depends on: step 14  
→ verify: file contains literal "VERDICT: PASS" and "2 iterations"

**16.** Create `.claude/skills/verify-subagent/SKILL.md` — how to dispatch: `Agent(subagent_type="claude-sonnet", system_prompt=verify_sop.md content, prompt="验证以下产物: {deliverable description}")`, read response for VERDICT literal, handle PASS/FAIL/PARTIAL branches  
- depends on: step 14, step 15  
→ verify: file contains "VERDICT" and "dispatch" in first 20 lines

**17.** Modify `.claude/skills/verification-gate/SKILL.md` — prepend a "Two Failure Modes" section (before "The Five Steps") that reads: "你的两个失败模式：①验证回避——遇到通过率高的测试就停止；②被前80%迷惑——大部分输出正确就宣布完成。两种模式都会让真正的 bug 逃过验证。"; also append to "Common Rationalizations" table: row `"80%的测试通过了" | "剩下20%正是 bug 藏身处" | "Run ALL tests. Fix every failure."`  
→ verify: `grep "两个失败模式" .claude/skills/verification-gate/SKILL.md` returns a match

**18.** Modify `SOUL/public/prompts/plan_template.md` — in "Gate 3: Implement → Done" section, add checklist item `[ ] Verify-subagent dispatched and returned VERDICT: PASS (required for plans ≥ 5 steps)`; in the Step Format section add note "Last step of every plan MUST be: `Dispatch verify-subagent with verify_sop.md → verify: agent response contains 'VERDICT: PASS'`"  
→ verify: `grep "VERDICT" SOUL/public/prompts/plan_template.md` returns at least 2 matches

### Phase 6 — P0-5: Memory Axioms + Access Stats

**19.** Create `SOUL/public/prompts/memory_axioms.md` — four axioms as a Gate that runs before any memory write: ①Action-Verified Only: "No Execution, No Memory — 没有对应 commit hash 或命令输出的信息禁止写入 L1/L2"; ②Sanctity of Verified Data: "GC 时不得丢弃 evidence=verbatim 或 evidence=artifact 的条目"; ③No Volatile State: "禁止在记忆文件中写入 PID、时间戳、session ID、临时路径"; ④Minimum Sufficient Pointer: "只记录召回所需的最小信息——文件名+行号优于复制整段代码"  
→ verify: `grep -c "①\|②\|③\|④" SOUL/public/prompts/memory_axioms.md` outputs 4

**20.** Create `.claude/skills/memory-axioms/SKILL.md` — Identity: memory write gate; How You Work: "Before any file_patch or file_write to SOUL/ or .claude/memory/, run through memory_axioms.md gate; if any axiom fails, abort write and explain which axiom"; links to `SOUL/public/prompts/memory_axioms.md`  
→ verify: file exists and contains "memory_axioms.md" reference

**21.** Create `.claude/skills/memory-axioms/constraints/no-volatile-state.md` — Layer 0: "HARD BLOCK: Any memory write containing patterns matching `\b(PID|pid|\d{5,}|session[-_]id|/tmp/|localhost:\d{4,})\b` MUST be rejected. The agent must remove volatile references before retrying the write. This is not a prompt suggestion — it is a pre-write validation rule."  
→ verify: file contains the regex pattern literal and "HARD BLOCK"

**22.** Create `SOUL/public/memory/file_access_stats.json` with initial content `{}` (empty JSON object)  
→ verify: `python3 -c "import json; d=json.load(open('SOUL/public/memory/file_access_stats.json')); print(type(d))"` outputs `<class 'dict'>`

**23.** Modify `.claude/hooks/session-start.sh` — add after existing SESSION_ID init: `STATS="$PROJECT_DIR/SOUL/public/memory/file_access_stats.json"; [ ! -f "$STATS" ] && echo '{}' > "$STATS"`  
→ verify: `grep "file_access_stats" .claude/hooks/session-start.sh` returns the new line

**24.** Modify `.claude/hooks/session-stop.sh` — add GC candidate report: `python3 "$PROJECT_DIR/SOUL/tools/memory_gc_report.py" 2>/dev/null || true` at the end (non-blocking; script will be written in a future session)  
→ verify: `grep "memory_gc_report" .claude/hooks/session-stop.sh` returns the new line

### Phase 7 — P1 Patterns

**25.** Create `.claude/skills/paste-ref/SKILL.md` — documents `{{file:path:start:end}}` pattern: "When constructing new_string for an Edit call that would require echoing >30 lines of existing file content, use `{{file:absolute/path:start_line:end_line}}` reference instead. Before submitting the Edit, expand all `{{file:...}}` references by reading the actual file lines. If expansion fails (file not found, line out of range), raise an error — do NOT silently substitute empty string." Includes one worked example.  
→ verify: file contains `{{file:` literal and "do NOT silently"

**26.** Create `.claude/skills/fuzzy-read/SKILL.md` — documents FileNotFound recovery protocol: "When a Read tool call returns FileNotFoundError, before reporting the error: ①list files in the target directory depth-1; ②compute basename similarity using Python `difflib.SequenceMatcher` against the requested path's basename; ③if any candidate scores >0.4, report 'Did you mean: {top-3 candidates with scores}?' before the error; ④only report raw FileNotFoundError if no candidate scores >0.4". Includes Python snippet for the similarity check.  
→ verify: file contains "difflib" and "0.4" and "Did you mean"

**27.** Create `.claude/skills/subagent-io/SKILL.md` — P1 subagent file IO protocol: parent creates `temp/{task_id}/` dir; writes `input.txt` with task spec; subagent reads `input.txt`, processes, appends each turn's output to `output.txt` followed by literal `[ROUND END]\n`; parent reads `reply.txt` to inject parent response; `context.json` contains `{"task_id": "...", "temp_dir": "/absolute/path/to/temp/task_id/", "parent_task": "..."}` with absolute paths; `--verbose` flag appends raw tool output to `output.txt`; parent monitors `output.txt` with Monitor tool  
→ verify: file contains "[ROUND END]" and "context.json" and "absolute"

--- PHASE GATE: Implementation → Verification ---
[ ] Deliverable exists: all 20 new files created, 4 existing files modified
[ ] Acceptance criteria met: each hook script exits 0 on clean input, exits 1 + JSON on trigger condition
[ ] No open questions: ASSUMPTION-1 through ASSUMPTION-5 resolved against actual settings.json
[ ] Owner review: required — hook wiring into .claude/settings.json changes agent behavior globally

### Phase 8 — Wire Hooks + Final Validation

**28.** Read `.claude/settings.json` to confirm current hook event mapping; add `turn-counter.sh` to PostToolUse array, add `turn-cadence-gate.sh` and `no-tool-gate.sh` to Stop array, add `subagent-channel.sh` to PostToolUse array  
- depends on: step 7, step 10, step 13  
→ verify: `python3 -c "import json; d=json.load(open('.claude/settings.json')); print(d['hooks'])"` shows all four scripts in their respective event lists

**29.** Run smoke test for turn-cadence-gate: `echo "7" > .claude/hooks/state/turn-test123.txt && echo '{"last_assistant_message":"done"}' | SESSION_ID=test123 bash .claude/hooks/turn-cadence-gate.sh; echo "exit=$?"` — must output JSON with "TURN 7" and exit 1; then `echo "6" > .claude/hooks/state/turn-test123.txt && echo '{"last_assistant_message":"done"}' | SESSION_ID=test123 bash .claude/hooks/turn-cadence-gate.sh; echo "exit=$?"` — must exit 0  
- depends on: step 7  
→ verify: both commands produce expected exit codes

**30.** Run smoke test for no-tool-gate: `echo '{"last_assistant_message":"任务完成，所有代码已更新。"}' | bash .claude/hooks/no-tool-gate.sh; echo "exit=$?"` — must exit 1 with block JSON; `echo '{"last_assistant_message":"任务完成。VERDICT: PASS — all tests green."}' | bash .claude/hooks/no-tool-gate.sh; echo "exit=$?"` — must exit 0  
- depends on: step 10  
→ verify: first call exits 1, second exits 0

**31.** Run smoke test for subagent-channel: `mkdir -p temp/smoke-test && echo "abort — owner redirected task" > temp/smoke-test/_stop.txt && TASK_ID=smoke-test bash .claude/hooks/subagent-channel.sh <<< '{}'; echo "exit=$?" && [ ! -f temp/smoke-test/_stop.txt ] && echo "file consumed OK"`  
- depends on: step 13  
→ verify: exits 1 with block JSON, `_stop.txt` no longer exists

## Non-Goals

- Do NOT port GenericAgent's LLM backend (SSE parsers, MixinSession, model-specific tool schemas) — we run Claude Code which handles this.
- Do NOT replicate GenericAgent's 9-tool minimal surface — we deliberately have a richer tool set.
- Do NOT implement L4 sliding-window history merge or compress_history_tags — those target GenericAgent's custom loop; Claude Code's context management is handled by the platform. (Defer to future P1 session if needed.)
- Do NOT implement scheduler port-lock singleton (P1-4) — CronCreate tool evaluation needed first; out of scope here.
- Do NOT create the `memory_gc_report.py` script (step 24 references it non-blocking) — it's a future session deliverable.
- Do NOT implement `{{file:...}}` as an actual pre-processor in hook code — step 25 is a SKILL.md documentation only; runtime expansion is a future code task.

## Rollback

All changes are additive (new files + appends to existing hooks). If a hook misfires:

1. Disable misfiring hook: comment out its entry in `.claude/settings.json` hooks array (surgical — does not affect other hooks).
2. New SKILL.md files have no runtime effect until an agent explicitly routes to them — safe to leave in place.
3. `file_access_stats.json` is additive data; deleting it resets counts but loses no critical state.
4. The two modifications to existing hook scripts (`session-start.sh`, `session-stop.sh`) are append-only — remove added lines if needed.
5. If `plan_template.md` or `verification-gate/SKILL.md` changes cause confusion, `git diff` will show exact additions; revert those lines only.

No database schema changes. No destructive file operations. Full rollback via `git revert` on the implementation commit.
