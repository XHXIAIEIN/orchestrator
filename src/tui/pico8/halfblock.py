"""Convert PICO-8 indexed framebuffer to half-block Rich markup for Textual."""

from .palette import PALETTE, PALETTE_EXT

_ALL = PALETTE + PALETTE_EXT


def _rgb_str(idx: int) -> str:
    r, g, b = _ALL[idx % len(_ALL)]
    return f"rgb({r},{g},{b})"


def render_to_markup(screen, width: int, height: int) -> str:
    """Convert indexed framebuffer (numpy uint8 HxW) to Rich markup string.

    Each terminal row encodes two pixel rows using the ▀ (upper half block)
    character: foreground = top pixel, background = bottom pixel.
    """
    lines: list[str] = []
    for y in range(0, height - 1, 2):
        parts: list[str] = []
        prev_fg = prev_bg = -1
        run: list[str] = []

        for x in range(width):
            top = int(screen[y, x])
            bot = int(screen[y + 1, x])

            if top == prev_fg and bot == prev_bg:
                run.append("▀")
            else:
                if run:
                    parts.append(
                        f"[{_rgb_str(prev_fg)} on {_rgb_str(prev_bg)}]{''.join(run)}[/]"
                    )
                run = ["▀"]
                prev_fg, prev_bg = top, bot

        if run:
            parts.append(
                f"[{_rgb_str(prev_fg)} on {_rgb_str(prev_bg)}]{''.join(run)}[/]"
            )
        lines.append("".join(parts))

    return "\n".join(lines)
