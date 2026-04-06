import pytest
import asyncio
from src.governance.continuous_scheduler import DAGScheduler, NodeSpec, ContinuousExecutor


def test_find_ready_nodes_no_deps():
    scheduler = DAGScheduler()
    scheduler.add_node(NodeSpec(node_id="A", dependencies=[]))
    scheduler.add_node(NodeSpec(node_id="B", dependencies=[]))
    ready = scheduler.find_ready_nodes(completed=set())
    assert set(ready) == {"A", "B"}


def test_find_ready_nodes_with_deps():
    scheduler = DAGScheduler()
    scheduler.add_node(NodeSpec(node_id="A", dependencies=[]))
    scheduler.add_node(NodeSpec(node_id="B", dependencies=["A"]))
    scheduler.add_node(NodeSpec(node_id="C", dependencies=["A", "B"]))
    ready = scheduler.find_ready_nodes(completed=set())
    assert ready == ["A"]
    ready = scheduler.find_ready_nodes(completed={"A"})
    assert ready == ["B"]
    ready = scheduler.find_ready_nodes(completed={"A", "B"})
    assert ready == ["C"]


def test_cycle_detection():
    scheduler = DAGScheduler()
    scheduler.add_node(NodeSpec(node_id="A", dependencies=["B"]))
    scheduler.add_node(NodeSpec(node_id="B", dependencies=["A"]))
    with pytest.raises(ValueError, match="cycle"):
        scheduler.validate()


@pytest.mark.asyncio
async def test_continuous_execution_order():
    results = []

    async def handler_a(ctx):
        await asyncio.sleep(0.05)
        results.append("A")
        return "a_output"

    async def handler_b(ctx):
        await asyncio.sleep(0.05)
        results.append("B")
        return "b_output"

    async def handler_c(ctx):
        await asyncio.sleep(0.05)
        results.append("C")
        return "c_output"

    scheduler = DAGScheduler()
    scheduler.add_node(NodeSpec("A", dependencies=[], handler=handler_a))
    scheduler.add_node(NodeSpec("B", dependencies=["A"], handler=handler_b))
    scheduler.add_node(NodeSpec("C", dependencies=["A"], handler=handler_c))

    from src.governance.execution_context import ExecutionContext
    ctx = ExecutionContext.create(workflow_id="test-wf")
    executor = ContinuousExecutor(scheduler)
    result_ctx = await executor.run(ctx)

    assert results[0] == "A"
    assert set(results[1:]) == {"B", "C"}
    assert result_ctx.outputs["A"] == "a_output"
    assert len(result_ctx.checkpoints) == 3


@pytest.mark.asyncio
async def test_node_failure_does_not_block_independent():
    async def handler_a(ctx):
        raise RuntimeError("boom")

    async def handler_b(ctx):
        return "ok"

    scheduler = DAGScheduler()
    scheduler.add_node(NodeSpec("A", dependencies=[], handler=handler_a))
    scheduler.add_node(NodeSpec("B", dependencies=[], handler=handler_b))

    from src.governance.execution_context import ExecutionContext
    ctx = ExecutionContext.create(workflow_id="test-wf")
    executor = ContinuousExecutor(scheduler)
    result_ctx = await executor.run(ctx)

    assert result_ctx.outputs["B"] == "ok"
    assert len(result_ctx.errors) == 1
    assert result_ctx.errors[0]["node"] == "A"
