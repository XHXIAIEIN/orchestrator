"""Tests for P2 big module integration: structured_memory + group_orchestration wiring.

Verifies that:
1. StructuredMemoryProvider integrates into ContextEngine pipeline
2. GroupOrchestrationSupervisor integrates with Governor dispatch path
3. cross_dept signals are emitted during group orchestration rounds
4. Existing single-department behavior is NOT broken
"""
import json
import gc
import pytest
import tempfile
import os
from unittest.mock import MagicMock, patch


# ── Helper to create a temp SQLite store that doesn't leak file handles ──

def _make_store(tmp_path):
    """Create an in-memory-like store using a temp path, returning (store, db_path)."""
    from src.governance.context.structured_memory import StructuredMemoryStore, _pools, _pool_lock
    db_path = os.path.join(str(tmp_path), "test_memory.db")
    store = StructuredMemoryStore(db_path=db_path)
    return store, db_path


def _cleanup_store(db_path):
    """Close pool connections to release SQLite file locks on Windows."""
    from src.governance.context.structured_memory import _pools, _pool_lock
    with _pool_lock:
        pool = _pools.pop(db_path, None)
        if pool and pool._conn:
            try:
                pool._conn.close()
            except Exception:
                pass
    gc.collect()


# ── structured_memory provider tests ──────────────────────────────


class TestStructuredMemoryProvider:
    """StructuredMemoryProvider integration into ContextEngine."""

    def test_provider_returns_hot_memories(self, tmp_path):
        """Hot-tier memories appear in provider output."""
        from src.governance.context.structured_memory import (
            StructuredMemoryStore, Dimension, ActivityMemory,
        )
        from src.governance.context.providers import StructuredMemoryProvider
        from src.governance.context.engine import TaskContext

        store, db_path = _make_store(tmp_path)
        try:
            store.add(Dimension.ACTIVITY, ActivityMemory(
                summary="User prefers direct execution without asking",
                detail="Observed across 10+ sessions",
                confidence=0.95,
            ))

            provider = StructuredMemoryProvider(store=store)
            ctx = TaskContext(department="engineering", task_text="refactor the module")
            chunks = provider.provide(ctx)

            hot_chunks = [c for c in chunks if "hot" in c.source]
            assert len(hot_chunks) >= 1
            assert "direct execution" in hot_chunks[0].content
        finally:
            _cleanup_store(db_path)

    def test_provider_returns_relevant_memories_for_query(self, tmp_path):
        """Relevant memories appear in provider output (via hot or search tier)."""
        from src.governance.context.structured_memory import (
            StructuredMemoryStore, Dimension, ExperienceMemory,
        )
        from src.governance.context.providers import StructuredMemoryProvider
        from src.governance.context.engine import TaskContext

        store, db_path = _make_store(tmp_path)
        try:
            store.add(Dimension.EXPERIENCE, ExperienceMemory(
                situation="Docker container OOM on collector",
                reasoning="Memory limit too low for image processing",
                action="Increased memory limit to 4GB",
                outcome="Resolved",
                confidence=0.9,
            ))

            provider = StructuredMemoryProvider(store=store)
            ctx = TaskContext(
                department="operations",
                task_text="fix Docker container OOM issue",
            )
            chunks = provider.provide(ctx)

            # The memory should appear in either hot or search tier
            assert len(chunks) >= 1
            all_content = " ".join(c.content for c in chunks)
            assert "Docker" in all_content or "OOM" in all_content
        finally:
            _cleanup_store(db_path)

    def test_provider_returns_empty_on_no_store(self):
        """Provider gracefully returns empty when store is unavailable."""
        from src.governance.context.providers import StructuredMemoryProvider
        from src.governance.context.engine import TaskContext

        provider = StructuredMemoryProvider(store=None)
        provider._store = None
        with patch(
            "src.governance.context.providers.StructuredMemoryProvider._get_store",
            return_value=None,
        ):
            ctx = TaskContext(department="engineering", task_text="test")
            chunks = provider.provide(ctx)
            assert chunks == []

    def test_provider_registered_in_default_engine(self):
        """StructuredMemoryProvider is registered in ContextEngine.default()."""
        from src.governance.context.engine import ContextEngine
        engine = ContextEngine.default()
        provider_names = [p.name for p in engine._providers]
        assert "structured_memory" in provider_names

    def test_hot_priority_lower_than_learnings(self, tmp_path):
        """Structured memory hot chunks have priority > learnings (5) but < guidelines (30)."""
        from src.governance.context.structured_memory import (
            StructuredMemoryStore, Dimension, IdentityMemory,
        )
        from src.governance.context.providers import StructuredMemoryProvider
        from src.governance.context.engine import TaskContext

        store, db_path = _make_store(tmp_path)
        try:
            store.add(Dimension.IDENTITY, IdentityMemory(
                fact="I am the orchestrator AI butler",
                confidence=0.95,
            ))

            provider = StructuredMemoryProvider(store=store)
            ctx = TaskContext(department="engineering", task_text="test")
            chunks = provider.provide(ctx)

            hot_chunks = [c for c in chunks if "hot" in c.source]
            for chunk in hot_chunks:
                assert 5 < chunk.priority < 30, (
                    f"Hot memory priority {chunk.priority} should be between 5 and 30"
                )
        finally:
            _cleanup_store(db_path)


