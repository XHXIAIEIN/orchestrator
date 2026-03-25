"""Pluggable perception layers for UI blueprint analysis.

Each layer extracts structural information from a window using a different
technique. Layers are tried in order by BlueprintBuilder — fast/free first,
expensive last.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from .types import UIElement, UIZone

log = logging.getLogger(__name__)

user32 = ctypes.windll.user32


@dataclass
class PerceptionResult:
    """Output of a single perception layer."""
    elements: list[UIElement] = field(default_factory=list)
    zones: list[UIZone] = field(default_factory=list)
    needs_fallback: bool = False
    layer_name: str = ""


class PerceptionLayer(ABC):
    """Interface for a perception layer."""

    @abstractmethod
    def analyze(self, hwnd: int, rect: tuple[int, int, int, int]) -> PerceptionResult:
        """Analyze a window and return detected elements/zones."""


class Win32Layer(PerceptionLayer):
    """Layer 0: Win32 EnumChildWindows + window properties.

    Free (0ms), works on standard Win32/WPF/WinForms apps.
    Returns needs_fallback=True for self-drawing apps (Qt, Electron, etc.)
    where the child window count is too low to be useful.
    """

    MIN_CHILDREN_FOR_COMPLETE = 5

    def analyze(self, hwnd: int, rect: tuple[int, int, int, int]) -> PerceptionResult:
        children = self._enum_children(hwnd)
        visible = [c for c in children if c["visible"]]
        return self._children_to_elements(visible, parent_rect=rect)

    def _children_to_elements(
        self, children: list[dict], parent_rect: tuple[int, int, int, int]
    ) -> PerceptionResult:
        elements = []
        px, py = parent_rect[0], parent_rect[1]

        for c in children:
            r = c["rect"]
            local_rect = (r[0] - px, r[1] - py, r[2] - px, r[3] - py)
            w, h = local_rect[2] - local_rect[0], local_rect[3] - local_rect[1]
            if w <= 0 or h <= 0:
                continue

            name = c.get("title", "") or c.get("class", "")
            el_type = self._classify_control(c["class"])
            action = "click+type" if el_type == "input" else "click" if el_type != "label" else "display"

            elements.append(UIElement(
                name=name,
                rect=local_rect,
                element_type=el_type,
                action=action,
                text=c.get("title", ""),
                source="win32",
                confidence=1.0,
            ))

        needs_fallback = len(elements) < self.MIN_CHILDREN_FOR_COMPLETE
        return PerceptionResult(
            elements=elements,
            needs_fallback=needs_fallback,
            layer_name="win32",
        )

    @staticmethod
    def _classify_control(class_name: str) -> str:
        cls = class_name.lower()
        if any(k in cls for k in ("edit", "richedit", "textbox", "scintilla")):
            return "input"
        if any(k in cls for k in ("button", "btn")):
            return "button"
        if any(k in cls for k in ("scrollbar",)):
            return "scrollbar"
        if any(k in cls for k in ("listview", "syslistview", "treeview", "systreeview")):
            return "list"
        if any(k in cls for k in ("toolbar", "toolbarwindow")):
            return "toolbar"
        if any(k in cls for k in ("static", "label")):
            return "label"
        return "panel"

    @staticmethod
    def _enum_children(hwnd: int) -> list[dict]:
        results = []

        def callback(child_hwnd, _):
            cls_buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(child_hwnd, cls_buf, 256)
            title_buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(child_hwnd, title_buf, 512)
            r = ctypes.wintypes.RECT()
            user32.GetWindowRect(child_hwnd, ctypes.byref(r))
            vis = bool(user32.IsWindowVisible(child_hwnd))
            results.append({
                "hwnd": child_hwnd,
                "class": cls_buf.value,
                "title": title_buf.value,
                "rect": (r.left, r.top, r.right, r.bottom),
                "visible": vis,
            })
            return True

        PROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_ulong, ctypes.c_ulong)
        user32.EnumChildWindows(hwnd, PROC(callback), 0)
        return results


class CVLayer(PerceptionLayer):
    """Layer 0.5: CV edge detection for self-drawing apps.

    Finds only the *major* structural dividers — lines that span a large
    portion of the window — then merges adjacent same-type cells into
    a small number of semantic zones (icon bar, contact list, chat area, etc.).

    ~15ms, no GPU, no model weights.
    """

    def __init__(self, min_line_ratio: float = 0.4, variance_threshold: float = 2000):
        self.min_line_ratio = min_line_ratio
        self.variance_threshold = variance_threshold

    def analyze(self, hwnd: int, rect: tuple[int, int, int, int]) -> PerceptionResult:
        """Not directly usable — use analyze_image() with screenshot bytes."""
        return PerceptionResult(layer_name="cv", needs_fallback=True)

    def analyze_image(
        self, png_bytes: bytes, window_size: tuple[int, int]
    ) -> PerceptionResult:
        try:
            import cv2
            import numpy as np
        except ImportError:
            log.warning("CVLayer: opencv not installed")
            return PerceptionResult(layer_name="cv", needs_fallback=True)

        nparr = np.frombuffer(png_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return PerceptionResult(layer_name="cv", needs_fallback=True)

        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 30, 120)

        raw_lines = cv2.HoughLinesP(
            edges, 1, np.pi / 180,
            threshold=80, minLineLength=100, maxLineGap=10,
        )

        h_lines, v_lines = [], []
        if raw_lines is not None:
            for line in raw_lines:
                x1, y1, x2, y2 = line[0]
                dx, dy = abs(x2 - x1), abs(y2 - y1)
                length = (dx * dx + dy * dy) ** 0.5
                if dy < 5 and length > w * self.min_line_ratio:
                    h_lines.append(y1)
                elif dx < 5 and length > h * self.min_line_ratio:
                    v_lines.append(x1)

        x_cuts = self._merge_positions(v_lines, threshold=15)
        y_cuts = self._merge_positions(h_lines, threshold=15)

        # Build raw grid cells
        x_edges = sorted(set([0] + x_cuts + [w]))
        y_edges = sorted(set([0] + y_cuts + [h]))

        raw_cells = []
        for yi in range(len(y_edges) - 1):
            for xi in range(len(x_edges) - 1):
                zx1, zy1 = int(x_edges[xi]), int(y_edges[yi])
                zx2, zy2 = int(x_edges[xi + 1]), int(y_edges[yi + 1])
                if zx2 - zx1 < 30 or zy2 - zy1 < 30:
                    continue

                cell = img[zy1:zy2, zx1:zx2]
                variance = float(np.var(cell))
                is_dynamic = variance > self.variance_threshold

                raw_cells.append({
                    "col": xi, "row": yi,
                    "rect": (zx1, zy1, zx2, zy2),
                    "dynamic": is_dynamic,
                })

        # Merge vertically: adjacent cells in same column with same type
        zones = self._merge_cells_vertically(raw_cells)

        return PerceptionResult(
            zones=zones,
            needs_fallback=len(zones) < 2,
            layer_name="cv",
        )

    @staticmethod
    def _merge_cells_vertically(cells: list[dict]) -> list[UIZone]:
        """Merge adjacent cells in the same column if they share dynamic type."""
        # Group by column
        by_col: dict[int, list[dict]] = {}
        for c in cells:
            by_col.setdefault(c["col"], []).append(c)

        zones: list[UIZone] = []
        zone_id = 0

        for col in sorted(by_col.keys()):
            col_cells = sorted(by_col[col], key=lambda c: c["rect"][1])
            if not col_cells:
                continue

            # Walk and merge
            current = col_cells[0].copy()
            for next_cell in col_cells[1:]:
                # Merge if same dynamic type and adjacent (y-gap < 5px)
                gap = next_cell["rect"][1] - current["rect"][3]
                if next_cell["dynamic"] == current["dynamic"] and gap < 5:
                    # Extend current rect downward
                    current["rect"] = (
                        current["rect"][0],
                        current["rect"][1],
                        max(current["rect"][2], next_cell["rect"][2]),
                        next_cell["rect"][3],
                    )
                else:
                    # Emit current, start new
                    zones.append(UIZone(
                        name=f"zone_{zone_id}",
                        rect=current["rect"],
                        zone_type="content" if current["dynamic"] else "panel",
                        dynamic=current["dynamic"],
                    ))
                    zone_id += 1
                    current = next_cell.copy()

            # Emit last
            zones.append(UIZone(
                name=f"zone_{zone_id}",
                rect=current["rect"],
                zone_type="content" if current["dynamic"] else "panel",
                dynamic=current["dynamic"],
            ))
            zone_id += 1

        return zones

    @staticmethod
    def _merge_positions(positions: list[int], threshold: int = 15) -> list[int]:
        if not positions:
            return []
        positions = sorted(positions)
        merged = [positions[0]]
        for p in positions[1:]:
            if p - merged[-1] > threshold:
                merged.append(p)
        return merged


class OCRLayer(PerceptionLayer):
    """Layer 1: WinRT OCR text extraction.

    Converts OCR words to UIElements with bounding boxes.
    Supports partial (zone-cropped) analysis with coordinate offset.

    ~100ms full window, ~30ms per zone crop.
    """

    def __init__(self, engine: object = None, lang: str = "zh-Hans-CN"):
        self.engine = engine
        self.lang = lang

    def analyze(self, hwnd: int, rect: tuple[int, int, int, int]) -> PerceptionResult:
        return PerceptionResult(layer_name="ocr", needs_fallback=True)

    def analyze_words(
        self,
        words: list,
        image_size: tuple[int, int],
        offset: tuple[int, int] = (0, 0),
    ) -> PerceptionResult:
        elements = []
        ox, oy = offset

        for w in words:
            elements.append(UIElement(
                name=w.text,
                rect=(ox + w.left, oy + w.top,
                      ox + w.left + w.width, oy + w.top + w.height),
                element_type="text",
                action="display",
                text=w.text,
                source="ocr",
                confidence=w.conf / 100.0,
            ))

        return PerceptionResult(
            elements=elements,
            needs_fallback=False,
            layer_name="ocr",
        )
