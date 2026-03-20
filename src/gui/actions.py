"""
Whitelist-based GUI action executor.

Only dispatches pre-approved pyautogui operations — never executes raw code.
"""

import threading
import time

import pyautogui

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.1

MAX_WAIT = 10  # seconds cap for wait action

ALLOWED_ACTIONS = {
    "click":        {"params": ["x", "y"], "optional": {"button": "left"}},
    "double_click": {"params": ["x", "y"]},
    "right_click":  {"params": ["x", "y"]},
    "type_text":    {"params": ["text"]},
    "hotkey":       {"params": ["keys"]},       # e.g. ["ctrl", "s"]
    "scroll":       {"params": ["x", "y", "clicks"]},
    "drag":         {"params": ["x1", "y1", "x2", "y2"]},
    "wait":         {"params": ["seconds"]},    # capped at MAX_WAIT
    "screenshot":   {"params": []},
    "done":         {"params": ["summary"]},    # control signal
    "fail":         {"params": ["reason"]},     # control signal
}


class ActionExecutor:
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
          - "INTERRUPTED: kill switch active"  — kill switch was set before dispatch
          - "REJECTED: unknown action 'X'"     — action not in whitelist
          - "DONE: <summary>"                  — done control signal
          - "FAIL: <reason>"                   — fail control signal
          - "screenshot_requested"             — screenshot action
          - "success"                          — pyautogui call completed
          - "INTERRUPTED: FailSafe triggered"  — pyautogui moved mouse to corner
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
            pyautogui.write(action["text"], interval=0.03)

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
