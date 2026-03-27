"""Slash command handling for chat channels."""
import logging

from src.channels import config as ch_cfg

log = logging.getLogger(__name__)


def handle_command(text: str, chat_id: str, reply_fn, channel_source: str = "channel"):
    """解析并执行 /command。"""
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower().split("@")[0]  # 去掉 @bot_name
    args = parts[1] if len(parts) > 1 else ""

    if cmd == "/help":
        _cmd_help(reply_fn, chat_id)
    elif cmd == "/status":
        _cmd_status(reply_fn, chat_id)
    elif cmd == "/tasks":
        _cmd_tasks(reply_fn, chat_id)
    elif cmd == "/run":
        _cmd_run(reply_fn, chat_id, args, channel_source)
    elif cmd == "/approve":
        _cmd_approval(reply_fn, chat_id, args, "approve", channel_source)
    elif cmd == "/deny":
        _cmd_approval(reply_fn, chat_id, args, "deny", channel_source)
    elif cmd == "/yolo":
        _cmd_yolo(reply_fn, chat_id, True, channel_source)
    elif cmd == "/noyolo":
        _cmd_yolo(reply_fn, chat_id, False, channel_source)
    elif cmd == "/pending":
        _cmd_pending(reply_fn, chat_id)
    elif cmd == "/channels":
        _cmd_channels(reply_fn, chat_id)
    elif cmd == "/wake":
        _cmd_wake(reply_fn, chat_id, args, channel_source)
    else:
        reply_fn(chat_id, f"未知命令: {cmd}\n发送 /help 查看可用命令")


COMMANDS = {
    "/status": "查看系统状态",
    "/tasks": "最近任务列表",
    "/run": "触发场景执行 (用法: /run <scenario>)",
    "/approve": "批准任务 (用法: /approve <task_id>)",
    "/deny": "拒绝任务 (用法: /deny <task_id>)",
    "/yolo": "别再问了 — 自动批准所有审批",
    "/noyolo": "恢复审批确认",
    "/pending": "查看待审批任务",
    "/channels": "查看 channel 状态",
    "/wake": "查看/派发/控制 wake 任务",
    "/help": "显示帮助",
}


def _cmd_help(reply_fn, chat_id: str):
    lines = ["Orchestrator 命令\n"]
    for cmd, desc in COMMANDS.items():
        lines.append(f"{cmd} — {desc}")
    reply_fn(chat_id, "\n".join(lines))


def _cmd_status(reply_fn, chat_id: str):
    try:
        from src.core.health import HealthCheck
        hc = HealthCheck()
        report = hc.run()
        lines = ["系统状态\n"]
        lines.append(f"整体: {'正常' if report.get('healthy') else '异常'}")
        for name, data in report.get("checks", {}).items():
            mark = "ok" if data.get("ok") else "异常"
            lines.append(f"  {name}: {mark}")
        reply_fn(chat_id, "\n".join(lines))
    except Exception as e:
        reply_fn(chat_id, f"获取状态失败: {e}")


def _cmd_tasks(reply_fn, chat_id: str):
    try:
        from src.storage.events_db import EventsDB
        db = EventsDB()
        tasks = db.query(
            "SELECT task_id, department, status, summary "
            f"FROM tasks ORDER BY created_at DESC LIMIT {ch_cfg.TASKS_DISPLAY_LIMIT}"
        )
        if not tasks:
            reply_fn(chat_id, "暂无任务记录")
            return
        lines = ["最近任务\n"]
        status_labels = {
            "done": "完成", "failed": "失败", "running": "执行中",
            "pending": "等待", "scrutiny_failed": "审查未通过",
        }
        for t in tasks:
            label = status_labels.get(t[2], t[2])
            dept = t[1] or "?"
            summary = (t[3] or "")[:60]
            lines.append(f"  {t[0][:8]} {dept} — {summary} ({label})")
        reply_fn(chat_id, "\n".join(lines))
    except Exception as e:
        reply_fn(chat_id, f"获取任务失败: {e}")


