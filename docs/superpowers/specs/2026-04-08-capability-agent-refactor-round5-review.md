# Capability + Agent Refactor — Round 5 Deep Review

**Date**: 2026-04-08
**Reviewer**: Orchestrator (Claude Opus 4.6)
**Input**: `2026-04-08-capability-agent-refactor-design.md` (post Round 1-4)
**Method**: Design doc analysis + current codebase cross-reference

---

## Summary

| Category | Count | Severity |
|----------|-------|----------|
| Architectural contradictions | 4 | P1-P2 |
| Confirmed bugs | 4 | P0-P2 |
| Consumer experience issues | 4 | P1-P2 |
| Missing items | 4 | P2 |

**Top 2 critical issues:**
1. Phase 0.5 Fact-Expression Split bypasses Semaphore + Scrutiny (security gap)
2. `active_capabilities` filters prompts but not model/tools/authority in compose() (design intent incomplete)

---

## I. Architectural Design Issues (Regression Risk)

### A1. `express` capability authority=READ vs actual needs (P2)

`express` is defined as READ authority, but its job is "expression layer rewriting, tone adjustment" — producing new output text. While READ is sufficient if `express` output is only returned as a value (not written to files), this breaks if `inspector` ever needs to write results to `.md` files or update DB records.

**Current system**: protocol department's authority should be checked — if it was MUTATE or PROPOSE, downgrading to READ is a regression.

**Recommendation**: Verify protocol department's current authority level. If it writes files, `express` needs at least EXECUTE or MUTATE.

---

### A2. Phase 0.5 Fact-Expression Split bypasses Semaphore + Scrutiny (P0)

In the dispatcher pipeline pseudocode:

```python
if needs_fact_expression_split(spec.intent):
    # Executes reviewer + inspector directly, then returns
    return merge(fact_output, expr_output)

# Phase 1: Semaphore acquire  ← only non-split tasks reach here
# Phase 2: Scrutiny            ← only non-split tasks reach here
```

**Bug**: The two sub-executions (reviewer + inspector) in Phase 0.5:
- **No semaphore acquisition** → could exceed `read_max` concurrency limits
- **No scrutiny check** → bypasses the safety audit layer entirely

**Fix**: Phase 0.5 sub-executions must individually acquire semaphore slots and pass through scrutiny before execution.

---

### A3. Ad-hoc mode vs scenarios.yaml — unclear relationship (P2)

Round 4 simplified ad-hoc multi-agent to "always serialize." But scenarios.yaml supports parallel execution with reducers (merge/append). The two paths:

- `dispatch(capabilities=["audit", "review"])` → ad-hoc → **always serial**
- `dispatch(scenario="full_audit")` → scenario → **parallel + reducer**

Consumer confusion: these achieve similar goals via different mechanisms, with different performance characteristics and no guidance on when to use which. The design should clarify the decision tree or unify the paths.

---

### A4. `rubric_override` status after Round 4 simplification (P1)

Round 4 declared FSM transition values as "pure strings only" (three kinds: `@agent`, `__self__`, terminal). But the Round 3 `rubric_override` feature uses structured values:

```yaml
transitions:
  fact_layer: __self__
    rubric_override:
      discipline: 0.6
```

Round 4 also removed `fact_layer` from FSM (moved to dispatcher). **The design doc is self-contradictory**: the rubric_override section (from Round 3) was never explicitly resolved in Round 4. Either:
- Remove rubric_override entirely (simplest, consistent with "pure strings")
- Move rubric_override to dispatcher's Phase 0.5 config (if still needed)

---

## II. Confirmed Bugs

### B1. Profile ceiling can force-downgrade critical capabilities (P1)

> Profile acts as a **ceiling** — it can lower model/turns/timeout from compose defaults but never raise them

If architect (compose→opus) receives a `LOW_LATENCY` profile, ceiling forces model to haiku. **An opus-level refactoring task running on haiku** is catastrophic.

The design doesn't distinguish between:
- **Capability-required model floor** (opus for plan/refactor — non-negotiable)
- **Performance preference ceiling** (profile suggests haiku for speed)

**Fix**: Add `model_floor` to capability manifest. Profile ceiling = `max(capability_model_floor, min(compose_model, profile_model))`.

---

### B2. Qdrant migration filter uses invalid syntax (P1)

```python
filter={"must_not": [{"key": "agent", "match": {"any": True}}]}
```

`{"any": True}` is not valid Qdrant filter syntax. Standard approach:
- Use `IsNull` condition: `{"must": [{"is_null": {"key": "agent"}}]}`
- Or use `has_id` / payload existence check

This code will throw a Qdrant API error at runtime.

---

### B3. DB migration doesn't handle NULL department values (P2)

```sql
UPDATE tasks SET agent = CASE department
    WHEN 'engineering' THEN 'engineer'
    ...
    ELSE department
END;
```

If `department` is NULL, no `WHEN` matches, `ELSE department` returns NULL for `agent`. Should add explicit handling:

```sql
WHEN department IS NULL THEN NULL
```

Or decide on a default agent for orphaned records.

---

### B4. `resolve_tools()` missing LSP and other tools (P2)

