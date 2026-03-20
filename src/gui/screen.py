"""ScreenManager — multi-monitor screenshot capture with DPI-aware coordinate mapping.

Coordinate spaces
-----------------
- Physical pixels : what mss captures, what Tesseract / UI-TARS return
- Logical pixels  : what pyautogui.moveTo / click expect

All coords returned to callers are in **logical** pixels.
"""

from __future__ import annotations

import io
import ctypes
import sys
from dataclasses import dataclass
from typing import List, Tuple

try:
    import mss as mss_module
except ImportError:
    mss_module = None  # type: ignore[assignment]

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class MonitorInfo:
    id: int
    x_offset: int        # global offset in logical pixels
    y_offset: int
    width: int           # physical pixels
    height: int
    width_logical: int   # logical pixels
    height_logical: int
    scale_factor: int    # Windows scale percentage (100, 125, 150, 200 …)


# ---------------------------------------------------------------------------
# ScreenManager
# ---------------------------------------------------------------------------

class ScreenManager:
    """Probe monitors, capture screenshots, and map between coordinate spaces."""

    def __init__(self) -> None:
        self.monitors: List[MonitorInfo] = self._probe_monitors()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def capture(self, monitor_id: int = 0) -> Tuple[bytes, MonitorInfo]:
        """Capture a specific monitor and return (PNG bytes, MonitorInfo).

        monitor_id=0  → virtual screen (all monitors stitched together by mss)
        monitor_id>=1 → individual monitor
        """
        if mss_module is None:
            raise RuntimeError("mss is not installed")

        if monitor_id == 0:
            with mss_module.mss() as sct:
                virtual = sct.monitors[0]  # mss index 0 = full virtual screen
                shot = sct.grab(virtual)
                png_bytes = self._shot_to_png(shot)
            info = MonitorInfo(
                id=0,
                x_offset=virtual.get("left", 0),
                y_offset=virtual.get("top", 0),
                width=virtual.get("width", shot.size[0]),
                height=virtual.get("height", shot.size[1]),
                width_logical=virtual.get("width", shot.size[0]),
                height_logical=virtual.get("height", shot.size[1]),
                scale_factor=100,
            )
            return png_bytes, info

        mon = self._get_monitor(monitor_id)

        with mss_module.mss() as sct:
            region = {
                "left": mon.x_offset,
                "top": mon.y_offset,
                "width": mon.width,
                "height": mon.height,
            }
            shot = sct.grab(region)
            png_bytes = self._shot_to_png(shot)

        return png_bytes, mon

    def capture_all(self) -> List[Tuple[bytes, MonitorInfo]]:
        """Capture each physical monitor separately."""
        return [self.capture(m.id) for m in self.monitors]

    def to_logical_coords(
        self, phys_x: int, phys_y: int, monitor_id: int
    ) -> Tuple[int, int]:
        """Convert physical pixel coordinates to logical pixels."""
        mon = self._get_monitor(monitor_id)
        scale = mon.scale_factor / 100
        return int(phys_x / scale), int(phys_y / scale)

    def to_global_coords(
        self, local_x: int, local_y: int, monitor_id: int
    ) -> Tuple[int, int]:
        """Convert monitor-local logical coordinates to global logical coordinates."""
        mon = self._get_monitor(monitor_id)
        return mon.x_offset + local_x, mon.y_offset + local_y

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_monitor(self, monitor_id: int) -> MonitorInfo:
        for m in self.monitors:
            if m.id == monitor_id:
                return m
        raise ValueError(
            f"monitor_id={monitor_id!r} not found. "
            f"Available: {[m.id for m in self.monitors]}"
        )

    def _probe_monitors(self) -> List[MonitorInfo]:
        """Enumerate physical monitors and read DPI scale factors."""
        if mss_module is None:
            return []

        monitors: List[MonitorInfo] = []
        with mss_module.mss() as sct:
            # mss index 0 = virtual screen, 1..N = individual monitors
            for idx, raw in enumerate(sct.monitors[1:], start=1):
                scale = self._get_scale_factor(idx - 1)  # 0-based for Win32
                phys_w = raw["width"]
                phys_h = raw["height"]
                log_w = int(phys_w / (scale / 100))
                log_h = int(phys_h / (scale / 100))
                monitors.append(
                    MonitorInfo(
                        id=idx,
                        x_offset=raw.get("left", 0),
                        y_offset=raw.get("top", 0),
                        width=phys_w,
                        height=phys_h,
                        width_logical=log_w,
                        height_logical=log_h,
                        scale_factor=scale,
                    )
                )
        return monitors

    @staticmethod
    def _get_scale_factor(monitor_index: int) -> int:
        """Read DPI scale factor from Win32 API.

        Returns the Windows scale percentage (e.g. 100, 125, 150, 200).
        Falls back to 100 on non-Windows or when the API is unavailable.
        """
        if sys.platform != "win32":
            return 100

        try:
            # EnumDisplayMonitors to get HMONITOR handles
            user32 = ctypes.windll.user32
            shcore = ctypes.windll.shcore

            monitors_found: list[int] = []

            MonitorEnumProc = ctypes.WINFUNCTYPE(
                ctypes.c_bool,
                ctypes.c_ulong,   # HMONITOR
                ctypes.c_ulong,   # HDC
                ctypes.POINTER(ctypes.c_long),  # LPRECT
                ctypes.c_double,  # LPARAM
            )

            def _callback(hmon, hdc, rect, data):
                monitors_found.append(hmon)
                return True

            cb = MonitorEnumProc(_callback)
            user32.EnumDisplayMonitors(None, None, cb, 0)

            if monitor_index >= len(monitors_found):
                return 100

            hmon = monitors_found[monitor_index]
            scale_factor = ctypes.c_uint(0)
            # GetScaleFactorForMonitor returns SCALE_FACTOR enum (100, 125, 150 …)
            result = shcore.GetScaleFactorForMonitor(
                ctypes.c_ulong(hmon),
                ctypes.byref(scale_factor),
            )
            if result == 0:  # S_OK
                return int(scale_factor.value)
            return 100
        except Exception:  # noqa: BLE001
            return 100

    @staticmethod
    def _shot_to_png(shot) -> bytes:
        """Convert an mss screenshot object to PNG bytes."""
        if Image is not None:
            img = Image.frombytes("RGB", shot.size, shot.rgb)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()

        # Fallback: return raw RGB bytes wrapped in a minimal pseudo-PNG marker
        # so callers always get bytes (real PNG only when Pillow is available)
        return shot.rgb
