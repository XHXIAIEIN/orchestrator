import pytest
from unittest.mock import MagicMock
from src.collectors.reputation import ReputationTracker


class TestReputation:
    def setup_method(self):
        self.db = MagicMock()
        self.db.execute_sql = MagicMock(return_value=[])
        self.tracker = ReputationTracker(self.db)

    def test_update_success(self):
        self.tracker.update("git", event_count=15)
        rep = self.tracker._cache["git"]
        assert rep["total_runs"] == 1
        assert rep["successful_runs"] == 1
        assert rep["streak"] == 1

    def test_update_failure(self):
        self.tracker.update("steam", event_count=-1, error="path not found")
        rep = self.tracker._cache["steam"]
        assert rep["streak"] == -1
        assert rep["last_failure_reason"] == "path not found"

    def test_health_score_good(self):
        for _ in range(10):
            self.tracker.update("git", event_count=20)
        rep = self.tracker._cache["git"]
        assert rep["health_score"] > 0.8

    def test_should_skip_after_5_failures(self):
        for _ in range(5):
            self.tracker.update("steam", event_count=-1, error="broken")
        skip, reason = self.tracker.should_skip("steam")
        assert skip is True
        assert "circuit" in reason.lower() or "consecutive" in reason.lower()

    def test_should_not_skip_healthy(self):
        self.tracker.update("git", event_count=10)
        skip, _ = self.tracker.should_skip("git")
        assert skip is False
