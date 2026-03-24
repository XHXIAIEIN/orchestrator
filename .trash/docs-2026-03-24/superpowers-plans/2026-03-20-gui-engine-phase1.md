# GUI Engine Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a working GUI automation engine that can capture screens, reason about actions via LLM, locate elements via OCR, and execute whitelisted mouse/keyboard operations.

**Architecture:** Generalist-specialist split — LLM Reasoner decides "what to do", OCR Grounder finds "where on screen", pyautogui Executor does "the physical action". Kill switch (ESC + FailSafe) ensures owner can always regain control. Multi-monitor + DPI-aware from day one.

**Tech Stack:** Python 3.12, mss (screenshots), pyautogui (mouse/keyboard), pytesseract (OCR), rapidfuzz (fuzzy match), pynput (kill switch), Pillow (image processing). LLM via existing LLM Router (Qwen3/Claude Haiku).

**Spec:** `docs/superpowers/specs/2026-03-19-gui-engine-design.md`

---

## File Map

| File | Purpose | Creates/Modifies |
|------|---------|-----------------|
| `src/gui/__init__.py` | Package init, exports GUIEngine | Create |
| `src/gui/screen.py` | ScreenManager: multi-monitor capture + DPI coord mapping | Create |
| `src/gui/actions.py` | ActionExecutor: whitelist ACL + pyautogui execution + kill switch | Create |
| `src/gui/grounder_ocr.py` | OCRGrounder: Tesseract word-level bbox + rapidfuzz matching | Create |
| `src/gui/grounder.py` | GroundingRouter: OCR → Vision fallback (Phase 1: OCR only) | Create |
| `src/gui/grounder_vision.py` | VisionGrounder: stub for Phase 2 (UI-TARS-7B) | Create |
| `src/gui/trajectory.py` | Trajectory sliding window context | Create |
| `src/gui/prompts.py` | Reasoner prompt templates | Create |
| `src/gui/engine.py` | GUIEngine: main perception-action loop | Create |
| `tests/test_gui_screen.py` | Tests for ScreenManager | Create |
| `tests/test_gui_actions.py` | Tests for ActionExecutor | Create |
| `tests/test_gui_grounder_ocr.py` | Tests for OCRGrounder | Create |
| `tests/test_gui_trajectory.py` | Tests for Trajectory | Create |
| `tests/test_gui_grounder.py` | Tests for GroundingRouter | Create |
| `tests/test_gui_engine.py` | Tests for GUIEngine loop | Create |
| `requirements.txt` | Add new dependencies | Modify |

---

### Task 1: Install Dependencies

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add GUI dependencies to requirements.txt**

Append to `requirements.txt`:
```
# GUI Engine
mss>=9.0.0
pyautogui>=0.9.54
pytesseract>=0.3.10
Pillow>=10.0.0
rapidfuzz>=3.0.0
pynput>=1.7.6
```

- [ ] **Step 2: Install dependencies**

Run: `pip install -r requirements.txt`
Expected: All packages install successfully.

- [ ] **Step 3: Install Tesseract OCR system dependency**

Run: `winget install UB-Mannheim.TesseractOCR --accept-package-agreements --accept-source-agreements`
Expected: Tesseract installed. Verify with: `tesseract --version`

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "deps: add GUI engine dependencies (mss, pyautogui, pytesseract, rapidfuzz, pynput)"
```

---

### Task 2: ScreenManager — Multi-Monitor Capture + Coordinate Mapping

**Files:**
- Create: `src/gui/__init__.py`
- Create: `src/gui/screen.py`
- Test: `tests/test_gui_screen.py`

- [ ] **Step 1: Create package init**

```python
# src/gui/__init__.py
```

- [ ] **Step 2: Write tests for ScreenManager**

```python
# tests/test_gui_screen.py
import pytest
from unittest.mock import patch, MagicMock
from src.gui.screen import ScreenManager, MonitorInfo


class TestMonitorInfo:
    def test_dataclass_fields(self):
        info = MonitorInfo(
            id=1, x_offset=0, y_offset=0,
            width=3840, height=2160,
            width_logical=1920, height_logical=1080,
            scale_factor=200,
        )
        assert info.scale_factor == 200
        assert info.width_logical == 1920

    def test_scale_factor_100_means_no_scaling(self):
        info = MonitorInfo(
            id=1, x_offset=0, y_offset=0,
            width=1920, height=1080,
            width_logical=1920, height_logical=1080,
            scale_factor=100,
        )
        assert info.width == info.width_logical


class TestScreenManager:
    @patch("src.gui.screen.mss_module")
    @patch("src.gui.screen.ScreenManager._probe_monitors")
    def test_capture_returns_bytes_and_monitor_info(self, mock_probe, mock_mss):
        """capture() should return (png_bytes, MonitorInfo)."""
        mock_probe.return_value = [
            MonitorInfo(id=1, x_offset=0, y_offset=0,
                        width=1920, height=1080,
                        width_logical=1920, height_logical=1080,
                        scale_factor=100),
        ]
        mock_sct = MagicMock()
        mock_sct.grab.return_value = MagicMock()
        mock_sct.grab.return_value.rgb = b"\x00" * (1920 * 1080 * 3)
        mock_sct.grab.return_value.size = (1920, 1080)
        mock_mss.return_value.__enter__ = lambda s: mock_sct
        mock_mss.return_value.__exit__ = MagicMock(return_value=False)

        sm = ScreenManager()
        data, info = sm.capture(monitor_id=1)
        assert isinstance(data, bytes)
        assert len(data) > 0
        assert info.id == 1

    def test_to_logical_coords_with_200_percent_scaling(self):
        """Physical (3840, 2160) at 200% DPI → logical (1920, 1080)."""
        sm = ScreenManager.__new__(ScreenManager)
        sm.monitors = [
            MonitorInfo(id=1, x_offset=0, y_offset=0,
                        width=3840, height=2160,
                        width_logical=1920, height_logical=1080,
                        scale_factor=200),
        ]
        lx, ly = sm.to_logical_coords(3840, 2160, monitor_id=1)
        assert lx == 1920
        assert ly == 1080

    def test_to_logical_coords_with_150_percent_scaling(self):
        """Physical (2880, 1620) at 150% → logical (1920, 1080)."""
        sm = ScreenManager.__new__(ScreenManager)
        sm.monitors = [
            MonitorInfo(id=1, x_offset=0, y_offset=0,
                        width=2880, height=1620,
                        width_logical=1920, height_logical=1080,
                        scale_factor=150),
        ]
        lx, ly = sm.to_logical_coords(1440, 810, monitor_id=1)
        assert lx == 960
        assert ly == 540

    def test_to_global_coords_with_offset(self):
        """Monitor 2 at offset (1920, 0) → local (100, 200) → global (2020, 200)."""
        sm = ScreenManager.__new__(ScreenManager)
        sm.monitors = [
            MonitorInfo(id=1, x_offset=0, y_offset=0,
                        width=1920, height=1080,
                        width_logical=1920, height_logical=1080,
                        scale_factor=100),
            MonitorInfo(id=2, x_offset=1920, y_offset=0,
                        width=1920, height=1080,
                        width_logical=1920, height_logical=1080,
                        scale_factor=100),
        ]
        gx, gy = sm.to_global_coords(100, 200, monitor_id=2)
        assert gx == 2020
        assert gy == 200

    def test_capture_invalid_monitor_raises(self):
        sm = ScreenManager.__new__(ScreenManager)
        sm.monitors = [
            MonitorInfo(id=1, x_offset=0, y_offset=0,
                        width=1920, height=1080,
                        width_logical=1920, height_logical=1080,
                        scale_factor=100),
        ]
        with pytest.raises(ValueError, match="monitor_id"):
            sm.capture(monitor_id=99)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_gui_screen.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.gui.screen'`

