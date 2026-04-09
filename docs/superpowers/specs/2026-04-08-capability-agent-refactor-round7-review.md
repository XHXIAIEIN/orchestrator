# Round 7 Review: End-to-End Consistency Audit + Consumer Experience

**Date**: 2026-04-09
**Reviewer**: Orchestrator (Opus 4.6, independent third-party perspective)
**Input**: design.md (post Round 1-6) + current codebase cross-reference
**Method**: Not incremental review — full end-to-end consistency check across all 6 rounds of accumulated patches, plus consumer-side experience walkthrough

## Summary

| Category | Count | Severity |
|----------|-------|----------|
| Structural design issues | 4 | 2 P1 / 2 P2 |
| Bugs | 4 | 1 P1 / 2 P2 / 1 P3 |
| Consumer experience | 3 | 2 P2 / 1 P3 |
| Meta-process issues | 2 | 2 P1 |

**Key observation**: 6 rounds of self-review created a "patch-on-patch" effect — each round fixed the previous round's issues but never re-validated the full design end-to-end. The accumulated patches themselves introduce new contradictions.

---

## I. Structural Design Issues

### 1. Phase 0.5 is Dispatcher Overreach — Should Be Governor's Job [P2]

Phase 0.5 (Fact-Expression Split in dispatcher) was born in Round 4 because `executor.resume()` doesn't exist. The fix moved multi-step orchestration into the dispatcher.

But Round 6 established: "FSM is declarative data. Governor is the executor." Phase 0.5 directly acquires semaphores, runs scrutiny, and executes tasks — that's Governor's charter, not dispatcher's.

**Consequence**: If future scenarios need multi-step orchestration (e.g., "audit then fix"), do we add Phase 0.6 in dispatcher? Or route through Governor? No unified pattern exists.

**Recommendation**: Tag Phase 0.5 as tech debt. During implementation, extract a `Governor.run_sub_chain()` method that both Phase 0.5 and FSM transitions use.

---

### 2. `active_capabilities` is a Hidden Agent Factory [P1]

Round 5 upgraded `active_capabilities` from "prompt filter" to "full compose chain filter (model, tools, authority, rubric)." Round 6 added warning log.

But this means **intent authors are implicitly defining entirely new agents**:

```yaml
# These two intents produce specs with almost nothing in common
engineer/code_fix:    active=[develop, test], authority=MUTATE, model=sonnet
engineer/quick_lint:  active=[inspect],       authority=READ,   model=haiku
```

The second is not an engineer — it's an inspector wearing engineer's identity. This breaks the core assumption that "agent = stable execution role."

**Impact**: Agent-level monitoring, dashboards, and cost tracking become meaningless when the same agent key produces wildly different runtime specs.

**Recommendation**: Limit `active_capabilities` to filtering prompts and rubric only. Model and authority should be explicitly declared per-intent, not derived by filtering capabilities. If an intent needs a fundamentally different spec, it belongs on a different agent.

---

### 3. Override Stack Has No Complete Conflict Resolution Table [P1]

The design defines L0-L3 override layers but scatters resolution semantics across code snippets in different rounds:

```
L0: Capability merge
L1: Agent overrides
L2: Blueprint overrides
L3: Intent profile + authority_cap
```

Missing a formal dimension × layer resolution table:

| Dimension | L0 (capability merge) | L1 (agent) | L2 (blueprint) | L3 (intent) | Resolution Rule |
|-----------|----------------------|------------|-----------------|-------------|-----------------|
| model | max(caps) | override | override | ceiling (profile) | `max(floor, min(L1 or L0, L3))` |
| max_turns | max(caps)? | override | override? | ceiling? | **Undefined** |
| timeout_s | max(caps)? | override | override? | ceiling? | **Undefined** |
| authority | max(caps) | — | — | cap (min) | Defined |
| tools | union(caps) | — | — | — | Defined |
| rubric | weighted merge | — | — | rubric_override (transition) | Partially defined |

Questions without answers:
- L2 (blueprint) override: is it a ceiling (like L3) or a hard override (like L1)?
- max_turns: does profile LOW_LATENCY cap it at 10? Can L1 or L2 override that cap?
- What happens when L1 says `max_turns: 25` and L3 says `max_turns: 10`?

**Recommendation**: Write a complete Dimension Resolution Table as a formal section in the design doc. Each cell = explicit merge semantic.

---

### 4. Specialization Routing is Static, Unlike Current Division Routing [P2]

Current system: intent → department → division (division selected dynamically by routing weights).
New system: intent → agent → intent.specialization (hardcoded in intent declaration).

```yaml
intents:
  code_fix:
    specialization: implement    # always implement, regardless of bug nature
```

Current system can dynamically route "fix a build system bug" to `engineering/integrate` vs "fix a logic bug" to `engineering/implement`. New system sends both to `develop/implement`.

This is an intentional granularity reduction, not a lossless migration. The design should acknowledge this trade-off explicitly.

---

## II. Bugs

### Bug 1: Qdrant Migration `IsNullCondition` Doesn't Match Missing Fields [P1]

