import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from src.governance.audit.wal import (
    WALSignal, scan_for_signals, write_wal_entry, load_session_state,
    SIGNAL_TYPES,
)


def test_scan_detects_correction():
    signals = scan_for_signals("Actually, we should use PostgreSQL not MySQL")
    assert any(s.signal_type == "correction" for s in signals)


def test_scan_detects_decision():
    signals = scan_for_signals("Let's go with option A, use React for the frontend")
    assert any(s.signal_type == "decision" for s in signals)


def test_scan_detects_preference():
    signals = scan_for_signals("I prefer 2-space indentation and single quotes")
    assert any(s.signal_type == "preference" for s in signals)


def test_scan_detects_precise_value():
    signals = scan_for_signals("The API key is sk-abc123 and the deadline is 2026-04-15")
    assert any(s.signal_type == "precise_value" for s in signals)


def test_scan_returns_empty_for_generic():
    signals = scan_for_signals("ok sounds good")
    assert len(signals) == 0


def test_write_wal_entry(tmp_path):
    state_path = tmp_path / "session-state.md"
    state_path.write_text(
        "# Session State (WAL)\n\n"
        "## Active Decisions\n\n"
        "## Active Tasks\n\n"
        "## Critical Context\n\n"
    )
    write_wal_entry(str(state_path), section="Active Decisions", content="Use PostgreSQL for the new service")
    text = state_path.read_text()
    assert "PostgreSQL" in text
    assert "Active Decisions" in text


def test_load_session_state(tmp_path):
    state_path = tmp_path / "session-state.md"
    state_path.write_text(
        "# Session State (WAL)\n\n"
        "## Active Decisions\n\n"
        "- Use React\n\n"
        "## Active Tasks\n\n"
        "- Build login page\n\n"
        "## Critical Context\n\n"
        "- Deadline: April 15\n"
    )
    state = load_session_state(str(state_path))
    assert "Use React" in state["Active Decisions"]
    assert "Build login page" in state["Active Tasks"]
    assert "April 15" in state["Critical Context"]