- [ ] **Step 4: Implement ScreenManager**

```python
# src/gui/screen.py
"""Multi-monitor screenshot capture and coordinate mapping.

Two coordinate spaces:
- Physical pixels: what mss captures, what OCR/VLM output
- Logical pixels: what pyautogui uses for mouse movement

Conversion: logical = physical / (scale_factor / 100)
"""
import ctypes
import logging
import platform
from dataclasses import dataclass
from io import BytesIO

from PIL import Image

try:
    import mss as mss_module
except ImportError:
    mss_module = None

log = logging.getLogger(__name__)


@dataclass
class MonitorInfo:
    id: int
    x_offset: int       # global offset (logical pixels)
    y_offset: int
    width: int           # physical pixels
    height: int
    width_logical: int   # logical pixels
    height_logical: int
    scale_factor: int    # Windows scale percentage (100, 125, 150, 200...)


class ScreenManager:
    def __init__(self):
        if mss_module is None:
            raise ImportError("mss is required: pip install mss")
        self.monitors: list[MonitorInfo] = self._probe_monitors()
        log.info(f"ScreenManager: found {len(self.monitors)} monitor(s)")
        for m in self.monitors:
            log.info(f"  Monitor {m.id}: {m.width}x{m.height} phys, "
                     f"{m.width_logical}x{m.height_logical} logical, "
                     f"scale={m.scale_factor}%, offset=({m.x_offset},{m.y_offset})")

    @staticmethod
    def _probe_monitors() -> list[MonitorInfo]:
        """Detect all monitors with their DPI scale factors."""
        monitors = []
        with mss_module.mss() as sct:
            # sct.monitors[0] is the "all monitors" virtual screen
            # sct.monitors[1..N] are individual monitors
            for i, mon in enumerate(sct.monitors[1:], start=1):
                scale = ScreenManager._get_scale_factor(i - 1)
                w_phys = mon["width"]
                h_phys = mon["height"]
                w_log = round(w_phys / (scale / 100))
                h_log = round(h_phys / (scale / 100))
                # mss offsets are physical; convert to logical for pyautogui
                x_off = round(mon["left"] / (scale / 100))
                y_off = round(mon["top"] / (scale / 100))
                monitors.append(MonitorInfo(
                    id=i,
                    x_offset=x_off,
                    y_offset=y_off,
                    width=w_phys,
                    height=h_phys,
                    width_logical=w_log,
                    height_logical=h_log,
                    scale_factor=scale,
                ))
        return monitors

    @staticmethod
    def _get_scale_factor(monitor_index: int) -> int:
        """Read DPI scale factor from Windows API. Returns 100 on non-Windows."""
        if platform.system() != "Windows":
            return 100
        try:
            # Use PROCESS_PER_MONITOR_DPI_AWARE for accurate readings
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass
        try:
            # EnumDisplayMonitors to get HMONITOR handles
            monitors = []
            def callback(hmonitor, hdc, lprect, lparam):
                monitors.append(hmonitor)
                return True
            MONITORENUMPROC = ctypes.WINFUNCTYPE(
                ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong,
                ctypes.POINTER(ctypes.c_long), ctypes.c_double,
            )
            ctypes.windll.user32.EnumDisplayMonitors(
                None, None, MONITORENUMPROC(callback), 0,
            )
            if monitor_index < len(monitors):
                scale = ctypes.c_uint()
                ctypes.windll.shcore.GetScaleFactorForMonitor(
                    monitors[monitor_index], ctypes.byref(scale),
                )
                return scale.value if scale.value > 0 else 100
        except Exception as e:
            log.warning(f"ScreenManager: DPI detection failed ({e}), assuming 100%")
        return 100

    def _get_monitor(self, monitor_id: int) -> MonitorInfo:
        for m in self.monitors:
            if m.id == monitor_id:
                return m
        raise ValueError(f"monitor_id {monitor_id} not found (have {[m.id for m in self.monitors]})")

    def capture(self, monitor_id: int = 0) -> tuple[bytes, MonitorInfo]:
        """Capture a specific monitor, or all monitors stitched (monitor_id=0).
        Returns (PNG bytes, MonitorInfo)."""
        with mss_module.mss() as sct:
            if monitor_id == 0:
                # Grab the "all monitors" virtual screen (mss index 0)
                raw = sct.grab(sct.monitors[0])
                img = Image.frombytes("RGB", raw.size, raw.rgb)
                buf = BytesIO()
                img.save(buf, format="PNG")
                # Synthesize a MonitorInfo for the virtual screen
                info = MonitorInfo(
                    id=0, x_offset=0, y_offset=0,
                    width=raw.size[0], height=raw.size[1],
                    width_logical=raw.size[0], height_logical=raw.size[1],
                    scale_factor=100,  # virtual screen uses raw coords
                )
                return buf.getvalue(), info
            else:
                info = self._get_monitor(monitor_id)
                raw = sct.grab(sct.monitors[monitor_id])
                img = Image.frombytes("RGB", raw.size, raw.rgb)
                buf = BytesIO()
                img.save(buf, format="PNG")
                return buf.getvalue(), info

    def capture_all(self) -> list[tuple[bytes, MonitorInfo]]:
        """Capture each monitor separately."""
        return [self.capture(m.id) for m in self.monitors]

    def to_logical_coords(self, phys_x: int, phys_y: int, monitor_id: int) -> tuple[int, int]:
        """Convert physical pixel coords to logical coords (for pyautogui)."""
        info = self._get_monitor(monitor_id)
        scale = info.scale_factor / 100
        return round(phys_x / scale), round(phys_y / scale)

    def to_global_coords(self, local_x: int, local_y: int, monitor_id: int) -> tuple[int, int]:
        """Convert monitor-local logical coords to global logical coords."""
        info = self._get_monitor(monitor_id)
        return local_x + info.x_offset, local_y + info.y_offset
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_gui_screen.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/gui/__init__.py src/gui/screen.py tests/test_gui_screen.py
git commit -m "feat(gui): add ScreenManager with multi-monitor capture and DPI coord mapping"
```

---

### Task 3: ActionExecutor — Whitelist ACL + Kill Switch

**Files:**
- Create: `src/gui/actions.py`
- Test: `tests/test_gui_actions.py`

- [ ] **Step 1: Write tests for ActionExecutor**

