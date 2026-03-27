"""Unicode Pixel Grid — render images and heatmaps as text using block characters.

Uses U+2584 (lower half block ▄) to encode 2 vertical pixels per character cell.
Foreground color = bottom pixel, background color = top pixel.
Supports 24-bit ANSI color for terminal, and plain block chars for Telegram.

Usage:
    grid = PixelGrid(width=40, height=20)
    grid.set_pixel(x, y, (255, 0, 0))  # red
    print(grid.render_ansi())  # terminal with colors
    print(grid.render_blocks())  # plain blocks for Telegram

    # Or from numpy array:
    text = image_to_text(frame, max_width=60)
"""

from __future__ import annotations


class PixelGrid:
    """2D pixel grid that renders as Unicode block characters."""

    def __init__(self, width: int, height: int):
        # Height must be even (2 pixels per row of text)
        self._width = width
        self._height = height + (height % 2)  # round up to even
        # RGB pixels: [y][x] = (r, g, b)
        self._pixels: list[list[tuple[int, int, int]]] = [
            [(0, 0, 0) for _ in range(width)]
            for _ in range(self._height)
        ]

    def set_pixel(self, x: int, y: int, color: tuple[int, int, int]):
        """Set a pixel color."""
        if 0 <= x < self._width and 0 <= y < self._height:
            self._pixels[y][x] = color

    def render_ansi(self) -> str:
        """Render as ANSI 24-bit color text for terminal.

        Each character = 2 vertical pixels using ▄ (lower half block).
        Top pixel = background color, bottom pixel = foreground color.
        """
        lines = []
        for y in range(0, self._height, 2):
            line = []
            for x in range(self._width):
                top = self._pixels[y][x]
                bot = self._pixels[y + 1][x] if y + 1 < self._height else (0, 0, 0)
                # ANSI: \033[38;2;R;G;B m (foreground) \033[48;2;R;G;B m (background)
                fg = f"\033[38;2;{bot[0]};{bot[1]};{bot[2]}m"
                bg = f"\033[48;2;{top[0]};{top[1]};{top[2]}m"
                line.append(f"{bg}{fg}▄")
            lines.append("".join(line) + "\033[0m")
        return "\n".join(lines)

    def render_blocks(self) -> str:
        """Render as plain block characters (no color, for Telegram/chat).

        Maps brightness to: █▓▒░ · (5 levels).
        """
        BLOCKS = " ░▒▓█"
        lines = []
        for y in range(0, self._height, 2):
            line = []
            for x in range(self._width):
                top = self._pixels[y][x]
                bot = self._pixels[y + 1][x] if y + 1 < self._height else (0, 0, 0)
                # Average brightness of both pixels
                avg = (sum(top) + sum(bot)) / 6  # 0-255
                idx = min(int(avg / 255 * (len(BLOCKS) - 1)), len(BLOCKS) - 1)
                line.append(BLOCKS[idx])
            lines.append("".join(line))
        return "\n".join(lines)

    def render_heatmap(self, values: list[list[float]], max_val: float | None = None) -> str:
        """Render a 2D array as a colored heatmap.

        Values are mapped to a blue→green→yellow→red gradient.
        """
        if not values or not values[0]:
            return ""

        rows = len(values)
        cols = len(values[0])
        if max_val is None:
            max_val = max(max(row) for row in values) or 1.0

        grid = PixelGrid(cols, rows)
        for y in range(rows):
            for x in range(cols):
                v = min(values[y][x] / max_val, 1.0)
                grid.set_pixel(x, y, _heatmap_color(v))

        return grid.render_ansi()


def _heatmap_color(t: float) -> tuple[int, int, int]:
    """Map 0-1 to blue→cyan→green→yellow→red gradient."""
    if t < 0.25:
        s = t / 0.25
        return (0, int(s * 255), 255)  # blue → cyan
    elif t < 0.5:
        s = (t - 0.25) / 0.25
        return (0, 255, int((1 - s) * 255))  # cyan → green
    elif t < 0.75:
        s = (t - 0.5) / 0.25
        return (int(s * 255), 255, 0)  # green → yellow
    else:
        s = (t - 0.75) / 0.25
        return (255, int((1 - s) * 255), 0)  # yellow → red


def image_to_text(image_array, max_width: int = 60) -> str:
    """Convert a numpy image array to Unicode text.

    Args:
        image_array: numpy array (H, W, 3) RGB or (H, W) grayscale
        max_width: maximum character width

    Returns:
        ANSI-colored text representation.
    """
    try:
        import numpy as np
    except ImportError:
        return "[numpy required for image_to_text]"

    h, w = image_array.shape[:2]

    # Downscale to fit max_width
    scale = min(max_width / w, 1.0)
    new_w = int(w * scale)
    new_h = int(h * scale)
    # Make height even
    new_h = new_h + (new_h % 2)

    # Simple nearest-neighbor resize
    y_indices = np.linspace(0, h - 1, new_h).astype(int)
    x_indices = np.linspace(0, w - 1, new_w).astype(int)
    resized = image_array[np.ix_(y_indices, x_indices)]

    grid = PixelGrid(new_w, new_h)
    for y in range(new_h):
        for x in range(new_w):
            pixel = resized[y, x]
            if image_array.ndim == 2:
                v = int(pixel)
                grid.set_pixel(x, y, (v, v, v))
            else:
                grid.set_pixel(x, y, (int(pixel[0]), int(pixel[1]), int(pixel[2])))

    return grid.render_ansi()
