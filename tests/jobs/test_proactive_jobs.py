"""Tests for proactive job entry points."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset_engine_singleton():
    """Reset the module-level singleton between tests."""
    import src.jobs.proactive_jobs as mod
    mod._engine = None
    yield
    mod._engine = None


def test_proactive_scan_calls_engine():
    from src.jobs.proactive_jobs import proactive_scan

    db = MagicMock()
    db._connect = MagicMock()

    with patch("src.jobs.proactive_jobs.ProactiveEngine") as MockEngine:
        with patch("src.jobs.proactive_jobs._get_registry"):
            instance = MockEngine.return_value
            instance.run_scan.return_value = (2, 1)
            proactive_scan(db)
            MockEngine.assert_called_once()
            instance.run_scan.assert_called_once()


def test_proactive_scan_reuses_engine():
    """Second call should reuse the singleton engine, not create a new one."""
    from src.jobs.proactive_jobs import proactive_scan

    db = MagicMock()
    db._connect = MagicMock()

    with patch("src.jobs.proactive_jobs.ProactiveEngine") as MockEngine:
        with patch("src.jobs.proactive_jobs._get_registry"):
            instance = MockEngine.return_value
            instance.run_scan.return_value = (0, 0)
            proactive_scan(db)
            proactive_scan(db)
            # Engine should only be constructed once
            MockEngine.assert_called_once()
            # But run_scan should be called twice
            assert instance.run_scan.call_count == 2


def test_proactive_daily_digest_broadcasts():
    from src.jobs.proactive_jobs import proactive_daily_digest

    db = MagicMock()

    with (
        patch("src.jobs.proactive_jobs.DigestBuilder") as MockDigest,
        patch("src.jobs.proactive_jobs._get_registry") as mock_get_reg,
    ):
        mock_reg = MagicMock()
        mock_get_reg.return_value = mock_reg
        MockDigest.return_value.build_daily.return_value = "<b>日报</b>\ntest"
        proactive_daily_digest(db)
        mock_reg.broadcast.assert_called_once()


def test_proactive_daily_digest_skips_when_empty():
    from src.jobs.proactive_jobs import proactive_daily_digest

    db = MagicMock()

    with (
        patch("src.jobs.proactive_jobs.DigestBuilder") as MockDigest,
        patch("src.jobs.proactive_jobs._get_registry") as mock_get_reg,
    ):
        mock_reg = MagicMock()
        mock_get_reg.return_value = mock_reg
        MockDigest.return_value.build_daily.return_value = None
        proactive_daily_digest(db)
        mock_reg.broadcast.assert_not_called()


def test_proactive_weekly_digest_broadcasts():
    from src.jobs.proactive_jobs import proactive_weekly_digest

    db = MagicMock()

    with (
        patch("src.jobs.proactive_jobs.DigestBuilder") as MockDigest,
        patch("src.jobs.proactive_jobs._get_registry") as mock_get_reg,
    ):
        mock_reg = MagicMock()
        mock_get_reg.return_value = mock_reg
        MockDigest.return_value.build_weekly.return_value = "<b>周报</b>\ntest"
        proactive_weekly_digest(db)
        mock_reg.broadcast.assert_called_once()