```python
filter=models.Filter(must=[
    models.IsNullCondition(is_null=models.PayloadField(key="agent"))
])
```

Initial state: all records have `department` field but **no `agent` field** (field doesn't exist ≠ field is null). Qdrant's `IsNullCondition` behavior on missing fields is version-dependent:
- Some versions: missing field = null → matches ✓
- Some versions: missing field ≠ null → no match ✗

If `IsNullCondition` only matches explicit null (not field absence), the filter matches **zero records**, migration silently skips everything, and all vectors remain untagged.

**Fix**: Use `models.Filter(must_not=[models.FieldCondition(key="agent", match=models.MatchValue(value=""))])` with a sentinel, or simply scroll all records and check `"agent" not in point.payload` in Python.

**Must-do**: Test against actual Qdrant instance before implementation.

---

### Bug 2: `model_floor` Can Completely Override LOW_LATENCY Profile [P2]

```python
floor = max(c.model_floor for c in active_caps)
ceiling = profile.model if profile else "opus"
composed.model = max(floor, min(compose_model, ceiling))
```

If a capability author sets `model_floor: sonnet` on `collect`, and an intent uses `profile: LOW_LATENCY` (ceiling=haiku):

```
floor=sonnet, ceiling=haiku → max(sonnet, min(haiku, haiku)) = sonnet
```

Floor unconditionally wins. **A capability author (bottom layer) can override intent strategy (top layer).**

This is a power inversion. The intent author chose LOW_LATENCY for cost reasons; a capability floor silently overrides that decision.

**Fix**: Either (a) floor cannot exceed L3 ceiling (defeats purpose of floor), or (b) emit a WARN-level log and require explicit `model_floor_override: true` in the intent to allow floor > ceiling.

---

### Bug 3: Cancel Storm in Pipeline — Passive vs Active Failure Indistinguishable [P2]

```python
for gate in ['clarify', 'synthesis']:
    workers[gate].add_done_callback(
        lambda t, all_tasks=workers: cancel_all_if_failed(t, all_tasks)
    )
```

When `clarify` fails and callback fires, `cancel_all_if_failed` cancels all other tasks including `scout`. Scout is awaiting `cog_mode` which is also being cancelled. Multiple CancelledErrors propagate simultaneously.

`gather(return_exceptions=True)` collects all exceptions, but `results` dict has multiple `CancelledError` entries. The subsequent `failed()` check needs to distinguish:
- **Active failure** (clarify/synthesis returned an error) → REJECTED
- **Passive cancellation** (scout/qdrant/etc cancelled because gate failed) → expected, ignore

Current code: `if isinstance(v, BaseException): if k in ('clarify', 'synthesis'): return REJECTED`. This works IF gate tasks fail before being cancelled. But if a gate task is BOTH failing AND being cancelled (by the other gate's callback), the exception type is ambiguous.

**Fix**: Use `task.cancelled()` method to distinguish cancellation from failure, rather than relying on exception type.

---

### Bug 4: YAML `None` vs `""` in Terminal Values [P3]

```yaml
# Explicit empty string — parsed as "" ✓
escalation: ""

# Missing value — parsed as None ✗
escalation:
```

`None` is not in `KNOWN_TERMINALS`, not `@`-prefixed, not `__self__` → triggers validation error. This is correct behavior (fail loudly), but the error message will be `AttributeError: 'NoneType' has no attribute 'startswith'` instead of a friendly schema validation error.

**Fix**: Schema validation should check for None before string operations and emit: `"Invalid transition value for 'escalation': got null, expected string. Use '' for terminal."`

---

## III. Consumer Experience Walkthrough

### Scenario A: "修 auth.py 的 bug" — Prompt Concatenation Degradation [P2]

| Step | Current | New | Risk |
|------|---------|-----|------|
| Prompt | Single coherent SKILL.md (tuned over 45 rounds) | develop.prompt + develop/implement/prompt.md + test.prompt concatenation | **Implicit degradation** |
| Post-review | quality department (full SKILL.md) | reviewer (review 70% + discipline 30%) | Weight may be insufficient |

The core risk: current SKILL.md is a **single coherent instruction set** with internal cross-references and carefully ordered sections. Splitting into capability prompt fragments and re-concatenating produces the same content but **different structure**. LLM attention distribution changes, section cross-references break, and the overall coherence drops.

The `## [Capability: X]` section headers (Round 5) help but don't fully compensate — they're delimiters, not coherence mechanisms.

**User perception**: "Before it could fix this in one round, now it takes two." This kind of regression is the hardest to diagnose because there's no error — just lower quality.

### Scenario B: "帮我做个重构计划" — Knowledge Filtered Out [P2]

```
architect/design_plan → active_capabilities: [plan] → only plan.prompt loaded
```

Round 5's active_capabilities filtering solved the "refactor.prompt injected into READ context" problem. But it over-corrected: **refactor.prompt contains domain knowledge about refactoring patterns and code structure analysis** that's valuable even in a planning context.

User perception: architect's refactoring plans are generic — missing the code-level refactoring details that refactor.prompt would have provided.

**Fix**: For design_plan intent, set `active_capabilities: [plan, refactor]` with `authority_cap: READ`. This injects refactor knowledge while the authority context line prevents actual writes. Current design's Round 5 fix threw out the baby with the bathwater.

### Scenario C: Ad-hoc "审查代码并修掉问题" — Context Handoff Gap [P2]

Ad-hoc serial chain: reviewer → engineer.

The chain is dynamically generated, not a pre-defined FSM transition. But `_AGENT_SPECIFIC_FIELDS` (handoff context filtering) is defined per-agent for known transitions. **Dynamic ad-hoc chains have no handoff context rules.**

reviewer outputs a list of issues → handoff filter doesn't know what fields to preserve for engineer → reviewer's output may be filtered out → engineer sees empty context → re-reviews from scratch → wasted tokens.

**Fix**: Ad-hoc chains should use a permissive handoff policy (pass all fields) or define a generic "sequential chain" handoff template.

---

## IV. Meta-Process Issues

### Meta 1: Big Bang Migration with No Rollback Path [P1]

> "No gradual migration. Current system stopped. Clean cut."

30+ files rewritten + 15 new directories + 8 YAML + DB migration + Qdrant migration. All at once.

Rollback analysis:
- DB: `department` column preserved → reversible ✓
- Qdrant: dual-query during transition → reversible ✓
- Code: all files rewritten → **only reversible via git revert of entire PR** ✗

A 30+ file revert PR is itself a high-risk operation. If post-migration eval shows >10% P50 drop and prompt tuning can't recover, the only option is reverting the entire thing.

**Recommendation**: Add a `ARCHITECTURE_VERSION=v1/v2` feature flag at the registry level. V1 loads `departments/`, V2 loads `capabilities/` + `agents/`. Both paths coexist during validation. Remove V1 path only after V2 is confirmed stable.

### Meta 2: No Isolated Prompt-Split Validation [P1]

The design's Step 0 (eval baseline) runs against current SKILL.md, then compares against post-migration concatenated prompts. **Two variables change simultaneously**: architecture + prompt format.

If P50 drops, is it because:
- (a) The compose/merge logic has bugs? → Architecture problem
- (b) Concatenated prompts are worse than monolithic SKILL.md? → Prompt format problem

Can't tell without isolation.

**Recommendation**: Before touching architecture, split current SKILL.md into capability prompt fragments and **run eval on the OLD architecture with concatenated prompts**. If scores drop, the problem is prompt splitting (fix before migration). If scores hold, any post-migration drop is in the compose logic.

This isolates variables and cuts debugging time in half.

---

## V. Severity Summary (Issues Not Covered by Rounds 1-6)

| # | Issue | Severity | Type |
|---|-------|----------|------|
| 1 | `active_capabilities` is hidden agent factory, breaks agent identity stability | **P1** | Design |
| 2 | Override Stack missing complete conflict resolution table | **P1** | Design gap |
| 3 | Qdrant migration `IsNullCondition` may not match missing fields | **P1** | Bug |
| 4 | Big Bang migration with no rollback path | **P1** | Process |
| 5 | No isolated prompt-split validation (two variables changed simultaneously) | **P1** | Process |
| 6 | Phase 0.5 dispatcher overreach (should be Governor) | P2 | Architecture smell |
| 7 | `model_floor` can override LOW_LATENCY profile (power inversion) | P2 | Design conflict |
| 8 | Cancel storm: passive vs active failure indistinguishable | P2 | Bug |
| 9 | Specialization routing is static (granularity reduction vs current) | P2 | Acknowledged trade-off |
| 10 | architect/design_plan filters out refactor domain knowledge | P2 | Experience |
| 11 | Ad-hoc chain context handoff undefined | P2 | Experience |
| 12 | Clawvard dimensions semantic drift (engineer ≠ engineering) | P2 | Regression |
| 13 | YAML None vs "" terminal value parsing | P3 | Bug |
| 14 | `build_semaphore_tiers` possibly dead code | P3 | Code |

---

## VI. Recommendations

### Must-fix before Implementation Plan

1. **Override Stack Dimension Resolution Table** — every dimension × every layer, explicit merge semantic, no scattered code snippets
2. **Prompt-split isolation test** — run concatenated prompts on OLD architecture first, isolate variables
3. **Rollback path** — `ARCHITECTURE_VERSION` feature flag at registry level, or at minimum a tested revert procedure
4. **Qdrant migration filter validation** — test `IsNullCondition` on actual Qdrant instance with missing-field records
5. **Limit `active_capabilities` scope** — filter prompts and rubric only; model and authority must be intent-explicit

### Iterate during implementation

6. Phase 0.5 → Governor unified orchestration (tech debt tag)
7. Ad-hoc chain handoff context rules (permissive default)
8. `model_floor` vs profile ceiling conflict logging
9. Semaphore queue visibility in dashboard
10. YAML schema validation with friendly None handling
11. architect/design_plan: `active_capabilities: [plan, refactor]` with authority_cap=READ