def _cmd_run(reply_fn, chat_id: str, scenario: str, channel_source: str):
    if not scenario.strip():
        reply_fn(chat_id, "用法: /run <scenario_name>")
        return
    try:
        from src.core.event_bus import get_event_bus, Event, Priority
        bus = get_event_bus()
        bus.publish(Event(
            event_type="channel.command.run",
            payload={"scenario": scenario.strip(), "source": channel_source},
            priority=Priority.HIGH,
            source=f"channel:{channel_source}",
        ))
        reply_fn(chat_id, f"已提交: {scenario.strip()}")
    except Exception as e:
        reply_fn(chat_id, f"提交失败: {e}")


def _cmd_yolo(reply_fn, chat_id: str, enabled: bool, channel_source: str):
    try:
        from src.governance.approval import get_approval_gateway
        gw = get_approval_gateway()
        gw.set_yolo(enabled, f"{channel_source}:{chat_id}")
        if enabled:
            reply_fn(chat_id, "YOLO 模式已开启 — 所有审批自动通过\n发送 /noyolo 恢复")
        else:
            reply_fn(chat_id, "YOLO 模式已关闭 — 恢复正常审批流程")
    except Exception as e:
        reply_fn(chat_id, f"操作失败: {e}")


def _cmd_approval(reply_fn, chat_id: str, task_id: str, decision: str, channel_source: str):
    task_id = task_id.strip()
    if not task_id:
        reply_fn(chat_id, f"用法: /{decision} <task_id>")
        return
    try:
        from src.governance.approval import get_approval_gateway
        gw = get_approval_gateway()
        gw.submit_decision(task_id, decision, f"{channel_source}:{chat_id}")
        label = "已批准" if decision == "approve" else "已拒绝"
        reply_fn(chat_id, f"{label}: {task_id}")
    except Exception as e:
        reply_fn(chat_id, f"操作失败: {e}")


def _cmd_pending(reply_fn, chat_id: str):
    try:
        from src.governance.approval import get_approval_gateway
        gw = get_approval_gateway()
        pending = gw.get_pending()
        if not pending:
            reply_fn(chat_id, "无待审批任务")
            return
        lines = ["待审批任务\n"]
        for req in pending:
            lines.append(f"  `{req.task_id}` — {req.description[:80]}")
        lines.append(f"\n使用 /approve <id> 或 /deny <id>")
        reply_fn(chat_id, "\n".join(lines))
    except Exception as e:
        reply_fn(chat_id, f"获取失败: {e}")


def _cmd_channels(reply_fn, chat_id: str):
    try:
        from src.channels.registry import get_channel_registry
        reg = get_channel_registry()
        status = reg.get_status()
        lines = ["Channel 状态\n"]
        for name, info in status.items():
            state = "在线" if info["enabled"] else "离线"
            lines.append(f"  {name} ({info['type']}): {state}")
        reply_fn(chat_id, "\n".join(lines))
    except Exception as e:
        reply_fn(chat_id, f"获取 channel 状态失败: {e}")


def _cmd_wake(reply_fn, chat_id: str, args: str, channel_source: str):
    """Handle /wake command with subcommand routing."""
    from src.channels.wake import (
        parse_wake_command, create_session, cancel_session,
        set_mode, list_active, format_session_status,
    )
    from src.channels import config as ch_cfg

    if not ch_cfg.user_can(chat_id, "wake_claude"):
        reply_fn(chat_id, "权限不足")
        return

    subcmd, rest = parse_wake_command(args)

    if subcmd == "status":
        sessions = list_active(chat_id)
        reply_fn(chat_id, format_session_status(sessions))

    elif subcmd == "cancel":
        msg = cancel_session(chat_id)
        reply_fn(chat_id, msg)

    elif subcmd == "verbose":
        msg = set_mode(chat_id, "milestone")
        reply_fn(chat_id, msg)

    elif subcmd == "quiet":
        msg = set_mode(chat_id, "silent")
        reply_fn(chat_id, msg)

    elif subcmd == "task":
        is_admin = ch_cfg.ALLOWED_USERS.get(chat_id) == "admin"
        result = create_session(
            chat_id=chat_id, spotlight=rest, channel=channel_source,
            auto_approve=is_admin,
        )
        status_msg = "已派发，直接执行" if is_admin else "已提交，等待审批"
        reply_fn(
            chat_id,
            f"Wake #{result['session_id']}（任务 #{result['task_id']}）{status_msg}",
        )
