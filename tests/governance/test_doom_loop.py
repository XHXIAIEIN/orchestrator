"""Tests for doom loop detection."""
from src.governance.safety.doom_loop import check_doom_loop, DoomLoopResult


def _make_turn(tool="Read", input_preview="file.py", error=None):
    return {
        "event_type": "agent_turn",
        "data": {
            "tools": [{"tool": tool, "input_preview": input_preview}],
            "error": error,
        },
    }


def test_no_events_no_doom():
    result = check_doom_loop([])
    assert not result.triggered


def test_repeated_tool_triggers():
    events = [_make_turn("Edit", "file_path: src/main.py") for _ in range(6)]
    result = check_doom_loop(events)
    assert result.triggered
    assert "repeated" in result.reason.lower() or "重复" in result.reason


def test_same_file_edited_triggers():
    events = [_make_turn("Edit", "file_path: src/app.py") for _ in range(5)]
    result = check_doom_loop(events)
    assert result.triggered


def test_consecutive_errors_trigger():
    events = [_make_turn(error="timeout") for _ in range(4)]
    result = check_doom_loop(events)
    assert result.triggered
    assert "error" in result.reason.lower() or "错误" in result.reason


def test_mixed_events_no_trigger():
    events = [
        _make_turn("Read", "file1.py"),
        _make_turn("Edit", "file2.py"),
        _make_turn("Grep", "pattern"),
        _make_turn("Read", "file3.py"),
    ]
    result = check_doom_loop(events)
    assert not result.triggered
