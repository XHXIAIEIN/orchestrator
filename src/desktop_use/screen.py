"""Screen capture interface + mss default implementation.

Coordinate spaces
-----------------
- Physical pixels : what mss captures, what OCR returns
- Logical pixels  : what pyautogui.moveTo / click expect

All coords returned to callers are in **logical** pixels.
"""

from __future__ import annotations

import ctypes
import io
import struct
import sys
import time
import logging
from abc import ABC, abstractmethod
from multiprocessing import shared_memory
from typing import List, Tuple

import numpy as np

from .types import MonitorInfo

try:
    import mss as mss_module
except ImportError:
    mss_module = None  # type: ignore[assignment]

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore[assignment]

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared-memory zero-copy frame buffer (P12 — Carbonyl pattern)
# ---------------------------------------------------------------------------

class SharedFrameBuffer:
    """Zero-copy frame buffer using shared memory.

    Layout: [8 bytes timestamp][4 bytes width][4 bytes height][4 bytes channels][... pixel data ...]

    Producer writes frames, consumers read directly — zero copy.
    Uses a simple header to communicate frame metadata.
    """

    HEADER_SIZE = 20  # 8 (timestamp) + 4 (width) + 4 (height) + 4 (channels)

    def __init__(
        self,
        name: str = "orchestrator_frame",
        width: int = 1920,
        height: int = 1080,
        channels: int = 4,
    ):
        self._name = name
        self._width = width
        self._height = height
        self._channels = channels
        self._frame_size = width * height * channels
        self._total_size = self.HEADER_SIZE + self._frame_size
        self._shm: shared_memory.SharedMemory | None = None

    def create(self):
        """Create shared memory (producer side)."""
        try:
            # Clean up any stale buffer with the same name
            old = shared_memory.SharedMemory(name=self._name, create=False)
            old.close()
            old.unlink()
        except FileNotFoundError:
            pass
        self._shm = shared_memory.SharedMemory(
            name=self._name, create=True, size=self._total_size
        )

    def attach(self):
        """Attach to existing shared memory (consumer side)."""
        self._shm = shared_memory.SharedMemory(name=self._name, create=False)

    def write_frame(self, frame: np.ndarray):
        """Write a frame to shared memory (producer)."""
        if self._shm is None:
            raise RuntimeError("SharedFrameBuffer not initialized — call create() first")

        h, w = frame.shape[:2]
        c = frame.shape[2] if frame.ndim == 3 else 1

        # Write header
        header = struct.pack("<dIII", time.time(), w, h, c)
        self._shm.buf[: self.HEADER_SIZE] = header

        # Write pixel data
        flat = frame.tobytes()
        end = self.HEADER_SIZE + len(flat)
        self._shm.buf[self.HEADER_SIZE : end] = flat

    def read_frame(self) -> tuple[np.ndarray | None, float]:
        """Read the latest frame from shared memory (consumer).

        Returns (frame_array, timestamp). frame is None if no frame written yet.
        """
        if self._shm is None:
            raise RuntimeError("SharedFrameBuffer not initialized — call attach() first")

        # Read header
        header = bytes(self._shm.buf[: self.HEADER_SIZE])
        timestamp, w, h, c = struct.unpack("<dIII", header)

        if timestamp == 0:
            return None, 0.0

        # Read pixel data
        pixel_size = w * h * c
        data = bytes(self._shm.buf[self.HEADER_SIZE : self.HEADER_SIZE + pixel_size])

        shape = (h, w, c) if c > 1 else (h, w)
        frame = np.frombuffer(data, dtype=np.uint8).reshape(shape)
        return frame, timestamp

    def get_timestamp(self) -> float:
        """Read just the timestamp (cheaper than full frame read)."""
        if self._shm is None:
            return 0.0
        header = bytes(self._shm.buf[:8])
        return struct.unpack("<d", header)[0]

    def close(self):
        """Close connection to shared memory."""
        if self._shm:
            self._shm.close()
            self._shm = None

    def destroy(self):
        """Destroy shared memory (producer cleanup)."""
        if self._shm:
            self._shm.close()
            self._shm.unlink()
            self._shm = None


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------

class ScreenCapture(ABC):
    """Pluggable screen capture backend."""

    @abstractmethod
    def capture(self, monitor_id: int = 0) -> Tuple[bytes, MonitorInfo]:
        """Capture a specific monitor. Returns (PNG bytes, MonitorInfo).

        monitor_id=0 -> virtual screen (all monitors stitched)
        monitor_id>=1 -> individual monitor
        """

    @abstractmethod
    def to_logical_coords(self, phys_x: int, phys_y: int, monitor_id: int) -> Tuple[int, int]:
        """Convert physical pixel coordinates to logical pixels."""

    @abstractmethod
    def to_global_coords(self, local_x: int, local_y: int, monitor_id: int) -> Tuple[int, int]:
        """Convert monitor-local logical coordinates to global logical coordinates."""


# ---------------------------------------------------------------------------
# Default implementation: mss + Win32 DPI APIs
# ---------------------------------------------------------------------------

class MSSScreenCapture(ScreenCapture):
    """Probe monitors, capture screenshots, and map between coordinate spaces."""

    def __init__(self) -> None:
        self.monitors: List[MonitorInfo] = self._probe_monitors()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def capture(self, monitor_id: int = 0) -> Tuple[bytes, MonitorInfo]:
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

    def capture_to_shared(self, buffer: SharedFrameBuffer, monitor_id: int = 0) -> float:
        """Capture screenshot directly to shared memory. Returns timestamp.

        This is an optional optimization path — raw BGRA pixels are written
        to *buffer* so that consumers (OCR, CV pipeline) can read them
        without serialization overhead.
        """
        if mss_module is None:
            raise RuntimeError("mss is not installed")

        if monitor_id == 0:
            with mss_module.mss() as sct:
                shot = sct.grab(sct.monitors[0])
        else:
            mon = self._get_monitor(monitor_id)
            with mss_module.mss() as sct:
                region = {
                    "left": mon.x_offset,
                    "top": mon.y_offset,
                    "width": mon.width,
                    "height": mon.height,
                }
                shot = sct.grab(region)

        frame = np.frombuffer(shot.rgb, dtype=np.uint8).reshape(
            shot.height, shot.width, 3
        )
        buffer.write_frame(frame)
        return time.time()

    def to_logical_coords(
        self, phys_x: int, phys_y: int, monitor_id: int
    ) -> Tuple[int, int]:
        mon = self._get_monitor(monitor_id)
        scale = mon.scale_factor / 100
        return int(phys_x / scale), int(phys_y / scale)

    def to_global_coords(
        self, local_x: int, local_y: int, monitor_id: int
    ) -> Tuple[int, int]:
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

        # Fallback: return raw RGB bytes
        return shot.rgb