# ── group_orchestration + governor integration tests ─────────────


class TestGroupOrchestrationIntegration:
    """GroupOrchestrationSupervisor wired through Governor dispatch path."""

    def test_needs_group_orchestration_multi_dept(self):
        """Dispatcher detects explicit multi-department specs."""
        from src.governance.dispatcher import TaskDispatcher

        dispatcher = TaskDispatcher.__new__(TaskDispatcher)
        # Explicit departments list
        spec = {"departments": ["engineering", "quality"], "problem": "test"}
        assert dispatcher.needs_group_orchestration(spec) is True

    def test_needs_group_orchestration_single_dept(self):
        """Single-department specs don't trigger group orchestration."""
        from src.governance.dispatcher import TaskDispatcher

        dispatcher = TaskDispatcher.__new__(TaskDispatcher)
        spec = {"department": "engineering", "problem": "fix a bug"}
        assert dispatcher.needs_group_orchestration(spec) is False

    def test_needs_group_orchestration_already_in_round(self):
        """Tasks already in orchestration round don't recurse."""
        from src.governance.dispatcher import TaskDispatcher

        dispatcher = TaskDispatcher.__new__(TaskDispatcher)
        spec = {
            "departments": ["engineering", "quality"],
            "orchestration_round": True,
        }
        assert dispatcher.needs_group_orchestration(spec) is False

    def test_needs_group_orchestration_complex_cross_dept(self):
        """COMPLEX tasks with cross-dept signals trigger group orchestration."""
        from src.governance.dispatcher import TaskDispatcher

        dispatcher = TaskDispatcher.__new__(TaskDispatcher)
        spec = {
            "department": "engineering",
            "complexity": "COMPLEX",
            "problem": "need cross-department security review of auth module",
        }
        assert dispatcher.needs_group_orchestration(spec) is True

    def test_needs_group_orchestration_complex_no_signals(self):
        """COMPLEX tasks without cross-dept signals don't trigger group orchestration."""
        from src.governance.dispatcher import TaskDispatcher

        dispatcher = TaskDispatcher.__new__(TaskDispatcher)
        spec = {
            "department": "engineering",
            "complexity": "COMPLEX",
            "problem": "refactor the data layer",
        }
        assert dispatcher.needs_group_orchestration(spec) is False

    def test_needs_group_orchestration_explicit_flag(self):
        """Explicit multi_department flag triggers group orchestration."""
        from src.governance.dispatcher import TaskDispatcher

        dispatcher = TaskDispatcher.__new__(TaskDispatcher)
        spec = {"department": "engineering", "multi_department": True}
        assert dispatcher.needs_group_orchestration(spec) is True

    def test_governor_run_group_exists(self):
        """Governor.run_group() method exists and is callable."""
        from src.governance.governor import Governor
        assert hasattr(Governor, "run_group")
        assert callable(getattr(Governor, "run_group"))


# ── cross_dept signal integration tests ──────────────────────────


