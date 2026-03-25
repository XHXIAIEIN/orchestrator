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


def greedy_expand_boxes(
    seed_boxes: list[tuple[int, int, int, int]],
    img_array,  # numpy array (h, w, 3)
    step: int = 0,
    bg_threshold: float = 0,
) -> list[tuple[int, int, int, int]]:
    """Greedy-expand each seed box outward until hitting empty background.

    For each box, try expanding each edge by `step` pixels. If the
    expanded strip has content (variance > bg_threshold), keep it.
    If it's pure background, stop that edge. Then merge overlapping boxes.

    Args:
        seed_boxes: initial bounding boxes (from OCR + contour detection)
        img_array: screenshot as numpy array
        step: expansion step size in pixels (0 = auto from avg char height)
        bg_threshold: pixel variance below this = empty background

    Returns:
        list of expanded and merged (x1, y1, x2, y2) boxes
    """
    import numpy as np

    if not seed_boxes or img_array is None:
        return list(seed_boxes) if seed_boxes else []

    h, w = img_array.shape[:2]

    # Auto-detect step from average box height (≈ 1 character)
    if step <= 0:
        heights = [b[3] - b[1] for b in seed_boxes if b[3] - b[1] > 5]
        step = max(8, int(np.median(heights)) if heights else 20)

    # Auto-detect background threshold from image corners
    if bg_threshold <= 0:
        corners = [
            img_array[:30, :30],
            img_array[:30, -30:],
            img_array[-30:, :30],
            img_array[-30:, -30:],
        ]
        bg_vars = [float(np.var(c)) for c in corners if c.size > 0]
        bg_threshold = max(bg_vars) * 2 + 50 if bg_vars else 200

    # Expand each box greedily
    expanded = []
    for bx1, by1, bx2, by2 in seed_boxes:
        # Expand in 4 directions
        for _ in range(15):  # max iterations
            grew = False

            # Try expand right
            if bx2 + step <= w:
                strip = img_array[max(0, by1):min(h, by2), bx2:min(w, bx2 + step)]
                if strip.size > 0 and float(np.var(strip)) > bg_threshold:
                    bx2 += step
                    grew = True

            # Try expand left
            if bx1 - step >= 0:
                strip = img_array[max(0, by1):min(h, by2), max(0, bx1 - step):bx1]
                if strip.size > 0 and float(np.var(strip)) > bg_threshold:
                    bx1 -= step
                    grew = True

            # Try expand down
            if by2 + step <= h:
                strip = img_array[by2:min(h, by2 + step), max(0, bx1):min(w, bx2)]
                if strip.size > 0 and float(np.var(strip)) > bg_threshold:
                    by2 += step
                    grew = True

            # Try expand up
            if by1 - step >= 0:
                strip = img_array[max(0, by1 - step):by1, max(0, bx1):min(w, bx2)]
                if strip.size > 0 and float(np.var(strip)) > bg_threshold:
                    by1 -= step
                    grew = True

            if not grew:
                break

        expanded.append((bx1, by1, bx2, by2))

    # Merge overlapping boxes
    return _merge_overlapping(expanded)


def _merge_overlapping(
    boxes: list[tuple[int, int, int, int]],
) -> list[tuple[int, int, int, int]]:
    """Merge boxes that overlap or are contained within each other."""
    if not boxes:
        return []

    merged = True
    result = [list(b) for b in boxes]
    while merged:
        merged = False
        new_result = []
        used = set()
        for i in range(len(result)):
            if i in used:
                continue
            bx1, by1, bx2, by2 = result[i]
            for j in range(i + 1, len(result)):
                if j in used:
                    continue
                cx1, cy1, cx2, cy2 = result[j]

                # Check overlap
                ox1 = max(bx1, cx1)
                oy1 = max(by1, cy1)
                ox2 = min(bx2, cx2)
                oy2 = min(by2, cy2)

                if ox1 < ox2 and oy1 < oy2:
                    # Overlapping — merge
                    bx1 = min(bx1, cx1)
                    by1 = min(by1, cy1)
                    bx2 = max(bx2, cx2)
                    by2 = max(by2, cy2)
                    used.add(j)
                    merged = True

            new_result.append([bx1, by1, bx2, by2])
            used.add(i)
        result = new_result

    return [tuple(b) for b in result]


