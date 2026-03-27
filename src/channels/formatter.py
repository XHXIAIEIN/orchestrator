"""
消息格式化器 — Event Bus 事件 → 人类可读消息。

将结构化的事件数据转为 Markdown 格式文本，供各 Channel 推送。

从 Carbonyl 偷师 #3: Unicode 块字符可视化。
Carbonyl 用 U+2584 (▄) 让终端字符格承载 2 个像素。
同理，我们用 Unicode 块字符在 Telegram 等等宽字体环境
里渲染热力图、状态矩阵、简易图表。
"""
from __future__ import annotations

from src.channels.base import ChannelMessage

# 部门中文名映射
DEPT_NAMES = {
    "engineering": "工部",
    "operations": "礼部",
    "protocol": "中书省",
    "security": "兵部",
    "quality": "刑部",
    "personnel": "吏部",
}

# 事件类型 → 模板
_TEMPLATES: dict[str, str] = {
    "task.completed":     "{dept}任务完成: {summary}",
    "task.failed":        "{dept}任务失败: {error}",
    "task.gate_failed":   "门下省质量门禁未通过: {reason}",
    "task.escalated":     "任务需要人工介入: {summary}",
    "task.started":       "{dept}任务开始: {summary}",
    "health.degraded":    "系统健康异常: {details}",
    "health.recovered":   "系统恢复正常",
    "collector.failed":   "采集器故障: {collector}",
    "doom_loop.detected": "Doom Loop: {task_id} 已被终止",
}


def format_event(event_type: str, data: dict, department: str = "") -> ChannelMessage:
    """将事件格式化为 ChannelMessage。"""
    dept_display = DEPT_NAMES.get(department, department)
    priority = data.get("priority", "NORMAL")
    if isinstance(priority, int):
        priority = ["CRITICAL", "HIGH", "NORMAL", "LOW"][min(priority, 3)]

    template = _TEMPLATES.get(event_type)
    if template:
        format_data = {
            "dept": f"{dept_display} " if dept_display else "",
            "summary": data.get("summary") or data.get("task_id", "?"),
            "error": data.get("error") or data.get("reason", "未知错误"),
            "reason": data.get("reason", "?"),
            "details": data.get("details") or data.get("message", "?"),
            "collector": data.get("collector", "?"),
            "task_id": data.get("task_id", "?"),
        }
        text = template.format(**format_data)
    else:
        summary = data.get("summary") or data.get("message") or str(data)[:200]
        text = f"{dept_display or '系统'} {event_type}: {summary}"

    return ChannelMessage(
        text=text,
        event_type=event_type,
        priority=priority,
        department=department,
    )


# ── Carbonyl 偷师: Unicode 块字符可视化工具 ────────────────────
# ▄▀█░▒▓ 在等宽字体环境（Telegram/终端）里画全彩低分辨率图

# 8 级灰度块字符，从空到满
_BLOCK_CHARS = " ░▒▓█"


def spark_bar(values: list[float], width: int = 0) -> str:
    """将数值列表渲染为 Unicode 火花条（spark line）。

    每个值映射到 ▁▂▃▄▅▆▇█ 之一。
    适合在一行内展示趋势：CPU、内存、请求量等。

    >>> spark_bar([0.1, 0.4, 0.8, 0.3, 1.0, 0.6])
    '▁▃▆▂█▅'
    """
    if not values:
        return ""
    sparks = "▁▂▃▄▅▆▇█"
    lo, hi = min(values), max(values)
    spread = hi - lo if hi > lo else 1.0
    result = []
    for v in values:
        idx = int((v - lo) / spread * (len(sparks) - 1))
        result.append(sparks[min(idx, len(sparks) - 1)])
    return "".join(result)


def heat_row(values: list[float], label: str = "") -> str:
    """将一行数值渲染为带颜色语义的块字符行。

    0.0=空白, 0.25=░, 0.5=▒, 0.75=▓, 1.0=█
    适合状态矩阵：每行一个部门/服务，每列一个时间段。

    >>> heat_row([0.0, 0.3, 0.7, 1.0], label="工部")
    '工部  ░▓█'
    """
    prefix = f"{label} " if label else ""
    cells = []
    for v in values:
        idx = int(v * (len(_BLOCK_CHARS) - 1))
        cells.append(_BLOCK_CHARS[min(idx, len(_BLOCK_CHARS) - 1)])
    return prefix + "".join(cells)


def status_matrix(rows: dict[str, list[float]]) -> str:
    """渲染部门状态矩阵——多行 heat_row 组合。

    rows: {部门名: [时段1负载, 时段2负载, ...]}，值域 0.0-1.0

    输出示例（等宽字体下对齐）::

        工部 ░▒▓█▓▒░
        礼部 ▒▒▒▓▓▒▒
        兵部 ░░░░█░░
    """
    if not rows:
        return ""
    max_label = max(len(k) for k in rows)
    lines = []
    for label, values in rows.items():
        padded = label.ljust(max_label)
        lines.append(heat_row(values, label=padded))
    return "\n".join(lines)


def progress_bar(value: float, width: int = 10, label: str = "") -> str:
    """渲染百分比进度条。

    >>> progress_bar(0.73, width=10, label="部署")
    '部署 [███████▒░░] 73%'
    """
    value = max(0.0, min(1.0, value))
    filled = int(value * width)
    partial = value * width - filled
    bar = "█" * filled
    if filled < width:
        if partial > 0.5:
            bar += "▓"
        elif partial > 0.25:
            bar += "▒"
        elif partial > 0:
            bar += "░"
        else:
            bar += "░"
        bar += "░" * (width - len(bar))
    prefix = f"{label} " if label else ""
    return f"{prefix}[{bar}] {int(value * 100)}%"
