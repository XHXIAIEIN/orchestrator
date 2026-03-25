"""Blueprint visualization — skeleton overlay and element annotation.

Two output modes:
- skeleton: semi-transparent color blocks showing major zones
- annotated: green bounding boxes on every detected element (text + icons)
"""
from __future__ import annotations

import io
import logging
from typing import Optional

from PIL import Image, ImageDraw

from .types import UIBlueprint, OCRWord

log = logging.getLogger(__name__)

# Zone overlay colors (RGBA) — distinct, semi-transparent
ZONE_COLORS = [
    (80, 80, 80, 90),      # gray — icon bars, toolbars
    (60, 60, 200, 70),     # blue — lists, navigation
    (180, 60, 180, 70),    # purple — headers, panels
    (60, 180, 60, 70),     # green — content areas
    (200, 140, 50, 70),    # brown/gold — input areas
    (200, 60, 60, 70),     # red — alerts, special
    (60, 180, 180, 70),    # cyan
    (180, 180, 60, 70),    # yellow
]

ELEMENT_COLOR = (0, 255, 0)  # green for element boxes
ELEMENT_WIDTH = 2


def render_skeleton(
    screenshot: Image.Image | bytes,
    blueprint: UIBlueprint,
) -> Image.Image:
    """Render skeleton overlay — semi-transparent color blocks per zone.

    Args:
        screenshot: PIL Image or PNG bytes
        blueprint: analyzed UIBlueprint with zones

    Returns:
        PIL Image with zone overlays and labels
    """
    if isinstance(screenshot, bytes):
        screenshot = Image.open(io.BytesIO(screenshot))

    base = screenshot.convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    for i, zone in enumerate(blueprint.zones):
        color = ZONE_COLORS[i % len(ZONE_COLORS)]
        r = zone.rect
        draw.rectangle([r[0], r[1], r[2], r[3]], fill=color)

        # Label: zone name + type
        tag = "动态" if zone.dynamic else "骨架"
        label = f"{zone.name} [{tag}]"
        draw.text((r[0] + 8, r[1] + 8), label, fill=(255, 255, 255, 220))

    result = Image.alpha_composite(base, overlay)
    return result.convert("RGB")


def render_annotated(
    screenshot: Image.Image | bytes,
    ocr_words: list[OCRWord] | None = None,
    contour_rects: list[tuple[int, int, int, int]] | None = None,
) -> Image.Image:
    """Render element annotation — green boxes around every detected element.

    Args:
        screenshot: PIL Image or PNG bytes
        ocr_words: OCR-detected words with bounding boxes
        contour_rects: CV-detected rectangular regions (x1, y1, x2, y2)

    Returns:
        PIL Image with green bounding boxes
    """
    if isinstance(screenshot, bytes):
        screenshot = Image.open(io.BytesIO(screenshot))

    img = screenshot.copy().convert("RGB")
    draw = ImageDraw.Draw(img)

    # Draw OCR word boxes
    if ocr_words:
        for w in ocr_words:
            x1, y1 = w.left, w.top
            x2, y2 = x1 + w.width, y1 + w.height
            draw.rectangle([x1, y1, x2, y2], outline=ELEMENT_COLOR, width=ELEMENT_WIDTH)

    # Draw CV contour boxes (non-text elements: icons, avatars, images)
    if contour_rects:
        for r in contour_rects:
            draw.rectangle([r[0], r[1], r[2], r[3]], outline=ELEMENT_COLOR, width=ELEMENT_WIDTH)

    return img


def detect_contour_rects(
    png_bytes: bytes,
    ocr_words: list[OCRWord] | None = None,
    min_area: int = 800,
    max_area: int = 80000,
    min_side: int = 25,
) -> list[tuple[int, int, int, int]]:
    """Detect rectangular UI elements via CV contour detection.

    Finds icon-sized and avatar-sized rectangles that don't overlap with
    OCR words (those are already covered by text annotation).

    Args:
        png_bytes: screenshot as PNG bytes
        ocr_words: OCR words to exclude overlapping regions
        min_area: minimum contour area
        max_area: maximum contour area
        min_side: minimum width/height

    Returns:
        list of (x1, y1, x2, y2) bounding rectangles
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        log.warning("detect_contour_rects: opencv not installed")
        return []

    nparr = np.frombuffer(png_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return []

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    kernel = np.ones((2, 2), np.uint8)
    edges = cv2.dilate(edges, kernel, iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Build OCR exclusion set
    ocr_boxes = []
    if ocr_words:
        for w in ocr_words:
            ocr_boxes.append((w.left, w.top, w.left + w.width, w.top + w.height))

    rects = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area or area > max_area:
            continue
        x, y, rw, rh = cv2.boundingRect(cnt)
        if rw < min_side or rh < min_side:
            continue

        # Skip if overlaps with any OCR word
        overlaps = False
        for ox1, oy1, ox2, oy2 in ocr_boxes:
            if not (x + rw < ox1 or x > ox2 or y + rh < oy1 or y > oy2):
                overlaps = True
                break
        if not overlaps:
            rects.append((x, y, x + rw, y + rh))

    return rects