def render_annotated(
    screenshot: Image.Image | bytes,
    ocr_words: list[OCRWord] | None = None,
    contour_rects: list[tuple[int, int, int, int]] | None = None,
) -> Image.Image:
    """Render element annotation — green boxes around UI components.

    All seed boxes (OCR words + CV contour rects) are fed into greedy
    expansion: each box grows outward until hitting empty background,
    then overlapping boxes are merged. This produces component-level
    boxes (one box per contact item, per message bubble, per icon).

    Args:
        screenshot: PIL Image or PNG bytes
        ocr_words: OCR-detected words with bounding boxes
        contour_rects: CV-detected rectangular regions (x1, y1, x2, y2)

    Returns:
        PIL Image with green bounding boxes
    """
    import numpy as np

    if isinstance(screenshot, bytes):
        img = Image.open(io.BytesIO(screenshot))
    else:
        img = screenshot.copy()

    img = img.convert("RGB")
    img_array = np.array(img)

    # Collect all seed boxes
    seeds: list[tuple[int, int, int, int]] = []
    if ocr_words:
        for w in ocr_words:
            seeds.append((w.left, w.top, w.left + w.width, w.top + w.height))
    if contour_rects:
        seeds.extend(contour_rects)

    # Greedy expand + merge
    element_boxes = greedy_expand_boxes(seeds, img_array)

    # Draw
    draw = ImageDraw.Draw(img)
    for x1, y1, x2, y2 in element_boxes:
        draw.rectangle([x1, y1, x2, y2], outline=ELEMENT_COLOR, width=ELEMENT_WIDTH)

    return img


def detect_contour_rects(
    png_bytes: bytes,
    ocr_words: list[OCRWord] | None = None,
    min_area: int = 400,
    max_area: int = 80000,
    min_side: int = 15,
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

    # Two-pass edge detection: normal + low-threshold for dim icons
    edges_normal = cv2.Canny(gray, 50, 150)
    edges_low = cv2.Canny(gray, 15, 60)
    edges = cv2.bitwise_or(edges_normal, edges_low)

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

    # Infer missing icons from regular spacing patterns
    rects = _infer_missing_from_pattern(rects, img)

    return rects


def _infer_missing_from_pattern(
    rects: list[tuple[int, int, int, int]],
    img,  # numpy array (h, w, 3)
    min_group: int = 3,
    spacing_tolerance: float = 0.25,
) -> list[tuple[int, int, int, int]]:
    """Infer missing elements from regular spacing patterns.

    If 3+ detected rects in a column have consistent vertical spacing,
    fill in gaps where icons should be but weren't detected (e.g. low-
    contrast icons on dark backgrounds).
    """
    import numpy as np

    img_h, img_w = img.shape[:2]

    if len(rects) < min_group:
        return rects

    # Compute background variance for comparison
    # Sample corners to estimate background level
    bg_samples = []
    for patch in [(0, 0, 30, 30), (img_w-30, 0, img_w, 30)]:
        bg_samples.append(float(np.var(img[patch[1]:patch[3], patch[0]:patch[2]])))
    bg_variance = max(bg_samples) if bg_samples else 100

    # Group rects by X center (same column within 20px)
    by_col: dict[int, list[tuple[int, int, int, int]]] = {}
    for r in rects:
        cx = (r[0] + r[2]) // 2
        col_key = cx // 20 * 20
        by_col.setdefault(col_key, []).append(r)

    new_rects = list(rects)

    for col_key, col_rects in by_col.items():
        if len(col_rects) < min_group:
            continue

        # Sort by Y
        col_rects.sort(key=lambda r: r[1])

        # Compute spacing between consecutive rects
        spacings = []
        for i in range(len(col_rects) - 1):
            cy1 = (col_rects[i][1] + col_rects[i][3]) // 2
            cy2 = (col_rects[i + 1][1] + col_rects[i + 1][3]) // 2
            spacings.append(cy2 - cy1)

        if not spacings:
            continue

        # Find the most common spacing (mode)
        median_spacing = sorted(spacings)[len(spacings) // 2]
        if median_spacing < 20:
            continue

        # Typical element size in this column
        avg_w = sum(r[2] - r[0] for r in col_rects) // len(col_rects)
        avg_h = sum(r[3] - r[1] for r in col_rects) // len(col_rects)

        # Find gaps that are ~2x the median spacing (one missing element)
        for i in range(len(col_rects) - 1):
            cy1 = (col_rects[i][1] + col_rects[i][3]) // 2
            cy2 = (col_rects[i + 1][1] + col_rects[i + 1][3]) // 2
            gap = cy2 - cy1

            # How many elements fit in this gap?
            n_missing = round(gap / median_spacing) - 1
            if n_missing < 1:
                continue

            cx = (col_rects[i][0] + col_rects[i][2]) // 2
            for k in range(1, n_missing + 1):
                inferred_cy = cy1 + k * median_spacing
                ix1 = cx - avg_w // 2
                iy1 = inferred_cy - avg_h // 2
                ix2 = ix1 + avg_w
                iy2 = iy1 + avg_h

                # Bounds check
                if iy1 < 0 or iy2 > img_h or ix1 < 0 or ix2 > img_w:
                    continue

                # Verify: inferred position must have content (not blank background)
                patch = img[max(0, iy1):min(img_h, iy2), max(0, ix1):min(img_w, ix2)]
                if patch.size == 0:
                    continue
                patch_var = float(np.var(patch))
                if patch_var < bg_variance * 1.5:
                    continue  # looks like empty background, skip

                new_rects.append((ix1, iy1, ix2, iy2))

    return new_rects
