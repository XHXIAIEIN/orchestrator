"""Import PNG sprites/spritesheets and quantize to PICO-8 palette.

Supports:
- Single sprite PNG → indexed numpy array
- Spritesheet PNG → list of animation frames
- GIF → list of animation frames
- Auto-quantization to PICO-8 32-color palette (nearest color)
"""

import math
import numpy as np
from pathlib import Path
from PIL import Image

from .palette import PALETTE, PALETTE_EXT

_ALL_COLORS = np.array(PALETTE + PALETTE_EXT, dtype=np.float32)  # (32, 3)


def _nearest_pico8(r: int, g: int, b: int, a: int = 255) -> int:
    """Find nearest PICO-8 palette index for an RGB(A) color.
    Transparent pixels (a < 128) map to index 0 (black).
    """
    if a < 128:
        return 0
    pixel = np.array([r, g, b], dtype=np.float32)
    dists = np.sum((_ALL_COLORS - pixel) ** 2, axis=1)
    return int(np.argmin(dists))


def _quantize_image(img: Image.Image) -> np.ndarray:
    """Convert a PIL image to PICO-8 indexed numpy array (H, W)."""
    img = img.convert("RGBA")
    pixels = np.array(img)  # (H, W, 4)
    h, w = pixels.shape[:2]
    result = np.zeros((h, w), dtype=np.uint8)

    # Build a cache for speed
    color_cache: dict[tuple, int] = {}

    for y in range(h):
        for x in range(w):
            r, g, b, a = int(pixels[y, x, 0]), int(pixels[y, x, 1]), int(pixels[y, x, 2]), int(pixels[y, x, 3])
            key = (r, g, b, a)
            if key not in color_cache:
                color_cache[key] = _nearest_pico8(r, g, b, a)
            result[y, x] = color_cache[key]

    return result


def load_sprite(path: str | Path) -> np.ndarray:
    """Load a single sprite PNG and quantize to PICO-8 palette.

    Returns: indexed numpy array (H, W) with values 0-31.
    """
    img = Image.open(path)
    return _quantize_image(img)


def load_spritesheet(path: str | Path, frame_width: int, frame_height: int,
                     columns: int | None = None) -> list[np.ndarray]:
    """Load a spritesheet and split into animation frames.

    Args:
        path: Path to spritesheet PNG
        frame_width: Width of each frame in pixels
        frame_height: Height of each frame in pixels
        columns: Number of columns (auto-detect if None)

    Returns: list of indexed numpy arrays, each (frame_height, frame_width).
    """
    img = Image.open(path).convert("RGBA")
    sheet_w, sheet_h = img.size

    if columns is None:
        columns = sheet_w // frame_width

    rows = sheet_h // frame_height
    frames: list[np.ndarray] = []

    for row in range(rows):
        for col in range(columns):
            x0 = col * frame_width
            y0 = row * frame_height
            frame_img = img.crop((x0, y0, x0 + frame_width, y0 + frame_height))
            frames.append(_quantize_image(frame_img))

    return frames


def load_gif(path: str | Path) -> list[np.ndarray]:
    """Load an animated GIF and quantize each frame to PICO-8 palette.

    Returns: list of indexed numpy arrays.
    """
    img = Image.open(path)
    frames: list[np.ndarray] = []

    try:
        while True:
            frame = img.convert("RGBA")
            frames.append(_quantize_image(frame))
            img.seek(img.tell() + 1)
    except EOFError:
        pass

    return frames


def resize_frames(frames: list[np.ndarray], target_w: int, target_h: int) -> list[np.ndarray]:
    """Resize animation frames using nearest-neighbor (preserves pixel art)."""
    resized: list[np.ndarray] = []
    for frame in frames:
        h, w = frame.shape
        img = Image.fromarray(frame, mode="P")
        img = img.resize((target_w, target_h), Image.NEAREST)
        resized.append(np.array(img, dtype=np.uint8))
    return resized


def preview_frame(frame: np.ndarray) -> str:
    """Return a text preview of a frame using block characters (for debugging)."""
    h, w = frame.shape
    lines: list[str] = []
    char_map = " .:-=+*#%@"
    for y in range(h):
        row = ""
        for x in range(w):
            idx = int(frame[y, x])
            if idx == 0:
                row += " "
            else:
                row += char_map[min(idx, len(char_map) - 1)]
            row += " "
        lines.append(row)
    return "\n".join(lines)
