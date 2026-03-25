"""Blueprint visualization — skeleton overlay and element annotation.

Two output modes:
- skeleton: semi-transparent color blocks showing major zones
- annotated: green bounding boxes on every detected UI component

Element detection uses grayscale + gamma correction + adaptive threshold
+ directional dilation + connected components. Pure CV, no OCR dependency,
~40ms.
"""
from __future__ import annotations

import io
import logging

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
    """Render skeleton overlay — semi-transparent color blocks per zone."""
    if isinstance(screenshot, bytes):
        screenshot = Image.open(io.BytesIO(screenshot))

    base = screenshot.convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    for i, zone in enumerate(blueprint.zones):
        color = ZONE_COLORS[i % len(ZONE_COLORS)]
        r = zone.rect
        draw.rectangle([r[0], r[1], r[2], r[3]], fill=color)

        tag = "动态" if zone.dynamic else "骨架"
        label = f"{zone.name} [{tag}]"
        draw.text((r[0] + 8, r[1] + 8), label, fill=(255, 255, 255, 220))

    result = Image.alpha_composite(base, overlay)
    return result.convert("RGB")


def detect_elements(
    png_bytes: bytes,
    gamma: float = 0.6,
    contrast: float = 1.3,
    brightness: float = 10,
    block_size: int = 51,
    threshold_c: int = -10,
    h_dilate: tuple[int, int] = (2, 15),
    v_dilate: tuple[int, int] = (7, 2),
    min_w: int = 15,
    min_h: int = 10,
) -> list[tuple[int, int, int, int]]:
    """Detect UI elements via grayscale adaptive threshold + morphology.

    Pipeline:
    1. Grayscale + gamma correction (lift dark icons)
    2. Contrast/brightness adjustment
    3. Adaptive threshold (content vs uniform background)
    4. Morphological close (seal small gaps within components)
    5. Horizontal dilation (connect icon + text on same row)
    6. Vertical dilation (connect title + subtitle)
    7. Connected component analysis → bounding boxes

    ~40ms, pure CV, no OCR or ML models needed.

    Args:
        png_bytes: screenshot as PNG bytes
        gamma: gamma correction value (<1 lifts shadows)
        contrast: contrast multiplier
        brightness: brightness offset
        block_size: adaptive threshold block size
        threshold_c: adaptive threshold constant (more negative = more selective)
        h_dilate: (height, width) of horizontal dilation kernel
        v_dilate: (height, width) of vertical dilation kernel
        min_w: minimum element width
        min_h: minimum element height

    Returns:
        list of (x1, y1, x2, y2) bounding rectangles
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        log.warning("detect_elements: opencv not installed")
        return []

    nparr = np.frombuffer(png_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return []

    img_h, img_w = img.shape[:2]

    # 1. Grayscale + gamma + contrast
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gray_gamma = np.power(gray / 255.0, gamma) * 255.0
    gray_adj = np.clip(contrast * gray_gamma + brightness, 0, 255).astype(np.uint8)

    # 2. Adaptive threshold
    binary = cv2.adaptiveThreshold(
        gray_adj, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, blockSize=block_size, C=threshold_c,
    )

    # 3. Close small gaps within components
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, np.ones((4, 4), np.uint8))

    # 4. Horizontal dilation — connect icon + text on same row
    binary = cv2.dilate(binary, np.ones(h_dilate, np.uint8), iterations=1)

    # 5. Vertical dilation — connect title + subtitle
    binary = cv2.dilate(binary, np.ones(v_dilate, np.uint8), iterations=1)

    # 6. Remove noise
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

    # 7. Connected components
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    rects = []
    for cnt in contours:
        x, y, rw, rh = cv2.boundingRect(cnt)
        if rw < min_w or rh < min_h:
            continue
        if rw > img_w * 0.95 and rh > img_h * 0.95:
            continue
        rects.append((x, y, x + rw, y + rh))

    return rects


def render_annotated(
    screenshot: Image.Image | bytes,
    element_rects: list[tuple[int, int, int, int]] | None = None,
) -> Image.Image:
    """Render element annotation — green boxes around detected UI components.

    If element_rects is not provided, runs detect_elements() automatically.

    Args:
        screenshot: PIL Image or PNG bytes
        element_rects: pre-computed element bounding boxes (optional)

    Returns:
        PIL Image with green bounding boxes
    """
    if isinstance(screenshot, bytes):
        png_bytes = screenshot
        img = Image.open(io.BytesIO(screenshot))
    else:
        img = screenshot.copy()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_bytes = buf.getvalue()

    img = img.convert("RGB")

    if element_rects is None:
        element_rects = detect_elements(png_bytes)

    draw = ImageDraw.Draw(img)
    for x1, y1, x2, y2 in element_rects:
        draw.rectangle([x1, y1, x2, y2], outline=ELEMENT_COLOR, width=ELEMENT_WIDTH)

    return img


def render_grayscale(
    screenshot: Image.Image | bytes,
    gamma: float = 0.6,
    contrast: float = 1.3,
    brightness: float = 10,
) -> Image.Image:
    """Render adjusted grayscale — the intermediate used for element detection.

    Useful for debugging and visual inspection.
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        if isinstance(screenshot, bytes):
            return Image.open(io.BytesIO(screenshot)).convert("L")
        return screenshot.convert("L")

    if isinstance(screenshot, bytes):
        nparr = np.frombuffer(screenshot, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    else:
        img = np.array(screenshot.convert("RGB"))
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gray_gamma = np.power(gray / 255.0, gamma) * 255.0
    gray_adj = np.clip(contrast * gray_gamma + brightness, 0, 255).astype(np.uint8)

    return Image.fromarray(gray_adj, mode="L")
