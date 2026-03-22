"""
ASCII Motion Art — Telegram 等宽字体动画。

通过 editMessageText 逐帧更新实现动画效果。
Telegram 限流 ~30 edits/sec，我们用 0.8s/frame 安全间隔。
"""

FRAME_INTERVAL = 0.8  # seconds between frames

# ── 启动动画 ──

BOOT_FRAMES = [
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

# ── 思考动画（等待 LLM 响应时循环播放）──

THINKING_FRAMES = [
    "```\n"
    "  .         \n"
    "```",
    "```\n"
    "  . .       \n"
    "```",
    "```\n"
    "  . . .     \n"
    "```",
    "```\n"
    "    . . .   \n"
    "```",
    "```\n"
    "      . . . \n"
    "```",
    "```\n"
    "        . . \n"
    "```",
    "```\n"
    "          . \n"
    "```",
]

# ── 工具执行动画 ──

def tool_frames(tool_name: str) -> list[str]:
    """Generate frames for tool execution."""
    bar_states = ["░░░░░░░░", "▓░░░░░░░", "▓▓░░░░░░", "▓▓▓░░░░░",
                  "▓▓▓▓░░░░", "▓▓▓▓▓░░░", "▓▓▓▓▓▓░░", "▓▓▓▓▓▓▓░"]
    return [
        f"```\n  {tool_name}\n  [{bar}]\n```"
        for bar in bar_states
    ]

# ── 任务进度 ──

def progress_bar(pct: int, label: str = "") -> str:
    """Static progress bar (single frame)."""
    filled = int(pct / 100 * 20)
    bar = "▓" * filled + "░" * (20 - filled)
    text = f"```\n  [{bar}] {pct}%\n"
    if label:
        text += f"  {label}\n"
    text += "```"
    return text
