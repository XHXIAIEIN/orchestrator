"""Tests for Auto-Freeze Circuit Breaker."""
from src.governance.freeze_breaker import FreezeBreaker


def test_no_freeze_when_tools_used():
    """Should not freeze when agent is actively using tools."""
    fb = FreezeBreaker(idle_threshold=3)
    fb.record_turn(tool_calls=2, text_len=100)
    fb.record_turn(tool_calls=1, text_len=50)
    fb.record_turn(tool_calls=3, text_len=200)
    assert not fb.should_freeze()


def test_freeze_after_consecutive_idle_turns():
    """Should freeze after N consecutive turns with no tool calls."""
    fb = FreezeBreaker(idle_threshold=3)
    fb.record_turn(tool_calls=0, text_len=50)
    fb.record_turn(tool_calls=0, text_len=30)
    assert not fb.should_freeze()
    fb.record_turn(tool_calls=0, text_len=40)
    assert fb.should_freeze()
    assert fb.reason == "idle_spin"


def test_freeze_resets_on_tool_call():
    """A tool call should reset the idle counter."""
    fb = FreezeBreaker(idle_threshold=3)
    fb.record_turn(tool_calls=0, text_len=50)
    fb.record_turn(tool_calls=0, text_len=30)
    fb.record_turn(tool_calls=1, text_len=100)  # reset!
    fb.record_turn(tool_calls=0, text_len=50)
    fb.record_turn(tool_calls=0, text_len=30)
    assert not fb.should_freeze()  # only 2 idle, not 3


def test_freeze_on_low_output():
    """Should freeze if output is consistently tiny (agent saying nothing useful)."""
    fb = FreezeBreaker(idle_threshold=3, min_useful_text=20)
    fb.record_turn(tool_calls=0, text_len=5)
    fb.record_turn(tool_calls=0, text_len=3)
    fb.record_turn(tool_calls=0, text_len=2)
    assert fb.should_freeze()


def test_get_status():
    """Status should report idle count and frozen state."""
    fb = FreezeBreaker(idle_threshold=3)
    fb.record_turn(tool_calls=0, text_len=10)
    status = fb.get_status()
    assert status["consecutive_idle"] == 1
    assert status["frozen"] is False
