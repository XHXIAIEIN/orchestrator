"""Tests for wake session lifecycle."""
import os
import tempfile
import pytest
from src.storage.events_db import EventsDB


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    d = EventsDB(db_path=path)
    yield d
    # Close the pooled connection before unlinking (Windows file-lock fix)
    pool = d._pool
    with pool.lock:
        if pool._conn is not None:
            try:
                pool._conn.close()
            except Exception:
                pass
            pool._conn = None
    try:
        os.unlink(path)
    except PermissionError:
        pass  # Windows: best-effort cleanup


def test_create_and_get(db):
    task_id = db.create_task(
        action="test wake", reason="test", priority="medium",
        spec={"summary": "test"}, source="wake",
    )
    sid = db.create_wake_session(
        task_id=task_id, chat_id="123", spotlight="fix TG bot [telegram, fix]",
    )
    assert sid > 0
    session = db.get_wake_session(sid)
    assert session["task_id"] == task_id
    assert session["chat_id"] == "123"
    assert session["spotlight"] == "fix TG bot [telegram, fix]"
    assert session["mode"] == "silent"
    assert session["status"] == "pending"
    assert session["result"] is None


def test_update_status(db):
    task_id = db.create_task(action="test", reason="test", priority="medium", spec={}, source="wake")
    sid = db.create_wake_session(task_id=task_id, chat_id="123", spotlight="test")
    db.update_wake_session(sid, status="approved")
    assert db.get_wake_session(sid)["status"] == "approved"
    db.update_wake_session(sid, status="running")
    s = db.get_wake_session(sid)
    assert s["status"] == "running"
    assert s["started_at"] is not None


def test_finish_session(db):
    task_id = db.create_task(action="test", reason="test", priority="medium", spec={}, source="wake")
    sid = db.create_wake_session(task_id=task_id, chat_id="123", spotlight="test")
    db.update_wake_session(sid, status="running")
    db.finish_wake_session(sid, status="done", result="Changed 3 files, tests pass")
    s = db.get_wake_session(sid)
    assert s["status"] == "done"
    assert s["result"] == "Changed 3 files, tests pass"
    assert s["finished_at"] is not None


def test_get_by_status(db):
    for i in range(3):
        tid = db.create_task(action=f"t{i}", reason="t", priority="medium", spec={}, source="wake")
        db.create_wake_session(task_id=tid, chat_id="123", spotlight=f"task {i}")
    pending = db.get_wake_sessions(status="pending")
    assert len(pending) == 3
    db.update_wake_session(pending[0]["id"], status="approved")
    assert len(db.get_wake_sessions(status="pending")) == 2
    assert len(db.get_wake_sessions(status="approved")) == 1


def test_get_active_for_chat(db):
    tid = db.create_task(action="t", reason="t", priority="medium", spec={}, source="wake")
    sid = db.create_wake_session(task_id=tid, chat_id="456", spotlight="test")
    db.update_wake_session(sid, status="running")
    active = db.get_active_wake_session(chat_id="456")
    assert active is not None
    assert active["id"] == sid
    assert db.get_active_wake_session(chat_id="999") is None


def test_update_mode(db):
    tid = db.create_task(action="t", reason="t", priority="medium", spec={}, source="wake")
    sid = db.create_wake_session(task_id=tid, chat_id="123", spotlight="test")
    db.update_wake_session(sid, mode="milestone")
    assert db.get_wake_session(sid)["mode"] == "milestone"
    db.update_wake_session(sid, mode="silent")
    assert db.get_wake_session(sid)["mode"] == "silent"


def test_full_lifecycle(db):
    """Test: create → approve → run → done."""
    from src.channels.wake import create_session, on_task_approved

    result = create_session(chat_id="100", spotlight="test task [test]", db=db)
    sid = result["session_id"]
    tid = result["task_id"]

    s = db.get_wake_session(sid)
    assert s["status"] == "pending"

    on_task_approved(tid, db=db)
    s = db.get_wake_session(sid)
    assert s["status"] == "approved"

    db.update_wake_session(sid, status="running")
    s = db.get_wake_session(sid)
    assert s["status"] == "running"
    assert s["started_at"] is not None

    db.finish_wake_session(sid, status="done", result="Changed 2 files")
    s = db.get_wake_session(sid)
    assert s["status"] == "done"
    assert s["result"] == "Changed 2 files"
    assert s["finished_at"] is not None


