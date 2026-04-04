"""Tests for Signal dataclass and SignalDetector framework."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.proactive.signals import Signal, SignalDetector
from src.storage.events_db import EventsDB


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    return EventsDB(str(tmp_path / "test.db"))


@pytest.fixture
def detector(db):
    return SignalDetector(db)


# ── Signal dataclass ──────────────────────────────────────────────────────────

def test_signal_fields_set_correctly():
    sig = Signal(id="S1", tier="A", title="test", severity="high", data={"k": "v"})
    assert sig.id == "S1"
    assert sig.tier == "A"
    assert sig.title == "test"
    assert sig.severity == "high"
    assert sig.data == {"k": "v"}


def test_signal_detected_at_defaults_to_utc_now():
    before = datetime.now(timezone.utc)
    sig = Signal(id="S1", tier="A", title="x", severity="low", data={})
    after = datetime.now(timezone.utc)
    assert sig.detected_at.tzinfo is not None
    assert before <= sig.detected_at <= after


def test_signal_detected_at_can_be_overridden():
    ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    sig = Signal(id="S2", tier="B", title="x", severity="medium", data={}, detected_at=ts)
    assert sig.detected_at == ts


def test_signal_data_defaults_to_empty_dict():
    sig = Signal(id="S3", tier="C", title="x", severity="low")
    assert sig.data == {}


# ── detect_all ────────────────────────────────────────────────────────────────

def test_detect_all_returns_list(detector):
    result = detector.detect_all()
    assert isinstance(result, list)


def test_detect_all_returns_only_signal_instances(detector):
    result = detector.detect_all()
    for item in result:
        assert isinstance(item, Signal)


def test_detect_all_catches_individual_detector_errors(detector):
    """A single broken detector must not crash detect_all."""
    def _bad_detector():
        raise RuntimeError("boom")

    detector._detectors = [_bad_detector]
    result = detector.detect_all()
    # Should return empty list without raising
    assert result == []


def test_detect_all_still_runs_remaining_detectors_after_error(detector):
    """Detectors after a broken one must still run."""
    called = []

    def _bad():
        raise ValueError("oops")

    def _good():
        called.append(True)
        return None

    detector._detectors = [_bad, _good]
    detector.detect_all()
    assert called == [True]


# ── S1: collector failures ────────────────────────────────────────────────────

def test_s1_returns_none_when_no_error_streak(db, detector):
    now = datetime.now(timezone.utc).isoformat()
    with db._connect() as conn:
        conn.execute(
            "INSERT INTO logs (level, source, message, created_at) VALUES (?,?,?,?)",
            ("INFO", "collector", "ok", now),
        )
    result = detector._check_collector_failures()
    assert result is None


def test_s1_returns_signal_on_error_streak(db, detector):
    now = datetime.now(timezone.utc).isoformat()
    with db._connect() as conn:
        for _ in range(4):
            conn.execute(
                "INSERT INTO logs (level, source, message, created_at) VALUES (?,?,?,?)",
                ("ERROR", "collector", "fail", now),
            )
    result = detector._check_collector_failures()
    assert result is not None
    assert result.id == "S1"
    assert result.data["streak"] >= 3


# ── S3: DB size ───────────────────────────────────────────────────────────────

def test_s3_returns_none_when_db_small(detector):
    result = detector._check_db_size()
    # fresh tmp db is tiny
    assert result is None


def test_s3_returns_signal_when_db_large(detector, tmp_path):
    """Patch stat to fake a large file."""
    import os
    from unittest.mock import patch as _patch

    fake_size = (detector.db.__class__.__module__, )  # noqa
    with _patch("src.proactive.signals.Path") as MockPath:
        mock_path_instance = MagicMock()
        mock_path_instance.exists.return_value = True
        mock_path_instance.stat.return_value = MagicMock(st_size=60 * 1024 * 1024)  # 60 MB
        MockPath.return_value = mock_path_instance

        result = detector._check_db_size()

    assert result is not None
    assert result.id == "S3"
    assert result.data["size_mb"] > 50


# ── S4: governor failures ─────────────────────────────────────────────────────

def test_s4_returns_none_when_no_fail_streak(db, detector):
    now = datetime.now(timezone.utc).isoformat()
    with db._connect() as conn:
        conn.execute(
            "INSERT INTO tasks (action, status, created_at) VALUES (?,?,?)",
            ("do something", "completed", now),
        )
    result = detector._check_governor_failures()
    assert result is None


def test_s4_returns_signal_on_fail_streak(db, detector):
    now = datetime.now(timezone.utc).isoformat()
    with db._connect() as conn:
        for i in range(4):
            conn.execute(
                "INSERT INTO tasks (action, status, created_at) VALUES (?,?,?)",
                (f"task {i}", "failed", now),
            )
    result = detector._check_governor_failures()
    assert result is not None
    assert result.id == "S4"
    assert result.data["streak"] >= 3


# ── S5: project silence ───────────────────────────────────────────────────────

def test_s5_returns_none_when_no_repos(db, detector):
    result = detector._check_project_silence()
    assert result is None


def test_s5_returns_signals_for_silent_repos(db, detector):
    import json

    old_ts = "2020-01-01T00:00:00+00:00"
    with db._connect() as conn:
        conn.execute(
            "INSERT INTO events (source, category, title, metadata, occurred_at) VALUES (?,?,?,?,?)",
            ("codebase", "commit", "old commit", json.dumps({"repo": "my-repo"}), old_ts),
        )
    result = detector._check_project_silence()
    assert result is not None
    assert isinstance(result, list)
    assert any(s.id == "S5" for s in result)
    assert any("my-repo" in s.data["repo"] for s in result)


# ── S6: late-night activity ───────────────────────────────────────────────────

def test_s6_returns_none_when_no_recent_commits(db, detector):
    result = detector._check_late_night_activity()
    assert result is None


# ── S9: steal progress ────────────────────────────────────────────────────────

def test_s9_returns_none_when_no_steal_branches(detector):
    with patch("src.proactive.signals.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        result = detector._check_steal_progress()
    assert result is None


def test_s9_returns_signal_when_active_steal_branch(detector):
    def fake_run(cmd, **kwargs):
        if "--list" in cmd:
            return MagicMock(returncode=0, stdout="  steal/test-topic\n")
        # git log call
        return MagicMock(returncode=0, stdout="abc1234 some commit\n")

    with patch("src.proactive.signals.subprocess.run", side_effect=fake_run):
        result = detector._check_steal_progress()

    assert result is not None
    assert result.id == "S9"
    assert "steal/test-topic" in result.data["active_branches"]


# ── placeholder detectors ─────────────────────────────────────────────────────

@pytest.mark.parametrize("method_name", [
    "_check_repeated_patterns",
    "_check_batch_completion",
    "_check_defer_overdue",
    "_check_github_activity",
    "_check_dependency_vulns",
])
def test_placeholder_detectors_return_none(detector, method_name):
    result = getattr(detector, method_name)()
    assert result is None
