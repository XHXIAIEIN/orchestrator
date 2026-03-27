"""Tests for GUIEngine — perception-action loop."""

from __future__ import annotations

import json
import threading
from unittest.mock import MagicMock, patch

import pytest

from src.desktop_use.grounder_ocr import LocateResult
from src.desktop_use.screen import MonitorInfo

FAKE_MONITOR = MonitorInfo(
    id=1, x_offset=0, y_offset=0,
    width=1920, height=1080,
    width_logical=1920, height_logical=1080,
    scale_factor=100,
)


def _make_fake_png() -> bytes:
    """Return valid PNG bytes (small RGB image, Pillow-generated)."""
    import io
    from PIL import Image
    img = Image.new("RGB", (64, 36), color=(100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestGUIEngineDoneAction:
    """LLM returns 'done' → GUIResult.success=True."""

    @patch("src.desktop_use.engine.ScreenManager")
    @patch("src.desktop_use.engine.GroundingRouter")
    @patch("src.desktop_use.engine.get_router")
    def test_done_action_stops_loop(self, mock_get_router, mock_grounder_cls, mock_screen_cls):
        mock_screen = MagicMock()
        mock_screen.capture.return_value = (_make_fake_png(), FAKE_MONITOR)
        mock_screen.monitors = [FAKE_MONITOR]
        mock_screen_cls.return_value = mock_screen

        mock_grounder_cls.return_value = MagicMock()

        mock_get_router.return_value.generate.return_value = json.dumps(
            {"action": "done", "summary": "task completed"}
        )

        from src.desktop_use.engine import GUIEngine
        engine = GUIEngine(max_steps=15)
        result = engine.execute("Open Notepad")

        assert result.success is True
        assert result.steps_taken == 1


class TestGUIEngineFailAction:
    """LLM returns 'fail' → GUIResult.success=False."""

    @patch("src.desktop_use.engine.ScreenManager")
    @patch("src.desktop_use.engine.GroundingRouter")
    @patch("src.desktop_use.engine.get_router")
    def test_fail_action_stops_loop(self, mock_get_router, mock_grounder_cls, mock_screen_cls):
        mock_screen = MagicMock()
        mock_screen.capture.return_value = (_make_fake_png(), FAKE_MONITOR)
        mock_screen.monitors = [FAKE_MONITOR]
        mock_screen_cls.return_value = mock_screen

        mock_grounder_cls.return_value = MagicMock()

        mock_get_router.return_value.generate.return_value = json.dumps(
            {"action": "fail", "reason": "cannot find element"}
        )

        from src.desktop_use.engine import GUIEngine
        engine = GUIEngine(max_steps=15)
        result = engine.execute("Click the close button")

        assert result.success is False
        assert result.steps_taken == 1


class TestGUIEngineMaxSteps:
    """LLM always returns click (never done), max_steps=3 → success=False, steps_taken=3."""

    @patch("src.desktop_use.engine.ActionExecutor")
    @patch("src.desktop_use.engine.ScreenManager")
    @patch("src.desktop_use.engine.GroundingRouter")
    @patch("src.desktop_use.engine.get_router")
    def test_max_steps_reached(self, mock_get_router, mock_grounder_cls, mock_screen_cls, mock_executor_cls):
        mock_screen = MagicMock()
        mock_screen.capture.return_value = (_make_fake_png(), FAKE_MONITOR)
        mock_screen.monitors = [FAKE_MONITOR]
        mock_screen_cls.return_value = mock_screen

        mock_grounder_cls.return_value = MagicMock()

        # Always returns a click with explicit coords (no grounding needed)
        mock_get_router.return_value.generate.return_value = json.dumps(
            {"action": "click", "x": 100, "y": 200}
        )

        mock_executor = MagicMock()
        mock_executor.execute.return_value = "success"
        mock_executor_cls.return_value = mock_executor

        from src.desktop_use.engine import GUIEngine
        engine = GUIEngine(max_steps=3)
        result = engine.execute("Do something forever")

        assert result.success is False
        assert result.steps_taken == 3
        assert "max steps" in result.summary.lower()


class TestGUIEngineTargetGrounding:
    """LLM returns target-based click → grounder is called, executor gets resolved x/y."""

    @patch("src.desktop_use.engine.ActionExecutor")
    @patch("src.desktop_use.engine.ScreenManager")
    @patch("src.desktop_use.engine.GroundingRouter")
    @patch("src.desktop_use.engine.get_router")
    def test_target_click_uses_grounder(self, mock_get_router, mock_grounder_cls, mock_screen_cls, mock_executor_cls):
        mock_screen = MagicMock()
        fake_png = _make_fake_png()
        mock_screen.capture.return_value = (fake_png, FAKE_MONITOR)
        mock_screen.monitors = [FAKE_MONITOR]
        mock_screen.to_global_coords.return_value = (300, 400)
        mock_screen_cls.return_value = mock_screen

        mock_grounder = MagicMock()
        mock_grounder.locate.return_value = LocateResult(
            x=300, y=400, confidence=95.0, monitor_id=1, method="ocr"
        )
        mock_grounder_cls.return_value = mock_grounder

        # First call returns target-based click, second call returns done
        mock_get_router.return_value.generate.side_effect = [
            json.dumps({"action": "click", "target": "我喜欢"}),
            json.dumps({"action": "done", "summary": "clicked it"}),
        ]

        mock_executor = MagicMock()
        mock_executor.execute.return_value = "success"
        mock_executor_cls.return_value = mock_executor

        from src.desktop_use.engine import GUIEngine
        engine = GUIEngine(max_steps=15)
        result = engine.execute("Click 我喜欢")

        # Grounder must have been called
        mock_grounder.locate.assert_called_once()
        call_args = mock_grounder.locate.call_args
        assert call_args[0][0] == "我喜欢"  # target_text

        # Executor must have received resolved coords, no "target" key
        executed_action = mock_executor.execute.call_args[0][0]
        assert executed_action.get("x") == 300
        assert executed_action.get("y") == 400
        assert "target" not in executed_action

        assert result.success is True


class TestGUIEngineParseAction:
    """_parse_action handles various LLM response formats."""

    def test_parse_clean_json(self):
        from src.desktop_use.engine import GUIEngine
        engine = GUIEngine.__new__(GUIEngine)
        result = engine._parse_action('{"action": "click", "x": 100, "y": 200}')
        assert result == {"action": "click", "x": 100, "y": 200}

    def test_parse_markdown_fenced(self):
        from src.desktop_use.engine import GUIEngine
        engine = GUIEngine.__new__(GUIEngine)
        raw = '```json\n{"action": "done", "summary": "ok"}\n```'
        result = engine._parse_action(raw)
        assert result == {"action": "done", "summary": "ok"}

    def test_parse_json_embedded_in_text(self):
        from src.desktop_use.engine import GUIEngine
        engine = GUIEngine.__new__(GUIEngine)
        raw = 'I will click here: {"action": "click", "x": 50, "y": 60} — that is my plan.'
        result = engine._parse_action(raw)
        assert result is not None
        assert result["action"] == "click"

    def test_parse_invalid_returns_none(self):
        from src.desktop_use.engine import GUIEngine
        engine = GUIEngine.__new__(GUIEngine)
        result = engine._parse_action("this is not json at all")
        assert result is None


class TestGUIEngineMakeThumbnail:
    """_make_thumbnail resizes to 640px wide JPEG."""

    def test_thumbnail_output_is_jpeg(self):
        from src.desktop_use.engine import GUIEngine
        import io
        from PIL import Image

        # Create a 1280x720 PNG
        img = Image.new("RGB", (1280, 720), color=(100, 150, 200))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        thumb = GUIEngine._make_thumbnail(png_bytes)

        # Should be valid JPEG
        result_img = Image.open(io.BytesIO(thumb))
        assert result_img.format == "JPEG"
        assert result_img.width == 640
        # Height should maintain aspect ratio: 720 * (640/1280) = 360
        assert result_img.height == 360
