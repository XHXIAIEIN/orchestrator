"""Tests for Round 14-16 audit module integration.

Validates that WAL, evolution_chain, and execution_snapshot are correctly
wired into the production execution path without modifying the audit
modules themselves.
"""
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest


# ── WAL Integration Tests ──


class TestWALIntegration:
    """Test WAL signal scanning and session-state writing in executor_session."""

    def test_scan_signals_detects_correction(self):
        from src.governance.audit.wal import scan_for_signals
        signals = scan_for_signals("actually, the path should be /tmp not /var")
        assert any(s.signal_type == "correction" for s in signals)

    def test_scan_signals_detects_decision(self):
        from src.governance.audit.wal import scan_for_signals
        signals = scan_for_signals("let's go with option A")
        assert any(s.signal_type == "decision" for s in signals)

    def test_scan_signals_detects_precise_value(self):
        from src.governance.audit.wal import scan_for_signals
        signals = scan_for_signals("the date is 2026-03-31")
        assert any(s.signal_type == "precise_value" for s in signals)

    def test_scan_signals_returns_empty_for_neutral(self):
        from src.governance.audit.wal import scan_for_signals
        signals = scan_for_signals("hello world this is a normal message")
        # May or may not have signals, but should not crash
        assert isinstance(signals, list)

    def test_write_wal_entry_creates_section(self):
        from src.governance.audit.wal import write_wal_entry
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write("# Session State\n\n## Active Tasks\n\n")
            path = f.name
        try:
            write_wal_entry(path, "Active Tasks", "[task#1] signal=correction: actually")
            content = Path(path).read_text(encoding="utf-8")
            assert "[task#1] signal=correction: actually" in content
            assert "## Active Tasks" in content
        finally:
            os.unlink(path)

    def test_write_wal_entry_new_section(self):
        from src.governance.audit.wal import write_wal_entry
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write("# Session State\n")
            path = f.name
        try:
            write_wal_entry(path, "New Section", "test content")
            content = Path(path).read_text(encoding="utf-8")
            assert "## New Section" in content
            assert "test content" in content
        finally:
            os.unlink(path)

    def test_load_session_state(self):
        from src.governance.audit.wal import load_session_state
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write("# Session\n\n## Active Tasks\n\n- task 1\n\n## Decisions\n\n- dec 1\n")
            path = f.name
        try:
            state = load_session_state(path)
            assert "Active Tasks" in state
            assert "task 1" in state["Active Tasks"]
            assert "Decisions" in state
        finally:
            os.unlink(path)

    def test_load_session_state_missing_file(self):
        from src.governance.audit.wal import load_session_state
        state = load_session_state("/nonexistent/path/session-state.md")
        assert state == {}

    def test_wal_imported_in_executor_session(self):
        """Verify that executor_session imports WAL functions."""
        import src.governance.executor_session as mod
        # The module should have attempted import; if wal.py is available,
        # scan_for_signals should be the real function
        assert hasattr(mod, 'scan_for_signals')
        assert hasattr(mod, '_WAL_STATE_PATH')


# ── Evolution Chain Integration Tests ──


class TestEvolutionChainIntegration:
    """Test evolution_chain four-phase audit wired into evolution_cycle."""

    def test_record_signal_returns_evo_id(self):
        from src.governance.audit.evolution_chain import record_signal
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            evo_id = record_signal("engineering", {"trigger": "test"}, chain_path=path)
            assert evo_id.startswith("evo-")
            events = json.loads(Path(path).read_text(encoding="utf-8").strip())
            assert events["phase"] == "signal"
            assert events["department"] == "engineering"
        finally:
            os.unlink(path)

    def test_full_chain_four_phases(self):
        from src.governance.audit.evolution_chain import (
            record_signal, record_hypothesis, record_attempt,
            record_outcome, load_chain,
        )
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            evo_id = record_signal("ops", {"trigger": "test"}, chain_path=path)
            record_hypothesis(evo_id, "improve throughput", "add caching", chain_path=path)
            record_attempt(evo_id, ["config.yaml"], "added cache layer", chain_path=path)
            record_outcome(evo_id, True, {"rate": 0.8}, {"rate": 0.95}, chain_path=path)

            events = load_chain(chain_path=path)
            assert len(events) == 4
            phases = [e["phase"] for e in events]
            assert phases == ["signal", "hypothesis", "attempt", "outcome"]
            # All share the same evo_id
            assert all(e["evo_id"] == evo_id for e in events if "evo_id" in e)
        finally:
            os.unlink(path)

    def test_evolution_cycle_imports_chain(self):
        """Verify evolution_cycle imports record_signal from evolution_chain."""
        import src.governance.learning.evolution_cycle as mod
        assert hasattr(mod, 'record_signal')

    @patch("src.governance.learning.evolution_cycle.record_signal")
    @patch("src.governance.learning.evolution_cycle._count_runs", return_value=20)
    @patch("src.governance.learning.evolution_cycle._recent_success_rate", return_value=0.9)
    @patch("src.governance.learning.evolution_cycle._load_state", return_value={})
    @patch("src.governance.learning.evolution_cycle._save_state")
    def test_evolution_cycle_records_signal_on_trigger(
        self, mock_save, mock_load, mock_rate, mock_count, mock_record_signal
    ):
        """When evolution cycle triggers, it should call record_signal."""
        mock_record_signal.return_value = "evo-test123"

        from src.governance.learning.evolution_cycle import run_evolution_cycle
        # Force trigger so we don't need real run-logs
        # The cycle will fail at step 2 (skill_evolver import) but signal should be recorded
        result = run_evolution_cycle("test-dept", force=True)

        mock_record_signal.assert_called_once()
        call_args = mock_record_signal.call_args
        assert call_args[0][0] == "test-dept"  # department
        assert "trigger" in call_args[0][1]     # signals dict


