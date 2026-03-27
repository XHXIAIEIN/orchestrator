"""
Tests for src/desktop_use/actions.py — ActionExecutor whitelist ACL.
All pyautogui calls are mocked to avoid real mouse/keyboard movement.
"""

import threading
import time
from unittest.mock import MagicMock, call, patch

import pytest

from src.desktop_use.actions import ALLOWED_ACTIONS, ActionExecutor


# ---------------------------------------------------------------------------
# Whitelist sanity checks
# ---------------------------------------------------------------------------

class TestWhitelist:
    def test_click_in_whitelist(self):
        assert "click" in ALLOWED_ACTIONS

    def test_done_in_whitelist(self):
        assert "done" in ALLOWED_ACTIONS

    def test_fail_in_whitelist(self):
        assert "fail" in ALLOWED_ACTIONS

    def test_no_exec_in_whitelist(self):
        assert "exec" not in ALLOWED_ACTIONS

    def test_no_eval_in_whitelist(self):
        assert "eval" not in ALLOWED_ACTIONS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def kill_event():
    return threading.Event()


@pytest.fixture
def executor(kill_event):
    return ActionExecutor(kill_event)


# ---------------------------------------------------------------------------
# click
# ---------------------------------------------------------------------------

class TestClick:
    @patch("src.desktop_use.actions.pyautogui")
    def test_click_calls_pyautogui_click(self, mock_pg, executor):
        result = executor.execute({"action": "click", "x": 100, "y": 200})
        mock_pg.click.assert_called_once_with(100, 200, button="left")
        assert result == "success"

    @patch("src.desktop_use.actions.pyautogui")
    def test_click_right_button(self, mock_pg, executor):
        result = executor.execute({"action": "click", "x": 50, "y": 60, "button": "right"})
        mock_pg.click.assert_called_once_with(50, 60, button="right")
        assert result == "success"


# ---------------------------------------------------------------------------
# type_text
# ---------------------------------------------------------------------------

class TestTypeText:
    @patch("src.desktop_use.actions._clipboard_paste")
    def test_type_text_uses_clipboard(self, mock_paste, executor):
        """type_text must use clipboard paste, not pyautogui.write(),
        to avoid IME interference (e.g. 'Hello' → '热车时突然投入')."""
        result = executor.execute({"action": "type_text", "text": "hello"})
        mock_paste.assert_called_once_with("hello")
        assert result == "success"


# ---------------------------------------------------------------------------
# hotkey
# ---------------------------------------------------------------------------

class TestHotkey:
    @patch("src.desktop_use.actions.pyautogui")
    def test_hotkey_unpacks_keys(self, mock_pg, executor):
        result = executor.execute({"action": "hotkey", "keys": ["ctrl", "s"]})
        mock_pg.hotkey.assert_called_once_with("ctrl", "s")
        assert result == "success"


# ---------------------------------------------------------------------------
# scroll
# ---------------------------------------------------------------------------

class TestScroll:
    @patch("src.desktop_use.actions.pyautogui")
    def test_scroll_passes_clicks_and_coords(self, mock_pg, executor):
        result = executor.execute({"action": "scroll", "x": 300, "y": 400, "clicks": -3})
        mock_pg.scroll.assert_called_once_with(-3, x=300, y=400)
        assert result == "success"


# ---------------------------------------------------------------------------
# drag
# ---------------------------------------------------------------------------

class TestDrag:
    @patch("src.desktop_use.actions.pyautogui")
    def test_drag_calls_moveto_then_drag_with_delta(self, mock_pg, executor):
        result = executor.execute({"action": "drag", "x1": 10, "y1": 20, "x2": 110, "y2": 70})
        mock_pg.moveTo.assert_called_once_with(10, 20)
        mock_pg.drag.assert_called_once_with(100, 50, duration=0.5)
        assert result == "success"


# ---------------------------------------------------------------------------
# wait
# ---------------------------------------------------------------------------

class TestWait:
    @patch("src.desktop_use.actions.time")
    def test_wait_capped_at_10s(self, mock_time, executor):
        result = executor.execute({"action": "wait", "seconds": 999})
        mock_time.sleep.assert_called_once_with(10)
        assert result == "success"

    @patch("src.desktop_use.actions.time")
    def test_wait_under_cap(self, mock_time, executor):
        result = executor.execute({"action": "wait", "seconds": 3})
        mock_time.sleep.assert_called_once_with(3)
        assert result == "success"


# ---------------------------------------------------------------------------
# Control signals
# ---------------------------------------------------------------------------

class TestControlSignals:
    def test_done_returns_summary(self, executor):
        result = executor.execute({"action": "done", "summary": "task finished"})
        assert result == "DONE: task finished"

    def test_fail_returns_reason(self, executor):
        result = executor.execute({"action": "fail", "reason": "element not found"})
        assert result == "FAIL: element not found"


# ---------------------------------------------------------------------------
# screenshot
# ---------------------------------------------------------------------------

class TestScreenshot:
    def test_screenshot_returns_sentinel(self, executor):
        result = executor.execute({"action": "screenshot"})
        assert result == "screenshot_requested"


# ---------------------------------------------------------------------------
# Unknown action
# ---------------------------------------------------------------------------

class TestUnknown:
    def test_unknown_action_rejected(self, executor):
        result = executor.execute({"action": "rm_rf_slash"})
        assert result == "REJECTED: unknown action 'rm_rf_slash'"


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------

class TestKillSwitch:
    @patch("src.desktop_use.actions.pyautogui")
    def test_kill_switch_prevents_execution(self, mock_pg, kill_event, executor):
        kill_event.set()
        result = executor.execute({"action": "click", "x": 1, "y": 1})
        mock_pg.click.assert_not_called()
        assert result == "INTERRUPTED: kill switch active"

    @patch("src.desktop_use.actions.pyautogui")
    def test_failsafe_sets_kill_event_and_returns_interrupted(self, mock_pg, kill_event, executor):
        import pyautogui as real_pg
        mock_pg.FailSafeException = real_pg.FailSafeException
        mock_pg.click.side_effect = real_pg.FailSafeException
        result = executor.execute({"action": "click", "x": 0, "y": 0})
        assert kill_event.is_set()
        assert result == "INTERRUPTED: FailSafe triggered"
