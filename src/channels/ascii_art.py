"""
ASCII Motion Art — Telegram 等宽字体动画。

通过 editMessageText 逐帧更新实现动画效果。
Telegram 限流 ~30 edits/sec，我们用 0.8s/frame 安全间隔。

两种风格：
  - "block": 代码块 + 方块字符（需要等宽字体支持）
  - "text":  纯文字百分比（任何字体都能看）

通过 CHANNEL_ANIMATION_STYLE 环境变量切换。
"""
import os

FRAME_INTERVAL = float(os.environ.get("CHANNEL_ANIMATION_INTERVAL", "0.8"))
STYLE = os.environ.get("CHANNEL_ANIMATION_STYLE", "minimal")  # "block", "text", or "minimal"


# ══════════════════════════════════════
# Block 风格（代码块 + ▓░ 字符）
# ══════════════════════════════════════

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

_THINKING_BLOCK = [
    "```\n  .         \n```",
    "```\n  . .       \n```",
    "```\n  . . .     \n```",
    "```\n    . . .   \n```",
    "```\n      . . . \n```",
    "```\n        . . \n```",
    "```\n          . \n```",
]


def _tool_block(tool_name: str) -> list[str]:
    bar_states = ["░░░░░░░░", "▓░░░░░░░", "▓▓░░░░░░", "▓▓▓░░░░░",
                  "▓▓▓▓░░░░", "▓▓▓▓▓░░░", "▓▓▓▓▓▓░░", "▓▓▓▓▓▓▓░"]
    return [f"```\n  {tool_name}\n  [{bar}]\n```" for bar in bar_states]


# ══════════════════════════════════════
# Text 风格（纯文字百分比，无代码块）
# ══════════════════════════════════════

_BOOT_STEPS = [
    ("loading", 0),
    ("collectors", 25),
    ("governor", 50),
    ("channels", 75),
    ("ready", 100),
]

_BOOT_TEXT = [
    "ORCHESTRATOR",
] + [
    f"ORCHESTRATOR — {label}  {pct}%"
    for label, pct in _BOOT_STEPS
]

_THINKING_TEXT = [
    ".",
    ". .",
    ". . .",
    "  . . .",
    "    . . .",
    "      . .",
    "        .",
]


def _tool_text(tool_name: str) -> list[str]:
    return [f"{tool_name}  {pct}%" for pct in range(0, 100, 12)]


# ══════════════════════════════════════
# Minimal 风格（最简 ... 动画）
# ══════════════════════════════════════

_BOOT_MINIMAL = [
    "ORCHESTRATOR",
    "ORCHESTRATOR .",
    "ORCHESTRATOR ..",
    "ORCHESTRATOR ...",
    "ORCHESTRATOR ready",
]

_THINKING_MINIMAL = [
    ".",
    "..",
    "...",
]


def _tool_minimal(tool_name: str) -> list[str]:
    return [f"{tool_name} .", f"{tool_name} ..", f"{tool_name} ..."]


# ══════════════════════════════════════
# Public API — 根据 STYLE 自动选择
# ══════════════════════════════════════

_STYLES = {
    "block": {
        "boot": lambda: _BOOT_BLOCK,
        "thinking": lambda: _THINKING_BLOCK,
        "tool": _tool_block,
    },
    "text": {
        "boot": lambda: _BOOT_TEXT,
        "thinking": lambda: _THINKING_TEXT,
        "tool": _tool_text,
    },
    "minimal": {
        "boot": lambda: _BOOT_MINIMAL,
        "thinking": lambda: _THINKING_MINIMAL,
        "tool": _tool_minimal,
    },
}


def _get(key: str):
    return _STYLES.get(STYLE, _STYLES["minimal"])[key]


def get_boot_frames() -> list[str]:
    return _get("boot")()


def get_thinking_frames() -> list[str]:
    return _get("thinking")()


def get_tool_frames(tool_name: str) -> list[str]:
    return _get("tool")(tool_name)


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
        if label:
            return f"{label}  {pct}%"
        return f"{pct}%"


# Backward compat aliases
BOOT_FRAMES = get_boot_frames()
THINKING_FRAMES = get_thinking_frames()
tool_frames = get_tool_frames
progress_bar = progress
