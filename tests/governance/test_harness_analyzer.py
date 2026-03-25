import json
import pytest
from unittest.mock import MagicMock
from src.governance.harness_analyzer import HarnessAnalyzer

def _mock_db(tasks, events):
    db = MagicMock()
    conn = MagicMock()
    db._connect.return_value.__enter__ = lambda s: conn
    db._connect.return_value.__exit__ = MagicMock(return_value=False)

    def execute_side_effect(sql, params=None):
        result = MagicMock()
        if "FROM tasks" in sql:
            result.fetchall.return_value = tasks
        elif "FROM agent_events" in sql:
            tid = params[0] if params else None
            result.fetchall.return_value = [e for e in events if e["task_id"] == tid]
        return result
    conn.execute = MagicMock(side_effect=execute_side_effect)
    return db

def test_empty_analysis():
    db = _mock_db([], [])
    analyzer = HarnessAnalyzer(db)
    report = analyzer.analyze(days=7)
    assert report["total_tasks"] == 0
    assert report["total_events"] == 0

def test_dept_stats_success_rate():
    tasks = [
        {"id": 1, "department": "engineering", "status": "done", "created_at": "2026-03-25T00:00:00"},
        {"id": 2, "department": "engineering", "status": "failed", "created_at": "2026-03-25T00:00:00"},
        {"id": 3, "department": "engineering", "status": "done", "created_at": "2026-03-25T00:00:00"},
    ]
    events = [
        {"task_id": 1, "event_type": "agent_result", "data": json.dumps({"status": "done", "num_turns": 5, "duration_ms": 10000, "cost_usd": 0.05}), "created_at": "2026-03-25"},
        {"task_id": 2, "event_type": "agent_result", "data": json.dumps({"status": "failed", "num_turns": 25, "duration_ms": 60000, "cost_usd": 0.20}), "created_at": "2026-03-25"},
        {"task_id": 3, "event_type": "agent_result", "data": json.dumps({"status": "done", "num_turns": 8, "duration_ms": 15000, "cost_usd": 0.08}), "created_at": "2026-03-25"},
    ]
    db = _mock_db(tasks, events)
    analyzer = HarnessAnalyzer(db)
    report = analyzer.analyze()
    eng = report["department_stats"]["engineering"]
    assert eng["success_rate"] == 0.67
    assert eng["total"] == 3

def test_tool_effectiveness():
    tasks = [{"id": 1, "department": "engineering", "status": "done", "created_at": "2026-03-25"}]
    events = [
        {"task_id": 1, "event_type": "agent_turn", "data": json.dumps({"tools": ["Read", "Edit"]}), "created_at": "2026-03-25"},
        {"task_id": 1, "event_type": "agent_turn", "data": json.dumps({"tools": ["Bash", "Read"]}), "created_at": "2026-03-25"},
        {"task_id": 1, "event_type": "agent_result", "data": json.dumps({"status": "done"}), "created_at": "2026-03-25"},
    ]
    db = _mock_db(tasks, events)
    analyzer = HarnessAnalyzer(db)
    report = analyzer.analyze()
    assert "Read" in report["tool_effectiveness"]
    assert report["tool_effectiveness"]["Read"]["success_rate"] == 1.0

def test_failure_patterns_stuck():
    tasks = [{"id": 1, "department": "engineering", "status": "failed", "created_at": "2026-03-25"}]
    events = [
        {"task_id": 1, "event_type": "stuck_detected", "data": "{}", "created_at": "2026-03-25"},
        {"task_id": 1, "event_type": "stuck_detected", "data": "{}", "created_at": "2026-03-25"},
    ]
    db = _mock_db(tasks, events)
    analyzer = HarnessAnalyzer(db)
    report = analyzer.analyze()
    stuck = [p for p in report["failure_patterns"] if p["pattern"] == "stuck_loop"]
    assert len(stuck) == 1
    assert stuck[0]["count"] == 2

def test_recommendations_low_success():
    tasks = [
        {"id": i, "department": "operations", "status": "failed" if i < 4 else "done", "created_at": "2026-03-25", "output": ""}
        for i in range(1, 6)
    ]
    events = [
        {"task_id": i, "event_type": "agent_result", "data": json.dumps({"status": "failed" if i < 4 else "done", "num_turns": 10}), "created_at": "2026-03-25"}
        for i in range(1, 6)
    ]
    db = _mock_db(tasks, events)
    analyzer = HarnessAnalyzer(db)
    report = analyzer.analyze()
    low_success = [r for r in report["recommendations"] if r["type"] == "dept_low_success"]
    assert len(low_success) >= 1
    assert low_success[0]["department"] == "operations"
