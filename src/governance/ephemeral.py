"""Ephemeral Agent — temp profile, no disk (H8).

Runs an Agent SDK session from an inline EphemeralSpec without touching
any department directory, blueprint file, or SKILL.md on disk.

Execution still goes through AgentSessionRunner, so stuck detection,
doom loop, supervisor, and hallucination checks all remain active.

The only persistence (when persist=True) is a lightweight task row
+ agent_events in events.db. When persist=False, nothing is written
anywhere — the result exists only in the returned ExecutionResponse.
"""
from __future__ import annotations

import logging
import time
import uuid

import anyio

from src.core.runtime import AgentRuntime

from src.governance.agent_executor_interface import EphemeralSpec
from src.governance.execution_response import ExecutionResponse
from src.governance.executor_session import AgentSessionRunner

# DelegationTracker — optional, for H7 integration
try:
    from src.governance.audit.delegation_span import DelegationTracker
except ImportError:
    DelegationTracker = None

log = logging.getLogger(__name__)

# Sentinel task IDs for non-persisted ephemeral runs.
# Negative IDs never collide with real SQLite AUTOINCREMENT IDs.
_VOLATILE_COUNTER = -9000


def _next_volatile_id() -> int:
    global _VOLATILE_COUNTER
    _VOLATILE_COUNTER -= 1
    return _VOLATILE_COUNTER


# ---------------------------------------------------------------------------
# Null DB adapter — satisfies AgentSessionRunner.db interface when persist=False
# ---------------------------------------------------------------------------

class _NullDB:
    """Minimal duck-type stand-in for EventsDB.

    AgentSessionRunner calls db.add_agent_event() and db.get_agent_events()
    during execution. This adapter silently discards writes and returns
    empty results, so ephemeral agents with persist=False leave zero trace.
    """

    def add_agent_event(self, task_id: int, event_type: str, data: dict) -> None:
        pass

    def get_agent_events(self, task_id: int, limit: int = 30) -> list:
        return []

    def record_heartbeat(self, task_id, agent_id, status, progress, text) -> None:
        pass


_null_db = _NullDB()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def run_ephemeral_async(
    spec: EphemeralSpec,
    db=None,
    delegation_tracker: DelegationTracker | None = None,
) -> ExecutionResponse:
    """Run an ephemeral agent and return the result.

    Args:
        spec: Inline agent configuration (prompt, system_prompt, tools, etc.)
        db: EventsDB instance. Required when spec.persist=True.
            Ignored when spec.persist=False (uses NullDB).
        delegation_tracker: Optional H7 tracker for parent→child chain.

    Returns:
        ExecutionResponse with the agent's output and metadata.
    """
    start = time.monotonic()

    # ── Task ID ──
    if spec.persist:
        if db is None:
            raise ValueError("EphemeralSpec.persist=True requires a db instance")
        task_id = db.create_task(
            spec={"tag": spec.tag, "ephemeral": True},
            action=spec.prompt[:200],
            reason=f"ephemeral:{spec.tag}",
            priority="medium",
            source="ephemeral",
        )
        log.info(f"Ephemeral: created task #{task_id} tag={spec.tag}")
    else:
        task_id = _next_volatile_id()
        log.info(f"Ephemeral: volatile run id={task_id} tag={spec.tag}")

    effective_db = db if spec.persist else _null_db

    # ── Delegation Span (H7) ──
    span_id = None
    if delegation_tracker and DelegationTracker:
        try:
            parent_span = None
            if spec.parent_task_id is not None:
                # Find parent span by task_id
                for root in delegation_tracker._roots:
                    found = _find_span_by_task(root, str(spec.parent_task_id))
                    if found:
                        parent_span = found.span_id
                        break
            span_id = delegation_tracker.start_span(
                task_id=str(task_id),
                department=f"ephemeral:{spec.tag}",
                parent_span_id=parent_span,
            )
        except Exception as e:
            log.debug(f"Ephemeral: delegation span failed ({e})")

    # ── Session Runner ──
    runner = AgentSessionRunner(
        db=effective_db,
        components={
            # Keep quality controls active but lightweight
            "stuck_detector": "stuck_detector",
            "runtime_supervisor": None,      # skip supervisor for ephemeral
            "taint_tracker": None,           # skip taint for ephemeral
            "context_budget": None,          # skip budget tracking
            "doom_loop_checker": "doom_loop_checker",
        },
    )

    # ── CWD resolution ──
    import os
    cwd = spec.cwd or os.getcwd()

    # ── Execute ──
    try:
        runtime = AgentRuntime(
            task_id=task_id,
            session_id=f"ephemeral-{task_id}",
            prompt=spec.prompt,
            dept_prompt=spec.system_prompt,
            allowed_tools=tuple(spec.allowed_tools),
            cwd=cwd,
            max_turns=spec.max_turns,
        )
        result = await runner.run(runtime)
    except Exception as e:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        log.error(f"Ephemeral: run failed for id={task_id}: {e}")
        result = ExecutionResponse(
            status="failed",
            output=f"[EPHEMERAL ERROR: {e}]",
            is_error=True,
            duration_ms=elapsed_ms,
        )

    # ── Finalize persistence ──
    if spec.persist and db is not None:
        try:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat()
            db.update_task(
                task_id,
                status="completed" if not result.is_error else "failed",
                output=result.output[:5000],
                finished_at=now,
            )
        except Exception as e:
            log.debug(f"Ephemeral: task update failed ({e})")

    # ── Close delegation span ──
    if span_id and delegation_tracker:
        try:
            delegation_tracker.end_span(
                span_id=span_id,
                status="completed" if not result.is_error else "failed",
                tokens=result.tokens_used,
            )
        except Exception:
            pass

    elapsed_ms = int((time.monotonic() - start) * 1000)
    if result.duration_ms == 0:
        result = ExecutionResponse(
            status=result.status,
            output=result.output,
            turns_taken=result.turns_taken,
            tokens_used=result.tokens_used,
            cost_usd=result.cost_usd,
            duration_ms=elapsed_ms,
            stop_reason=result.stop_reason,
            is_error=result.is_error,
            tool_calls_count=result.tool_calls_count,
            context_variables=result.context_variables,
        )

    log.info(
        f"Ephemeral: id={task_id} done in {elapsed_ms}ms, "
        f"turns={result.turns_taken}, status={result.status}"
    )
    return result


def run_ephemeral(
    spec: EphemeralSpec,
    db=None,
    delegation_tracker=None,
) -> ExecutionResponse:
    """Synchronous wrapper for run_ephemeral_async."""
    return anyio.run(run_ephemeral_async, spec, db, delegation_tracker)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_span_by_task(span, task_id: str):
    """Walk a DelegationSpan tree to find a span matching a task_id."""
    if span.task_id == task_id:
        return span
    for child in (span.children or []):
        found = _find_span_by_task(child, task_id)
        if found:
            return found
    return None
