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
from .input_capture import InputCapture

try:
    from PIL import Image as _PIL_Image
except ImportError:
    _PIL_Image = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

POST_ACTION_DELAY = 0.75  # seconds -- let UI settle before post-action screenshot


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
        capture_input: bool = False,
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
        self._input_capture = InputCapture() if capture_input else None

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
        if self._input_capture:
            self._input_capture.start()
        try:
            result = self._run_loop(instruction, target_app, monitor_id)
        finally:
            if self._input_capture:
                self._input_capture.stop()
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
        # Post-action screenshot cache: reuse on next iteration to avoid
        # redundant captures.  None means "take a fresh screenshot".
        _cached_screenshot: bytes | None = None
        _cached_thumbnail: bytes | None = None

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

            # 1.5 Drain user input events into trajectory
            if self._input_capture:
                for user_action in self._input_capture.drain():
                    self.trajectory.append(TrajectoryStep(
                        screenshot_thumbnail=b"",
                        action=user_action,
                        result="user_input",
                        timestamp=time.time(),
                        source="user",
                    ))

            # 2. Capture screenshot (reuse post-action cache if available)
            if _cached_screenshot is not None:
                screenshot_png = _cached_screenshot
                thumbnail = _cached_thumbnail
                _cached_screenshot = None
                _cached_thumbnail = None
            else:
                screenshot_png = self._capture(monitor_id)
                thumbnail = self._make_thumbnail(screenshot_png)

            thumb_b64 = base64.b64encode(thumbnail).decode("ascii")

            # 3. Build reasoner prompt
            prompt = build_reasoner_prompt(
                instruction=instruction,
                step_number=step_num,
                max_steps=self.max_steps,
                trajectory_summary=self.trajectory.get_action_summary(),
                target_app=target_app,
            )

            # 4. Collect images: trajectory history + current thumbnail (last 3 total)
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

            # 5. Parse action
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

            # 6. Done / Fail signals
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

            # 7. Target-based grounding -- resolve "target" -> x/y via OCR
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

            # 8. Execute action
            if self.background and self.window.target:
                result_str = self._execute_background(action)
            else:
                if self.window.target:
                    self.window.focus()
                result_str = self.executor.execute(action)

            # 9. Kill check after execution
            if result_str.startswith("INTERRUPTED"):
                log.warning("engine: step %d -- execution interrupted: %s",
                            step_num, result_str)
                return GUIResult(
                    success=False,
                    summary=result_str,
                    steps_taken=step_num,
                    trajectory=self.trajectory,
                )

            # 10. Post-action screenshot: wait for UI to settle, then capture.
            #     Cache it so next iteration skips redundant capture.
            if result_str == "success" and action_name not in ("wait", "screenshot"):
                time.sleep(POST_ACTION_DELAY)
                _cached_screenshot = self._capture(monitor_id)
                _cached_thumbnail = self._make_thumbnail(_cached_screenshot)
                post_thumb = _cached_thumbnail
            else:
                post_thumb = thumbnail

            # 11. Append to trajectory (mask sensitive text, use post-action screenshot)
            logged_action = _mask_sensitive(action)
            self.trajectory.append(TrajectoryStep(
                screenshot_thumbnail=post_thumb,
                action=logged_action,
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
        """Locate a text element using text-first strategy + OCR fallback.

        从 Carbonyl 偷师 #2: TextCaptureDevice 文本保真拦截。
        Carbonyl 在 Skia 光栅化前拦截文字，根本不需要 OCR。
        同理：如果 Win32 API 能直接拿到控件文本和坐标，就不走 OCR。
        分层策略: Win32 文本 → OCR fallback，和 Carbonyl 的
        TextCapture + 像素 fallback 同构。
        """
        # ── 快速路径: Win32 控件文本匹配（0ms，confidence=1.0）──
        result = self._locate_via_win32(target_text, monitor_id)
        if result is not None:
            return result

        # ── 慢路径: OCR 文本匹配（~100ms）──
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

    def _locate_via_win32(self, target_text: str,
                          monitor_id: int) -> LocateResult | None:
        """尝试通过 Win32 API 定位文本元素（不需要截图/OCR）。

        仅在有锁定窗口时可用——通过 EnumChildWindows 获取控件文本
        和坐标，做模糊匹配。成本为零，准确度 100%。
        """
        if not self.window.target:
            return None
        try:
            from .perception import Win32Layer
            hwnd = self.window.target.hwnd
            info = self.window.target
            rect = (info.rect.left, info.rect.top, info.rect.right, info.rect.bottom)

            layer = Win32Layer()
            result = layer.analyze(hwnd, rect)
            if not result.elements:
                return None

            # 构造 OCRWord 格式的列表给 match_strategy 复用
            pseudo_words = []
            for el in result.elements:
                if not el.text or not el.text.strip():
                    continue
                x1, y1, x2, y2 = el.rect
                pseudo_words.append(OCRWord(
                    text=el.text,
                    left=x1, top=y1,
                    width=x2 - x1, height=y2 - y1,
                    conf=100.0,
                    line_num=0, word_num=0,
                ))

            if not pseudo_words:
                return None

            hit = self.match_strategy.match(target_text, pseudo_words)
            if hit is None:
                return None

            cx = hit.left + hit.width // 2
            cy = hit.top + hit.height // 2
            # Win32 坐标已经是全局逻辑坐标（GetWindowRect 返回的）
            return LocateResult(
                x=cx, y=cy,
                confidence=1.0,
                monitor_id=monitor_id,
                method="win32",
            )
        except Exception as exc:
            log.debug("win32 locate fallthrough: %s", exc)
            return None

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
            if name in ("type_text", "paste_text"):
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

    def analyze(self, window_title: str = "", process_name: str = "",
                force: bool = False):
        """Analyze a window and return its UIBlueprint.

        Uses multi-layer perception: Win32 API -> CV edge detection -> OCR.
        Results are cached by window_class + size.
        """
        from .blueprint import BlueprintBuilder
        from .perception import Win32Layer, CVLayer, OCRLayer
        from .types import UIBlueprint

        # Lock onto window
        info = self.window.lock(title_contains=window_title, process_name=process_name)
        if not info:
            return UIBlueprint("unknown", (0, 0))

        # Build perception layers (lazy init)
        if not hasattr(self, '_blueprint_builder'):
            layers = [Win32Layer(), CVLayer(), OCRLayer(engine=self.ocr_engine)]
            self._blueprint_builder = BlueprintBuilder(layers=layers)

        rect = info.rect
        bp = self._blueprint_builder.build(
            hwnd=info.hwnd,
            window_class=info.class_name,
            rect=rect,
            force=force,
            screenshot_fn=self.window.capture_window,
        )
        return bp

    def read_zone(self, blueprint, zone_name: str) -> list[str]:
        """Read text from a dynamic zone using cropped OCR."""
        zone = blueprint.zone(zone_name)
        if not zone:
            return []

        # Capture window
        png = self.window.capture_window()
        if not png:
            return []

        # Crop to zone
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(png))
        zx1, zy1, zx2, zy2 = zone.rect
        cropped = img.crop((zx1, zy1, zx2, zy2))

        # OCR the crop
        words = self.ocr_engine.extract_words(cropped, "zh-Hans-CN")
        by_line = {}
        for w in words:
            by_line.setdefault(w.line_num, []).append(w)
        lines = []
        for ln in sorted(by_line):
            line_words = sorted(by_line[ln], key=lambda w: w.left)
            lines.append("".join(w.text for w in line_words))
        return lines


def _mask_sensitive(action: dict) -> dict:
    """Return a copy of *action* with text masked if sensitive=True."""
    if not action.get("sensitive"):
        return action
    masked = dict(action)
    if "text" in masked:
        masked["text"] = "***"
    return masked
