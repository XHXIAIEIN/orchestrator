"""GroupOrchestrationSupervisor — multi-round multi-department orchestration layer.

Stolen from: LobeHub Supervisor-Executor architecture (Round 16).
LobeHub's ChatGroup uses a supervisorId pointing to a GroupOrchestrationSupervisor
that runs a state-machine loop: evaluate → dispatch → aggregate → repeat.

This module sits ABOVE the existing Governor single-dispatch model.
Simple tasks still go through Governor directly; complex multi-department
tasks get routed here for iterative coordination.

Integration point: Governor can call GroupOrchestrationSupervisor.run() when
it detects a task requires cross-department collaboration.
"""
import json
import logging
import operator
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from src.governance.channel_reducer import (
    AppendChannel,
    LastValueChannel,
    MergeChannel,
    ReducerChannel,
)

# ── FutureGate (stolen from ChatDev 2.0, Round 13) ──
# Coordination primitive for multi-department batch dispatches.
# Each department gets a gate; the orchestrator waits for all gates
# to be provided (or time out) before proceeding to evaluation.
try:
    from src.core.future_gate import FutureGate, GateTimeout, GateCancelled
except ImportError:
    FutureGate = None
    GateTimeout = None
    GateCancelled = None

log = logging.getLogger(__name__)


# ── Dispatch Modes ──────────────────────────────────────────────

class DispatchMode(str, Enum):
    """How the supervisor dispatches work in a given round."""
    SINGLE = "single"        # Route to one specific department
    BROADCAST = "broadcast"  # All relevant departments execute the same task simultaneously
    BATCH = "batch"          # Multiple departments execute in parallel, wait for all
    DELEGATE = "delegate"    # Hand off to another supervisor (future extensibility)


# ── Data Structures ─────────────────────────────────────────────

@dataclass
class SupervisorDecision:
    """What the supervisor decides after evaluating a round's results."""
    mode: DispatchMode
    targets: list[str]           # Department keys to dispatch to
    instruction: str = ""        # Additional instruction for the next round
    skip_supervisor: bool = False  # True = early termination, no more rounds

    def to_dict(self) -> dict:
        return {
            "mode": self.mode.value,
            "targets": self.targets,
            "instruction": self.instruction,
            "skip_supervisor": self.skip_supervisor,
        }


@dataclass
class RoundResult:
    """Captures the output of one orchestration round."""
    round_num: int
    department_results: dict[str, dict] = field(default_factory=dict)
    # Each value: {"status": "success"|"failed"|"skipped", "output": str, "task_id": int|None}
    aggregated_output: str = ""
    superstep_count: int = 0  # R43: BSP superstep tracking

    def all_succeeded(self) -> bool:
        return all(
            r.get("status") == "success"
            for r in self.department_results.values()
        )

    def any_failed(self) -> bool:
        return any(
            r.get("status") == "failed"
            for r in self.department_results.values()
        )

    def failed_departments(self) -> list[str]:
        return [
            dept for dept, r in self.department_results.items()
            if r.get("status") == "failed"
        ]

    def to_dict(self) -> dict:
        return {
            "round_num": self.round_num,
            "department_results": self.department_results,
            "aggregated_output": self.aggregated_output[:500],
        }


# ── Collaboration Detection ─────────────────────────────────────

# Patterns that indicate a department's output needs another department's help.
# Maps regex pattern → target department key.
_COLLABORATION_PATTERNS: dict[str, str] = {
    r"需要工程部|需要engineering|工程部配合": "engineering",
    r"需要运维|需要operations|运维配合": "operations",
    r"需要安全|需要security|安全审查": "security",
    r"需要质量|需要quality|质量审查": "quality",
    r"需要礼部|需要protocol|协议配合": "protocol",
    r"需要吏部|需要personnel|人事配合": "personnel",
}

# Patterns that indicate failure / need for retry.
_FAILURE_PATTERNS: list[str] = [
    r"执行失败",
    r"错误[:：]",
    r"error[:：]",
    r"failed to",
    r"无法完成",
    r"超时",
    r"timeout",
]


