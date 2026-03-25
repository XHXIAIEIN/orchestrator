"""DesktopEngine -- perception-action loop for GUI automation.

Orchestrates screenshot capture, LLM reasoning, element grounding (OCR),
and action execution in a kill-switch-protected loop.

All components are pluggable via constructor injection.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
import threading
import time

from .types import GUIResult, MonitorInfo, LocateResult, OCRWord, TrajectoryStep
from .ocr import OCREngine, WinOCREngine
from .match import MatchStrategy, FuzzyMatchStrategy
from .screen import ScreenCapture, MSSScreenCapture
from .window import WindowManager, Win32WindowManager
from .actions import ActionExecutor, PyAutoGUIExecutor
from .trajectory import Trajectory
from .prompts import REASONER_SYSTEM, build_reasoner_prompt

try:
    from PIL import Image as _PIL_Image
except ImportError:
    _PIL_Image = None  # type: ignore[assignment]

log = logging.getLogger(__name__)


class DesktopEngine:
    """Main desktop automation engine.

    All components are injectable. If not provided, defaults are used.

    Args:
        max_steps: Maximum perception-action steps before giving up.
        trajectory_size: How many recent steps to keep in the sliding window.
        background: If True, use background input (PostMessage/SendMessage).
        ocr_engine: OCR backend (default: WinOCREngine).
        match_strategy: Text matching (default: FuzzyMatchStrategy).
        screen: Screen capture backend (default: MSSScreenCapture).
        window: Window management backend (default: Win32WindowManager).
        executor: Action executor (default: PyAutoGUIExecutor).
        ocr_lang: Language code for OCR (default: "zh-Hans-CN").
    """

    def __init__(
        self,
        max_steps: int = 15,
        trajectory_size: int = 8,
        background: bool = False,
        ocr_engine: OCREngine | None = None,
        match_strategy: MatchStrategy | None = None,
        screen: ScreenCapture | None = None,
        window: WindowManager | None = None,
        executor: ActionExecutor | None = None,
        ocr_lang: str = "zh-Hans-CN",
    ) -> None:
        self.max_steps = max_steps
        self.background = background
        self.kill_event = threading.Event()

        self.ocr_engine = ocr_engine or WinOCREngine()
        self.match_strategy = match_strategy or FuzzyMatchStrategy()
        self.screen = screen or MSSScreenCapture()
        self.window = window or Win32WindowManager()
        self.executor = executor or PyAutoGUIExecutor(self.kill_event)
        self.trajectory = Trajectory(max_steps=trajectory_size)
        self.ocr_lang = ocr_lang
        self._kill_listener = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(self, instruction: str, target_app: str = "",
                monitor_id: int = 1, process_name: str = "",
                window_title: str = "") -> GUIResult:
        """Run the automation loop for *instruction*.

        Window targeting (optional but recommended):
            process_name: lock onto window by process (e.g. "notepad")
            window_title: lock onto window by title substring

        When a window is locked:
            - background=True:  screenshots via PrintWindow, input via SendMessage
            - background=False: focus window first, then use pyautogui
        """
        self.kill_event.clear()

        # Lock onto target window if specified
        target_spec = process_name or window_title or target_app
        if target_spec:
            info = self.window.lock(
                process_name=process_name,
                title_contains=window_title or target_app,
            )
            if info:
                log.info("engine: locked onto '%s' (bg=%s)", info.title, self.background)
            else:
                log.warning("engine: could not find window '%s', running unlocked",
                            target_spec)

        self._start_kill_listener()
        try:
            result = self._run_loop(instruction, target_app, monitor_id)
        finally:
            self._stop_kill_listener()
            self.window.unlock()
        return result

    def read_text(self, window_title: str = "", monitor_id: int = 1) -> list[str]:
        """Convenience: capture a window (or screen) and OCR all text lines.

        No LLM loop -- just capture + OCR.
        """
        screenshot_png = b""

        if window_title:
            info = self.window.lock(title_contains=window_title)
            if info:
                png = self.window.capture_window()
                if png:
                    screenshot_png = png
            self.window.unlock()

        if not screenshot_png:
            screenshot_png, _ = self.screen.capture(monitor_id)

        if not screenshot_png:
            return []

        img = _PIL_Image.open(io.BytesIO(screenshot_png))
        words = self.ocr_engine.extract_words(img, self.ocr_lang)
        if not words:
            return []

        # Group by line
        by_line: dict[int, list[OCRWord]] = {}
        for w in words:
            by_line.setdefault(w.line_num, []).append(w)

        lines = []
        for line_num in sorted(by_line.keys()):
            line_words = sorted(by_line[line_num], key=lambda w: w.left)
            lines.append("".join(w.text for w in line_words))
        return lines

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    def _run_loop(self, instruction: str, target_app: str, monitor_id: int) -> GUIResult:
        """Main perception-action loop."""
        for step_num in range(1, self.max_steps + 1):
            # 1. Kill-switch check
            if self.kill_event.is_set():
                log.info("engine: kill event set -- aborting at step %d", step_num)
                return GUIResult(
                    success=False,
                    summary="INTERRUPTED by kill switch",
                    steps_taken=step_num - 1,
                    trajectory=self.trajectory,
                )

            # 2. Capture screenshot
            screenshot_png = self._capture(monitor_id)

            # 3. Make thumbnail
            thumbnail = self._make_thumbnail(screenshot_png)
            thumb_b64 = base64.b64encode(thumbnail).decode("ascii")

            # 4. Build reasoner prompt
            prompt = build_reasoner_prompt(
                instruction=instruction,
                step_number=step_num,
                max_steps=self.max_steps,
                trajectory_summary=self.trajectory.get_action_summary(),
                target_app=target_app,
            )

            # 5. Collect images: trajectory history + current thumbnail (last 3 total)
            images_b64 = self.trajectory.get_images_b64()
            images_b64.append(thumb_b64)
            images_b64 = images_b64[-3:]

            # Call LLM
            from src.core.llm_router import get_router
            raw_response = get_router().generate(
                REASONER_SYSTEM + "\n\n" + prompt,
                task_type="gui_reason",
                images=images_b64,
            )

            # 6. Parse action
            action = self._parse_action(raw_response)
            if action is None:
                log.warning("engine: step %d -- failed to parse LLM response: %r",
                            step_num, raw_response[:200])
                self.trajectory.append(TrajectoryStep(
                    screenshot_thumbnail=thumbnail,
                    action={"action": "parse_error", "raw": raw_response[:200]},
                    result="parse_error",
                    timestamp=time.time(),
                ))
                continue

            action_name = action.get("action", "")

            # 7. Done / Fail signals
            if action_name == "done":
                summary = action.get("summary", "Task completed")
                log.info("engine: step %d -- DONE: %s", step_num, summary)
                return GUIResult(
                    success=True,
                    summary=summary,
                    steps_taken=step_num,
                    trajectory=self.trajectory,
                )

            if action_name == "fail":
                reason = action.get("reason", "Unknown failure")
                log.info("engine: step %d -- FAIL: %s", step_num, reason)
                return GUIResult(
                    success=False,
                    summary=reason,
                    steps_taken=step_num,
                    trajectory=self.trajectory,
                )

            # 8. Target-based grounding -- resolve "target" -> x/y via OCR
            if "target" in action and "x" not in action:
                target_text = action["target"]
                locate_result = self._locate(target_text, screenshot_png, monitor_id)
                if locate_result is None:
                    log.warning("engine: step %d -- OCR failed to locate %r",
                                step_num, target_text)
                    self.trajectory.append(TrajectoryStep(
                        screenshot_thumbnail=thumbnail,
                        action=action,
                        result=f"grounding_failed: {target_text!r}",
                        timestamp=time.time(),
                    ))
                    continue

                # Convert to global logical coords
                gx, gy = self.screen.to_global_coords(
                    locate_result.x, locate_result.y, monitor_id
                )
                action = dict(action)
                action["x"] = gx
                action["y"] = gy
                del action["target"]

            # 9. Execute action
            if self.background and self.window.target:
                result_str = self._execute_background(action)
            else:
                if self.window.target:
                    self.window.focus()
                result_str = self.executor.execute(action)

            # 10. Kill check after execution
            if result_str.startswith("INTERRUPTED"):
                log.warning("engine: step %d -- execution interrupted: %s",
                            step_num, result_str)
                return GUIResult(
                    success=False,
                    summary=result_str,
                    steps_taken=step_num,
                    trajectory=self.trajectory,
                )

            # 11. Append to trajectory
            self.trajectory.append(TrajectoryStep(
                screenshot_thumbnail=thumbnail,
                action=action,
                result=result_str,
                timestamp=time.time(),
            ))

        # Max steps exhausted
        log.info("engine: max steps (%d) reached", self.max_steps)
        return GUIResult(
            success=False,
            summary="max steps reached",
            steps_taken=self.max_steps,
            trajectory=self.trajectory,
        )

    # ------------------------------------------------------------------
    # OCR-based grounding
    # ------------------------------------------------------------------

    def _locate(self, target_text: str, screenshot_png: bytes,
                monitor_id: int) -> LocateResult | None:
        """Locate a text element in the screenshot using OCR + match strategy."""
        if _PIL_Image is None:
            return None
        img = _PIL_Image.open(io.BytesIO(screenshot_png))
        words = self.ocr_engine.extract_words(img, self.ocr_lang)
        hit = self.match_strategy.match(target_text, words)
        if hit is None:
            return None

        cx = hit.left + hit.width // 2
        cy = hit.top + hit.height // 2

        # Apply DPI coordinate transform
        lx, ly = self.screen.to_logical_coords(cx, cy, monitor_id)

        return LocateResult(
            x=lx, y=ly,
            confidence=hit.conf,
            monitor_id=monitor_id,
            method="ocr",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _capture(self, monitor_id: int) -> bytes:
        """Capture screenshot -- window-specific if locked, else full monitor."""
        if self.window.target:
            if not self.window.is_alive():
                log.warning("engine: target window is gone")
                return b""
            png = self.window.capture_window()
            if png:
                return png
            log.warning("engine: PrintWindow failed, falling back to screen capture")
        png, _ = self.screen.capture(monitor_id)
        return png

    def _execute_background(self, action: dict) -> str:
        """Execute action via WindowManager (background, no focus needed)."""
        name = action.get("action", "")
        wm = self.window

        try:
            if name == "type_text":
                ok = wm.send_text(action["text"])
                return "success" if ok else "ERROR: send_text failed"

            elif name == "click":
                ok = wm.send_click(action["x"], action["y"],
                                   action.get("button", "left"))
                return "success" if ok else "ERROR: send_click failed"

            elif name == "hotkey":
                ok = wm.send_hotkey(*action["keys"])
                return "success" if ok else "ERROR: send_hotkey failed"

            elif name == "scroll":
                # No background scroll support yet, fall back to foreground
                wm.focus()
                return self.executor.execute(action)

            elif name == "wait":
                time.sleep(min(action.get("seconds", 1), 10))
                return "success"

            elif name == "screenshot":
                return "screenshot_requested"

            elif name in ("done", "fail", "double_click", "right_click", "drag"):
                wm.focus()
                return self.executor.execute(action)

            else:
                return f"REJECTED: unknown action '{name}'"

        except Exception as e:
            log.error("engine: background action '%s' failed: %s", name, e)
            return f"ERROR: {e}"

    @staticmethod
    def _parse_action(raw: str) -> dict | None:
        """Parse JSON action from LLM response.

        Handles:
        - Clean JSON
        - Markdown code fences (```json ... ```)
        - JSON embedded in surrounding text
        """
        if not raw:
            return None

        # Strip markdown code fences
        text = re.sub(r"```(?:json)?\s*", "", raw).strip()
        text = text.replace("```", "").strip()

        # Try direct parse first
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

        # Fallback: find first {...} block in original raw text
        match = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
        if match:
            try:
                obj = json.loads(match.group())
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                pass

        return None

    @staticmethod
    def _make_thumbnail(png_bytes: bytes) -> bytes:
        """Resize PNG to 640px wide and return JPEG bytes."""
        if _PIL_Image is None:
            return png_bytes

        img = _PIL_Image.open(io.BytesIO(png_bytes))
        target_width = 640
        w, h = img.size
        target_height = int(h * target_width / w)
        img = img.resize((target_width, target_height), _PIL_Image.LANCZOS)

        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=75)
        return buf.getvalue()

    def _start_kill_listener(self) -> None:
        """Start ESC key listener as a daemon thread."""
        try:
            from pynput import keyboard

            def on_press(key):
                if key == keyboard.Key.esc:
                    log.info("engine: ESC pressed -- setting kill event")
                    self.kill_event.set()

            listener = keyboard.Listener(on_press=on_press)
            listener.daemon = True
            listener.start()
            self._kill_listener = listener
        except ImportError:
            log.debug("engine: pynput not available -- ESC kill listener disabled")
            self._kill_listener = None
        except Exception as exc:
            log.warning("engine: failed to start kill listener: %s", exc)
            self._kill_listener = None

    def _stop_kill_listener(self) -> None:
        """Stop the kill listener if running."""
        if self._kill_listener is not None:
            try:
                self._kill_listener.stop()
            except Exception as exc:
                log.debug("engine: error stopping kill listener: %s", exc)
            finally:
                self._kill_listener = None