CEILING_TOOL_CAPS covers Read/Glob/Grep/Bash/Write/Edit. ALWAYS_AVAILABLE adds Task tools. But:
- `LSP` tool (code intelligence, diagnostics) — used by develop/refactor capabilities
- `NotebookEdit` — if any capability works with notebooks
- `EnterPlanMode`/`ExitPlanMode` — if plan capability needs these

The tool mapping is incomplete. Should be audited against the full tool inventory.

---

## III. Consumer Experience Issues

### C1. Prompt concat "middle child" problem (P2)

Weight-descending concat puts highest-weight capability prompt last (recency bias). For 2-capability agents, this works. But for 3+ capabilities:

```
operator: compress(0.2) → collect(0.3) → operate(0.5)
                              ↑
                    "middle child" — neither primacy nor recency effect
```

The middle capability's prompt gets minimal LLM attention. For operator, `collect` instructions could be systematically ignored during operate+collect+compress tasks.

**Mitigation**: Consider a delimiter/section header strategy instead of relying purely on position-based attention.

---

### C2. Agent identity conflicts with authority_cap in read-only intents (P1)

architect's identity: "You design and refactor." But with `intent=design_plan` (authority_cap=READ), tools are read-only. The LLM sees "I can refactor" in its identity but has no write tools — creating cognitive dissonance.

**Fix**: Inject an authority context line into the prompt:
```
[Authority: READ — this task is observation-only. You may analyze and recommend but not modify files.]
```

Or dynamically trim identity prompt based on active_capabilities.

---

### C3. active_capabilities doesn't filter model/tools/authority compose (P0)

This is the most impactful design gap. Intent-level `active_capabilities` filters which prompts are injected, but the compose engine still merges **all** capabilities for model/tools/authority:

```python
# operator with intent=data_collect, active_capabilities=[collect]
compose model = max(operate.sonnet, collect.haiku, compress.haiku) = sonnet
# But profile LOW_LATENCY ceiling → haiku
# Net result: haiku (correct by accident, not by design)
```

If active_capabilities properly filtered the compose inputs:
```python
compose model = max(collect.haiku) = haiku  # correct by design
```

The difference matters when:
- No profile is set (default BALANCED) → model stays sonnet for a haiku-level task
- Tools include MUTATE tools from inactive capabilities when authority_cap isn't set
- Authority is inflated by inactive capabilities

**Fix**: `resolve_active_capabilities()` should be called BEFORE compose merges model/tools/authority, not just for prompt injection.

---

### C4. Subtask capability→agent matching algorithm undefined (P2)

Architect outputs subtasks with capability declarations:
```yaml
- action: "Do X"
  capabilities: [develop, audit]  # crosses engineer + sentinel
```

Design says "multi-agent → sequential/parallel plan" but doesn't define:
- Matching algorithm (greedy? exact? weighted?)
- Tie-breaking (if two agents both partially cover)
- Failure mode (no single agent covers all capabilities)
- Whether partial coverage is acceptable

This is critical for Governor's subtask dispatch logic.

---

## IV. Missing Items

### M1. Clawvard `dimensions` migration details (P2)

`primary/secondary/boost` dimensions move from department manifest to `agents/{key}.yaml`. But `prompt_eval.py`'s loading logic needs the new path. The File Changes section lists the file but not the specific code changes needed. Risk of exam routing breaking silently.

---

### M2. `denials.jsonl` split across capabilities complicates queries (P2)

Current: one `policy-denials.jsonl` per department → easy to query "what was rejected for engineering."

New: `denials.jsonl` per capability → querying "what was rejected for engineer agent" requires scanning `develop/denials.jsonl` + `test/denials.jsonl` + merging. No aggregation strategy defined.

**Recommendation**: Keep a denials index at agent level, or add a query helper that aggregates across an agent's capabilities.

---

### M3. Hot reload atomicity (P2)

`reload()` mutates singletons in-place. If capabilities reload before agents, there's a window where agents reference stale capability data. In a concurrent system, a dispatch during reload could get inconsistent state.

**Fix**: Build new registries in a temporary dict, then swap atomically:
```python
new_caps = _discover_capabilities()
new_agents = _discover_agents(new_caps)
# Atomic swap
CAPABILITIES.clear(); CAPABILITIES.update(new_caps)
AGENTS.clear(); AGENTS.update(new_agents)
```

---

### M4. No default/fallback agent defined (P2)

Current system falls back to `engineering` department (executor.py line 490-491). New system has no defined fallback agent. If IntentGateway returns an unknown agent key, or if ad-hoc capability resolution finds no match, what happens?

**Recommendation**: Define `engineer` as the default fallback agent, matching current behavior. Add explicit error handling for unresolvable capability sets.

---

## Recommended Resolution Priority

1. **P0**: Fix Phase 0.5 semaphore/scrutiny bypass (A2)
2. **P0**: Fix active_capabilities compose filtering (C3)
3. **P1**: Resolve rubric_override status post-Round 4 (A4)
4. **P1**: Add model_floor to prevent profile over-downgrade (B1)
5. **P1**: Fix agent identity vs authority_cap conflict (C2)
6. **P1**: Fix Qdrant migration filter syntax (B2)
7. **P2**: All remaining items (can be resolved during implementation)
