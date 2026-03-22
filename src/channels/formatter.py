"""
消息格式化器 — Event Bus 事件 → 人类可读消息。

将结构化的事件数据转为 Markdown 格式文本，供各 Channel 推送。
"""
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
