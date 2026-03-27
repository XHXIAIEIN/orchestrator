"""Tests for src/desktop_use/trajectory.py — TDD first."""

import base64
import json
import time

import pytest

from src.desktop_use.trajectory import Trajectory, TrajectoryStep


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_step(action: dict = None, result: str = "success") -> TrajectoryStep:
    """Return a minimal TrajectoryStep with a tiny fake JPEG thumbnail."""
    # Minimal valid JPEG header bytes (will not render, but enough for b64 tests)
    fake_jpeg = bytes([0xFF, 0xD8, 0xFF, 0xE0]) + b"\x00" * 16 + bytes([0xFF, 0xD9])
    return TrajectoryStep(
        screenshot_thumbnail=fake_jpeg,
        action=action or {"type": "click", "x": 100, "y": 200},
        result=result,
        timestamp=time.time(),
    )


# ---------------------------------------------------------------------------
# TrajectoryStep
# ---------------------------------------------------------------------------

class TestTrajectoryStep:
    def test_fields_accessible(self):
        step = _make_step()
        assert isinstance(step.screenshot_thumbnail, bytes)
        assert isinstance(step.action, dict)
        assert isinstance(step.result, str)
        assert isinstance(step.timestamp, float)


# ---------------------------------------------------------------------------
# Trajectory.append / __len__
# ---------------------------------------------------------------------------

class TestTrajectoryAppendLen:
    def test_empty_on_creation(self):
        t = Trajectory()
        assert len(t) == 0

    def test_append_increases_len(self):
        t = Trajectory()
        t.append(_make_step())
        assert len(t) == 1
        t.append(_make_step())
        assert len(t) == 2

    def test_append_stores_step(self):
        t = Trajectory()
        step = _make_step(action={"type": "type", "text": "hello"})
        t.append(step)
        assert t.steps[0] is step


# ---------------------------------------------------------------------------
# Sliding window eviction
# ---------------------------------------------------------------------------

class TestSlidingWindow:
    def test_evicts_oldest_when_full(self):
        t = Trajectory(max_steps=2)
        steps = [_make_step(action={"i": i}) for i in range(5)]
        for s in steps:
            t.append(s)
        assert len(t) == 2
        # Should keep last 2 (index 3 and 4)
        assert t.steps[0] is steps[3]
        assert t.steps[1] is steps[4]

    def test_exactly_max_steps_no_eviction(self):
        t = Trajectory(max_steps=3)
        for _ in range(3):
            t.append(_make_step())
        assert len(t) == 3

    def test_default_max_steps_is_8(self):
        t = Trajectory()
        for _ in range(10):
            t.append(_make_step())
        assert len(t) == 8


# ---------------------------------------------------------------------------
# to_prompt_context
# ---------------------------------------------------------------------------

class TestToPromptContext:
    def test_empty_trajectory_returns_empty_list(self):
        t = Trajectory()
        assert t.to_prompt_context() == []

    def test_returns_list_of_dicts(self):
        t = Trajectory()
        t.append(_make_step())
        ctx = t.to_prompt_context()
        assert isinstance(ctx, list)
        assert len(ctx) == 1
        assert isinstance(ctx[0], dict)

    def test_each_entry_has_text_key(self):
        t = Trajectory()
        t.append(_make_step(action={"type": "click", "x": 5, "y": 10}))
        ctx = t.to_prompt_context()
        assert "text" in ctx[0]

    def test_each_entry_has_image_or_screenshot_key(self):
        t = Trajectory()
        t.append(_make_step())
        ctx = t.to_prompt_context()
        entry = ctx[0]
        assert "image" in entry or "screenshot" in entry

    def test_text_contains_action_json(self):
        action = {"type": "click", "x": 42, "y": 99}
        t = Trajectory()
        t.append(_make_step(action=action))
        ctx = t.to_prompt_context()
        text = ctx[0]["text"]
        assert "click" in text
        assert "42" in text

    def test_text_contains_result(self):
        t = Trajectory()
        t.append(_make_step(result="some_error"))
        ctx = t.to_prompt_context()
        assert "some_error" in ctx[0]["text"]

    def test_image_is_base64_string(self):
        t = Trajectory()
        t.append(_make_step())
        ctx = t.to_prompt_context()
        img_key = "image" if "image" in ctx[0] else "screenshot"
        img_val = ctx[0][img_key]
        assert isinstance(img_val, str)
        # Must be valid base64
        decoded = base64.b64decode(img_val)
        assert len(decoded) > 0

    def test_multiple_steps_all_included(self):
        t = Trajectory(max_steps=5)
        for i in range(3):
            t.append(_make_step(action={"i": i}))
        ctx = t.to_prompt_context()
        assert len(ctx) == 3

    def test_step_numbers_in_text(self):
        t = Trajectory()
        t.append(_make_step())
        t.append(_make_step())
        ctx = t.to_prompt_context()
        assert "1" in ctx[0]["text"]
        assert "2" in ctx[1]["text"]


# ---------------------------------------------------------------------------
# get_images_b64
# ---------------------------------------------------------------------------

class TestGetImagesB64:
    def test_returns_list(self):
        t = Trajectory()
        assert isinstance(t.get_images_b64(), list)

    def test_empty_when_no_steps(self):
        t = Trajectory()
        assert t.get_images_b64() == []

    def test_returns_strings(self):
        t = Trajectory()
        t.append(_make_step())
        imgs = t.get_images_b64()
        assert all(isinstance(s, str) for s in imgs)

    def test_count_matches_steps(self):
        t = Trajectory()
        t.append(_make_step())
        t.append(_make_step())
        assert len(t.get_images_b64()) == 2

    def test_each_is_valid_base64(self):
        t = Trajectory()
        t.append(_make_step())
        for b64 in t.get_images_b64():
            decoded = base64.b64decode(b64)
            assert len(decoded) > 0


# ---------------------------------------------------------------------------
# get_action_summary
# ---------------------------------------------------------------------------

class TestGetActionSummary:
    def test_returns_string(self):
        t = Trajectory()
        assert isinstance(t.get_action_summary(), str)

    def test_empty_trajectory_returns_empty_or_blank(self):
        t = Trajectory()
        assert t.get_action_summary().strip() == ""

    def test_contains_step_numbers(self):
        t = Trajectory()
        t.append(_make_step())
        t.append(_make_step())
        summary = t.get_action_summary()
        assert "Step 1" in summary
        assert "Step 2" in summary

    def test_contains_result(self):
        t = Trajectory()
        t.append(_make_step(result="success"))
        summary = t.get_action_summary()
        assert "success" in summary

    def test_contains_action_info(self):
        t = Trajectory()
        t.append(_make_step(action={"type": "scroll", "direction": "down"}))
        summary = t.get_action_summary()
        assert "scroll" in summary

    def test_multiline_for_multiple_steps(self):
        t = Trajectory()
        t.append(_make_step())
        t.append(_make_step())
        summary = t.get_action_summary()
        assert "\n" in summary
