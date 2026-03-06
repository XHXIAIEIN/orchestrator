import pytest
from src.db import Database


def test_database_creates_tables(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    tables = db.get_tables()
    assert "sessions" in tables
    assert "messages" in tables
    assert "problems" in tables


def test_create_session_returns_id(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    session_id = db.create_session("测试输入")
    assert isinstance(session_id, int)
    assert session_id > 0


def test_save_and_retrieve_messages(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    session_id = db.create_session("测试输入")
    db.save_message(session_id, "user", "我想做一个网站")
    db.save_message(session_id, "assistant", "你的网站要解决什么问题？")
    messages = db.get_messages(session_id)
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"


def test_save_problem_definition(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    session_id = db.create_session("测试输入")
    db.save_problem(session_id, "帮助独立开发者追踪项目进度", "中等", ["进度追踪", "独立开发"])
    problems = db.get_problems()
    assert len(problems) == 1
    assert problems[0]["definition"] == "帮助独立开发者追踪项目进度"