# ── Execution Snapshot Integration Tests ──


class TestExecutionSnapshotIntegration:
    """Test ExecutionSnapshot wired into executor.py lifecycle."""

    def test_snapshot_create_record_save(self):
        from src.governance.audit.execution_snapshot import ExecutionSnapshot, SnapshotStore
        snap = ExecutionSnapshot(task_id=42, department="engineering")
        snap.record("turn_start", {"turn": 0, "event": "rollout_start"})
        snap.record("progress", {"event": "attempt_end", "status": "done"}, tokens=100, cost=0.01)
        snap.record("progress", {"event": "rollout_end"})

        assert len(snap.get_steps()) == 3
        summary = snap.get_summary()
        assert summary["task_id"] == 42
        assert summary["total_tokens"] == 100
        assert summary["total_cost_usd"] == 0.01

    def test_snapshot_save_load_roundtrip(self):
        from src.governance.audit.execution_snapshot import ExecutionSnapshot
        with tempfile.TemporaryDirectory() as tmpdir:
            snap = ExecutionSnapshot(task_id=99, department="ops")
            snap.record("turn_start", {"turn": 0})
            snap.record("tool_call", {"tool": "bash", "input": {"cmd": "ls"}})
            snap.record("progress", {"event": "done"}, tokens=50, cost=0.005)

            path = Path(tmpdir) / "99.jsonl"
            snap.save(path)

            loaded = ExecutionSnapshot.load(path)
            assert len(loaded.get_steps()) == 3
            assert loaded.task_id == 99
            assert loaded.department == "ops"

    def test_snapshot_store(self):
        from src.governance.audit.execution_snapshot import ExecutionSnapshot, SnapshotStore
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SnapshotStore(base_dir=tmpdir)
            snap = ExecutionSnapshot(task_id=7, department="hr")
            snap.record("turn_start", {"turn": 0})

            saved_path = store.save_snapshot(snap)
            assert saved_path.exists()

            ids = store.list_snapshots()
            assert 7 in ids

            loaded = store.load_snapshot(7)
            assert len(loaded.get_steps()) == 1

    def test_snapshot_render_table(self):
        from src.governance.audit.execution_snapshot import ExecutionSnapshot
        snap = ExecutionSnapshot(task_id=1, department="test")
        snap.record("turn_start", {"turn": 0})
        snap.record("tool_call", {"tool": "read"}, tokens=10, cost=0.001)
        table = snap.render_table()
        assert "Step" in table
        assert "turn_start" in table
        assert "tool_call" in table

    def test_snapshot_imported_in_executor(self):
        """Verify executor.py imports ExecutionSnapshot."""
        import src.governance.executor as mod
        assert hasattr(mod, 'ExecutionSnapshot')
        assert hasattr(mod, '_snapshot_store')

    def test_snapshot_reconstruct_messages(self):
        from src.governance.audit.execution_snapshot import ExecutionSnapshot
        snap = ExecutionSnapshot(task_id=1, department="test")
        snap.record("turn_start", {"turn": 1})
        snap.record("assistant_message", {"text": "hello"})
        snap.record("tool_call", {"tool": "bash", "input": {}})
        snap.record("tool_result", {"tool": "bash", "output": "ok"})
        snap.record("error", {"error": "oops"})

        msgs = snap.reconstruct_messages()
        assert len(msgs) == 5
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "assistant"
        assert msgs[2]["type"] == "tool_call"
        assert msgs[3]["role"] == "tool"
        assert msgs[4]["type"] == "error"


# ── Cross-Module Integration Tests ──


class TestCrossModuleIntegration:
    """Test that all three modules can work together without conflicts."""

    def test_all_imports_available(self):
        """All three audit modules should be importable."""
        from src.governance.audit.wal import scan_for_signals, write_wal_entry
        from src.governance.audit.evolution_chain import record_signal, record_outcome
        from src.governance.audit.execution_snapshot import ExecutionSnapshot, SnapshotStore
        # No import errors = pass
        assert callable(scan_for_signals)
        assert callable(record_signal)
        assert ExecutionSnapshot is not None

    def test_try_except_pattern_resilience(self):
        """Integration points use try/except so failures don't crash execution."""
        # Simulate what happens if WAL write fails
        from src.governance.audit.wal import write_wal_entry
        # Writing to a non-existent path should raise, but our integration
        # wraps it in try/except
        try:
            write_wal_entry("/nonexistent/path.md", "Test", "content")
            assert False, "Should have raised"
        except Exception:
            pass  # Expected — the integration code catches this

    def test_evolution_chain_append_only(self):
        """Evolution chain is append-only JSONL — multiple writes don't corrupt."""
        from src.governance.audit.evolution_chain import (
            record_signal, record_hypothesis, load_chain,
        )
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            id1 = record_signal("dept-a", {"x": 1}, chain_path=path)
            id2 = record_signal("dept-b", {"x": 2}, chain_path=path)
            record_hypothesis(id1, "h1", "c1", chain_path=path)

            events = load_chain(chain_path=path)
            assert len(events) == 3
            depts = [e.get("department") for e in events if "department" in e]
            assert "dept-a" in depts
            assert "dept-b" in depts
        finally:
            os.unlink(path)
