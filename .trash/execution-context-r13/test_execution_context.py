"""Tests for ExecutionContext — stolen from ChatDev 2.0."""
import threading
import pytest
from src.core.execution_context import ExecutionContext, ExecutionContextBuilder


def test_context_creation():
    ctx = ExecutionContext(task_id=42, department="engineering")
    assert ctx.task_id == 42
    assert ctx.department == "engineering"
    assert ctx.global_state == {}
    assert ctx.cancel_event is not None
    assert not ctx.cancel_event.is_set()


def test_context_cancellation():
    ctx = ExecutionContext(task_id=1, department="quality")
    assert not ctx.is_cancelled
    ctx.cancel("test reason")
    assert ctx.is_cancelled
    assert ctx.cancel_reason == "test reason"
    assert ctx.cancel_event.is_set()


def test_context_global_state():
    ctx = ExecutionContext(task_id=1, department="engineering")
    ctx.global_state["key"] = "value"
    assert ctx.global_state["key"] == "value"


def test_builder_pattern():
    builder = ExecutionContextBuilder(task_id=99, department="security")
    builder.with_cwd("/tmp/test")
    builder.with_timeout(300.0)
    ctx = builder.build()
    assert ctx.task_id == 99
    assert ctx.department == "security"
    assert ctx.cwd == "/tmp/test"
    assert ctx.timeout_s == 300.0


def test_builder_defaults():
    ctx = ExecutionContextBuilder(task_id=1, department="ops").build()
    assert ctx.timeout_s == 300.0
    assert ctx.max_turns == 25
    assert ctx.cwd == ""
