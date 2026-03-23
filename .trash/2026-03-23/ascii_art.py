"""
ASCII Motion Art — Telegram 等宽字体动画。

通过 editMessageText 逐帧更新实现动画效果。
Telegram 限流 ~30 edits/sec，我们用 0.8s/frame 安全间隔。

风格 (CHANNEL_ANIMATION_STYLE):
  - "minimal": 最简 ... 动画（默认）
  - "text":    纯文字百分比
  - "block":   代码块 + 方块字符

思考动画 (CHANNEL_THINKING_STYLE):
  - "dots":  . .. ...（出现，默认）
  - "wave":  .   . .   . . .（位移）
"""
import os

FRAME_INTERVAL = float(os.environ.get("CHANNEL_ANIMATION_INTERVAL", "0.8"))
STYLE = os.environ.get("CHANNEL_ANIMATION_STYLE", "minimal")
THINKING_STYLE = os.environ.get("CHANNEL_THINKING_STYLE", "dots")


# ── Thinking 动画（独立于主风格）──

_THINKING_DOTS = [
    ".",
    "..",
    "...",
]

_THINKING_WAVE = [
    ".",
    ". .",
    ". . .",
    "  . . .",
    "    . . .",
    "      . .",
    "        .",
]

_THINKING_DOTS_BLOCK = [
    "```\n  .       \n```",
    "```\n  ..      \n```",
    "```\n  ...     \n```",
]

_THINKING_WAVE_BLOCK = [
    "```\n  .         \n```",
    "```\n  . .       \n```",
    "```\n  . . .     \n```",
    "```\n    . . .   \n```",
    "```\n      . . . \n```",
    "```\n        . . \n```",
    "```\n          . \n```",
]


# ── Minimal 风格 ──

_BOOT_MINIMAL = [
    "ORCHESTRATOR",
    "ORCHESTRATOR .",
    "ORCHESTRATOR ..",
    "ORCHESTRATOR ...",
    "ORCHESTRATOR ready",
]


def _tool_minimal(tool_name: str) -> list[str]:
    return [f"{tool_name} .", f"{tool_name} ..", f"{tool_name} ..."]


# ── Text 风格 ──

_BOOT_TEXT = [
    "ORCHESTRATOR",
] + [
    f"ORCHESTRATOR — {label}  {pct}%"
    for label, pct in [("loading", 0), ("collectors", 25), ("governor", 50),
                        ("channels", 75), ("ready", 100)]
]


def _tool_text(tool_name: str) -> list[str]:
    return [f"{tool_name}  {pct}%" for pct in range(0, 100, 12)]


# ── Block 风格 ──

_BOOT_BLOCK = [
    "```\n"
    "  ╔══════════════════╗\n"
    "  ║                  ║\n"
    "  ║   ORCHESTRATOR   ║\n"
    "  ║                  ║\n"
    "  ╚══════════════════╝\n"
    "```",

    "```\n"
    "  ╔══════════════════╗\n"
    "  ║  ░░░░░░░░░░░░░░  ║\n"
    "  ║   ORCHESTRATOR   ║\n"
    "  ║  ░░░░░░░░░░░░░░  ║\n"
    "  ╚══════════════════╝\n"
    "         loading...\n"
    "```",

    "```\n"
    "  ╔══════════════════╗\n"
    "  ║  ▓▓▓▓░░░░░░░░░░  ║\n"
    "  ║   ORCHESTRATOR   ║\n"
    "  ║  ▓▓▓▓░░░░░░░░░░  ║\n"
    "  ╚══════════════════╝\n"
    "       collectors...\n"
    "```",

    "```\n"
    "  ╔══════════════════╗\n"
    "  ║  ▓▓▓▓▓▓▓▓░░░░░░  ║\n"
    "  ║   ORCHESTRATOR   ║\n"
    "  ║  ▓▓▓▓▓▓▓▓░░░░░░  ║\n"
    "  ╚══════════════════╝\n"
    "        governor...\n"
    "```",

    "```\n"
    "  ╔══════════════════╗\n"
    "  ║  ▓▓▓▓▓▓▓▓▓▓▓▓░░  ║\n"
    "  ║   ORCHESTRATOR   ║\n"
    "  ║  ▓▓▓▓▓▓▓▓▓▓▓▓░░  ║\n"
    "  ╚══════════════════╝\n"
    "        channels...\n"
    "```",

    "```\n"
    "  ╔══════════════════╗\n"
    "  ║  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓  ║\n"
    "  ║   ORCHESTRATOR   ║\n"
    "  ║  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓  ║\n"
    "  ╚══════════════════╝\n"
    "          ready\n"
    "```",
]


def _tool_block(tool_name: str) -> list[str]:
    bar_states = ["░░░░░░░░", "▓░░░░░░░", "▓▓░░░░░░", "▓▓▓░░░░░",
                  "▓▓▓▓░░░░", "▓▓▓▓▓░░░", "▓▓▓▓▓▓░░", "▓▓▓▓▓▓▓░"]
    return [f"```\n  {tool_name}\n  [{bar}]\n```" for bar in bar_states]


# ══════════════════════════════════════
# Public API
# ══════════════════════════════════════

_BOOTS = {"minimal": _BOOT_MINIMAL, "text": _BOOT_TEXT, "block": _BOOT_BLOCK}
_TOOLS = {"minimal": _tool_minimal, "text": _tool_text, "block": _tool_block}

# Thinking 是 2x2 矩阵：(dots/wave) x (plain/block)
_THINKINGS = {
    ("dots", "minimal"):  _THINKING_DOTS,
    ("dots", "text"):     _THINKING_DOTS,
    ("dots", "block"):    _THINKING_DOTS_BLOCK,
    ("wave", "minimal"):  _THINKING_WAVE,
    ("wave", "text"):     _THINKING_WAVE,
    ("wave", "block"):    _THINKING_WAVE_BLOCK,
}


def get_boot_frames() -> list[str]:
    return _BOOTS.get(STYLE, _BOOT_MINIMAL)


def get_thinking_frames() -> list[str]:
    return _THINKINGS.get((THINKING_STYLE, STYLE), _THINKING_DOTS)


def get_tool_frames(tool_name: str) -> list[str]:
    return _TOOLS.get(STYLE, _tool_minimal)(tool_name)


def progress(pct: int, label: str = "") -> str:
    """Single-frame progress display."""
    if STYLE == "block":
        filled = int(pct / 100 * 20)
        bar = "▓" * filled + "░" * (20 - filled)
        text = f"```\n  [{bar}] {pct}%\n"
        if label:
            text += f"  {label}\n"
        text += "```"
        return text
    else:
        return f"{label}  {pct}%" if label else f"{pct}%"


# Backward compat
BOOT_FRAMES = get_boot_frames()
THINKING_FRAMES = get_thinking_frames()
tool_frames = get_tool_frames
progress_bar = progress
