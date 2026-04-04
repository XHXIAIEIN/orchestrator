"""Tests for evolution actions — execute + rollback."""
import pytest
from unittest.mock import MagicMock, patch
from src.evolution.actions import (
    ActionResult, MemoryHygieneAction, CollectorHealAction,
    StealPatrolAction, ActionStatus,
)


class TestMemoryHygieneAction:
    def test_execute_calls_experience_cull(self):
        db = MagicMock()
        action = MemoryHygieneAction()
        with patch("src.governance.learning.experience_cull.run_cull") as mock_cull:
            mock_cull.return_value = MagicMock(
                retired=[{"id": 1}], at_risk=[], promoted=[], total_active=40,
                format=MagicMock(return_value="1 retired"),
            )
            result = action.execute(db, signal_data={"size_mb": 55})
        assert result.status == ActionStatus.SUCCESS
        assert result.detail["retired_count"] == 1
        mock_cull.assert_called_once_with(db)

    def test_rollback_is_noop(self):
        action = MemoryHygieneAction()
        action.rollback(MagicMock(), {})


class TestCollectorHealAction:
    def test_execute_restarts_collector(self):
        db = MagicMock()
        action = CollectorHealAction()
        with patch("src.jobs.collectors.run_collectors") as mock_collect:
            mock_collect.return_value = None
            result = action.execute(db, signal_data={"collector": "git", "error": "path not found"})
        assert result.status == ActionStatus.SUCCESS
        mock_collect.assert_called_once()

    def test_execute_handles_failure(self):
        db = MagicMock()
        action = CollectorHealAction()
        with patch("src.jobs.collectors.run_collectors", side_effect=Exception("boom")):
            result = action.execute(db, signal_data={"collector": "git"})
        assert result.status == ActionStatus.FAILED
        assert "boom" in result.detail.get("error", "")


class TestStealPatrolAction:
    def test_execute_returns_skipped(self):
        db = MagicMock()
        action = StealPatrolAction()
        result = action.execute(db, signal_data={})
        assert result.status == ActionStatus.SKIPPED


class TestActionResult:
    def test_is_success(self):
        r = ActionResult(status=ActionStatus.SUCCESS, detail={"msg": "ok"})
        assert r.is_success

    def test_is_not_success_on_fail(self):
        r = ActionResult(status=ActionStatus.FAILED, detail={"error": "bad"})
        assert not r.is_success