```python
# tests/test_gui_actions.py
import threading
import pytest
from unittest.mock import patch, MagicMock, call
from src.gui.actions import ActionExecutor, ALLOWED_ACTIONS


class TestAllowedActions:
    def test_click_in_whitelist(self):
        assert "click" in ALLOWED_ACTIONS

    def test_done_and_fail_are_control_signals(self):
        assert "done" in ALLOWED_ACTIONS
        assert "fail" in ALLOWED_ACTIONS

    def test_no_exec_or_eval(self):
        """Whitelist must never contain raw code execution."""
        for name in ALLOWED_ACTIONS:
            assert name not in ("exec", "eval", "run_code", "shell")


class TestActionExecutor:
    def setup_method(self):
        self.kill_event = threading.Event()

    @patch("src.gui.actions.pyautogui")
    def test_click_calls_pyautogui(self, mock_pag):
        executor = ActionExecutor(self.kill_event)
        result = executor.execute({"action": "click", "x": 100, "y": 200})
        mock_pag.click.assert_called_once_with(100, 200, button="left")
        assert result == "success"

    @patch("src.gui.actions.pyautogui")
    def test_click_with_right_button(self, mock_pag):
        executor = ActionExecutor(self.kill_event)
        result = executor.execute({"action": "click", "x": 100, "y": 200, "button": "right"})
        mock_pag.click.assert_called_once_with(100, 200, button="right")
        assert result == "success"

    @patch("src.gui.actions.pyautogui")
    def test_type_text(self, mock_pag):
        executor = ActionExecutor(self.kill_event)
        result = executor.execute({"action": "type_text", "text": "hello"})
        mock_pag.write.assert_called_once_with("hello", interval=0.03)
        assert result == "success"

    @patch("src.gui.actions.pyautogui")
    def test_hotkey(self, mock_pag):
        executor = ActionExecutor(self.kill_event)
        result = executor.execute({"action": "hotkey", "keys": ["ctrl", "s"]})
        mock_pag.hotkey.assert_called_once_with("ctrl", "s")
        assert result == "success"

    @patch("src.gui.actions.pyautogui")
    def test_scroll(self, mock_pag):
        executor = ActionExecutor(self.kill_event)
        result = executor.execute({"action": "scroll", "x": 500, "y": 300, "clicks": -3})
        mock_pag.scroll.assert_called_once_with(-3, x=500, y=300)
        assert result == "success"

    @patch("src.gui.actions.pyautogui")
    def test_drag(self, mock_pag):
        executor = ActionExecutor(self.kill_event)
        result = executor.execute({"action": "drag", "x1": 10, "y1": 20, "x2": 100, "y2": 200})
        mock_pag.moveTo.assert_called_once_with(10, 20)
        mock_pag.drag.assert_called_once_with(90, 180, duration=0.5)
        assert result == "success"

    @patch("src.gui.actions.pyautogui")
    def test_wait_capped_at_10s(self, mock_pag):
        executor = ActionExecutor(self.kill_event)
        with patch("src.gui.actions.time") as mock_time:
            executor.execute({"action": "wait", "seconds": 99})
            mock_time.sleep.assert_called_once_with(10)  # capped

    def test_unknown_action_rejected(self):
        executor = ActionExecutor(self.kill_event)
        result = executor.execute({"action": "exec", "code": "import os; os.system('rm -rf /')"})
        assert "rejected" in result.lower()

    def test_done_returns_signal(self):
        executor = ActionExecutor(self.kill_event)
        result = executor.execute({"action": "done", "summary": "task complete"})
        assert result == "DONE: task complete"

    def test_fail_returns_signal(self):
        executor = ActionExecutor(self.kill_event)
        result = executor.execute({"action": "fail", "reason": "element not found"})
        assert result == "FAIL: element not found"

    @patch("src.gui.actions.pyautogui")
    def test_kill_switch_prevents_execution(self, mock_pag):
        self.kill_event.set()  # simulate ESC pressed
        executor = ActionExecutor(self.kill_event)
        result = executor.execute({"action": "click", "x": 100, "y": 200})
        mock_pag.click.assert_not_called()
        assert "interrupted" in result.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_gui_actions.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement ActionExecutor**

```python
# src/gui/actions.py
"""Whitelist-based action executor. Only allows predefined pyautogui operations.
Never executes raw code strings — this is not Agent S."""
import logging
import threading
import time

try:
    import pyautogui
    pyautogui.FAILSAFE = True  # keep built-in FailSafe (mouse to top-left corner)
    pyautogui.PAUSE = 0.1      # small pause between actions for stability
except ImportError:
    pyautogui = None

log = logging.getLogger(__name__)

ALLOWED_ACTIONS = {
    "click":        {"params": ["x", "y"], "optional": {"button": "left"}},
    "double_click": {"params": ["x", "y"]},
    "right_click":  {"params": ["x", "y"]},
    "type_text":    {"params": ["text"]},
    "hotkey":       {"params": ["keys"]},
    "scroll":       {"params": ["x", "y", "clicks"]},
    "drag":         {"params": ["x1", "y1", "x2", "y2"]},
    "wait":         {"params": ["seconds"]},
    "screenshot":   {"params": []},
    "done":         {"params": ["summary"]},
    "fail":         {"params": ["reason"]},
}

MAX_WAIT = 10  # seconds


class ActionExecutor:
    def __init__(self, kill_event: threading.Event):
        if pyautogui is None:
            raise ImportError("pyautogui is required: pip install pyautogui")
        self.kill_event = kill_event

    def execute(self, action: dict) -> str:
        """Execute a single whitelisted action. Returns 'success', a signal string, or an error."""
        name = action.get("action", "")

        # Kill switch check
        if self.kill_event.is_set():
            log.warning(f"ActionExecutor: kill switch active, rejecting '{name}'")
            return "INTERRUPTED: kill switch active"

        if name not in ALLOWED_ACTIONS:
            log.warning(f"ActionExecutor: rejected unknown action '{name}'")
            return f"REJECTED: unknown action '{name}'"

        try:
            return self._dispatch(name, action)
        except pyautogui.FailSafeException:
            self.kill_event.set()
            log.warning("ActionExecutor: FailSafe triggered (mouse at top-left corner)")
            return "INTERRUPTED: FailSafe triggered"
        except Exception as e:
            log.error(f"ActionExecutor: '{name}' failed: {e}")
            return f"ERROR: {e}"

    def _dispatch(self, name: str, action: dict) -> str:
        if name == "click":
            pyautogui.click(action["x"], action["y"],
                           button=action.get("button", "left"))
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
            pyautogui.moveTo(action["x1"], action["y1"])
            dx = action["x2"] - action["x1"]
            dy = action["y2"] - action["y1"]
            pyautogui.drag(dx, dy, duration=0.5)
        elif name == "wait":
            time.sleep(min(action.get("seconds", 1), MAX_WAIT))
        elif name == "screenshot":
            return "screenshot_requested"
        elif name == "done":
            return f"DONE: {action.get('summary', '')}"
        elif name == "fail":
            return f"FAIL: {action.get('reason', '')}"
        else:
            return f"REJECTED: unknown action '{name}'"

        return "success"
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_gui_actions.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gui/actions.py tests/test_gui_actions.py
git commit -m "feat(gui): add ActionExecutor with whitelist ACL and kill switch"
```

---

### Task 4: Trajectory — Sliding Window Context

**Files:**
- Create: `src/gui/trajectory.py`
- Test: `tests/test_gui_trajectory.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_gui_trajectory.py
import base64
import time
import pytest
from src.gui.trajectory import Trajectory, TrajectoryStep


