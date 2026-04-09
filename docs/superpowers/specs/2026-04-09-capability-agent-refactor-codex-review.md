# Codex Adversarial Review — Capability-Agent Refactor Design

**Date**: 2026-04-09
**Target**: working tree diff (10 untracked spec files)
**Verdict**: **needs-attention** (No-ship)
**Reviewer**: Codex (adversarial mode)

---

## Summary

The plan still has rollout-breaking gaps: its rollback path is self-contradictory, its gateway migration assumption is false in the current code, and its schema rewrite leaves budget/accounting consumers on the old department model.

---

## Findings

### [CRITICAL] Rollback plan removes the legacy tree before the proposed fallback can work

**Location**: `2026-04-08-capability-agent-refactor-design.md:947-964`

The design promises side-by-side `v1`/`v2` operation via `ORCHESTRATOR_ARCH` and says `departments/` stays until v2 is proven stable, but the migration sequence later moves `departments/` into `.trash/` before validation is complete.

This is not a documentation nit: current runtime code still probes or calls the legacy tree directly:
- `src/channels/wake.py` — root detection
- `src/jobs/shared_knowledge.py` — writing `departments/shared/`
- `src/jobs/periodic.py` — calling `vet_all_departments("departments")`

**Impact**: A v2 trial would either break those consumers outright or make the advertised rollback path unusable, because the filesystem contract they still depend on has already been removed.

**Recommendation**: Do not move `departments/` until every direct consumer is gated or migrated. Keep the legacy tree live during validation, or add a compatibility shim/symlink and make the cutover/removal a separate post-validation step.

---

### [HIGH] The design's 'intent prompt auto-updates from registry' assumption is false

**Location**: `2026-04-08-capability-agent-refactor-design.md:999-1000`

The plan relies on the note that `intent.py` will "auto-update when AGENTS replaces DEPARTMENTS", but the current gateway is not registry-agnostic:

- `src/gateway/intent.py` hardcodes the JSON output field as `department`
- Validates against `VALID_DEPARTMENTS`
- Defaults invalid outputs to `engineering`
- Emits governor specs with `{"department": ...}`

**Impact**: If this rewrite is missed or under-scoped, the new architecture keeps generating the old schema and silently routes unknown agent outputs back to `engineering`. That is a direct consumer regression at the front door, not an implementation detail.

**Recommendation**: Treat gateway schema migration as explicit required work, not an automatic side effect. Specify the exact field changes (`department` -> `agent`) in prompt text, validation, defaults, and `TaskIntent.to_governor_spec()`, and add an integration test that rejects legacy `department` outputs.

---

### [HIGH] Budget/accounting remains on the old department key — agent traffic bypasses throttling

**Location**: `2026-04-08-capability-agent-refactor-design.md:726-752`

The data migration section adds `agent` columns for `tasks`, `run_logs`, and `learnings`, but the rewrite inventory still omits the budget/accounting path:

- `src/governance/budget/token_budget.py` loads usage with `json_extract(t.spec, '$.department')`
- Stores `UsageRecord.department`
- Enforces daily caps per department

**Impact**: If new tasks write only `agent`, those records fall through as empty/unknown and the downgrade logic stops constraining the new roles. Spend controls fail open and per-role cost history becomes misleading right when the rollout needs trustworthy telemetry.

**Recommendation**: Add explicit budget migration work to the design: schema/query changes for `token_budget.py`, backward-compatible reads during transition, and verification that new `agent` traffic still contributes to per-role daily limits before cutover.

---

## Next Steps

1. Fold these three blockers into the design doc before implementation begins
2. Rerun review against the updated plan and full migration file list
3. Specifically validate: rollback sequence, gateway field migration, budget path coverage
