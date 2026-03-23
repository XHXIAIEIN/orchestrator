import json
import pytest
from pathlib import Path
from src.collectors.claude_collector import ClaudeCollector
from src.storage.events_db import EventsDB


def make_fake_session(tmp_path, project="test_project", messages=None):
    """Create a fake Claude session file in the expected JSONL format."""
    if messages is None:
        messages = [
            {"type": "user", "message": {"content": "帮我写一个 Python 脚本"},
             "timestamp": "2026-03-23T00:00:00Z"},
            {"type": "assistant", "message": {"content": "好的，这是代码..."}},
        ]
    project_dir = tmp_path / ".claude" / "projects" / project
    project_dir.mkdir(parents=True)
    session_file = project_dir / "session_abc123.jsonl"
    with open(session_file, "w", encoding="utf-8") as f:
        for msg in messages:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
    return session_file


def test_collector_finds_sessions(tmp_path):
    make_fake_session(tmp_path)
    db = EventsDB(str(tmp_path / "events.db"))
    collector = ClaudeCollector(db=db, claude_home=str(tmp_path / ".claude"))
    count = collector.collect()
    assert count >= 1


def test_collector_deduplicates(tmp_path):
    make_fake_session(tmp_path)
    db = EventsDB(str(tmp_path / "events.db"))
    collector = ClaudeCollector(db=db, claude_home=str(tmp_path / ".claude"))
    count1 = collector.collect()
    count2 = collector.collect()
    assert count1 >= 1
    assert count2 == 0


def test_collector_extracts_topics(tmp_path):
    make_fake_session(tmp_path, messages=[
        {"type": "user", "message": {"content": "帮我设计一个多 agent 系统"},
         "timestamp": "2026-03-23T00:00:00Z"},
        {"type": "assistant", "message": {"content": "我建议使用 orchestrator 模式..."}},
    ])
    db = EventsDB(str(tmp_path / "events.db"))
    collector = ClaudeCollector(db=db, claude_home=str(tmp_path / ".claude"))
    collector.collect()
    events = db.get_recent_events(days=1, source="claude")
    assert len(events) >= 1
