"""Shared data models for desktop_use. No logic, no external imports."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class OCRWord:
    """A single word/line detected by OCR with bounding box."""
    text: str
    left: int
    top: int
    width: int
    height: int
    conf: float             # 0-100
    line_num: int
    word_num: int


@dataclass
class LocateResult:
    """Unified result returned by all grounding methods."""
    x: int
    y: int
    confidence: Optional[float]
    monitor_id: int
    method: str             # "ocr" | "vision" | ...


@dataclass
class MonitorInfo:
    """Physical monitor descriptor with DPI-aware dimensions."""
    id: int
    x_offset: int        # global offset in logical pixels
    y_offset: int
    width: int           # physical pixels
    height: int
    width_logical: int   # logical pixels
    height_logical: int
    scale_factor: int    # Windows scale percentage (100, 125, 150, 200 ...)


@dataclass
class WindowInfo:
    """Descriptor for a Win32 window."""
    hwnd: int
    title: str
    pid: int
    class_name: str
    rect: tuple[int, int, int, int]  # (left, top, right, bottom)

    @property
    def width(self) -> int:
        return self.rect[2] - self.rect[0]

    @property
    def height(self) -> int:
        return self.rect[3] - self.rect[1]


@dataclass
class GUIResult:
    """Result of a DesktopEngine.execute() run."""
    success: bool
    summary: str
    steps_taken: int
    trajectory: object = None  # Trajectory | None (avoid circular import)


@dataclass
class TrajectoryStep:
    """One perception-action step in the trajectory."""
    screenshot_thumbnail: bytes  # resized JPEG, ~80-120 KB
    action: dict                 # the action that was taken
    result: str                  # "success" / error string
    timestamp: float