def _detect_collaboration_needs(output: str) -> list[str]:
    """Scan output text for signals that another department is needed."""
    needed = []
    for pattern, dept in _COLLABORATION_PATTERNS.items():
        if re.search(pattern, output, re.IGNORECASE):
            needed.append(dept)
    return needed


def _detect_failure(output: str) -> bool:
    """Scan output text for failure signals."""
    for pattern in _FAILURE_PATTERNS:
        if re.search(pattern, output, re.IGNORECASE):
            return True
    return False


# ── GroupOrchestrationSupervisor ────────────────────────────────

class GroupOrchestrationSupervisor:
    """Multi-round multi-department orchestration supervisor.

    Sits above Governor's single-dispatch model. Runs a state-machine loop:
      1. Execute initial dispatch (from Governor's task decomposition)
      2. Evaluate results — rule-driven, no LLM calls
      3. Decide next action (SINGLE/BROADCAST/BATCH/DELEGATE or terminate)
      4. Repeat until done or max_rounds reached

    Safety: max_rounds prevents infinite loops. skip_supervisor allows
    any round's evaluation to force early termination.
    """

    def __init__(
        self,
        max_rounds: int = 5,
        departments: Optional[list[str]] = None,
        signal_bus=None,
        gate_timeout: float = 300.0,
    ):
        self.max_rounds = max_rounds
        self.departments = departments or [
            "engineering", "operations", "security", "quality", "protocol", "personnel",
        ]
        self._round_results: list[RoundResult] = []
        self._signal_bus = signal_bus
        self._gate_timeout = gate_timeout
        self._superstep_count: int = 0  # R43: BSP superstep counter
        # FutureGate for coordinating multi-department batch dispatches
        self._gate = FutureGate() if FutureGate else None
        # R43: Channel-Reducer state for deterministic aggregation
        self._state_channels = self._create_state_channels()
        self._init_signal_bus()

    def _create_state_channels(self) -> MergeChannel:
        """Create typed state channels for reducer-based aggregation (R43).

        Each field uses a different reduction strategy:
          - messages: AppendChannel — all department outputs collected in order
          - status: LastValueChannel — final status wins
          - artifacts: ReducerChannel(or_) — merge artifact dicts
        """
        return MergeChannel({
            "messages": AppendChannel(str),
            "status": LastValueChannel(str),
            "artifacts": ReducerChannel(lambda a, b: {**a, **b}, dict, {}),
        })

    def _init_signal_bus(self):
        """Initialize the cross-department signal bus for inter-round communication."""
        if self._signal_bus is not None:
            return
        try:
            from src.governance.signals.cross_dept import SignalBus
            self._signal_bus = SignalBus()
        except (ImportError, Exception) as e:
            log.debug(f"GroupOrchestration: signal bus init failed: {e}")
            self._signal_bus = None

    def _emit_cross_dept_signals(self, round_result: RoundResult, task: dict):
        """Emit cross-department signals based on round results.

        Scans outputs for collaboration patterns and sends structured signals
        through the SignalBus instead of relying solely on text pattern matching.
        """
        if not self._signal_bus:
            return

        try:
            from src.governance.signals.cross_dept import (
                Signal, SignalType, SignalPriority,
            )
        except ImportError:
            return

        for dept, dr in round_result.department_results.items():
            output = dr.get("output", "")
            status = dr.get("status", "")
            task_id = dr.get("task_id") or 0

            if not output:
                continue

            # Emit signals for detected collaboration needs
            collab_needs = _detect_collaboration_needs(output)
            for target_dept in collab_needs:
                if target_dept == dept:
                    continue
                try:
                    signal = Signal(
                        signal_type=SignalType.ESCALATION,
                        priority=SignalPriority.HIGH,
                        source_dept=dept,
                        target_dept=target_dept,
                        title=f"Collaboration needed from round {round_result.round_num}",
                        description=output[:300],
                        related_task_id=task_id,
                    )
                    self._signal_bus.send(signal)
                except Exception as e:
                    log.debug(f"GroupOrchestration: signal emit failed: {e}")

            # Emit failure signals
            if status == "failed" and _detect_failure(output):
                try:
                    signal = Signal(
                        signal_type=SignalType.ESCALATION,
                        priority=SignalPriority.CRITICAL,
                        source_dept=dept,
                        target_dept="",  # will be auto-routed
                        title=f"Department {dept} failed in round {round_result.round_num}",
                        description=output[:300],
                        related_task_id=task_id,
                    )
                    self._signal_bus.send(signal)
                except Exception as e:
                    log.debug(f"GroupOrchestration: failure signal emit failed: {e}")

    # ── Core Loop ───────────────────────────────────────────────

    def run(self, task: dict) -> str:
        """Execute the full multi-round orchestration loop.

        Args:
            task: Task dict with at least 'action', 'spec' (may be str or dict).
                  spec should contain 'department' or 'departments' for initial routing.

        Returns:
            Aggregated final output string.
        """
        self._round_results = []
        self._superstep_count = 0
        self._state_channels = self._create_state_channels()
        spec = task.get("spec", {})
        if isinstance(spec, str):
            try:
                spec = json.loads(spec)
            except (json.JSONDecodeError, TypeError):
                spec = {}

        # Determine initial targets
        initial_targets = self._resolve_initial_targets(spec)
        if not initial_targets:
            log.warning("GroupOrchestration: no initial targets resolved, falling back to engineering")
            initial_targets = ["engineering"]

        action = task.get("action", "")
        log.info(
            f"GroupOrchestration: starting multi-round loop for '{action[:60]}' "
            f"with targets={initial_targets}, max_rounds={self.max_rounds}"
        )

        # Initial decision: batch if multiple targets, single if one
        current_decision = SupervisorDecision(
            mode=DispatchMode.BATCH if len(initial_targets) > 1 else DispatchMode.SINGLE,
            targets=initial_targets,
            instruction=spec.get("problem", action),
        )

        for round_num in range(1, self.max_rounds + 1):
            log.info(
                f"GroupOrchestration: round {round_num}/{self.max_rounds} — "
                f"mode={current_decision.mode.value}, targets={current_decision.targets}"
            )

            # Execute this round
            round_result = self._execute_round(round_num, current_decision, task)
            self._round_results.append(round_result)

            # Emit cross-department signals based on round output
            try:
                self._emit_cross_dept_signals(round_result, task)
            except Exception as e:
                log.debug(f"GroupOrchestration: signal emission failed: {e}")

            # Evaluate and decide next step
            next_decision = self.evaluate(task, self._round_results)

            if next_decision.skip_supervisor:
                log.info(
                    f"GroupOrchestration: early termination after round {round_num} "
                    f"(skip_supervisor=True)"
                )
                break

            if not next_decision.targets:
                log.info(f"GroupOrchestration: no more targets after round {round_num}, done")
                break

            current_decision = next_decision

        final_output = self.aggregate(self._round_results)
        log.info(
            f"GroupOrchestration: completed after {len(self._round_results)} rounds, "
            f"output length={len(final_output)}"
        )
        return final_output

    # ── Evaluation (Rule-Driven) ────────────────────────────────

    def evaluate(self, task: dict, round_results: list[RoundResult]) -> SupervisorDecision:
        """Evaluate current round results and decide next action.

        Rule-driven logic (no LLM calls):
        1. All departments succeeded → terminate
        2. Output mentions needing another department → add to next round
        3. Output contains failure signals → retry failed departments
        4. Max rounds approaching → force terminate
        """
        if not round_results:
            return SupervisorDecision(
                mode=DispatchMode.SINGLE,
                targets=[],
                skip_supervisor=True,
            )

        latest = round_results[-1]
        already_dispatched = self._all_dispatched_departments()

        # Rule 1: All succeeded with no collaboration needs → done
        if latest.all_succeeded():
            collab_needs = self._scan_collaboration_needs(latest)
            # Filter out departments already dispatched in previous rounds
            new_needs = [d for d in collab_needs if d not in already_dispatched]

            if not new_needs:
                return SupervisorDecision(
                    mode=DispatchMode.SINGLE,
                    targets=[],
                    skip_supervisor=True,
                    instruction="All departments succeeded, no further action needed.",
                )

            # Collaboration needed — dispatch additional departments
            log.info(f"GroupOrchestration: collaboration needs detected: {new_needs}")
            return SupervisorDecision(
                mode=DispatchMode.BATCH if len(new_needs) > 1 else DispatchMode.SINGLE,
                targets=new_needs,
                instruction=f"Followup: departments {', '.join(new_needs)} needed based on round {latest.round_num} output.",
            )

        # Rule 2: Some failed → retry failed departments (once)
        if latest.any_failed():
            failed = latest.failed_departments()
            # Count how many times each department has been retried
            retry_counts = self._department_attempt_counts()
            retriable = [d for d in failed if retry_counts.get(d, 0) < 2]

            if retriable:
                log.info(f"GroupOrchestration: retrying failed departments: {retriable}")
                return SupervisorDecision(
                    mode=DispatchMode.BATCH if len(retriable) > 1 else DispatchMode.SINGLE,
                    targets=retriable,
                    instruction=f"Retry: departments {', '.join(retriable)} failed in round {latest.round_num}.",
                )

            # All failed departments exhausted retries → terminate with partial results
            log.warning("GroupOrchestration: all failed departments exhausted retries, terminating")
            return SupervisorDecision(
                mode=DispatchMode.SINGLE,
                targets=[],
                skip_supervisor=True,
                instruction="Failed departments exhausted retries.",
            )

        # Rule 3: Mixed results — check collaboration needs from successful outputs
        collab_needs = self._scan_collaboration_needs(latest)
        new_needs = [d for d in collab_needs if d not in already_dispatched]
        if new_needs:
            return SupervisorDecision(
                mode=DispatchMode.BATCH if len(new_needs) > 1 else DispatchMode.SINGLE,
                targets=new_needs,
                instruction=f"Followup from mixed results in round {latest.round_num}.",
            )

        # Default: terminate
        return SupervisorDecision(
            mode=DispatchMode.SINGLE,
            targets=[],
            skip_supervisor=True,
            instruction="No further action determined.",
        )

    # ── Aggregation ─────────────────────────────────────────────

    def aggregate(self, results: list[RoundResult]) -> str:
        """Aggregate outputs from all rounds using Channel-Reducer protocol (R43).

        Uses MergeChannel with per-field reducers for deterministic aggregation:
          - messages: AppendChannel (all outputs collected)
          - status: LastValueChannel (final status wins)
          - artifacts: ReducerChannel (merged dicts)

        Falls back to legacy concatenation if channels produce nothing.
        """
        if not results:
            return ""

        # Feed round results into state channels
        channels = self._create_state_channels()
        for rr in results:
            for dept, dr in rr.department_results.items():
                status = dr.get("status", "unknown")
                output = dr.get("output", "")
                artifacts = dr.get("artifacts", {})

                if status == "success" and output:
                    channels.update({
                        "messages": [f"[{dept}] {output}"],
                        "status": ["success"],
                    })
                elif status == "failed":
                    channels.update({
                        "messages": [f"[{dept}] (FAILED) {output[:200]}"],
                        "status": ["failed"],
                    })

                if artifacts:
                    channels.update({"artifacts": [artifacts]})

        state = channels.get()
        messages = state.get("messages", [])

        if messages:
            return "\n\n".join(messages)

        # Legacy fallback: aggregated_output if channels produced nothing
        return "\n\n".join(
            rr.aggregated_output for rr in results if rr.aggregated_output
        )

    # ── Execution (delegates to Governor/Dispatcher) ────────────

    def _execute_round(
        self,
        round_num: int,
        decision: SupervisorDecision,
        task: dict,
    ) -> RoundResult:
        """Execute one round of dispatch.

        This is the integration seam — it imports Governor lazily to avoid
        circular imports and delegates actual task creation/execution.

        Enhanced with FutureGate (ChatDev 2.0, Round 13): BATCH mode dispatches
        departments in parallel using a thread pool and FutureGate for coordination.
        SINGLE mode preserves the original sequential behavior.
        """
        result = RoundResult(round_num=round_num)

        # Filter valid departments first
        valid_targets = []
        for dept in decision.targets:
            if dept not in self.departments:
                log.warning(f"GroupOrchestration: skipping unknown department '{dept}'")
                result.department_results[dept] = {
                    "status": "skipped",
                    "output": f"Unknown department: {dept}",
                    "task_id": None,
                }
            else:
                valid_targets.append(dept)

        # ── BATCH with FutureGate: parallel dispatch + coordinated wait ──
        if (decision.mode == DispatchMode.BATCH and len(valid_targets) > 1
                and self._gate is not None):
            gate_ids: dict[str, str] = {}
            for dept in valid_targets:
                gate_ids[dept] = self._gate.open(label=f"round{round_num}:{dept}")

            def _dispatch_and_provide(dept: str, gate_id: str):
                try:
                    dept_result = self._dispatch_to_department(
                        dept, decision.instruction, task
                    )
                    self._gate.provide(gate_id, dept_result)
                    return dept, dept_result
                except Exception as e:
                    error_result = {
                        "status": "failed",
                        "output": f"Gate dispatch error: {e}",
                        "task_id": None,
                    }
                    self._gate.provide(gate_id, error_result)
                    return dept, error_result

            # Dispatch all departments in parallel
            with ThreadPoolExecutor(
                max_workers=min(len(valid_targets), 4),
                thread_name_prefix="group-orch"
            ) as pool:
                futures = {
                    pool.submit(_dispatch_and_provide, dept, gate_ids[dept]): dept
                    for dept in valid_targets
                }

                # Wait for all gates with timeout
                for dept in valid_targets:
                    gate_id = gate_ids[dept]
                    try:
                        dept_result = self._gate.wait(
                            gate_id, timeout=self._gate_timeout
                        )
                        result.department_results[dept] = dept_result
                    except (GateTimeout, Exception) as e:
                        log.warning(
                            f"GroupOrchestration: gate wait failed for {dept}: {e}"
                        )
                        result.department_results[dept] = {
                            "status": "failed",
                            "output": f"Gate coordination failed: {e}",
                            "task_id": None,
                        }
        else:
            # ── Sequential dispatch (original behavior, preserved) ──
            for dept in valid_targets:
                dept_result = self._dispatch_to_department(
                    dept, decision.instruction, task
                )
                result.department_results[dept] = dept_result

        # ── R43 BSP: Write phase — feed results into state channels ──
        self._superstep_count += 1
        result.superstep_count = self._superstep_count

        for dept, dr in result.department_results.items():
            status = dr.get("status", "unknown")
            output = dr.get("output", "")
            artifacts = dr.get("artifacts", {})

            if status == "success" and output:
                self._state_channels.update({
                    "messages": [f"[{dept}] {output}"],
                    "status": ["success"],
                })
            elif status == "failed":
                self._state_channels.update({
                    "messages": [f"[{dept}] (FAILED) {output[:200]}"],
                    "status": ["failed"],
                })
            if artifacts:
                self._state_channels.update({"artifacts": [artifacts]})

        # ── R43 BSP: Sync barrier — advance to next superstep ──
        self._state_channels.finish()

        # Build aggregated output for this round
        outputs = [
            dr.get("output", "")
            for dr in result.department_results.values()
            if dr.get("status") == "success" and dr.get("output")
        ]
        result.aggregated_output = "\n".join(outputs)

        return result

    def _dispatch_to_department(
        self,
        department: str,
        instruction: str,
        parent_task: dict,
    ) -> dict:
        """Dispatch a sub-task to a specific department via Governor.

        Returns: {"status": "success"|"failed", "output": str, "task_id": int|None}
        """
        try:
            from src.governance.governor import Governor

            spec = parent_task.get("spec", {})
            if isinstance(spec, str):
                try:
                    spec = json.loads(spec)
                except (json.JSONDecodeError, TypeError):
                    spec = {}

            sub_spec = {
                **spec,
                "department": department,
                "problem": instruction,
                "summary": f"[GroupOrch] {instruction[:80]}",
                "orchestration_round": True,
            }

            governor = Governor()
            result_task = governor._dispatch_task(
                spec=sub_spec,
                action=f"[GroupOrch → {department}] {instruction[:100]}",
                reason=f"Multi-department orchestration dispatch",
                priority=spec.get("priority", "high"),
                source="group_orchestration",
            )

            if result_task is None:
                return {
                    "status": "failed",
                    "output": "Dispatch rejected (preflight/scrutiny/semaphore)",
                    "task_id": None,
                }

            # Task was dispatched and executed (async).
            # For synchronous orchestration, we read back the result.
            task_id = result_task.get("id")
            status = result_task.get("status", "unknown")
            output = result_task.get("output", "")

            # Map task status to round result status
            if status in ("completed", "done", "success"):
                return {"status": "success", "output": output, "task_id": task_id}
            elif status in ("failed", "scrutiny_failed", "preflight_failed"):
                return {"status": "failed", "output": output, "task_id": task_id}
            else:
                # Task is still running or in unknown state — treat as pending success
                # (async execution means we may not have the result yet)
                return {
                    "status": "success",
                    "output": output or f"Task #{task_id} dispatched (status: {status})",
                    "task_id": task_id,
                }

        except Exception as e:
            log.error(f"GroupOrchestration: dispatch to {department} failed: {e}")
            return {
                "status": "failed",
                "output": f"Dispatch error: {e}",
                "task_id": None,
            }

    # ── Helpers ──────────────────────────────────────────────────

    def _resolve_initial_targets(self, spec: dict) -> list[str]:
        """Determine which departments to dispatch to initially."""
        # Explicit multi-department specification
        if "departments" in spec:
            depts = spec["departments"]
            if isinstance(depts, str):
                depts = [d.strip() for d in depts.split(",")]
            return [d for d in depts if d in self.departments]

        # Single department
        dept = spec.get("department", "")
        if dept and dept in self.departments:
            return [dept]

        return []

    def _all_dispatched_departments(self) -> set[str]:
        """Collect all departments that have been dispatched across all rounds."""
        dispatched = set()
        for rr in self._round_results:
            dispatched.update(rr.department_results.keys())
        return dispatched

    def _department_attempt_counts(self) -> dict[str, int]:
        """Count how many times each department has been dispatched."""
        counts: dict[str, int] = {}
        for rr in self._round_results:
            for dept in rr.department_results:
                counts[dept] = counts.get(dept, 0) + 1
        return counts

    def _scan_collaboration_needs(self, round_result: RoundResult) -> list[str]:
        """Scan all outputs in a round for collaboration signals."""
        needs: list[str] = []
        for dept, dr in round_result.department_results.items():
            output = dr.get("output", "")
            if output:
                detected = _detect_collaboration_needs(output)
                for d in detected:
                    if d != dept and d not in needs:
                        needs.append(d)
        return needs

    @property
    def round_results(self) -> list[RoundResult]:
        """Access round results (read-only view for inspection)."""
        return list(self._round_results)

    def get_execution_summary(self) -> dict:
        """Generate a summary of the orchestration execution."""
        return {
            "total_rounds": len(self._round_results),
            "max_rounds": self.max_rounds,
            "departments_involved": sorted(self._all_dispatched_departments()),
            "attempt_counts": self._department_attempt_counts(),
            "rounds": [rr.to_dict() for rr in self._round_results],
        }