def test_cancel_running(db):
    """Test: cancel a running session."""
    from src.channels.wake import create_session, cancel_session, on_task_approved

    result = create_session(chat_id="200", spotlight="cancellable [test]", db=db)
    sid = result["session_id"]
    on_task_approved(result["task_id"], db=db)
    db.update_wake_session(sid, status="running")

    msg = cancel_session("200", db=db)
    assert "正在取消" in msg
    assert db.get_wake_session(sid)["status"] == "cancelled"


def test_cancel_no_active(db):
    """Test: cancel when no active session."""
    from src.channels.wake import cancel_session
    msg = cancel_session("999", db=db)
    assert "没有" in msg


def test_deny_session(db):
    """Test: deny a wake session."""
    from src.channels.wake import create_session, on_task_denied

    result = create_session(chat_id="300", spotlight="denied task", db=db)
    on_task_denied(result["task_id"], db=db)
    s = db.get_wake_session(result["session_id"])
    assert s["status"] == "denied"
    assert s["finished_at"] is not None


def test_parse_wake_command():
    from src.channels.wake import parse_wake_command
    assert parse_wake_command("") == ("status", "")
    assert parse_wake_command("cancel") == ("cancel", "")
    assert parse_wake_command("cancel something") == ("cancel", "something")
    assert parse_wake_command("verbose") == ("verbose", "")
    assert parse_wake_command("quiet") == ("quiet", "")
    assert parse_wake_command("修复 TG bot") == ("task", "修复 TG bot")
    assert parse_wake_command("修复 cancel 相关") == ("task", "修复 cancel 相关")
    assert parse_wake_command("CANCEL") == ("cancel", "")


def test_set_mode(db):
    """Test: switch mode on active session."""
    from src.channels.wake import create_session, set_mode

    result = create_session(chat_id="400", spotlight="mode test", db=db)
    msg = set_mode("400", "milestone", db=db)
    assert "里程碑" in msg
    assert db.get_wake_session(result["session_id"])["mode"] == "milestone"

    msg = set_mode("400", "silent", db=db)
    assert "静默" in msg


def test_list_active(db):
    """Test: list active sessions."""
    from src.channels.wake import create_session, list_active

    create_session(chat_id="500", spotlight="task 1", db=db)
    create_session(chat_id="500", spotlight="task 2", db=db)
    create_session(chat_id="600", spotlight="task 3", db=db)

    all_active = list_active(db=db)
    assert len(all_active) == 3

    filtered = list_active(chat_id="500", db=db)
    assert len(filtered) == 2


def test_inject_message(db):
    """Test: inject message into running session via agent_events."""
    from src.channels.wake import create_session, on_task_approved
    import json

    result = create_session(chat_id="700", spotlight="inject test", db=db)
    on_task_approved(result["task_id"], db=db)
    db.update_wake_session(result["session_id"], status="running")

    db.add_agent_event(
        task_id=result["task_id"],
        event_type="wake.inject",
        data={"message": "also fix the tests", "chat_id": "700"},
    )

    events = db.get_agent_events(result["task_id"])
    assert len(events) >= 1
    data = json.loads(events[0]["data"]) if isinstance(events[0]["data"], str) else events[0]["data"]
    assert data["message"] == "also fix the tests"


def test_format_session_status(db):
    """Test: format_session_status output."""
    from src.channels.wake import create_session, format_session_status, list_active

    create_session(chat_id="800", spotlight="format test [ui]", db=db)
    sessions = list_active(chat_id="800", db=db)
    output = format_session_status(sessions)
    assert "format test" in output
    assert "[pending]" in output

    # Empty list
    assert "没有" in format_session_status([])