class TestTrajectory:
    def test_append_and_len(self):
        t = Trajectory(max_steps=3)
        step = TrajectoryStep(
            screenshot_thumbnail=b"fake_png",
            action={"action": "click", "x": 100, "y": 200},
            result="success",
            timestamp=time.time(),
        )
        t.append(step)
        assert len(t) == 1

    def test_sliding_window_evicts_oldest(self):
        t = Trajectory(max_steps=2)
        for i in range(5):
            t.append(TrajectoryStep(
                screenshot_thumbnail=f"img_{i}".encode(),
                action={"action": "click", "x": i},
                result="success",
                timestamp=time.time(),
            ))
        assert len(t) == 2
        # Most recent steps should be 3 and 4
        assert t.steps[0].screenshot_thumbnail == b"img_3"
        assert t.steps[1].screenshot_thumbnail == b"img_4"

    def test_to_prompt_context_returns_list(self):
        t = Trajectory(max_steps=8)
        t.append(TrajectoryStep(
            screenshot_thumbnail=b"\x89PNG_fake",
            action={"action": "click", "x": 50, "y": 60},
            result="success",
            timestamp=time.time(),
        ))
        ctx = t.to_prompt_context()
        assert isinstance(ctx, list)
        assert len(ctx) == 1
        assert "action" in ctx[0]["text"]

    def test_to_prompt_context_includes_base64_images(self):
        t = Trajectory(max_steps=8)
        t.append(TrajectoryStep(
            screenshot_thumbnail=b"\x89PNG_fake_data",
            action={"action": "type_text", "text": "hello"},
            result="success",
            timestamp=time.time(),
        ))
        ctx = t.to_prompt_context()
        # Each step should have an image reference
        assert "image" in ctx[0] or "screenshot" in str(ctx[0])

    def test_empty_trajectory_returns_empty_context(self):
        t = Trajectory(max_steps=8)
        assert t.to_prompt_context() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_gui_trajectory.py -v`
Expected: FAIL

- [ ] **Step 3: Implement Trajectory**

```python
# src/gui/trajectory.py
"""Sliding window trajectory for GUI engine context.
Keeps the last N steps (screenshot + action + result) for the Reasoner."""
import base64
import json
import time
from dataclasses import dataclass, field


@dataclass
class TrajectoryStep:
    screenshot_thumbnail: bytes    # resized JPEG, ~80-120KB
    action: dict                   # the action that was taken
    result: str                    # "success" / error string
    timestamp: float


@dataclass
class Trajectory:
    max_steps: int = 8
    steps: list[TrajectoryStep] = field(default_factory=list)

    def append(self, step: TrajectoryStep):
        self.steps.append(step)
        if len(self.steps) > self.max_steps:
            self.steps = self.steps[-self.max_steps:]

    def __len__(self):
        return len(self.steps)

    def to_prompt_context(self) -> list[dict]:
        """Convert trajectory to a list of context entries for the Reasoner.
        Each entry has 'text' (action description) and 'image' (base64 screenshot)."""
        entries = []
        for i, step in enumerate(self.steps):
            b64 = base64.b64encode(step.screenshot_thumbnail).decode()
            action_str = json.dumps(step.action, ensure_ascii=False)
            entries.append({
                "text": f"Step {i+1}: action={action_str}, result={step.result}",
                "image": b64,
                "screenshot": b64,
            })
        return entries

    def get_images_b64(self) -> list[str]:
        """Return base64-encoded screenshots for LLM Router images param."""
        return [
            base64.b64encode(s.screenshot_thumbnail).decode()
            for s in self.steps
        ]

    def get_action_summary(self) -> str:
        """Return a text summary of all actions taken so far."""
        lines = []
        for i, step in enumerate(self.steps):
            action_str = json.dumps(step.action, ensure_ascii=False)
            lines.append(f"Step {i+1}: {action_str} → {step.result}")
        return "\n".join(lines)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_gui_trajectory.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gui/trajectory.py tests/test_gui_trajectory.py
git commit -m "feat(gui): add Trajectory sliding window for action context"
```

---

### Task 5: OCRGrounder — Tesseract Word-Level Grounding

**Files:**
- Create: `src/gui/grounder_ocr.py`
- Test: `tests/test_gui_grounder_ocr.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_gui_grounder_ocr.py
import pytest
from unittest.mock import patch, MagicMock
from src.gui.grounder_ocr import OCRGrounder, LocateResult


class TestLocateResult:
    def test_dataclass_fields(self):
        r = LocateResult(x=100, y=200, confidence=85.0, monitor_id=1, method="ocr")
        assert r.x == 100
        assert r.method == "ocr"

    def test_confidence_none_for_vision(self):
        r = LocateResult(x=100, y=200, confidence=None, monitor_id=1, method="vision")
        assert r.confidence is None


class TestOCRGrounder:
    @patch("src.gui.grounder_ocr.pytesseract")
    def test_locate_finds_exact_match(self, mock_tess):
        """When Tesseract finds the exact text, return center of bounding box."""
        # Simulate Tesseract output: word "我喜欢" at box (100, 200, 60, 30)
        mock_tess.image_to_data.return_value = (
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
            "5\t1\t1\t1\t1\t1\t100\t200\t60\t30\t95\t我喜欢\n"
        )
        grounder = OCRGrounder()
        result = grounder.locate("我喜欢", b"fake_png", monitor_id=1)
        assert result is not None
        assert result.x == 130  # center: 100 + 60/2
        assert result.y == 215  # center: 200 + 30/2
        assert result.confidence == 95.0
        assert result.method == "ocr"

    @patch("src.gui.grounder_ocr.pytesseract")
    def test_locate_fuzzy_match(self, mock_tess):
        """When exact text not found, fuzzy match should work (e.g. '我 喜欢' matches '我喜欢')."""
        mock_tess.image_to_data.return_value = (
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
            "5\t1\t1\t1\t1\t1\t100\t200\t40\t30\t90\t我\n"
            "5\t1\t1\t1\t1\t2\t140\t200\t60\t30\t88\t喜欢\n"
        )
        grounder = OCRGrounder()
        result = grounder.locate("我喜欢", b"fake_png", monitor_id=1)
        # Should merge adjacent words and match
        assert result is not None
        assert result.method == "ocr"

    @patch("src.gui.grounder_ocr.pytesseract")
    def test_locate_returns_none_when_not_found(self, mock_tess):
        mock_tess.image_to_data.return_value = (
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
            "5\t1\t1\t1\t1\t1\t100\t200\t60\t30\t95\t设置\n"
        )
        grounder = OCRGrounder()
        result = grounder.locate("退出程序", b"fake_png", monitor_id=1)
        assert result is None

    @patch("src.gui.grounder_ocr.pytesseract")
    def test_locate_rejects_low_confidence(self, mock_tess):
        """Words with confidence < threshold should be ignored."""
        mock_tess.image_to_data.return_value = (
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
            "5\t1\t1\t1\t1\t1\t100\t200\t60\t30\t30\t我喜欢\n"
        )
        grounder = OCRGrounder(min_confidence=70)
        result = grounder.locate("我喜欢", b"fake_png", monitor_id=1)
        assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_gui_grounder_ocr.py -v`
Expected: FAIL

- [ ] **Step 3: Implement OCRGrounder**

```python
# src/gui/grounder_ocr.py
"""OCR-based element grounding using Tesseract.
Finds UI elements by matching text labels in screenshots."""
import logging
from dataclasses import dataclass
from io import BytesIO

from PIL import Image

try:
    import pytesseract
except ImportError:
    pytesseract = None

try:
    from rapidfuzz import fuzz
except ImportError:
    fuzz = None

log = logging.getLogger(__name__)

OCR_LANG = "chi_sim+eng"  # Chinese simplified + English


@dataclass
class LocateResult:
    x: int                      # logical pixels (DPI-adjusted)
    y: int
    confidence: float | None    # 0-100 for OCR, None for vision
    monitor_id: int
    method: str                 # "ocr" | "vision"


