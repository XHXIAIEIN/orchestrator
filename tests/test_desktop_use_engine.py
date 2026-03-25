"""Tests for DesktopEngine -- perception-action loop with all components mocked."""

from __future__ import annotations

import io
import json
import threading
from unittest.mock import MagicMock, patch

import pytest

from src.desktop_use.types import LocateResult, MonitorInfo


FAKE_MONITOR = MonitorInfo(
    id=1, x_offset=0, y_offset=0,
    width=1920, height=1080,
    width_logical=1920, height_logical=1080,
    scale_factor=100,
)


def _make_fake_png() -> bytes:
    """Return valid PNG bytes (small RGB image, Pillow-generated)."""
    from PIL import Image
    img = Image.new("RGB", (64, 36), color=(100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_engine(**overrides):
    """Create a DesktopEngine with all external components mocked."""
    from src.desktop_use.engine import DesktopEngine
    from src.desktop_use.ocr import OCREngine
    from src.desktop_use.match import MatchStrategy

    mock_screen = MagicMock()
    mock_screen.capture.return_value = (_make_fake_png(), FAKE_MONITOR)
    mock_screen.monitors = [FAKE_MONITOR]
    mock_screen.to_logical_coords.side_effect = lambda x, y, mid: (x, y)
    mock_screen.to_global_coords.side_effect = lambda x, y, mid: (x, y)

    mock_window = MagicMock()
    mock_window.target = None
    mock_window.lock.return_value = None

    mock_ocr = MagicMock(spec=OCREngine)
    mock_ocr.extract_words.return_value = []

    mock_match = MagicMock(spec=MatchStrategy)
    mock_match.match.return_value = None

    mock_executor = MagicMock()
    mock_executor.execute.return_value = "success"

    defaults = dict(
        screen=mock_screen,
        window=mock_window,
        ocr_engine=mock_ocr,
        match_strategy=mock_match,
        executor=mock_executor,
    )
    defaults.update(overrides)

    engine = DesktopEngine.__new__(DesktopEngine)
    engine.max_steps = overrides.get("max_steps", 15)
    engine.background = overrides.get("background", False)
    engine.kill_event = threading.Event()
    engine.ocr_engine = defaults["ocr_engine"]
    engine.match_strategy = defaults["match_strategy"]
    engine.screen = defaults["screen"]
    engine.window = defaults["window"]
    engine.executor = defaults["executor"]
    engine.ocr_lang = "zh-Hans-CN"
    engine._kill_listener = None

    from src.desktop_use.trajectory import Trajectory
    engine.trajectory = Trajectory(max_steps=8)

    return engine


class TestDesktopEngineDoneAction:
    """LLM returns 'done' -> GUIResult.success=True."""

    @patch("src.core.llm_router.get_router")
    def test_done_action_stops_loop(self, mock_get_router):
        mock_get_router.return_value.generate.return_value = json.dumps(
            {"action": "done", "summary": "task completed"}
        )
        engine = _make_engine()
        result = engine._run_loop("Open Notepad", "", 1)
        assert result.success is True
        assert result.steps_taken == 1


class TestDesktopEngineFailAction:
    """LLM returns 'fail' -> GUIResult.success=False."""

    @patch("src.core.llm_router.get_router")
    def test_fail_action_stops_loop(self, mock_get_router):
        mock_get_router.return_value.generate.return_value = json.dumps(
            {"action": "fail", "reason": "cannot find element"}
        )
        engine = _make_engine()
        result = engine._run_loop("Click close", "", 1)
        assert result.success is False
        assert result.steps_taken == 1


class TestDesktopEngineMaxSteps:
    """LLM always returns click (never done), max_steps=3 -> success=False."""

    @patch("src.core.llm_router.get_router")
    def test_max_steps_reached(self, mock_get_router):
        mock_get_router.return_value.generate.return_value = json.dumps(
            {"action": "click", "x": 100, "y": 200}
        )
        engine = _make_engine(max_steps=3)
        result = engine._run_loop("Do something forever", "", 1)
        assert result.success is False
        assert result.steps_taken == 3
        assert "max steps" in result.summary.lower()


class TestDesktopEngineTargetGrounding:
    """LLM returns target-based click -> OCR is called, executor gets resolved x/y."""

    @patch("src.core.llm_router.get_router")
    def test_target_click_uses_ocr(self, mock_get_router):
        from src.desktop_use.types import OCRWord

        mock_ocr = MagicMock()
        mock_ocr.extract_words.return_value = [
            OCRWord(text="我喜欢", left=100, top=200, width=60, height=30,
                    conf=95.0, line_num=1, word_num=1)
        ]

        mock_match = MagicMock()
        mock_match.match.return_value = OCRWord(
            text="我喜欢", left=100, top=200, width=60, height=30,
            conf=95.0, line_num=1, word_num=1
        )

        mock_get_router.return_value.generate.side_effect = [
            json.dumps({"action": "click", "target": "我喜欢"}),
            json.dumps({"action": "done", "summary": "clicked it"}),
        ]

        mock_executor = MagicMock()
        mock_executor.execute.return_value = "success"

        engine = _make_engine(
            ocr_engine=mock_ocr,
            match_strategy=mock_match,
            executor=mock_executor,
        )
        result = engine._run_loop("Click 我喜欢", "", 1)

        # Match strategy must have been called
        mock_match.match.assert_called_once()
        assert mock_match.match.call_args[0][0] == "我喜欢"

        # Executor must have received resolved coords, no "target" key
        executed_action = mock_executor.execute.call_args[0][0]
        assert "x" in executed_action
        assert "y" in executed_action
        assert "target" not in executed_action
        assert result.success is True


class TestDesktopEngineParseAction:
    """_parse_action handles various LLM response formats."""

    def test_parse_clean_json(self):
        from src.desktop_use.engine import DesktopEngine
        result = DesktopEngine._parse_action('{"action": "click", "x": 100, "y": 200}')
        assert result == {"action": "click", "x": 100, "y": 200}

    def test_parse_markdown_fenced(self):
        from src.desktop_use.engine import DesktopEngine
        raw = '```json\n{"action": "done", "summary": "ok"}\n```'
        result = DesktopEngine._parse_action(raw)
        assert result == {"action": "done", "summary": "ok"}

    def test_parse_json_embedded_in_text(self):
        from src.desktop_use.engine import DesktopEngine
        raw = 'I will click here: {"action": "click", "x": 50, "y": 60} -- that is my plan.'
        result = DesktopEngine._parse_action(raw)
        assert result is not None
        assert result["action"] == "click"

    def test_parse_invalid_returns_none(self):
        from src.desktop_use.engine import DesktopEngine
        result = DesktopEngine._parse_action("this is not json at all")
        assert result is None


class TestDesktopEngineMakeThumbnail:
    """_make_thumbnail resizes to 640px wide JPEG."""

    def test_thumbnail_output_is_jpeg(self):
        from src.desktop_use.engine import DesktopEngine
        from PIL import Image

        img = Image.new("RGB", (1280, 720), color=(100, 150, 200))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        thumb = DesktopEngine._make_thumbnail(png_bytes)

        result_img = Image.open(io.BytesIO(thumb))
        assert result_img.format == "JPEG"
        assert result_img.width == 640
        assert result_img.height == 360


class TestDesktopEngineKillSwitch:
    """Kill event set -> loop aborts immediately."""

    @patch("src.core.llm_router.get_router")
    def test_kill_event_aborts(self, mock_get_router):
        engine = _make_engine()
        engine.kill_event.set()
        result = engine._run_loop("Do something", "", 1)
        assert result.success is False
        assert "INTERRUPTED" in result.summary
