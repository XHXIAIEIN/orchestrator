"""Tests for Session Manager."""
from src.governance.session_manager import SessionManager


def test_create_session():
    mgr = SessionManager()
    s = mgr.create("task_1", cwd="/project", env={"KEY": "val"})
    assert s.task_id == "task_1"
    assert s.cwd == "/project"
    assert s.status == "active"
    assert not s.has_parent


def test_fork_inherits_env():
    mgr = SessionManager()
    parent = mgr.create("task_1", cwd="/project", env={"API_KEY": "secret"})
    child = mgr.fork(parent.id, reason="overflow")
    assert child is not None
    assert child.cwd == "/project"
    assert child.env == {"API_KEY": "secret"}
    assert child.parent_id == parent.id
    assert child.has_parent


def test_fork_marks_parent():
    mgr = SessionManager()
    parent = mgr.create("task_1")
    mgr.fork(parent.id)
    assert parent.status == "forked"


def test_fork_independent_env():
    """Child's env should be independent copy."""
    mgr = SessionManager()
    parent = mgr.create("task_1", env={"KEY": "val"})
    child = mgr.fork(parent.id)
    child.env["NEW_KEY"] = "new"
    assert "NEW_KEY" not in parent.env


def test_fork_unknown_returns_none():
    mgr = SessionManager()
    assert mgr.fork("nonexistent") is None


def test_lineage():
    mgr = SessionManager()
    s1 = mgr.create("task_1", cwd="/a")
    s2 = mgr.fork(s1.id)
    s3 = mgr.fork(s2.id)
    lineage = mgr.get_lineage(s3.id)
    assert len(lineage) == 3
    assert lineage[0].id == s1.id
    assert lineage[2].id == s3.id


def test_get_children():
    mgr = SessionManager()
    parent = mgr.create("task_1")
    c1 = mgr.fork(parent.id)
    c2 = mgr.fork(parent.id)
    children = mgr.get_children(parent.id)
    assert len(children) == 2


def test_complete_and_fail():
    mgr = SessionManager()
    s1 = mgr.create("task_1")
    s2 = mgr.create("task_2")
    mgr.complete(s1.id, cost_usd=0.05)
    mgr.fail(s2.id, reason="timeout")
    assert s1.status == "completed"
    assert s1.cost_usd == 0.05
    assert s2.status == "failed"


def test_get_active():
    mgr = SessionManager()
    s1 = mgr.create("task_1")
    s2 = mgr.create("task_2")
    mgr.complete(s1.id)
    active = mgr.get_active()
    assert len(active) == 1
    assert active[0].id == s2.id


def test_stats():
    mgr = SessionManager()
    mgr.create("t1")
    mgr.create("t2")
    s3 = mgr.create("t3")
    mgr.complete(s3.id)
    stats = mgr.get_stats()
    assert stats["total"] == 3
    assert stats["active"] == 2
    assert stats["by_status"]["active"] == 2
    assert stats["by_status"]["completed"] == 1