class OCRGrounder:
    def __init__(self, min_confidence: int = 70, fuzzy_threshold: int = 80):
        if pytesseract is None:
            raise ImportError("pytesseract is required: pip install pytesseract")
        self.min_confidence = min_confidence
        self.fuzzy_threshold = fuzzy_threshold

    def locate(self, target_text: str, screenshot_png: bytes,
               monitor_id: int = 1) -> LocateResult | None:
        """Find target_text in screenshot. Returns center coords or None."""
        img = Image.open(BytesIO(screenshot_png))
        words = self._extract_words(img)

        if not words:
            log.debug("OCRGrounder: no words detected in screenshot")
            return None

        # Strategy 1: exact single-word match
        for w in words:
            if w["text"] == target_text and w["conf"] >= self.min_confidence:
                cx = w["left"] + w["width"] // 2
                cy = w["top"] + w["height"] // 2
                log.debug(f"OCRGrounder: exact match '{target_text}' at ({cx},{cy}) conf={w['conf']}")
                return LocateResult(x=cx, y=cy, confidence=w["conf"],
                                    monitor_id=monitor_id, method="ocr")

        # Strategy 2: merge adjacent words on same line, then match
        merged = self._merge_adjacent_words(words)
        for m in merged:
            if m["text"] == target_text and m["conf"] >= self.min_confidence:
                cx = m["left"] + m["width"] // 2
                cy = m["top"] + m["height"] // 2
                log.debug(f"OCRGrounder: merged match '{target_text}' at ({cx},{cy}) conf={m['conf']}")
                return LocateResult(x=cx, y=cy, confidence=m["conf"],
                                    monitor_id=monitor_id, method="ocr")

        # Strategy 3: fuzzy match
        if fuzz is not None:
            all_texts = words + merged
            best = None
            best_score = 0
            for w in all_texts:
                if w["conf"] < self.min_confidence:
                    continue
                score = fuzz.ratio(target_text, w["text"])
                if score > best_score:
                    best_score = score
                    best = w
            if best and best_score >= self.fuzzy_threshold:
                cx = best["left"] + best["width"] // 2
                cy = best["top"] + best["height"] // 2
                log.debug(f"OCRGrounder: fuzzy match '{target_text}'≈'{best['text']}' "
                         f"score={best_score} at ({cx},{cy}) conf={best['conf']}")
                return LocateResult(x=cx, y=cy, confidence=best["conf"],
                                    monitor_id=monitor_id, method="ocr")

        log.debug(f"OCRGrounder: '{target_text}' not found")
        return None

    @staticmethod
    def _extract_words(img: Image.Image) -> list[dict]:
        """Run Tesseract and parse word-level bounding boxes."""
        tsv = pytesseract.image_to_data(img, lang=OCR_LANG)
        words = []
        for line in tsv.strip().split("\n")[1:]:  # skip header
            parts = line.split("\t")
            if len(parts) < 12:
                continue
            text = parts[11].strip()
            if not text:
                continue
            try:
                conf = float(parts[10])
            except (ValueError, IndexError):
                conf = 0
            if conf < 0:  # Tesseract uses -1 for non-word blocks
                continue
            words.append({
                "text": text,
                "left": int(parts[6]),
                "top": int(parts[7]),
                "width": int(parts[8]),
                "height": int(parts[9]),
                "conf": conf,
                "line_num": int(parts[4]),
                "word_num": int(parts[5]),
            })
        return words

    @staticmethod
    def _merge_adjacent_words(words: list[dict]) -> list[dict]:
        """Merge words on the same line into compound strings."""
        by_line: dict[int, list[dict]] = {}
        for w in words:
            by_line.setdefault(w["line_num"], []).append(w)

        merged = []
        for line_words in by_line.values():
            line_words.sort(key=lambda w: w["left"])
            for i in range(len(line_words)):
                for j in range(i + 1, min(i + 5, len(line_words) + 1)):
                    chunk = line_words[i:j]
                    text = "".join(w["text"] for w in chunk)
                    left = chunk[0]["left"]
                    top = min(w["top"] for w in chunk)
                    right = max(w["left"] + w["width"] for w in chunk)
                    bottom = max(w["top"] + w["height"] for w in chunk)
                    avg_conf = sum(w["conf"] for w in chunk) / len(chunk)
                    merged.append({
                        "text": text,
                        "left": left,
                        "top": top,
                        "width": right - left,
                        "height": bottom - top,
                        "conf": avg_conf,
                        "line_num": chunk[0]["line_num"],
                        "word_num": chunk[0]["word_num"],
                    })
        return merged
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_gui_grounder_ocr.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gui/grounder_ocr.py tests/test_gui_grounder_ocr.py
git commit -m "feat(gui): add OCRGrounder with Tesseract word-level grounding and fuzzy match"
```

---

### Task 6: GroundingRouter — OCR → Vision Fallback + VisionGrounder Stub

**Files:**
- Create: `src/gui/grounder.py`
- Create: `src/gui/grounder_vision.py`
- Test: `tests/test_gui_grounder.py`

- [ ] **Step 1: Create VisionGrounder stub for Phase 2**

```python
# src/gui/grounder_vision.py
"""Vision-based element grounding using UI-TARS-7B.
Phase 2 implementation — this is a stub for now."""
import logging
from src.gui.grounder_ocr import LocateResult

log = logging.getLogger(__name__)


class VisionGrounder:
    """Stub — will be implemented in Phase 2 with UI-TARS-7B via vLLM."""

    def __init__(self, **kwargs):
        log.info("VisionGrounder: Phase 2 stub — not yet implemented")

    def locate(self, target_text: str, screenshot_png: bytes,
               monitor_id: int = 1) -> LocateResult | None:
        """Phase 2: will use UI-TARS-7B to visually locate elements."""
        raise NotImplementedError(
            "VisionGrounder is a Phase 2 feature. "
            "Install UI-TARS-7B via vLLM and implement grounder_vision.py."
        )
```

- [ ] **Step 2: Implement GroundingRouter**

```python
# src/gui/grounder.py
"""Grounding router: OCR first, Vision fallback.
Phase 1: OCR only. Phase 2 adds VisionGrounder as fallback."""
import logging
from src.gui.grounder_ocr import OCRGrounder, LocateResult
from src.gui.grounder_vision import VisionGrounder

log = logging.getLogger(__name__)


class GroundingRouter:
    def __init__(self, screen_manager=None, enable_vision: bool = False):
        self.ocr = OCRGrounder()
        self.screen_manager = screen_manager
        self.vision = VisionGrounder() if enable_vision else None

    def locate(self, target_text: str, screenshot_png: bytes,
               monitor_id: int = 1) -> LocateResult | None:
        """Try OCR first. If OCR fails, try vision grounding.
        Returns LocateResult with logical pixel coords, or None."""

        # OCR path
        result = self.ocr.locate(target_text, screenshot_png, monitor_id)
        if result is not None:
            return self._apply_coord_transform(result, monitor_id)

        # Vision fallback (Phase 2)
        if self.vision is not None:
            try:
                result = self.vision.locate(target_text, screenshot_png, monitor_id)
                if result is not None:
                    return self._apply_coord_transform(result, monitor_id)
            except NotImplementedError:
                log.debug("GroundingRouter: vision grounding not yet implemented")
            except Exception as e:
                log.warning(f"GroundingRouter: vision grounding failed: {e}")

        log.debug(f"GroundingRouter: '{target_text}' not found by any method")
        return None

    def _apply_coord_transform(self, result: LocateResult, monitor_id: int) -> LocateResult:
        """Convert physical pixel coords → logical coords if screen_manager is available."""
        if self.screen_manager is None:
            return result
        lx, ly = self.screen_manager.to_logical_coords(
            result.x, result.y, monitor_id,
        )
        return LocateResult(
            x=lx, y=ly,
            confidence=result.confidence,
            monitor_id=monitor_id,
            method=result.method,
        )
