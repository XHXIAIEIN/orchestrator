"""Three-Phase Transaction — concurrent-safe write pattern.

Source: R64 Hindsight (hindsight_api/engine/retain/orchestrator.py)

Problem: Doing expensive reads AND atomic writes inside one long transaction
causes deadlocks and poor concurrency.

Solution: Split into three phases:
  Phase 1 (lock-free): Expensive reads on an independent connection
    - Entity resolution, ANN similarity search, etc.
    - Uses placeholder IDs (real IDs don't exist yet)
  Phase 2 (atomic): Short transaction window for all writes
    - Insert facts, remap placeholder→real IDs, create links
    - Lock duration minimized
  Phase 3 (best-effort): Post-transaction supplementary writes
    - UI graph visualization, index updates
    - Failure acceptable, won't corrupt data

Worker stage tracking for diagnostics (set_stage("retain.phase1.resolve")).
"""

import contextvars
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)

# ── Stage tracking: contextvars so concurrent tasks don't stomp each other ──
_current_stage: contextvars.ContextVar[str] = contextvars.ContextVar(
    "_current_stage", default=""
)


def set_stage(label: str) -> None:
    """Set the current diagnostic stage label for this context."""
    _current_stage.set(label)


def get_stage() -> str:
    """Get the current diagnostic stage label for this context."""
    return _current_stage.get()


# ── Phase enum ──

class Phase(Enum):
    PREPARE = "prepare"       # Phase 1: lock-free expensive reads
    COMMIT = "commit"         # Phase 2: atomic short-window writes
    SUPPLEMENT = "supplement" # Phase 3: best-effort post-transaction


# ── Data types ──

@dataclass
class PhaseResult:
    """Result of a single phase execution."""
    phase: Phase
    success: bool
    data: dict
    duration_ms: float
    error: Optional[str] = None


@dataclass
class PhaseSpec:
    """Specification for a single phase: what to run and how to undo it."""
    phase: Phase
    callable: Callable
    rollback: Optional[Callable] = None
    description: str = ""


@dataclass
class TransactionPlan:
    """A complete three-phase plan ready for execution."""
    plan_id: str
    phases: list[PhaseSpec]
    created_at: float = field(default_factory=time.time)


# ── Executor ──

class ThreePhaseExecutor:
    """Executes a TransactionPlan through three isolated phases.

    Phase 1 (PREPARE): lock-free, reads only. Result fed into Phase 2.
    Phase 2 (COMMIT):  atomic writes. Receives Phase 1 data. Rollback
                       invoked on failure if a rollback callable is provided.
    Phase 3 (SUPPLEMENT): best-effort. Receives Phase 1 + 2 data.
                           Errors are logged but never propagated.
    """

    def __init__(self, plan: TransactionPlan) -> None:
        self._plan = plan

    async def execute(self, context: dict) -> list[PhaseResult]:
        """Run all three phases in order.

        Args:
            context: Arbitrary caller-supplied data passed as the first
                     positional argument to each phase callable.

        Returns:
            List of PhaseResult, one per phase that was executed.
        """
        results: list[PhaseResult] = []
        accumulated: dict[str, Any] = {}

        # Index phases by type for easy lookup
        specs: dict[Phase, PhaseSpec] = {s.phase: s for s in self._plan.phases}

        # ── Phase 1: PREPARE (lock-free reads) ──
        prepare_spec = specs.get(Phase.PREPARE)
        if prepare_spec:
            set_stage(f"transaction.{self._plan.plan_id}.phase1.prepare")
            result = await self._run_phase(prepare_spec, context, accumulated)
            results.append(result)
            if result.success:
                accumulated.update(result.data)
            else:
                # Prepare failed — abort the whole plan
                log.warning(
                    "three_phase: plan=%s PREPARE failed (%s), aborting",
                    self._plan.plan_id, result.error,
                )
                return results

        # ── Phase 2: COMMIT (atomic writes) ──
        commit_spec = specs.get(Phase.COMMIT)
        if commit_spec:
            set_stage(f"transaction.{self._plan.plan_id}.phase2.commit")
            result = await self._run_phase(commit_spec, context, accumulated)
            results.append(result)
            if result.success:
                accumulated.update(result.data)
            else:
                log.warning(
                    "three_phase: plan=%s COMMIT failed (%s), attempting rollback",
                    self._plan.plan_id, result.error,
                )
                if commit_spec.rollback is not None:
                    await self._run_rollback(commit_spec, context, accumulated)
                return results

        # ── Phase 3: SUPPLEMENT (best-effort, failures tolerated) ──
        supplement_spec = specs.get(Phase.SUPPLEMENT)
        if supplement_spec:
            set_stage(f"transaction.{self._plan.plan_id}.phase3.supplement")
            result = await self._run_phase(
                supplement_spec, context, accumulated, best_effort=True
            )
            results.append(result)

        set_stage("")
        return results

    # ── Internals ──

    async def _run_phase(
        self,
        spec: PhaseSpec,
        context: dict,
        accumulated: dict,
        best_effort: bool = False,
    ) -> PhaseResult:
        t0 = time.monotonic()
        try:
            data = await spec.callable(context, accumulated)
            duration_ms = (time.monotonic() - t0) * 1000
            if not isinstance(data, dict):
                data = {"result": data}
            log.debug(
                "three_phase: phase=%s desc=%r ok (%.1fms)",
                spec.phase.value, spec.description, duration_ms,
            )
            return PhaseResult(
                phase=spec.phase,
                success=True,
                data=data,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = (time.monotonic() - t0) * 1000
            if best_effort:
                log.warning(
                    "three_phase: phase=%s (best-effort) raised %s — ignoring",
                    spec.phase.value, exc,
                )
            else:
                log.error(
                    "three_phase: phase=%s raised %s",
                    spec.phase.value, exc,
                )
            return PhaseResult(
                phase=spec.phase,
                success=False,
                data={},
                duration_ms=duration_ms,
                error=str(exc),
            )

    async def _run_rollback(self, spec: PhaseSpec, context: dict, accumulated: dict) -> None:
        try:
            await spec.rollback(context, accumulated)
            log.info("three_phase: plan=%s rollback succeeded", self._plan.plan_id)
        except Exception as exc:
            log.error(
                "three_phase: plan=%s rollback FAILED: %s", self._plan.plan_id, exc
            )


# ── Convenience wrapper ──

async def three_phase_write(
    prepare_fn: Callable,
    commit_fn: Callable,
    supplement_fn: Optional[Callable] = None,
    context: Optional[dict] = None,
) -> list[PhaseResult]:
    """Build a TransactionPlan from callables and execute it immediately.

    Args:
        prepare_fn:    async (context, accumulated) -> dict — lock-free reads
        commit_fn:     async (context, accumulated) -> dict — atomic writes
        supplement_fn: async (context, accumulated) -> dict — best-effort extras
        context:       Caller data forwarded to every phase callable

    Returns:
        List of PhaseResult for each executed phase.
    """
    phases = [
        PhaseSpec(phase=Phase.PREPARE, callable=prepare_fn, description="prepare"),
        PhaseSpec(phase=Phase.COMMIT,  callable=commit_fn,  description="commit"),
    ]
    if supplement_fn is not None:
        phases.append(
            PhaseSpec(
                phase=Phase.SUPPLEMENT,
                callable=supplement_fn,
                description="supplement",
            )
        )

    plan = TransactionPlan(
        plan_id=str(uuid.uuid4()),
        phases=phases,
    )
    return await ThreePhaseExecutor(plan).execute(context or {})
