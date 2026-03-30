"""Tests for src/exam/runner.py — all mock urllib, no real API calls."""
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.exam.runner import ExamRunner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_urlopen(response_data: dict):
    """Return a context-manager mock that yields a fake HTTP response."""
    encoded = json.dumps(response_data).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.read.return_value = encoded
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_cm = MagicMock(return_value=mock_resp)
    return mock_cm


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_start_returns_batch(tmp_path: Path):
    """start() hits /start, stores examId/hash, saves start.json, returns batch."""
    fake_response = {
        "examId": "exam-001",
        "hash": "abc123",
        "totalQuestions": 10,
        "totalBatches": 2,
        "batch": [{"questionId": "q1", "text": "What is 1+1?"}],
    }

    runner = ExamRunner(runs_dir=tmp_path)

    with patch("urllib.request.urlopen", _mock_urlopen(fake_response)):
        batch = runner.start()

    assert runner.exam_id == "exam-001"
    assert runner.hash == "abc123"
    assert batch == [{"questionId": "q1", "text": "What is 1+1?"}]

    saved = json.loads((tmp_path / "exam-001_start.json").read_text(encoding="utf-8"))
    assert saved["examId"] == "exam-001"
    assert saved["hash"] == "abc123"


def test_submit_returns_next_batch(tmp_path: Path):
    """submit() sends answers, updates hash, saves batch file, returns nextBatch."""
    start_response = {
        "examId": "exam-002",
        "hash": "hash-v1",
        "totalQuestions": 4,
        "totalBatches": 2,
        "batch": [{"questionId": "q1", "text": "Q1"}],
    }
    submit_response = {
        "hash": "hash-v2",
        "examComplete": False,
        "progress": {"current": 2, "total": 4, "percentage": 50},
        "nextBatch": [{"questionId": "q3", "text": "Q3"}],
    }

    runner = ExamRunner(runs_dir=tmp_path)

    with patch("urllib.request.urlopen", _mock_urlopen(start_response)):
        runner.start()

    with patch("urllib.request.urlopen", _mock_urlopen(submit_response)):
        next_batch = runner.submit([{"questionId": "q1", "answer": "2"}])

    assert runner.hash == "hash-v2"
    assert next_batch == [{"questionId": "q3", "text": "Q3"}]

    saved = json.loads((tmp_path / "exam-002_batch1.json").read_text(encoding="utf-8"))
    assert saved["submitted"] == [{"questionId": "q1", "answer": "2"}]
    assert saved["response"]["hash"] == "hash-v2"


def test_submit_final_returns_none(tmp_path: Path):
    """submit() with examComplete=True stores report and saves final.json, returns None."""
    start_response = {
        "examId": "exam-003",
        "hash": "hash-a",
        "totalQuestions": 2,
        "totalBatches": 1,
        "batch": [{"questionId": "q1", "text": "Q1"}],
    }
    final_response = {
        "hash": "hash-b",
        "examComplete": True,
        "grade": "A",
        "percentile": 95,
        "progress": {"current": 2, "total": 2, "percentage": 100},
    }

    runner = ExamRunner(runs_dir=tmp_path)

    with patch("urllib.request.urlopen", _mock_urlopen(start_response)):
        runner.start()

    with patch("urllib.request.urlopen", _mock_urlopen(final_response)):
        result = runner.submit([{"questionId": "q1", "answer": "42"}])

    assert result is None
    assert runner.report is not None
    assert runner.report["grade"] == "A"
    assert runner.report["percentile"] == 95

    saved = json.loads((tmp_path / "exam-003_final.json").read_text(encoding="utf-8"))
    assert saved["examComplete"] is True
    assert saved["grade"] == "A"
