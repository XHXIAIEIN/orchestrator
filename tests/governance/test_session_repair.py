"""Tests for Session Repair."""
import json

from src.governance.session_repair import SessionRepairer, RepairReport


def _make_event(event_type, data=None):
    return {"event_type": event_type, "data": data or {}}


def test_clean_history():
    repairer = SessionRepairer()
    events = [
        _make_event("agent_turn", {
            "text": ["hello"],
            "tools": ["Bash"],
            "tools_detail": [{"id": "tu_001", "tool": "Bash"}],
        }),
        _make_event("tool_result", {"tool_use_id": "tu_001", "output": "ok"}),
        _make_event("agent_turn", {"text": ["done"], "tools": []}),
    ]
    report = repairer.validate(events)
    assert report.clean


def test_detect_empty_messages():
    repairer = SessionRepairer()
    events = [
        _make_event("agent_turn", {"text": [], "tools": []}),
        _make_event("agent_turn", {"text": ["ok"], "tools": []}),
    ]
    report = repairer.validate(events)
    assert report.empty_messages == 1


def test_detect_consecutive_roles():
    repairer = SessionRepairer()
    events = [
        _make_event("agent_turn", {"text": ["a"], "tools": []}),
        _make_event("agent_turn", {"text": ["b"], "tools": []}),
    ]
    report = repairer.validate(events)
    assert report.consecutive_roles == 1


def test_detect_orphan_tool_use():
    """tool_use without matching tool_result."""
    repairer = SessionRepairer()
    events = [
        _make_event("agent_turn", {
            "text": ["let me check"],
            "tools": ["Bash"],
            "tools_detail": [{"id": "tu_001", "tool": "Bash"}],
        }),
        # No tool_result for tu_001
    ]
    report = repairer.validate(events)
    assert report.orphan_tool_uses == 1


def test_detect_orphan_tool_result():
    """tool_result without preceding tool_use."""
    repairer = SessionRepairer()
    events = [
        _make_event("agent_turn", {"text": ["hi"], "tools": []}),
        _make_event("tool_result", {"tool_use_id": "orphan_123", "output": "result"}),
    ]
    report = repairer.validate(events)
    assert report.orphan_tool_results == 1


def test_detect_truncated_json():
    repairer = SessionRepairer()
    events = [
        _make_event("agent_turn", {
            "text": ["ok"],
            "tools": ["Bash"],
            "input_preview": '{"command": "echo hello...',  # unbalanced braces + ellipsis
        }),
    ]
    report = repairer.validate(events)
    assert report.truncated_json == 1


def test_repair_removes_empty():
    repairer = SessionRepairer()
    events = [
        _make_event("agent_turn", {"text": [], "tools": []}),
        _make_event("agent_turn", {"text": ["real content"], "tools": ["Read"]}),
    ]
    repaired, report = repairer.repair(events)
    assert len(repaired) == 1
    assert report.events_removed == 1


def test_repair_removes_orphan_tool_result():
    repairer = SessionRepairer()
    events = [
        _make_event("agent_turn", {"text": ["hi"], "tools": []}),
        _make_event("tool_result", {"tool_use_id": "orphan_123", "output": "result"}),
    ]
    repaired, report = repairer.repair(events)
    assert len(repaired) == 1  # tool_result removed


def test_repair_keeps_matched_tool_result():
    """tool_result with matching tool_use should be kept."""
    repairer = SessionRepairer()
    events = [
        _make_event("agent_turn", {
            "text": ["checking"],
            "tools": ["Bash"],
            "tools_detail": [{"id": "tu_100", "tool": "Bash"}],
        }),
        _make_event("tool_result", {"tool_use_id": "tu_100", "output": "ok"}),
    ]
    repaired, report = repairer.repair(events)
    assert len(repaired) == 2  # both kept


def test_repair_clean_returns_original():
    """Clean history should return the original list unchanged."""
    repairer = SessionRepairer()
    events = [
        _make_event("agent_turn", {"text": ["hello"], "tools": ["Read"]}),
    ]
    repaired, report = repairer.repair(events)
    assert repaired is events
    assert report.clean


def test_report_summary_clean():
    report = RepairReport(total_events=5)
    assert "clean" in report.summary()


def test_report_summary_issues():
    report = RepairReport(total_events=10, orphan_tool_uses=2, empty_messages=1,
                          events_removed=3, events_repaired=0)
    summary = report.summary()
    assert "orphan tool_use" in summary
    assert "empty" in summary


def test_validate_string_data():
    """Should handle data stored as JSON string."""
    repairer = SessionRepairer()
    events = [
        {"event_type": "agent_turn", "data": json.dumps({"text": ["ok"], "tools": ["Bash"]})},
    ]
    report = repairer.validate(events)
    assert report.clean


def test_repair_string_data():
    """Repair should also handle JSON-string data."""
    repairer = SessionRepairer()
    events = [
        {"event_type": "agent_turn", "data": json.dumps({"text": [], "tools": []})},
        {"event_type": "agent_turn", "data": json.dumps({"text": ["ok"], "tools": ["Bash"]})},
    ]
    repaired, report = repairer.repair(events)
    assert len(repaired) == 1
    assert report.events_removed == 1