```

- [ ] **Step 3: Write tests for GroundingRouter**

```python
# tests/test_gui_grounder.py
import pytest
from unittest.mock import MagicMock, patch
from src.gui.grounder import GroundingRouter
from src.gui.grounder_ocr import LocateResult


class TestGroundingRouter:
    def test_ocr_hit_returns_result(self):
        """When OCR finds the element, return its result."""
        router = GroundingRouter(screen_manager=None)
        router.ocr = MagicMock()
        router.ocr.locate.return_value = LocateResult(
            x=100, y=200, confidence=95.0, monitor_id=1, method="ocr",
        )
        result = router.locate("我喜欢", b"fake_png", monitor_id=1)
        assert result is not None
        assert result.x == 100
        assert result.method == "ocr"

    def test_ocr_miss_returns_none_when_no_vision(self):
        """When OCR misses and vision is disabled, return None."""
        router = GroundingRouter(screen_manager=None, enable_vision=False)
        router.ocr = MagicMock()
        router.ocr.locate.return_value = None
        result = router.locate("不存在的按钮", b"fake_png", monitor_id=1)
        assert result is None

    def test_coord_transform_applied_when_screen_manager_present(self):
        """When screen_manager is provided, physical→logical conversion should happen."""
        mock_sm = MagicMock()
        mock_sm.to_logical_coords.return_value = (50, 100)
        router = GroundingRouter(screen_manager=mock_sm)
        router.ocr = MagicMock()
        router.ocr.locate.return_value = LocateResult(
            x=100, y=200, confidence=90.0, monitor_id=1, method="ocr",
        )
        result = router.locate("按钮", b"fake_png", monitor_id=1)
        assert result is not None
        assert result.x == 50   # transformed
        assert result.y == 100  # transformed
        mock_sm.to_logical_coords.assert_called_once_with(100, 200, 1)

    def test_no_coord_transform_when_screen_manager_is_none(self):
        """When screen_manager is None, return raw OCR coords."""
        router = GroundingRouter(screen_manager=None)
        router.ocr = MagicMock()
        router.ocr.locate.return_value = LocateResult(
            x=100, y=200, confidence=90.0, monitor_id=1, method="ocr",
        )
        result = router.locate("按钮", b"fake_png", monitor_id=1)
        assert result.x == 100  # untransformed
        assert result.y == 200

    def test_vision_fallback_on_ocr_miss(self):
        """When OCR misses but vision is enabled, try vision grounding."""
        router = GroundingRouter(screen_manager=None, enable_vision=False)
        router.ocr = MagicMock()
        router.ocr.locate.return_value = None
        # Manually set a mock vision grounder
        router.vision = MagicMock()
        router.vision.locate.return_value = LocateResult(
            x=300, y=400, confidence=None, monitor_id=1, method="vision",
        )
        result = router.locate("图标", b"fake_png", monitor_id=1)
        assert result is not None
        assert result.method == "vision"
        assert result.x == 300
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_gui_grounder.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gui/grounder.py src/gui/grounder_vision.py tests/test_gui_grounder.py
git commit -m "feat(gui): add GroundingRouter with OCR-first strategy + VisionGrounder stub"
```

---

### Task 7: Reasoner Prompts

**Files:**
- Create: `src/gui/prompts.py`

- [ ] **Step 1: Write prompts**

```python
# src/gui/prompts.py
"""Prompt templates for the GUI Reasoner — the LLM that decides what action to take next."""

REASONER_SYSTEM = """You are a GUI automation agent. You see screenshots and decide what action to take next.

You output ONLY valid JSON — one action per response. No markdown, no explanation.

Available actions:
- click: {"action": "click", "x": <int>, "y": <int>, "button": "left"|"right"}
- double_click: {"action": "double_click", "x": <int>, "y": <int>}
- right_click: {"action": "right_click", "x": <int>, "y": <int>}
- type_text: {"action": "type_text", "text": "<string>"}
- hotkey: {"action": "hotkey", "keys": ["ctrl", "a"]}
- scroll: {"action": "scroll", "x": <int>, "y": <int>, "clicks": <int>}
- drag: {"action": "drag", "x1": <int>, "y1": <int>, "x2": <int>, "y2": <int>}
- wait: {"action": "wait", "seconds": <float>}
- done: {"action": "done", "summary": "<what was accomplished>"}
- fail: {"action": "fail", "reason": "<why this can't be done>"}

When you need to click a text element, output:
{"action": "click", "target": "<visible text label>"}
The grounding system will find the coordinates for you.

Rules:
- One action at a time
- If unsure, take a screenshot first: {"action": "screenshot"}
- If stuck after 3 attempts at the same element, use "fail"
- Never guess coordinates — use "target" for text elements
- For non-text elements (icons, images), describe them: {"action": "click", "target": "heart icon next to song title"}
"""

REASONER_STEP_TEMPLATE = """Task: {instruction}
{target_app_line}
Current step: {step_number}/{max_steps}

{trajectory_summary}

Looking at the current screenshot, what is the next action?
Output ONLY the JSON action object."""


def build_reasoner_prompt(instruction: str, step_number: int, max_steps: int,
                          trajectory_summary: str = "", target_app: str = "") -> str:
    target_app_line = f"Target application: {target_app}" if target_app else ""
    return REASONER_STEP_TEMPLATE.format(
        instruction=instruction,
        target_app_line=target_app_line,
        step_number=step_number,
        max_steps=max_steps,
        trajectory_summary=trajectory_summary or "(no actions taken yet)",
    )
```

- [ ] **Step 2: Commit**

```bash
git add src/gui/prompts.py
git commit -m "feat(gui): add Reasoner prompt templates"
```

---

### Task 8: GUIEngine — Main Perception-Action Loop

**Files:**
- Create: `src/gui/engine.py`
- Test: `tests/test_gui_engine.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_gui_engine.py
import json
import threading
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from src.gui.engine import GUIEngine, GUIResult
from src.gui.grounder_ocr import LocateResult
from src.gui.screen import MonitorInfo


FAKE_MONITOR = MonitorInfo(
    id=1, x_offset=0, y_offset=0,
    width=1920, height=1080,
    width_logical=1920, height_logical=1080,
    scale_factor=100,
)


class TestGUIResult:
    def test_success_result(self):
        r = GUIResult(success=True, summary="opened notepad", steps_taken=3)
        assert r.success
        assert r.steps_taken == 3

    def test_failure_result(self):
        r = GUIResult(success=False, summary="element not found", steps_taken=5)
        assert not r.success


