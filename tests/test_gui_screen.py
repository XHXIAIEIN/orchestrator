"""Tests for src/gui/screen.py — ScreenManager multi-monitor capture + DPI coord mapping."""

from dataclasses import fields
from unittest.mock import MagicMock, patch, PropertyMock
import pytest


# ---------------------------------------------------------------------------
# MonitorInfo dataclass
# ---------------------------------------------------------------------------

def test_monitor_info_fields():
    from src.gui.screen import MonitorInfo

    field_names = {f.name for f in fields(MonitorInfo)}
    expected = {
        "id", "x_offset", "y_offset",
        "width", "height",
        "width_logical", "height_logical",
        "scale_factor",
    }
    assert expected == field_names


def test_monitor_info_construction():
    from src.gui.screen import MonitorInfo

    m = MonitorInfo(
        id=1,
        x_offset=0, y_offset=0,
        width=3840, height=2160,
        width_logical=1920, height_logical=1080,
        scale_factor=200,
    )
    assert m.id == 1
    assert m.scale_factor == 200


# ---------------------------------------------------------------------------
# capture() — mock mss so we don't need a real display
# ---------------------------------------------------------------------------

def _make_screen_manager_with_monitors(monitors):
    """Bypass __init__ and inject monitor list directly."""
    from src.gui.screen import ScreenManager
    sm = ScreenManager.__new__(ScreenManager)
    sm.monitors = monitors
    return sm


def test_capture_returns_bytes_and_monitor_info():
    from src.gui.screen import ScreenManager, MonitorInfo
    import src.gui.screen as screen_module

    monitor = MonitorInfo(
        id=1,
        x_offset=0, y_offset=0,
        width=1920, height=1080,
        width_logical=1920, height_logical=1080,
        scale_factor=100,
    )
    sm = _make_screen_manager_with_monitors([monitor])

    # Build fake mss grab result
    fake_grab = MagicMock()
    fake_grab.rgb = b"\x00" * (1920 * 1080 * 3)
    fake_grab.size = (1920, 1080)

    fake_mss_ctx = MagicMock()
    fake_mss_ctx.grab.return_value = fake_grab

    fake_mss_module = MagicMock()
    fake_mss_module.mss.return_value.__enter__ = MagicMock(return_value=fake_mss_ctx)
    fake_mss_module.mss.return_value.__exit__ = MagicMock(return_value=False)

    with patch.object(screen_module, "mss_module", fake_mss_module):
        result = sm.capture(monitor_id=1)

    assert isinstance(result, tuple) and len(result) == 2
    png_bytes, info = result
    assert isinstance(png_bytes, bytes)
    assert isinstance(info, MonitorInfo)
    assert info.id == 1


def test_capture_monitor_id_zero_virtual_screen():
    """monitor_id=0 should capture the virtual (stitched) screen."""
    from src.gui.screen import ScreenManager, MonitorInfo
    import src.gui.screen as screen_module

    monitor = MonitorInfo(
        id=1,
        x_offset=0, y_offset=0,
        width=1920, height=1080,
        width_logical=1920, height_logical=1080,
        scale_factor=100,
    )
    sm = _make_screen_manager_with_monitors([monitor])

    fake_grab = MagicMock()
    fake_grab.rgb = b"\xff" * (1920 * 1080 * 3)
    fake_grab.size = (1920, 1080)

    fake_mss_ctx = MagicMock()
    fake_mss_ctx.grab.return_value = fake_grab
    # mss exposes monitors[0] as virtual screen dict
    fake_mss_ctx.monitors = [{"left": 0, "top": 0, "width": 1920, "height": 1080}]

    fake_mss_module = MagicMock()
    fake_mss_module.mss.return_value.__enter__ = MagicMock(return_value=fake_mss_ctx)
    fake_mss_module.mss.return_value.__exit__ = MagicMock(return_value=False)

    with patch.object(screen_module, "mss_module", fake_mss_module):
        png_bytes, info = sm.capture(monitor_id=0)

    assert isinstance(png_bytes, bytes)
    assert info.id == 0
    assert info.scale_factor == 100


# ---------------------------------------------------------------------------
# to_logical_coords
# ---------------------------------------------------------------------------

def test_to_logical_coords_200_percent():
    from src.gui.screen import MonitorInfo

    monitor = MonitorInfo(
        id=1,
        x_offset=0, y_offset=0,
        width=3840, height=2160,
        width_logical=1920, height_logical=1080,
        scale_factor=200,
    )
    sm = _make_screen_manager_with_monitors([monitor])

    lx, ly = sm.to_logical_coords(3840, 2160, monitor_id=1)
    assert (lx, ly) == (1920, 1080)


def test_to_logical_coords_150_percent():
    from src.gui.screen import MonitorInfo

    monitor = MonitorInfo(
        id=1,
        x_offset=0, y_offset=0,
        width=1440, height=810,
        width_logical=960, height_logical=540,
        scale_factor=150,
    )
    sm = _make_screen_manager_with_monitors([monitor])

    lx, ly = sm.to_logical_coords(1440, 810, monitor_id=1)
    assert (lx, ly) == (960, 540)


# ---------------------------------------------------------------------------
# to_global_coords
# ---------------------------------------------------------------------------

def test_to_global_coords_with_offset():
    from src.gui.screen import MonitorInfo

    monitor = MonitorInfo(
        id=2,
        x_offset=1920, y_offset=0,
        width=1920, height=1080,
        width_logical=1920, height_logical=1080,
        scale_factor=100,
    )
    sm = _make_screen_manager_with_monitors([monitor])

    gx, gy = sm.to_global_coords(100, 200, monitor_id=2)
    assert (gx, gy) == (2020, 200)


# ---------------------------------------------------------------------------
# Invalid monitor_id raises ValueError
# ---------------------------------------------------------------------------

def test_invalid_monitor_id_capture():
    from src.gui.screen import MonitorInfo

    monitor = MonitorInfo(
        id=1,
        x_offset=0, y_offset=0,
        width=1920, height=1080,
        width_logical=1920, height_logical=1080,
        scale_factor=100,
    )
    sm = _make_screen_manager_with_monitors([monitor])

    with pytest.raises(ValueError):
        sm.capture(monitor_id=99)


def test_invalid_monitor_id_logical_coords():
    from src.gui.screen import MonitorInfo

    monitor = MonitorInfo(
        id=1,
        x_offset=0, y_offset=0,
        width=1920, height=1080,
        width_logical=1920, height_logical=1080,
        scale_factor=100,
    )
    sm = _make_screen_manager_with_monitors([monitor])

    with pytest.raises(ValueError):
        sm.to_logical_coords(100, 100, monitor_id=5)


def test_invalid_monitor_id_global_coords():
    from src.gui.screen import MonitorInfo

    monitor = MonitorInfo(
        id=1,
        x_offset=0, y_offset=0,
        width=1920, height=1080,
        width_logical=1920, height_logical=1080,
        scale_factor=100,
    )
    sm = _make_screen_manager_with_monitors([monitor])

    with pytest.raises(ValueError):
        sm.to_global_coords(0, 0, monitor_id=7)
