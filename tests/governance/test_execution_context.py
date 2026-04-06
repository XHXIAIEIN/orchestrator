import pytest
from src.governance.execution_context import ExecutionContext, NodeExecution, NodeStatus

def test_create_context():
    ctx = ExecutionContext.create(workflow_id="wf-1")
    assert ctx.workflow_id == "wf-1"
    assert ctx.execution_id
    assert ctx.node_executions == {}

def test_record_node_start():
    ctx = ExecutionContext.create(workflow_id="wf-1")
    ctx.start_node("node-A")
    assert "node-A" in ctx.node_executions
    assert ctx.node_executions["node-A"].status == NodeStatus.RUNNING

def test_record_node_complete():
    ctx = ExecutionContext.create(workflow_id="wf-1")
    ctx.start_node("node-A")
    ctx.complete_node("node-A", output={"result": 42})
    assert ctx.node_executions["node-A"].status == NodeStatus.COMPLETED
    assert ctx.outputs["node-A"] == {"result": 42}
    assert "node-A" in ctx.checkpoints

def test_record_node_failure():
    ctx = ExecutionContext.create(workflow_id="wf-1")
    ctx.start_node("node-A")
    ctx.fail_node("node-A", error="timeout")
    assert ctx.node_executions["node-A"].status == NodeStatus.FAILED
    assert len(ctx.errors) == 1
    assert ctx.errors[0]["node"] == "node-A"

def test_contexts_are_independent():
    ctx1 = ExecutionContext.create(workflow_id="wf-1")
    ctx2 = ExecutionContext.create(workflow_id="wf-2")
    ctx1.start_node("A")
    assert "A" not in ctx2.node_executions
    assert ctx1.execution_id != ctx2.execution_id

def test_to_dict_roundtrip():
    ctx = ExecutionContext.create(workflow_id="wf-1")
    ctx.start_node("node-A")
    ctx.complete_node("node-A", output={"x": 1})
    d = ctx.to_dict()
    assert d["workflow_id"] == "wf-1"
    assert "node-A" in d["checkpoints"]