class TestGUIEngine:
    @patch("src.gui.engine.ScreenManager")
    @patch("src.gui.engine.GroundingRouter")
    @patch("src.gui.engine.get_router")
    def test_done_action_stops_loop(self, mock_llm_router, mock_grounder_cls, mock_screen_cls):
        """When Reasoner outputs 'done', engine should stop and return success."""
        # Setup mocks
        mock_screen = MagicMock()
        mock_screen.capture.return_value = (b"fake_png", FAKE_MONITOR)
        mock_screen.monitors = [FAKE_MONITOR]
        mock_screen_cls.return_value = mock_screen

        mock_grounder = MagicMock()
        mock_grounder_cls.return_value = mock_grounder

        # LLM returns "done" action on first step
        mock_llm_router.return_value.generate.return_value = json.dumps(
            {"action": "done", "summary": "task completed successfully"}
        )

        engine = GUIEngine(max_steps=5, trajectory_size=3)
        result = engine.execute("do something", monitor_id=1)

        assert result.success
        assert "completed" in result.summary

    @patch("src.gui.engine.ScreenManager")
    @patch("src.gui.engine.GroundingRouter")
    @patch("src.gui.engine.get_router")
    def test_fail_action_stops_loop(self, mock_llm_router, mock_grounder_cls, mock_screen_cls):
        mock_screen = MagicMock()
        mock_screen.capture.return_value = (b"fake_png", FAKE_MONITOR)
        mock_screen.monitors = [FAKE_MONITOR]
        mock_screen_cls.return_value = mock_screen
        mock_grounder_cls.return_value = MagicMock()

        mock_llm_router.return_value.generate.return_value = json.dumps(
            {"action": "fail", "reason": "cannot find the button"}
        )

        engine = GUIEngine(max_steps=5)
        result = engine.execute("click something", monitor_id=1)

        assert not result.success
        assert "cannot find" in result.summary

    @patch("src.gui.engine.ScreenManager")
    @patch("src.gui.engine.GroundingRouter")
    @patch("src.gui.engine.get_router")
    @patch("src.gui.engine.ActionExecutor")
    def test_max_steps_reached(self, mock_executor_cls, mock_llm_router,
                                mock_grounder_cls, mock_screen_cls):
        """Engine should stop after max_steps and return failure."""
        mock_screen = MagicMock()
        mock_screen.capture.return_value = (b"fake_png", FAKE_MONITOR)
        mock_screen.monitors = [FAKE_MONITOR]
        mock_screen_cls.return_value = mock_screen
        mock_grounder_cls.return_value = MagicMock()
        mock_executor_cls.return_value.execute.return_value = "success"

        # LLM always returns click (never done)
        mock_llm_router.return_value.generate.return_value = json.dumps(
            {"action": "click", "x": 100, "y": 200}
        )

        engine = GUIEngine(max_steps=3)
        result = engine.execute("infinite task", monitor_id=1)

        assert not result.success
        assert result.steps_taken == 3

    @patch("src.gui.engine.ScreenManager")
    @patch("src.gui.engine.GroundingRouter")
    @patch("src.gui.engine.get_router")
    @patch("src.gui.engine.ActionExecutor")
    def test_target_based_click_uses_grounder(self, mock_executor_cls, mock_llm_router,
                                               mock_grounder_cls, mock_screen_cls):
        """When action has 'target' instead of coords, grounder should be called."""
        mock_screen = MagicMock()
        mock_screen.capture.return_value = (b"fake_png", FAKE_MONITOR)
        mock_screen.monitors = [FAKE_MONITOR]
        mock_screen.to_global_coords.return_value = (300, 400)
        mock_screen_cls.return_value = mock_screen

        mock_grounder = MagicMock()
        mock_grounder.locate.return_value = LocateResult(x=300, y=400, confidence=95.0, monitor_id=1, method="ocr")
        mock_grounder_cls.return_value = mock_grounder

        mock_executor = MagicMock()
        call_count = [0]
        def side_effect(action):
            call_count[0] += 1
            return "success"
        mock_executor.execute.side_effect = side_effect
        mock_executor_cls.return_value = mock_executor

        # First call: click with target, second call: done
        responses = [
            json.dumps({"action": "click", "target": "我喜欢"}),
            json.dumps({"action": "done", "summary": "clicked it"}),
        ]
        mock_llm_router.return_value.generate.side_effect = responses

        engine = GUIEngine(max_steps=5)
        result = engine.execute("click the favorite button", monitor_id=1)

        mock_grounder.locate.assert_called_once()
        # The executor should have received resolved coordinates
        executed_action = mock_executor.execute.call_args_list[0][0][0]
        assert executed_action["x"] == 300
        assert executed_action["y"] == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_gui_engine.py -v`
Expected: FAIL

- [ ] **Step 3: Implement GUIEngine**

```python
# src/gui/engine.py
"""GUIEngine — main perception-action loop.
Captures screen → asks LLM what to do → locates elements → executes action → repeats."""
import base64
import json
import logging
import threading
import time
from dataclasses import dataclass
from io import BytesIO

from PIL import Image

from src.gui.actions import ActionExecutor
from src.gui.grounder import GroundingRouter
from src.gui.prompts import REASONER_SYSTEM, build_reasoner_prompt
from src.gui.screen import ScreenManager
from src.gui.trajectory import Trajectory, TrajectoryStep
from src.core.llm_router import get_router

log = logging.getLogger(__name__)

THUMBNAIL_WIDTH = 640  # resize screenshots for trajectory context


@dataclass
class GUIResult:
    success: bool
    summary: str
    steps_taken: int
    trajectory: Trajectory | None = None


