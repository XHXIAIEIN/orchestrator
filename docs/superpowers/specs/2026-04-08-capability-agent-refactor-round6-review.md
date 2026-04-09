# Round 6 Review: Consumer-Side Integration Audit

**Date**: 2026-04-08
**Reviewer**: Orchestrator (Opus 4.6)
**Scope**: Design soundness, regression risks, consumer-side experience
**Method**: Cross-reference design doc against current codebase (dispatcher, executor, registry, semaphore, handoff, group_orchestration, FSM, intent)

## Summary

| Category | Count | Severity |
|----------|-------|----------|
| Design issues | 4 | 2 High / 2 Medium |
| Regression bugs | 6 | 3 High / 3 Medium |
| Consumer experience | 4 | 1 High / 3 Medium |

Previous 5 rounds focused on design self-consistency. This round audits **integration points** — where the new architecture meets existing consumer code.

---

## Design Issues (Structural)

### D1. `active_capabilities` is an implicit model selector [HIGH]

`active_capabilities` filters the entire compose chain including model. This means intent authors silently control model selection without any explicit model declaration:

```
engineer/code_fix → active_capabilities: [develop, test] → sonnet ✓
engineer/quick_check → active_capabilities: [inspect] → haiku (silent downgrade)
```

`model_floor` only guards against profile ceiling downgrades, not against active_capabilities filtering.

**Risk**: Someone edits an intent's active_capabilities, model changes silently. No log, no warning.

**Fix**: Either (a) add `model_floor` at the intent level, or (b) emit a warning log when compose model differs from agent's default: `"model downgraded from {agent_default} to {composed} via active_capabilities filtering"`.

---

### D2. Fact-Expression Split loses task traceability [HIGH]

Current system creates two independent tasks (fact_task, expr_task) with task_ids, statuses, retry capability, and dashboard visibility. New design inlines them as anonymous sub-executions in dispatcher Phase 0.5:

```python
fact_output = await executor.execute(fact_spec, spec)
expr_output = await executor.execute(expr_spec, spec, context=fact_output)
return merge(fact_output, expr_output)
```

Problems:
- No task_id → no dashboard visibility, no history, no retry granularity
- If fact succeeds but expr fails, fact's work is lost (entire dispatch fails)
- `return merge(...)` skips Phase 1-3 entirely — different execution path semantics

**Fix**: Phase 0.5 should create sub-tasks (with task_ids) rather than anonymous inline executions. Preserves traceability while keeping the dispatcher-side orchestration.

---

### D3. Ad-hoc multi-agent "always serialize" is overly conservative [MEDIUM]

Round 4 simplified ad-hoc dependency detection to "multi-agent ad-hoc always serialized". But:

```
dispatch(capabilities=["audit", "review", "inspect"])
→ [sentinel, reviewer, inspector] — all READ authority
→ forced serial execution despite zero conflict potential
```

Meanwhile, `scenarios.yaml/full_audit` with the same agents runs parallel. Same capability set, different code path, different behavior.

**Fix**: Default to "all READ → parallel, mixed authority with overlapping paths → serial" instead of blanket serialization.

---

### D4. FSM terminal value detection is fragile [MEDIUM]

Transition values: `@reviewer` (agent ref), `__self__` (retry), `""` / `approved` / `log_only` (terminal). Detection logic:

```python
if value.startswith("@"):  # agent ref
elif value == "__self__":   # retry
else:                       # terminal — but typos also land here silently
```

Any misspelled agent ref (e.g., `@reviwer`) fails loudly (good), but a misspelled terminal (e.g., `aproved`) is silently accepted as terminal (bad — no error, just wrong behavior).

**Fix**: Add `KNOWN_TERMINALS = {"", "approved", "log_only"}` whitelist. Values not in whitelist and not starting with `@` → raise error at registry load time.

---

## Regression Bugs

### B1. `_COLLABORATION_PATTERNS` Chinese department names [HIGH]

`group_orchestration.py` detects cross-department collaboration via regex:

```python
r"需要工程部|需要engineering|工程部配合": "engineering"
```

Post-refactor: department key `engineering` → agent key `engineer`, and agent identity no longer says "工程部". These regexes will **never match** in agent output, silently breaking multi-agent collaboration detection.

**Fix**: Migration step 5 (grep + replace) must include `_COLLABORATION_PATTERNS` — update both pattern text AND target values. Consider whether patterns should match agent identity terms instead of legacy department names.

---

### B2. `_DEPT_SPECIFIC_FIELDS` missing `architect` [HIGH]

`task_handoff.py` context filtering:

```python
_DEPT_SPECIFIC_FIELDS = {
    "engineering": {"code_diff", "file_list", "git_log", "implementation_notes"},
    ...
}
```

Current `engineering` covers both develop and refactor. Post-refactor, `engineer` and `architect` are separate agents. Simple 1:1 key rename (`engineering` → `engineer`) loses architect's access to `code_diff`, `file_list`, `git_log`.

**Fix**: New mapping needs both `engineer` and `architect` entries with appropriate field sets. Not a simple rename.

---

### B3. Semaphore tier for EXECUTE agents undefined [HIGH]

Current semaphore has two hardcoded tiers:

```python
MUTATE_DEPARTMENTS = {"engineering", "operations"}
READ_DEPARTMENTS = {"protocol", "security", "quality", "personnel"}
```

