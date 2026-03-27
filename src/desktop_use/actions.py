"""Action executor interface + pyautogui default implementation.

Only dispatches pre-approved operations -- never executes raw code.
"""

from __future__ import annotations

import subprocess
import threading
import time
from abc import ABC, abstractmethod

import pyautogui

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.1

MAX_WAIT = 10  # seconds cap for wait action

ALLOWED_ACTIONS = {
    "click":        {"params": ["x", "y"], "optional": {"button": "left"}},
    "double_click": {"params": ["x", "y"]},
    "right_click":  {"params": ["x", "y"]},
    "type_text":    {"params": ["text"], "optional": {"sensitive": False}},  # char-by-char, for passwords
    "paste_text":   {"params": ["text"], "optional": {"sensitive": False}},  # clipboard paste, for long/unicode text
    "hotkey":       {"params": ["keys"]},       # e.g. ["ctrl", "s"]
    "scroll":       {"params": ["x", "y", "clicks"]},
    "drag":         {"params": ["x1", "y1", "x2", "y2"]},
    "wait":         {"params": ["seconds"]},    # capped at MAX_WAIT
    "screenshot":   {"params": []},
    "done":         {"params": ["summary"]},    # control signal
    "fail":         {"params": ["reason"]},     # control signal
}


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------

class ActionExecutor(ABC):
    """Pluggable action executor backend."""

    @abstractmethod
    def execute(self, action: dict) -> str:
        """Execute a single action. Returns a status string."""


# ---------------------------------------------------------------------------
# Default implementation: pyautogui
# ---------------------------------------------------------------------------

class PyAutoGUIExecutor(ActionExecutor):
    """Dispatch GUI actions from an explicit whitelist.

    Args:
        kill_event: A threading.Event used as a kill switch. When set, all
                    execution is halted immediately.
    """

    def __init__(self, kill_event: threading.Event) -> None:
        self._kill = kill_event

    def execute(self, action: dict) -> str:
        """Execute a single whitelisted action.

        Returns a status string:
          - "INTERRUPTED: kill switch active"  -- kill switch was set before dispatch
          - "REJECTED: unknown action 'X'"     -- action not in whitelist
          - "DONE: <summary>"                  -- done control signal
          - "FAIL: <reason>"                   -- fail control signal
          - "screenshot_requested"             -- screenshot action
          - "success"                          -- pyautogui call completed
          - "INTERRUPTED: FailSafe triggered"  -- pyautogui moved mouse to corner
        """
        if self._kill.is_set():
            return "INTERRUPTED: kill switch active"

        name = action.get("action", "")

        if name not in ALLOWED_ACTIONS:
            return f"REJECTED: unknown action '{name}'"

        try:
            return self._dispatch(name, action)
        except pyautogui.FailSafeException:
            self._kill.set()
            return "INTERRUPTED: FailSafe triggered"

    # ------------------------------------------------------------------
    # Internal dispatch
    # ------------------------------------------------------------------

    def _dispatch(self, name: str, action: dict) -> str:
        if name == "done":
            return f"DONE: {action['summary']}"

        if name == "fail":
            return f"FAIL: {action['reason']}"

        if name == "screenshot":
            return "screenshot_requested"

        if name == "click":
            button = action.get("button", "left")
            pyautogui.click(action["x"], action["y"], button=button)

        elif name == "double_click":
            pyautogui.doubleClick(action["x"], action["y"])

        elif name == "right_click":
            pyautogui.rightClick(action["x"], action["y"])

        elif name == "type_text":
            # Char-by-char typing via pyautogui -- use for passwords / short ASCII.
            text = action["text"]
            pyautogui.write(text, interval=0.03)

        elif name == "paste_text":
            # Clipboard paste -- use for long text, unicode, CJK.
            text = action["text"]
            _clipboard_paste(text)

        elif name == "hotkey":
            pyautogui.hotkey(*action["keys"])

        elif name == "scroll":
            pyautogui.scroll(action["clicks"], x=action["x"], y=action["y"])

        elif name == "drag":
            x1, y1 = action["x1"], action["y1"]
            x2, y2 = action["x2"], action["y2"]
            pyautogui.moveTo(x1, y1)
            pyautogui.drag(x2 - x1, y2 - y1, duration=0.5)

        elif name == "wait":
            seconds = min(action["seconds"], MAX_WAIT)
            time.sleep(seconds)

        return "success"


def _clipboard_paste(text: str) -> None:
    """Write text via clipboard + Ctrl+V to bypass IME interference.
    Saves and restores the original clipboard content."""
    # Save current clipboard
    try:
        original = subprocess.run(
            ["powershell", "-Command", "Get-Clipboard"],
            capture_output=True, text=True, timeout=3,
        ).stdout.rstrip("\r\n")
    except Exception:
        original = None

    # Set clipboard to our text
    subprocess.run(
        ["powershell", "-Command", f"Set-Clipboard -Value {_ps_escape(text)}"],
        capture_output=True, timeout=3,
    )

    # Paste
    time.sleep(0.05)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.1)

    # Restore original clipboard
    if original is not None:
        try:
            subprocess.run(
                ["powershell", "-Command", f"Set-Clipboard -Value {_ps_escape(original)}"],
                capture_output=True, timeout=3,
            )
        except Exception:
            pass


def _ps_escape(text: str) -> str:
    """Escape a string for safe embedding in a PowerShell -Command argument."""
    escaped = text.replace("'", "''")
    return f"'{escaped}'"