class GUIEngine:
    def __init__(self, max_steps: int = 15, trajectory_size: int = 8):
        self.max_steps = max_steps
        self.kill_event = threading.Event()
        self.screen = ScreenManager()
        self.grounder = GroundingRouter(screen_manager=self.screen)
        self.executor = ActionExecutor(self.kill_event)
        self.trajectory = Trajectory(max_steps=trajectory_size)
        self._kill_listener = None

    def execute(self, instruction: str, target_app: str = "",
                monitor_id: int = 1) -> GUIResult:
        """Run the full GUI automation loop. Returns GUIResult."""
        self._start_kill_listener()
        try:
            return self._run_loop(instruction, target_app, monitor_id)
        finally:
            self._stop_kill_listener()

    def _run_loop(self, instruction: str, target_app: str,
                  monitor_id: int) -> GUIResult:
        router = get_router()

        for step in range(1, self.max_steps + 1):
            # Check kill switch
            if self.kill_event.is_set():
                return GUIResult(
                    success=False,
                    summary="INTERRUPTED: kill switch activated",
                    steps_taken=step - 1,
                    trajectory=self.trajectory,
                )

            # 1. Capture screenshot
            screenshot_png, monitor_info = self.screen.capture(monitor_id)
            thumbnail = self._make_thumbnail(screenshot_png)

            # 2. Ask Reasoner what to do
            prompt = build_reasoner_prompt(
                instruction=instruction,
                step_number=step,
                max_steps=self.max_steps,
                trajectory_summary=self.trajectory.get_action_summary(),
                target_app=target_app,
            )
            # Build image list: recent trajectory + current screenshot
            current_b64 = base64.b64encode(thumbnail).decode()
            images = self.trajectory.get_images_b64() + [current_b64]

            # Note: gui_reason uses vision-capable model (gemma3:27b).
            # Qwen3 is text-only and would silently ignore images.
            raw_response = router.generate(
                f"{REASONER_SYSTEM}\n\n{prompt}",
                task_type="gui_reason",
                images=images[-3:],  # last 3 screenshots to save tokens
            )
            action = self._parse_action(raw_response)
            if action is None:
                log.warning(f"GUIEngine step {step}: failed to parse LLM response: {raw_response[:200]}")
                self.trajectory.append(TrajectoryStep(
                    screenshot_thumbnail=thumbnail,
                    action={"action": "parse_error"},
                    result=f"failed to parse: {raw_response[:100]}",
                    timestamp=time.time(),
                ))
                continue

            # 3. Handle control signals
            action_name = action.get("action", "")
            if action_name == "done":
                summary = action.get("summary", "task completed")
                return GUIResult(success=True, summary=summary,
                                steps_taken=step, trajectory=self.trajectory)
            if action_name == "fail":
                reason = action.get("reason", "unknown failure")
                return GUIResult(success=False, summary=reason,
                                steps_taken=step, trajectory=self.trajectory)

            # 4. Resolve target → coordinates via grounder
            if "target" in action and "x" not in action:
                locate_result = self.grounder.locate(
                    action["target"], screenshot_png, monitor_id,
                )
                if locate_result is None:
                    log.info(f"GUIEngine step {step}: element '{action['target']}' not found")
                    self.trajectory.append(TrajectoryStep(
                        screenshot_thumbnail=thumbnail,
                        action=action,
                        result=f"element not found: {action['target']}",
                        timestamp=time.time(),
                    ))
                    continue
                # Inject resolved coords, convert to global
                gx, gy = self.screen.to_global_coords(
                    locate_result.x, locate_result.y, monitor_id,
                )
                action["x"] = gx
                action["y"] = gy
                action.pop("target", None)

            # 5. Execute action
            result_str = self.executor.execute(action)
            log.info(f"GUIEngine step {step}: {action_name} → {result_str}")

            if result_str.startswith("INTERRUPTED"):
                return GUIResult(success=False, summary=result_str,
                                steps_taken=step, trajectory=self.trajectory)

            # 6. Record in trajectory
            self.trajectory.append(TrajectoryStep(
                screenshot_thumbnail=thumbnail,
                action=action,
                result=result_str,
                timestamp=time.time(),
            ))

        # Max steps exhausted
        return GUIResult(
            success=False,
            summary=f"max steps ({self.max_steps}) reached without completion",
            steps_taken=self.max_steps,
            trajectory=self.trajectory,
        )

    @staticmethod
    def _parse_action(raw: str) -> dict | None:
        """Parse JSON action from LLM response. Handles markdown code blocks."""
        text = raw.strip()
        # Strip markdown code fence if present
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1]) if len(lines) > 2 else lines[0]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON object in the text
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start:end])
                except json.JSONDecodeError:
                    return None
        return None

    @staticmethod
    def _make_thumbnail(png_bytes: bytes) -> bytes:
        """Resize screenshot to THUMBNAIL_WIDTH for trajectory storage."""
        img = Image.open(BytesIO(png_bytes))
        ratio = THUMBNAIL_WIDTH / img.width
        new_size = (THUMBNAIL_WIDTH, round(img.height * ratio))
        img = img.resize(new_size, Image.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=75)
        return buf.getvalue()

    def _start_kill_listener(self):
        """Start ESC key listener in daemon thread."""
        try:
            from pynput import keyboard

            def on_press(key):
                if key == keyboard.Key.esc:
                    log.warning("GUIEngine: ESC pressed, activating kill switch")
                    self.kill_event.set()
                    return False  # stop listener

            self._kill_listener = keyboard.Listener(on_press=on_press)
            self._kill_listener.daemon = True
            self._kill_listener.start()
            log.info("GUIEngine: kill switch listener started (press ESC to interrupt)")
        except ImportError:
            log.warning("GUIEngine: pynput not available, kill switch disabled")

    def _stop_kill_listener(self):
        if self._kill_listener is not None:
            self._kill_listener.stop()
            self._kill_listener = None
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_gui_engine.py -v`
Expected: All PASS.

- [ ] **Step 5: Run all GUI tests together**

Run: `python -m pytest tests/test_gui_*.py -v`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add src/gui/engine.py src/gui/grounder.py src/gui/prompts.py tests/test_gui_engine.py
git commit -m "feat(gui): add GUIEngine main loop with perception-action cycle"
```

---

### Task 9: LLM Router — Add gui_reason Route

**Files:**
- Modify: `src/core/llm_router.py:19-28` (ROUTES dict)

- [ ] **Step 1: Add gui_reason route to ROUTES**

In `src/core/llm_router.py`, add to the `ROUTES` dict:

```python
# gui_reason MUST use a vision-capable model (gemma3) since it receives screenshots.
# Qwen3 is text-only and would silently ignore image inputs.
"gui_reason": {"backend": "ollama", "model": "gemma3:27b", "timeout": 45, "fallback": "claude", "fallback_model": "claude-haiku-4-5-20251001"},
```

- [ ] **Step 2: Write a test for the new route**

Add to `tests/test_llm_router.py`:

```python
def test_gui_reason_route_exists():
    """gui_reason route should use a vision-capable model with claude fallback."""
    assert "gui_reason" in ROUTES
    route = ROUTES["gui_reason"]
    assert route["backend"] == "ollama"
    assert route["model"] == "gemma3:27b"  # must be multimodal, not text-only
    assert route["fallback"] == "claude"
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_llm_router.py -v`
Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add src/core/llm_router.py tests/test_llm_router.py
git commit -m "feat(router): add gui_reason route for GUI engine reasoner"
```

---

### Task 10: Package Export + Smoke Test

**Files:**
- Modify: `src/gui/__init__.py`

- [ ] **Step 1: Update package init with exports**

```python
# src/gui/__init__.py
from src.gui.engine import GUIEngine, GUIResult
from src.gui.screen import ScreenManager, MonitorInfo
from src.gui.grounder_ocr import LocateResult

__all__ = ["GUIEngine", "GUIResult", "ScreenManager", "MonitorInfo", "LocateResult"]
```

- [ ] **Step 2: Run full test suite to make sure nothing is broken**

Run: `python -m pytest tests/ -v --tb=short`
Expected: All existing tests still PASS + all new GUI tests PASS.

- [ ] **Step 3: Commit**

```bash
git add src/gui/__init__.py
git commit -m "feat(gui): Phase 1 complete — GUI engine with OCR grounding, kill switch, multi-monitor"
```

---

## Summary

| Task | What | Files | Depends On |
|------|------|-------|-----------|
| 1 | Install dependencies | requirements.txt | — |
| 2 | ScreenManager | screen.py + test | 1 |
| 3 | ActionExecutor | actions.py + test | 1 |
| 4 | Trajectory | trajectory.py + test | 1 |
| 5 | OCRGrounder | grounder_ocr.py + test | 1 |
| 6 | GroundingRouter + VisionGrounder stub | grounder.py + grounder_vision.py + test | 5 |
| 7 | Prompts | prompts.py | — |
| 8 | GUIEngine | engine.py + test | 2, 3, 4, 6, 7 |
| 9 | LLM Router route (gemma3:27b) | llm_router.py | — |
| 10 | Package export + smoke | __init__.py | all |

**Tasks 2, 3, 4, 5 can run in parallel** (no dependencies between them). Task 8 depends on all of them.

## Spec Deviations

| Spec says | Plan does | Reason |
|-----------|-----------|--------|
| Reasoner uses Qwen3:32b | Uses gemma3:27b | Qwen3 is text-only, cannot process screenshots. gemma3 is already deployed as vision route. |
| `capture(monitor_id=0)` for all monitors | Implemented | Phase 1 supports it via mss virtual screen |
| `pynput` not in spec §8 deps | Added to requirements.txt | Required by spec §11 (kill switch). Spec oversight. |
