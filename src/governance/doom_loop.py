"""
Doom Loop Detection — 熔断器，防止 agent 陷入死循环。

orc-safe 启发：
  - 相同 tool+input 滑动窗口重复 5 次 → 触发熔断
  - 同一文件编辑 4 次 → 触发熔断
  - 连续失败 3 次 → 触发熔断

集成点：Governor._run_agent_session 中检查 agent_events。
"""
import json
import logging
from collections import Counter
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class DoomLoopResult:
    """熔断检测结果。"""
    triggered: bool
    reason: str = ""
    details: dict = None

    def __post_init__(self):
        if self.details is None:
            self.details = {}


# ── Thresholds ──
MAX_SAME_TOOL_INPUT = 5     # 同一 tool+input 重复次数
MAX_SAME_FILE_EDITS = 4     # 同一文件编辑次数
MAX_CONSECUTIVE_FAILURES = 3  # 连续失败次数
WINDOW_SIZE = 15             # 滑动窗口大小（最近 N 个 agent turn）


def check_doom_loop(agent_events: list[dict]) -> DoomLoopResult:
    """检查 agent 事件流是否陷入 doom loop。

    Args:
        agent_events: 从 db.get_agent_events() 获取的事件列表

    Returns:
        DoomLoopResult: triggered=True 时应熔断
    """
    if not agent_events:
        return DoomLoopResult(triggered=False)

    # 提取最近的 agent_turn 事件
    turns = []
    for evt in agent_events:
        if evt.get("event_type") != "agent_turn":
            continue
        data = evt.get("data", {})
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                continue
        turns.append(data)

    if not turns:
        return DoomLoopResult(triggered=False)

    # 只看最近的窗口
    recent = turns[-WINDOW_SIZE:]

    # ── Check 1: 相同 tool+input 重复 ──
    tool_inputs = []
    for turn in recent:
        for tool in (turn.get("tools") or []):
            tool_name = tool.get("tool", "")
            input_preview = tool.get("input_preview", "")[:100]
            tool_inputs.append(f"{tool_name}:{input_preview}")

    if tool_inputs:
        counts = Counter(tool_inputs)
        most_common, count = counts.most_common(1)[0]
        if count >= MAX_SAME_TOOL_INPUT:
            return DoomLoopResult(
                triggered=True,
                reason=f"相同操作重复 {count} 次：{most_common[:60]}",
                details={"type": "repeated_tool", "count": count, "tool_input": most_common},
            )

    # ── Check 2: 同一文件被编辑多次 ──
    edited_files = []
    for turn in recent:
        for tool in (turn.get("tools") or []):
            if tool.get("tool") in ("Edit", "Write"):
                inp = tool.get("input_preview", "")
                # 尝试提取文件路径
                if "file_path" in inp:
                    import re
                    m = re.search(r"file_path['\"]?\s*[:=]\s*['\"]?([^'\"}\s,]+)", inp)
                    if m:
                        edited_files.append(m.group(1))

    if edited_files:
        counts = Counter(edited_files)
        most_edited, count = counts.most_common(1)[0]
        if count >= MAX_SAME_FILE_EDITS:
            return DoomLoopResult(
                triggered=True,
                reason=f"文件 {most_edited} 被编辑 {count} 次",
                details={"type": "repeated_edit", "count": count, "file": most_edited},
            )

    # ── Check 3: 连续错误 ──
    consecutive_errors = 0
    for turn in reversed(recent):
        if turn.get("error"):
            consecutive_errors += 1
        else:
            break

    if consecutive_errors >= MAX_CONSECUTIVE_FAILURES:
        return DoomLoopResult(
            triggered=True,
            reason=f"连续 {consecutive_errors} 次错误",
            details={"type": "consecutive_errors", "count": consecutive_errors},
        )

    return DoomLoopResult(triggered=False)
