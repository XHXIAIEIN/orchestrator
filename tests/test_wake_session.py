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
