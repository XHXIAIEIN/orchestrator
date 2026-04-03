"""
Agent Trajectory Capture + Scoring (R38 — stolen from promptfoo + LangChain AgentEvals).

Captures the full sequence of agent tool calls during a Governor dispatch,
then scores the trajectory for efficiency, correctness, recovery, and tool selection.

Three matching modes (from LangChain AgentEvals):
  - strict:    identical tool calls in same order
  - unordered: same tool calls, any order
  - subset:    reference trajectory is a subset of actual

Integrates with ExecutionSnapshot (R16) for data capture,
and with eval_loop.py for inclusion in EvalResult.

Usage:
    # During execution — capture tool calls
    tracker = TrajectoryTracker(task_id=42)
    tracker.record_tool_call("bash", {"command": "ls"}, success=True)
    tracker.record_tool_call("read_file", {"path": "foo.py"}, success=True)
    tracker.record_recovery("bash", error="permission denied", recovered=True)

    # After execution — score the trajectory
    score = score_trajectory(tracker.trajectory)
    # TrajectoryScore(efficiency=0.85, correctness=0.9, recovery=1.0, tool_selection=0.8)

    # Optional: assert against reference trajectory
    result = assert_trajectory(tracker.trajectory, reference, mode="subset")
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Literal

log = logging.getLogger(__name__)


# ── Data Structures ──────────────────────────────────────────


class ToolCallVerdict(str, Enum):
    """Post-hoc judgment of a tool call's necessity."""
    NECESSARY = "necessary"      # contributed to the goal
    REDUNDANT = "redundant"      # repeated information already known
    INCORRECT = "incorrect"      # wrong tool or wrong args
    RECOVERY = "recovery"        # fixing a previous mistake
    EXPLORATORY = "exploratory"  # information gathering (neutral)


@dataclass
class TrajectoryStep:
    """One tool call in the agent's trajectory."""
    tool_name: str
    tool_args: dict
    success: bool
    timestamp: str                             # ISO 8601
    duration_ms: int = 0
    token_cost: int = 0
    verdict: ToolCallVerdict = ToolCallVerdict.NECESSARY
    error_message: str = ""                    # if success=False
    recovered_from: str = ""                   # if this step recovered from a previous error

    def to_dict(self) -> dict:
        d = asdict(self)
        d["verdict"] = self.verdict.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> TrajectoryStep:
        d = dict(d)
        if isinstance(d.get("verdict"), str):
            d["verdict"] = ToolCallVerdict(d["verdict"])
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class TrajectoryScore:
    """Four-dimensional trajectory quality score."""
    efficiency: float = 0.0       # optimal_steps / actual_steps (1.0 = perfect)
    correctness: float = 0.0      # steps that were correct / total steps
    recovery: float = 0.0         # recovered errors / total errors (1.0 if no errors)
    tool_selection: float = 0.0   # necessary+recovery steps / total steps

    @property
    def composite(self) -> float:
        """Weighted composite score (0-1).

        Weights: correctness 40%, efficiency 20%, recovery 20%, tool_selection 20%.
        """
        return (
            self.efficiency * 0.2
            + self.correctness * 0.4
            + self.recovery * 0.2
            + self.tool_selection * 0.2
        )

    def to_dict(self) -> dict:
        return {
            "efficiency": round(self.efficiency, 3),
            "correctness": round(self.correctness, 3),
            "recovery": round(self.recovery, 3),
            "tool_selection": round(self.tool_selection, 3),
            "composite": round(self.composite, 3),
        }


@dataclass
class Trajectory:
    """Complete tool call trajectory for one task execution."""
    schema_version: str = "orch-v1.0"  # R38 AutoAgent: versioned for future migration
    task_id: int = 0
    steps: list[TrajectoryStep] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""
    total_tokens: int = 0
    total_cost_usd: float = 0.0

    @property
    def tool_calls_count(self) -> int:
        return len(self.steps)

    @property
    def error_count(self) -> int:
        return sum(1 for s in self.steps if not s.success)

    @property
    def unique_tools(self) -> set[str]:
        return {s.tool_name for s in self.steps}

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "steps": [s.to_dict() for s in self.steps],
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "total_tokens": self.total_tokens,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "tool_calls_count": self.tool_calls_count,
            "error_count": self.error_count,
            "unique_tools": sorted(self.unique_tools),
        }


