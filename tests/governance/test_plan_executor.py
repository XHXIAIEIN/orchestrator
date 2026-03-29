"""Tests for Plan-then-Execute Dual Mode."""
from src.governance.plan_executor import (
    PlanExecutor, ExecutionPlan, PlanStep, PlanStatus,
)


def test_create_plan():
    executor = PlanExecutor()
    plan = executor.create_plan("task_1", "Fix Auth", "Fix the auth bug", steps=[
        {"description": "Read auth.py", "files": ["src/auth.py"]},
        {"description": "Fix the return type", "files": ["src/auth.py"]},
        {"description": "Run tests", "command": "pytest tests/"},
    ])
    assert len(plan.steps) == 3
    assert plan.status == PlanStatus.DRAFT
    assert plan.progress == 0.0


def test_plan_to_markdown():
    plan = ExecutionPlan(task_id="t1", title="Fix Bug", goal="Fix it")
    plan.add_step("Read the file", files=["src/main.py"])
    plan.add_step("Run tests", command="pytest")
    md = plan.to_markdown()
    assert "Fix Bug" in md
    assert "src/main.py" in md
    assert "pytest" in md


def test_approve_plan():
    executor = PlanExecutor()
    plan = executor.create_plan("task_1", "Test", "Test goal")
    assert executor.approve_plan("task_1")
    assert plan.status == PlanStatus.READY


def test_execute_plan():
    executor = PlanExecutor()
    plan = executor.create_plan("task_1", "Test", "Goal", steps=[
        {"description": "Step 1"},
        {"description": "Step 2"},
    ])
    executor.approve_plan("task_1")
    result = executor.execute_plan("task_1")
    assert result.status == PlanStatus.COMPLETED
    assert result.progress == 1.0
    assert all(s.status == "done" for s in result.steps)


def test_execute_with_step_fn():
    executor = PlanExecutor()
    plan = executor.create_plan("task_1", "Test", "Goal", steps=[
        {"description": "Compute"},
    ])
    executor.approve_plan("task_1")
    result = executor.execute_plan("task_1", step_fn=lambda s: f"did: {s.description}")
    assert result.steps[0].output == "did: Compute"


def test_execute_step_failure():
    executor = PlanExecutor()
    plan = executor.create_plan("task_1", "Test", "Goal", steps=[
        {"description": "Good step"},
        {"description": "Bad step"},
        {"description": "Never reached"},
    ])
    executor.approve_plan("task_1")

    def failing_fn(step):
        if step.index == 1:
            raise RuntimeError("boom")
        return "ok"

    result = executor.execute_plan("task_1", step_fn=failing_fn)
    assert result.status == PlanStatus.FAILED
    assert result.steps[0].status == "done"
    assert result.steps[1].status == "failed"
    assert result.steps[2].status == "pending"


def test_cancel_plan():
    executor = PlanExecutor()
    plan = executor.create_plan("task_1", "Test", "Goal", steps=[
        {"description": "Step 1"},
        {"description": "Step 2"},
    ])
    executor.cancel_plan("task_1")
    assert plan.status == PlanStatus.CANCELLED
    assert all(s.status == "skipped" for s in plan.steps)


def test_current_step():
    plan = ExecutionPlan(task_id="t1", title="T", goal="G")
    plan.add_step("First")
    plan.add_step("Second")
    assert plan.current_step.index == 0
    plan.steps[0].status = "done"
    assert plan.current_step.index == 1


def test_step_callback():
    executor = PlanExecutor()
    callbacks = []
    executor.on_step_complete(lambda plan, step: callbacks.append(step.index))
    executor.create_plan("t1", "T", "G", steps=[
        {"description": "A"}, {"description": "B"},
    ])
    executor.approve_plan("t1")
    executor.execute_plan("t1")
    assert callbacks == [0, 1]


def test_get_stats():
    executor = PlanExecutor()
    executor.create_plan("t1", "A", "G")
    executor.create_plan("t2", "B", "G")
    executor.approve_plan("t2")
    executor.execute_plan("t2")
    stats = executor.get_stats()
    assert stats["total"] == 2
    assert stats["by_status"]["draft"] == 1
    assert stats["by_status"]["completed"] == 1
