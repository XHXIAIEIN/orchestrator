"""Terminal Display — structured ANSI output for status dashboards.

Lightweight alternative to a full TUI framework. Renders status panels,
tables, and progress bars directly to terminal with ANSI codes.
"""

import os
import sys


class TerminalDisplay:
    """Render structured status panels in the terminal."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    CYAN = "\033[36m"

    def __init__(self, width: int | None = None):
        self._width = width or os.get_terminal_size().columns

    def panel(self, title: str, content: str, border_color: str = "") -> str:
        """Render a bordered panel."""
        color = border_color or self.CYAN
        w = self._width - 2
        lines = content.split("\n")

        result = []
        result.append(f"{color}┌{'─' * w}┐{self.RESET}")
        result.append(f"{color}│{self.RESET} {self.BOLD}{title}{self.RESET}{' ' * (w - len(title) - 1)}{color}│{self.RESET}")
        result.append(f"{color}├{'─' * w}┤{self.RESET}")
        for line in lines:
            padding = w - len(self._strip_ansi(line)) - 1
            if padding < 0:
                padding = 0
            result.append(f"{color}│{self.RESET} {line}{' ' * padding}{color}│{self.RESET}")
        result.append(f"{color}└{'─' * w}┘{self.RESET}")
        return "\n".join(result)

    def table(self, headers: list[str], rows: list[list[str]]) -> str:
        """Render a simple table."""
        col_widths = [len(h) for h in headers]
        for row in rows:
            for i, cell in enumerate(row):
                if i < len(col_widths):
                    col_widths[i] = max(col_widths[i], len(self._strip_ansi(str(cell))))

        result = []
        # Header
        header_line = " │ ".join(
            f"{self.BOLD}{h:<{col_widths[i]}}{self.RESET}" for i, h in enumerate(headers)
        )
        result.append(header_line)
        result.append("─┼─".join("─" * w for w in col_widths))
        # Rows
        for row in rows:
            cells = []
            for i, cell in enumerate(row):
                w = col_widths[i] if i < len(col_widths) else 10
                cells.append(f"{str(cell):<{w}}")
            result.append(" │ ".join(cells))
        return "\n".join(result)

    def progress_bar(self, label: str, value: float, width: int = 30) -> str:
        """Render a progress bar. value is 0.0-1.0."""
        filled = int(value * width)
        empty = width - filled

        if value >= 0.8:
            color = self.RED
        elif value >= 0.5:
            color = self.YELLOW
        else:
            color = self.GREEN

        bar = f"{color}{'█' * filled}{'░' * empty}{self.RESET}"
        pct = f"{value * 100:.0f}%"
        return f"{label}: {bar} {pct}"

    def status_line(self, items: dict[str, str]) -> str:
        """Render a status line with key-value pairs."""
        parts = []
        for key, val in items.items():
            parts.append(f"{self.DIM}{key}:{self.RESET} {val}")
        return " │ ".join(parts)

    @staticmethod
    def _strip_ansi(text: str) -> str:
        """Remove ANSI escape codes for length calculation."""
        import re
        return re.sub(r'\033\[[0-9;]*m', '', text)

    def clear(self):
        """Clear terminal screen."""
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()