class TestCrossDeptSignalIntegration:
    """cross_dept.py signals wired into GroupOrchestrationSupervisor."""

    def test_signal_bus_initialized(self):
        """GroupOrchestrationSupervisor initializes a SignalBus."""
        from src.governance.group_orchestration import GroupOrchestrationSupervisor
        supervisor = GroupOrchestrationSupervisor(max_rounds=2)
        assert supervisor._signal_bus is not None

    def test_signal_bus_custom_injection(self):
        """Custom signal bus can be injected."""
        from src.governance.group_orchestration import GroupOrchestrationSupervisor
        mock_bus = MagicMock()
        supervisor = GroupOrchestrationSupervisor(max_rounds=2, signal_bus=mock_bus)
        assert supervisor._signal_bus is mock_bus

    def test_emit_signals_on_collaboration_needs(self):
        """Signals are emitted when round output contains collaboration patterns."""
        from src.governance.group_orchestration import (
            GroupOrchestrationSupervisor, RoundResult,
        )

        mock_bus = MagicMock()
        mock_bus.send = MagicMock(return_value=(True, "sent"))
        supervisor = GroupOrchestrationSupervisor(max_rounds=2, signal_bus=mock_bus)

        round_result = RoundResult(
            round_num=1,
            department_results={
                "engineering": {
                    "status": "success",
                    "output": "Done. But this 需要安全审查 before merge.",
                    "task_id": 42,
                },
            },
        )

        # Emit signals
        supervisor._emit_cross_dept_signals(round_result, {"action": "test"})

        # Should have called send at least once (security detected)
        assert mock_bus.send.called

    def test_emit_signals_on_failure(self):
        """Failure signals are emitted when department output indicates failure."""
        from src.governance.group_orchestration import (
            GroupOrchestrationSupervisor, RoundResult,
        )

        mock_bus = MagicMock()
        mock_bus.send = MagicMock(return_value=(True, "sent"))
        supervisor = GroupOrchestrationSupervisor(max_rounds=2, signal_bus=mock_bus)

        round_result = RoundResult(
            round_num=1,
            department_results={
                "operations": {
                    "status": "failed",
                    "output": "执行失败: Docker container could not start",
                    "task_id": 99,
                },
            },
        )

        supervisor._emit_cross_dept_signals(round_result, {"action": "deploy"})
        assert mock_bus.send.called

    def test_no_signals_on_clean_success(self):
        """No signals emitted when round succeeds cleanly without collaboration needs."""
        from src.governance.group_orchestration import (
            GroupOrchestrationSupervisor, RoundResult,
        )

        mock_bus = MagicMock()
        mock_bus.send = MagicMock(return_value=(True, "sent"))
        supervisor = GroupOrchestrationSupervisor(max_rounds=2, signal_bus=mock_bus)

        round_result = RoundResult(
            round_num=1,
            department_results={
                "engineering": {
                    "status": "success",
                    "output": "Refactored the module successfully. All tests pass.",
                    "task_id": 10,
                },
            },
        )

        supervisor._emit_cross_dept_signals(round_result, {"action": "refactor"})
        assert not mock_bus.send.called


# ── Preservation tests: existing behavior unchanged ──────────────


class TestExistingBehaviorPreserved:
    """Verify that new integrations don't break existing single-department flow."""

    def test_single_dept_dispatch_unchanged(self):
        """Single department spec doesn't get routed to group orchestration."""
        from src.governance.dispatcher import TaskDispatcher

        dispatcher = TaskDispatcher.__new__(TaskDispatcher)
        spec = {
            "department": "engineering",
            "problem": "fix the login bug",
            "summary": "Login fix",
        }
        assert dispatcher.needs_group_orchestration(spec) is False

    def test_context_engine_still_has_core_providers(self):
        """Core providers (system_prompt, guidelines, memory, history) still registered."""
        from src.governance.context.engine import ContextEngine
        engine = ContextEngine.default()
        provider_names = [p.name for p in engine._providers]

        for expected in ["system_prompt", "guidelines", "memory", "history"]:
            assert expected in provider_names, f"Core provider '{expected}' missing from engine"

    def test_group_orchestration_supervisor_evaluate_terminates(self):
        """Supervisor evaluate() terminates on all-success with no collab needs."""
        from src.governance.group_orchestration import (
            GroupOrchestrationSupervisor, RoundResult,
        )
        supervisor = GroupOrchestrationSupervisor(max_rounds=3)
        result = RoundResult(
            round_num=1,
            department_results={
                "engineering": {"status": "success", "output": "Done cleanly.", "task_id": 1},
            },
        )
        decision = supervisor.evaluate({}, [result])
        assert decision.skip_supervisor is True
        assert decision.targets == []