# ── Trajectory Tracker ───────────────────────────────────────


class TrajectoryTracker:
    """Captures tool calls during agent execution.

    Attach to an executor session and call record_tool_call() for each tool use.
    """

    def __init__(self, task_id: int):
        self._trajectory = Trajectory(
            task_id=task_id,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        self._last_ts = time.monotonic()

    @property
    def trajectory(self) -> Trajectory:
        return self._trajectory

    def record_tool_call(
        self,
        tool_name: str,
        tool_args: dict,
        success: bool = True,
        error_message: str = "",
        tokens: int = 0,
        cost: float = 0.0,
    ) -> TrajectoryStep:
        """Record a tool call. Returns the created step."""
        now = time.monotonic()
        duration_ms = int((now - self._last_ts) * 1000)
        self._last_ts = now

        self._trajectory.total_tokens += tokens
        self._trajectory.total_cost_usd += cost

        step = TrajectoryStep(
            tool_name=tool_name,
            tool_args=tool_args,
            success=success,
            timestamp=datetime.now(timezone.utc).isoformat(),
            duration_ms=duration_ms,
            token_cost=tokens,
            error_message=error_message,
        )
        self._trajectory.steps.append(step)
        return step

    def record_recovery(self, tool_name: str, error: str, recovered: bool):
        """Mark the most recent step as a recovery attempt."""
        for step in reversed(self._trajectory.steps):
            if step.tool_name == tool_name:
                step.recovered_from = error
                step.verdict = ToolCallVerdict.RECOVERY if recovered else ToolCallVerdict.INCORRECT
                break

    def finish(self):
        """Mark trajectory as complete."""
        self._trajectory.finished_at = datetime.now(timezone.utc).isoformat()


# ── Trajectory Scoring ───────────────────────────────────────


def score_trajectory(
    trajectory: Trajectory,
    optimal_steps: int | None = None,
) -> TrajectoryScore:
    """Score a completed trajectory on 4 dimensions.

    Args:
        trajectory: the completed trajectory
        optimal_steps: expected optimal step count (if known).
                       If None, estimates from unique tools used.
    """
    steps = trajectory.steps
    if not steps:
        return TrajectoryScore(efficiency=1.0, correctness=1.0, recovery=1.0, tool_selection=1.0)

    total = len(steps)

    # Efficiency: optimal / actual (capped at 1.0)
    if optimal_steps is None:
        # Heuristic: unique tools used ≈ minimum necessary steps
        optimal_steps = max(len(trajectory.unique_tools), 1)
    efficiency = min(optimal_steps / total, 1.0) if total > 0 else 1.0

    # Correctness: successful steps / total
    correct = sum(1 for s in steps if s.success)
    correctness = correct / total

    # Recovery: recovered errors / total errors
    errors = [s for s in steps if not s.success]
    if not errors:
        recovery = 1.0  # no errors = perfect recovery score
    else:
        recovered = sum(1 for s in steps if s.verdict == ToolCallVerdict.RECOVERY and s.success)
        recovery = min(recovered / len(errors), 1.0)

    # Tool selection: necessary+recovery steps / total
    useful = sum(1 for s in steps
                 if s.verdict in (ToolCallVerdict.NECESSARY, ToolCallVerdict.RECOVERY, ToolCallVerdict.EXPLORATORY))
    tool_selection = useful / total

    return TrajectoryScore(
        efficiency=efficiency,
        correctness=correctness,
        recovery=recovery,
        tool_selection=tool_selection,
    )


# ── Trajectory Assertions (R38: promptfoo + LangChain AgentEvals) ─


MatchMode = Literal["strict", "unordered", "subset"]


@dataclass
class TrajectoryAssertionResult:
    """Result of a trajectory assertion check."""
    passed: bool
    mode: MatchMode
    message: str = ""
    expected_tools: list[str] = field(default_factory=list)
    actual_tools: list[str] = field(default_factory=list)
    missing_tools: list[str] = field(default_factory=list)
    extra_tools: list[str] = field(default_factory=list)


def assert_trajectory(
    actual: Trajectory,
    reference_tools: list[str],
    mode: MatchMode = "subset",
) -> TrajectoryAssertionResult:
    """Assert that a trajectory matches a reference tool sequence.

    Modes:
      - strict:    identical tools in same order
      - unordered: same tools, any order
      - subset:    all reference tools appear in actual (actual may have more)
    """
    actual_tools = [s.tool_name for s in actual.steps]

    if mode == "strict":
        passed = actual_tools == reference_tools
        msg = "" if passed else f"strict mismatch: expected {reference_tools}, got {actual_tools}"
        missing = [t for t in reference_tools if t not in actual_tools]
        extra = [t for t in actual_tools if t not in reference_tools]

    elif mode == "unordered":
        passed = sorted(actual_tools) == sorted(reference_tools)
        msg = "" if passed else f"unordered mismatch: expected {sorted(reference_tools)}, got {sorted(actual_tools)}"
        missing = [t for t in reference_tools if t not in actual_tools]
        extra = [t for t in actual_tools if t not in reference_tools]

    elif mode == "subset":
        # All reference tools must appear in actual
        actual_set = set(actual_tools)
        missing = [t for t in reference_tools if t not in actual_set]
        extra = []  # not relevant in subset mode
        passed = len(missing) == 0
        msg = "" if passed else f"missing tools: {missing}"

    else:
        passed = False
        msg = f"unknown match mode: {mode}"
        missing = []
        extra = []

    return TrajectoryAssertionResult(
        passed=passed,
        mode=mode,
        message=msg,
        expected_tools=list(reference_tools),
        actual_tools=actual_tools,
        missing_tools=missing,
        extra_tools=extra,
    )


def assert_step_count(trajectory: Trajectory, max_steps: int) -> TrajectoryAssertionResult:
    """Assert that the trajectory didn't exceed max_steps."""
    actual = trajectory.tool_calls_count
    passed = actual <= max_steps
    return TrajectoryAssertionResult(
        passed=passed,
        mode="strict",
        message="" if passed else f"step count {actual} exceeds max {max_steps}",
        actual_tools=[s.tool_name for s in trajectory.steps],
    )


def assert_tool_used(trajectory: Trajectory, tool_name: str) -> TrajectoryAssertionResult:
    """Assert that a specific tool was used at least once."""
    used = tool_name in trajectory.unique_tools
    return TrajectoryAssertionResult(
        passed=used,
        mode="subset",
        message="" if used else f"tool '{tool_name}' was not used",
        actual_tools=[s.tool_name for s in trajectory.steps],
        missing_tools=[] if used else [tool_name],
    )


# ── Integration: build from ExecutionSnapshot ─────────────────


def trajectory_from_snapshot(snapshot) -> Trajectory:
    """Build a Trajectory from an ExecutionSnapshot (R16 integration).

    Extracts tool_call events from the snapshot's step sequence.
    """
    trajectory = Trajectory(task_id=snapshot.task_id)
    steps = snapshot.get_steps()

    if steps:
        trajectory.started_at = steps[0].timestamp

    for step in steps:
        if step.event_type == "tool_call":
            t_step = TrajectoryStep(
                tool_name=step.data.get("tool", "unknown"),
                tool_args=step.data.get("input", {}),
                success=True,  # tool_call event = call initiated
                timestamp=step.timestamp,
                duration_ms=step.duration_ms,
                token_cost=step.cumulative_tokens,
            )
            trajectory.steps.append(t_step)

        elif step.event_type == "tool_result":
            # Update the last matching tool call with result status
            tool_name = step.data.get("tool", "")
            for t_step in reversed(trajectory.steps):
                if t_step.tool_name == tool_name and not t_step.error_message:
                    output = step.data.get("output", "")
                    if "error" in output.lower()[:50] or "Error" in output[:50]:
                        t_step.success = False
                        t_step.error_message = output[:200]
                    break

        elif step.event_type == "error":
            # Record as a failed step
            trajectory.steps.append(TrajectoryStep(
                tool_name="<error>",
                tool_args={"error": step.data.get("error", "")},
                success=False,
                timestamp=step.timestamp,
                duration_ms=step.duration_ms,
                error_message=step.data.get("error", "")[:200],
                verdict=ToolCallVerdict.INCORRECT,
            ))

    if steps:
        trajectory.finished_at = steps[-1].timestamp
        trajectory.total_tokens = steps[-1].cumulative_tokens
        trajectory.total_cost_usd = steps[-1].cumulative_cost_usd

    return trajectory
