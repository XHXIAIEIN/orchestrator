"""Plan-then-Execute Dual Mode — stolen from OpenHands Planning Agent.

For complex tasks (designer cognitive mode), generates a structured plan
before execution. The plan is a reviewable artifact that can be approved,
modified, or rejected before any code changes happen.

Modes:
  - PLAN: Generate structured plan, ask clarifying questions if needed
  - EXECUTE: Execute plan steps sequentially, checkpoint after each

Usage:
    executor = PlanExecutor()
    plan = executor.create_plan(task_spec)
    # Optional: human reviews plan
    results = executor.execute_plan(plan)
"""
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable

log = logging.getLogger(__name__)


class PlanStatus(Enum):
    DRAFT = "draft"
    READY = "ready"         # reviewed and approved
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class PlanStep:
    """A single step in a plan."""
    index: int
    description: str
    files: list[str] = field(default_factory=list)  # files to touch
    command: str = ""        # optional command to run
    status: str = "pending"  # pending, running, done, failed, skipped
    output: str = ""
    duration_ms: int = 0


@dataclass
class ExecutionPlan:
    """A structured plan for task execution."""
    task_id: str
    title: str
    goal: str
    steps: list[PlanStep] = field(default_factory=list)
    status: PlanStatus = PlanStatus.DRAFT
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    clarifications: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @property
    def progress(self) -> float:
        """Completion ratio 0.0-1.0."""
        if not self.steps:
            return 0.0
        done = sum(1 for s in self.steps if s.status in ("done", "skipped"))
        return done / len(self.steps)

    @property
    def current_step(self) -> Optional[PlanStep]:
        """Get the next pending step."""
        for step in self.steps:
            if step.status == "pending":
                return step
        return None

    def add_step(self, description: str, files: list[str] = None,
                 command: str = "") -> PlanStep:
        step = PlanStep(
            index=len(self.steps),
            description=description,
            files=files or [],
            command=command,
        )
        self.steps.append(step)
        return step

    def to_markdown(self) -> str:
        """Render plan as markdown for human review."""
        lines = [f"# {self.title}", "", f"**Goal:** {self.goal}", ""]
        if self.clarifications:
            lines.append("## Clarifications Needed")
            for q in self.clarifications:
                lines.append(f"- {q}")
            lines.append("")
        lines.append("## Steps")
        for step in self.steps:
            status_icon = {"pending": "[ ]", "done": "[x]", "running": "[~]",
                          "failed": "[!]", "skipped": "[-]"}.get(step.status, "[ ]")
            lines.append(f"- {status_icon} **Step {step.index + 1}:** {step.description}")
            if step.files:
                lines.append(f"  - Files: {', '.join(step.files)}")
            if step.command:
                lines.append(f"  - Run: `{step.command}`")
        return "\n".join(lines)


class PlanExecutor:
    """Manages plan lifecycle: create -> review -> execute."""

    def __init__(self):
        self._plans: dict[str, ExecutionPlan] = {}
        self._step_callback: Optional[Callable] = None

    def on_step_complete(self, callback: Callable):
        """Register callback fired after each step completes."""
        self._step_callback = callback

    def create_plan(self, task_id: str, title: str, goal: str,
                    steps: list[dict] = None) -> ExecutionPlan:
        """Create a new execution plan."""
        plan = ExecutionPlan(task_id=task_id, title=title, goal=goal)
        for step_data in (steps or []):
            plan.add_step(
                description=step_data.get("description", ""),
                files=step_data.get("files", []),
                command=step_data.get("command", ""),
            )
        self._plans[task_id] = plan
        log.info(f"plan_executor: created plan for {task_id} ({len(plan.steps)} steps)")
        return plan

    def approve_plan(self, task_id: str) -> bool:
        """Mark a plan as ready for execution."""
        plan = self._plans.get(task_id)
        if not plan:
            return False
        if plan.status != PlanStatus.DRAFT:
            return False
        plan.status = PlanStatus.READY
        log.info(f"plan_executor: plan {task_id} approved")
        return True

    def execute_plan(self, task_id: str,
                     step_fn: Callable[[PlanStep], str] = None) -> ExecutionPlan:
        """Execute a plan step by step.

        Args:
            task_id: The task/plan ID
            step_fn: Optional function to execute each step.
                     Receives PlanStep, returns output string.
                     If None, steps are just marked as done.

        Returns:
            The updated plan.
        """
        plan = self._plans.get(task_id)
        if not plan:
            raise ValueError(f"No plan found for {task_id}")

        if plan.status not in (PlanStatus.READY, PlanStatus.DRAFT):
            raise ValueError(f"Plan {task_id} is {plan.status.value}, cannot execute")

        plan.status = PlanStatus.EXECUTING
        plan.started_at = time.time()

        for step in plan.steps:
            if step.status != "pending":
                continue

            step.status = "running"
            t0 = time.time()

            try:
                if step_fn:
                    step.output = step_fn(step)
                step.status = "done"
            except Exception as e:
                step.status = "failed"
                step.output = str(e)
                plan.status = PlanStatus.FAILED
                log.warning(f"plan_executor: step {step.index} failed: {e}")
                break
            finally:
                step.duration_ms = int((time.time() - t0) * 1000)

            if self._step_callback:
                try:
                    self._step_callback(plan, step)
                except Exception:
                    pass

        if plan.status == PlanStatus.EXECUTING:
            plan.status = PlanStatus.COMPLETED
            plan.completed_at = time.time()

        log.info(f"plan_executor: {task_id} {plan.status.value} ({plan.progress:.0%})")
        return plan

    def cancel_plan(self, task_id: str) -> bool:
        """Cancel a plan."""
        plan = self._plans.get(task_id)
        if not plan:
            return False
        plan.status = PlanStatus.CANCELLED
        # Skip remaining pending steps
        for step in plan.steps:
            if step.status == "pending":
                step.status = "skipped"
        return True

    def get_plan(self, task_id: str) -> Optional[ExecutionPlan]:
        return self._plans.get(task_id)

    def get_stats(self) -> dict:
        statuses = {}
        for p in self._plans.values():
            s = p.status.value
            statuses[s] = statuses.get(s, 0) + 1
        return {"total": len(self._plans), "by_status": statuses}