New design introduces EXECUTE authority (analyst, verifier) with its own concurrency limit (max 3). But semaphore code only knows MUTATE and READ. EXECUTE agents fall through to... unknown behavior.

**Fix**: Semaphore must derive tier from agent's effective authority dynamically, not from hardcoded sets. Three tiers: MUTATE(2), EXECUTE(3), READ(4).

---

### B4. `resolve_tools()` incomplete tool set [MEDIUM]

`CEILING_TOOL_CAPS` lists basic tools but omits `LSP`, `NotebookEdit`, `PowerShell`, and potentially MCP tools. Design acknowledges this (Round 5 P2): "Full tool audit deferred to implementation."

**Risk**: On migration day, any agent needing an unlisted tool will fail. This is not safely deferrable — it must be resolved before implementation begins.

**Fix**: Run a tool audit against current department manifests. Every tool currently in any `allowed_tools` must appear in the new authority mapping.

---

### B5. `department` field in spec dict — field name migration gap [MEDIUM]

Design uses `agent_key` conceptually but never specifies the actual spec dict field name change. Current codebase has `spec["department"]` in dozens of locations across dispatcher, executor, prompt builder, handoff, semaphore, DB queries, etc.

**Fix**: Add an explicit field mapping table to the design doc:
```
spec["department"] → spec["agent"]
task.department → task.agent
TaskIntent.department → TaskIntent.agent
```
And a grep audit: `grep -rn 'spec\["department"\]\|\.department' src/ --include="*.py"` to count all change points.

---

### B6. `intent_rules.py` hardcoded department values [MEDIUM]

Rule-based fast path returns `TaskIntent(department="engineering")`. Post-refactor this must become `TaskIntent(agent="engineer")` (or whatever the field name is — see B5). If the field name changes but rule code doesn't, it's a silent KeyError or wrong-field write.

**Fix**: Include `intent_rules.py` in the "Rewrite" file list (currently missing from the design's File Changes section).

---

## Consumer Experience Issues

### C1. FSM transition execution semantics undefined [HIGH]

`done: @reviewer` means "route to reviewer agent." But WHO executes this transition? Current system uses ReviewManager to create a new task and dispatch it. New design puts the transition in FSM config but doesn't specify:

- Does `@reviewer` create a new task (with task_id, queued status)?
- Or does it inline-execute (like Phase 0.5)?
- Who reads the FSM and acts on transitions — Governor? Executor callback? A new FSM runner?

**Fix**: Define the transition executor. Recommended: FSM transitions always create new tasks via Governor (preserving traceability, semaphore, scrutiny). The FSM is declarative config; Governor is the executor.

---

### C2. spec dict schema change not documented [MEDIUM]

Every consumer of the dispatch pipeline passes and reads spec dicts. The design changes the fundamental entity from "department" to "agent" but never provides a spec dict schema diff. Consumers include:

- `gateway/dispatcher.py` (constructs spec)
- `governance/dispatcher.py` (reads spec)
- `governance/executor.py` (reads spec)
- `governance/executor_prompt.py` (reads spec)
- `governance/task_handoff.py` (filters spec)
- `governance/review.py` (reads spec)
- DB task table (stores spec as JSON)
- Dashboard (displays spec fields)

**Fix**: Add a "Spec Schema Migration" section with before/after field names.

---

### C3. Dashboard observability regression for split tasks [MEDIUM]

Current: fact-expression split creates visible sub-tasks in dashboard. Users can see:
- Fact layer task: status, output, duration
- Expression layer task: status, dependency, output

New: Phase 0.5 inline execution produces no task records. Dashboard shows nothing between dispatch and final result.

**Fix**: If sub-tasks are created per D2 fix, this resolves automatically.

---

### C4. Hot reload atomicity gap [MEDIUM]

Design says "build new dicts then atomic swap." But CAPABILITIES and AGENTS are two separate dicts. Between the two swaps, a consumer could read new CAPABILITIES + old AGENTS (or vice versa), causing KeyError if an agent references a capability that was renamed/added in the new version.

```python
# Dangerous window:
CAPABILITIES.clear(); CAPABILITIES.update(new_caps)  # swap 1
# <-- consumer reads here: new caps, old agents referencing old cap keys
AGENTS.clear(); AGENTS.update(new_agents)             # swap 2
```

**Fix**: Either (a) use a single wrapper object with one atomic reference swap, or (b) build both dicts, then swap in rapid succession with a generation counter that consumers check.

---

## Files Missing from "File Changes" Section

The design's migration File Changes list is missing these consumer files that need updates:

| File | Reason |
|------|--------|
| `src/gateway/intent_rules.py` | Hardcoded department values in rule returns |
| `src/governance/group_orchestration.py` | `_COLLABORATION_PATTERNS` department names |
| `src/governance/task_handoff.py` | `_DEPT_SPECIFIC_FIELDS` keys (not just rename) |
| Dashboard frontend (if exists) | Department labels, task status display |
| `src/governance/governor.py` | `_dispatch_task` reads `spec["department"]` |

---

## Recommended Action

1. **Before implementation**: Resolve D1, D2, C1 (design gaps that affect architecture)
2. **During implementation**: Use B1-B6 as a checklist for migration step 4-5
3. **After implementation**: Run eval baseline comparison per migration step 0
