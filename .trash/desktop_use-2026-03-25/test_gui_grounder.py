"""Tests for GroundingRouter (OCR-first + Vision fallback strategy)."""
from unittest.mock import MagicMock

import pytest

from src.desktop_use.grounder import GroundingRouter
from src.desktop_use.grounder_ocr import LocateResult

DUMMY_PNG = b"\x89PNG\r\n\x1a\n"  # minimal fake bytes — OCR is mocked


def _make_result(x=10, y=20, method="ocr") -> LocateResult:
    return LocateResult(x=x, y=y, confidence=90.0, monitor_id=1, method=method)


# ---------------------------------------------------------------------------
# Test 1 — OCR hit: result returned directly (after coord passthrough)
# ---------------------------------------------------------------------------

def test_ocr_hit_returns_result():
    router = GroundingRouter()
    router.ocr = MagicMock()
    router.ocr.locate.return_value = _make_result(x=10, y=20)

    result = router.locate("Submit", DUMMY_PNG, monitor_id=1)

    assert result is not None
    assert result.x == 10
    assert result.y == 20
    router.ocr.locate.assert_called_once_with("Submit", DUMMY_PNG, 1)


# ---------------------------------------------------------------------------
# Test 2 — OCR miss, no vision → None
# ---------------------------------------------------------------------------

def test_ocr_miss_no_vision_returns_none():
    router = GroundingRouter(enable_vision=False)
    router.ocr = MagicMock()
    router.ocr.locate.return_value = None

    result = router.locate("Nonexistent", DUMMY_PNG)

    assert result is None


# ---------------------------------------------------------------------------
# Test 3 — Coord transform applied when screen_manager is present
# ---------------------------------------------------------------------------

def test_coord_transform_applied_with_screen_manager():
    sm = MagicMock()
    sm.to_logical_coords.return_value = (50, 100)

    router = GroundingRouter(screen_manager=sm)
    router.ocr = MagicMock()
    router.ocr.locate.return_value = _make_result(x=10, y=20)

    result = router.locate("OK", DUMMY_PNG, monitor_id=2)

    assert result is not None
    assert result.x == 50
    assert result.y == 100
    sm.to_logical_coords.assert_called_once_with(10, 20, 2)


# ---------------------------------------------------------------------------
# Test 4 — No coord transform when screen_manager is None
# ---------------------------------------------------------------------------

def test_no_coord_transform_without_screen_manager():
    router = GroundingRouter(screen_manager=None)
    router.ocr = MagicMock()
    router.ocr.locate.return_value = _make_result(x=333, y=444)

    result = router.locate("Cancel", DUMMY_PNG)

    assert result is not None
    assert result.x == 333
    assert result.y == 444


# ---------------------------------------------------------------------------
# Test 5 — Vision fallback used when OCR misses
# ---------------------------------------------------------------------------

def test_vision_fallback_on_ocr_miss():
    router = GroundingRouter(enable_vision=False)
    router.ocr = MagicMock()
    router.ocr.locate.return_value = None

    vision_result = _make_result(x=77, y=88, method="vision")
    router.vision = MagicMock()
    router.vision.locate.return_value = vision_result

    result = router.locate("Settings", DUMMY_PNG, monitor_id=1)

    assert result is not None
    assert result.x == 77
    assert result.y == 88
    assert result.method == "vision"
    router.vision.locate.assert_called_once_with("Settings", DUMMY_PNG, 1)
