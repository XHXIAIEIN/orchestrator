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
    source: str = "agent"        # "agent" (LLM-driven) or "user" (human takeover)


@dataclass
class UIElement:
    """A UI element in a blueprint — button, input, label, icon, etc."""
    name: str
    rect: tuple[int, int, int, int]  # (left, top, right, bottom)
    element_type: str                # "button" | "input" | "icon" | "label" | "text"
    action: str                      # "click" | "click+type" | "display"
    text: str                        # visible text (may be empty)
    source: str                      # "win32" | "uia" | "cv" | "ocr" | "omniparser"
    confidence: float                # 0.0 - 1.0

    @property
    def center(self) -> tuple[int, int]:
        return (self.rect[0] + self.rect[2]) // 2, (self.rect[1] + self.rect[3]) // 2

    @property
    def width(self) -> int:
        return self.rect[2] - self.rect[0]

    @property
    def height(self) -> int:
        return self.rect[3] - self.rect[1]


@dataclass
class UIZone:
    """A rectangular region in the UI — may be static (skeleton) or dynamic."""
    name: str
    rect: tuple[int, int, int, int]
    zone_type: str                   # "list" | "messages" | "input" | "toolbar"
    dynamic: bool

    @property
    def width(self) -> int:
        return self.rect[2] - self.rect[0]

    @property
    def height(self) -> int:
        return self.rect[3] - self.rect[1]


@dataclass
class UIBlueprint:
    """Cached structural analysis of a window."""
    window_class: str
    window_size: tuple[int, int]
    elements: list[UIElement] = field(default_factory=list)
    zones: list[UIZone] = field(default_factory=list)
    perception_layers: list[str] = field(default_factory=list)
    created_at: float = 0.0

    def find(self, text: str) -> UIElement | None:
        """Find skeleton element by text (exact or substring)."""
        for e in self.elements:
            if e.text == text:
                return e
        for e in self.elements:
            if text in e.text or e.text in text:
                return e
        return None

    def zone(self, name: str) -> UIZone | None:
        """Find zone by name."""
        for z in self.zones:
            if z.name == name:
                return z
        return None

    def visualize(
        self,
        screenshot: object,
        mode: str = "skeleton",
        save_path: str = "",
    ) -> object:
        """Generate visualization of this blueprint.

        Args:
            screenshot: PIL Image or PNG bytes
            mode: "skeleton" (zone overlay), "annotated" (element boxes),
                  or "grayscale" (adjusted grayscale for debugging)
            save_path: if set, save the result to this path

        Returns:
            PIL Image
        """
        from src.desktop_use.visualize import (
            render_skeleton, render_annotated, render_grayscale,
        )

        if mode == "skeleton":
            result = render_skeleton(screenshot, self)
        elif mode == "annotated":
            result = render_annotated(screenshot)
        elif mode == "grayscale":
            result = render_grayscale(screenshot)
        else:
            raise ValueError(f"Unknown mode: {mode!r}. Use 'skeleton', 'annotated', or 'grayscale'.")

        if save_path:
            result.save(save_path)

        return result
