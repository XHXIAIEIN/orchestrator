"""
Test: Governor async execution path fix.

Verifies that _run_agent_session (an async method) is correctly wrapped
for anyio.run() — it must be passed as a callable, NOT a coroutine object.

Bug: governor.py was calling self._run_agent_session() (producing a coroutine)
then passing that coroutine to anyio.run(), which expects a zero-arg async callable.
Error: 'coroutine' object is not callable.

Fix: wrap in `async def _agent_coro(): return await self._run_agent_session(...)`
"""
import threading
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import anyio


def test_anyio_run_rejects_coroutine_object():
    """Prove the original bug: anyio.run(coroutine_obj) raises TypeError."""
    async def my_async_fn():
        return "ok"

    coro = my_async_fn()  # This creates a coroutine OBJECT
    with pytest.raises(TypeError, match="coroutine"):
        anyio.run(coro)
    coro.close()  # cleanup


def test_anyio_run_accepts_async_callable():
    """Prove the fix: anyio.run(async_fn) works with a callable."""
    async def my_async_fn():
        return "ok"

    result = anyio.run(my_async_fn)  # Pass the function, not a call
    assert result == "ok"


def test_wrapped_closure_pattern():
    """Verify the exact pattern used in the governor fix."""
    class FakeGovernor:
        async def _run_agent_session(self, task_id, prompt):
            return f"result-{task_id}"

    gov = FakeGovernor()
    task_id = 42
    prompt = "test prompt"

    # The FIX pattern: wrap in closure
    async def _agent_coro():
        return await gov._run_agent_session(task_id, prompt)

    result = anyio.run(_agent_coro)
    assert result == "result-42"


def test_wrapped_closure_in_thread():
    """Verify the pattern works from a background thread (how governor actually runs)."""
    class FakeGovernor:
        async def _run_agent_session(self, task_id):
            return f"done-{task_id}"

    gov = FakeGovernor()
    results = {}

    def thread_fn():
        async def _agent_coro():
            return await gov._run_agent_session(99)

        results["output"] = anyio.run(_agent_coro)

    t = threading.Thread(target=thread_fn)
    t.start()
    t.join(timeout=5)
    assert results.get("output") == "done-99"


def test_from_thread_run_in_async_context():
    """Verify anyio.from_thread.run works when called from a worker thread inside an event loop."""
    class FakeGovernor:
        async def _run_agent_session(self, task_id):
            return f"async-{task_id}"

    gov = FakeGovernor()

    async def main():
        async def _agent_coro():
            return await gov._run_agent_session(77)

        # Simulate: we're in async context, dispatch to thread, then call back
        result = await anyio.to_thread.run_sync(
            lambda: anyio.from_thread.run(_agent_coro)
        )
        assert result == "async-77"

    anyio.run(main)


def test_governor_execute_task_calls_agent_correctly():
    """Integration-style test: mock Agent SDK, verify governor doesn't produce 'coroutine not callable'."""
    from src.storage.events_db import EventsDB
    from src.governance.safety.verify_gate import GateResult, GateRecord
    import tempfile, os

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        db = EventsDB(db_path)

        # Create a task
        task_id = db.create_task(
            action="test async fix",
            reason="verify no coroutine error",
            priority="medium",
            spec={"department": "engineering", "problem": "test"},
            source="auto",
        )
        db.update_task(task_id, status="running",
                       started_at="2026-01-01T00:00:00+00:00")

        from src.governance.governor import Governor

        gov = Governor(db=db)

        # Mock the async _run_agent_session to return immediately
        async def fake_agent_session(*args, **kwargs):
            return "DONE: test passed"

        # Mock verify gates to pass (real git diff has 100+ files in dev env)
        def fake_run_gates(department, task_id, task_cwd, extra_gates=None):
            return GateRecord(
                task_id=task_id, department=department,
                gates=[], all_passed=True,
            )

        with patch.object(gov.executor, '_run_agent_session', side_effect=fake_agent_session), \
             patch('src.governance.review.run_gates', side_effect=fake_run_gates):
            # This should NOT raise 'coroutine object is not callable'
            result = gov.execute_task(task_id)

        assert result is not None
        assert result["status"] == "done"
        assert "test passed" in result.get("output", "")
