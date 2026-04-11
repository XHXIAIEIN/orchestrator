"""
Wake Session Manager — 创建、查询、取消 wake session。

DB-driven，不再写文件。tmp/wake/{channel}/{session_id}/ 仅用作临时工作目录。
"""
import logging
from datetime import datetime, timezone
from pathlib import Path

from src.storage.events_db import EventsDB

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent
while _REPO_ROOT != _REPO_ROOT.parent and not ((_REPO_ROOT / "departments").is_dir() and (_REPO_ROOT / "src").is_dir()):
    _REPO_ROOT = _REPO_ROOT.parent

WAKE_WORK_DIR = _REPO_ROOT / "tmp" / "wake"


def _execute_task(task_id: int, db: EventsDB):
    """Kick off task execution via Governor in a background thread."""
    import threading

    def _run():
        try:
            from src.governance.governor import Governor
            gov = Governor(db=db)
            gov.execute_task_async(task_id)
            log.info(f"wake: task #{task_id} dispatched to executor")
        except Exception as e:
            log.error(f"wake: task #{task_id} execution failed: {e}")

    threading.Thread(target=_run, daemon=True, name=f"wake-exec-{task_id}").start()

# Sub-commands reserved words — first token match
_SUBCOMMANDS = {"cancel", "verbose", "quiet"}


def create_session(chat_id: str, spotlight: str, channel: str = "telegram",
                   mode: str = "silent", db: EventsDB = None,
                   auto_approve: bool = False) -> dict:
    """Create a wake session + Governor task. Returns {"session_id", "task_id"}."""
    db = db or EventsDB()

    # admin auto-approve: source='auto' → status='pending' (executor picks it up)
    source = "auto" if auto_approve else "wake"

    task_id = db.create_task(
        action=spotlight,
        reason=f"Wake request from {channel}:{chat_id}",
        priority="high",
        spec={"summary": spotlight, "source": "wake", "chat_id": chat_id},
        source=source,
    )

    session_status = "approved" if auto_approve else "pending"
    session_id = db.create_wake_session(
        task_id=task_id,
        chat_id=chat_id,
        spotlight=spotlight,
        mode=mode,
        status=session_status,
    )

    work_dir = WAKE_WORK_DIR / channel / str(session_id)
    work_dir.mkdir(parents=True, exist_ok=True)

    log.info(f"wake: session #{session_id} created (task #{task_id}): {spotlight}")

    # auto_approve → kick off execution immediately
    if auto_approve:
        _execute_task(task_id, db)

    return {"session_id": session_id, "task_id": task_id}


def cancel_session(chat_id: str, db: EventsDB = None) -> str:
    """Cancel the active wake session for a chat. Returns status message."""
    db = db or EventsDB()
    session = db.get_active_wake_session(chat_id)
    if not session:
        return "没有正在进行的 wake 任务"

    sid = session["id"]
    old_status = session["status"]

    if old_status == "pending":
        db.finish_wake_session(sid, status="cancelled")
        db.update_task(session["task_id"], status="cancelled")
        return f"Wake #{sid} 已取消（还没开始审批）"

    if old_status == "approved":
        db.finish_wake_session(sid, status="cancelled")
        return f"Wake #{sid} 已取消（审批通过但还没执行）"

    if old_status == "running":
        db.update_wake_session(sid, status="cancelled")
        return f"Wake #{sid} 正在取消（等待当前 turn 结束）"

    return f"Wake #{sid} 状态为 {old_status}，无法取消"


def set_mode(chat_id: str, mode: str, db: EventsDB = None) -> str:
    """Switch mode for the active wake session. Returns status message."""
    db = db or EventsDB()
    session = db.get_active_wake_session(chat_id)
    if not session:
        return "没有正在进行的 wake 任务"

    db.update_wake_session(session["id"], mode=mode)
    label = "里程碑模式（实时推送进度）" if mode == "milestone" else "静默模式（完成后推送报告）"
    return f"Wake #{session['id']} 已切换到{label}"


def list_active(chat_id: str = "", db: EventsDB = None) -> list[dict]:
    """List active wake sessions, optionally filtered by chat_id."""
    db = db or EventsDB()
    active = []
    for status in ("pending", "approved", "running"):
        active.extend(db.get_wake_sessions(status=status))
    if chat_id:
        active = [s for s in active if s["chat_id"] == chat_id]
    return active


def format_session_status(sessions: list[dict]) -> str:
    """Format session list for display."""
    if not sessions:
        return "没有活跃的 wake 任务"
    lines = []
    for s in sessions:
        elapsed = ""
        if s["started_at"]:
            start = datetime.fromisoformat(s["started_at"])
            mins = int((datetime.now(timezone.utc) - start).total_seconds() / 60)
            elapsed = f" ({mins}min)"
        lines.append(
            f"#{s['id']} [{s['status']}] {s['spotlight']}{elapsed}"
        )
    return "\n".join(lines)


def parse_wake_command(args: str) -> tuple[str, str]:
    """Parse /wake args. Returns (subcommand, rest) or ('task', full_args)."""
    if not args.strip():
        return ("status", "")
    parts = args.strip().split(maxsplit=1)
    first = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""
    if first in _SUBCOMMANDS:
        return (first, rest)
    return ("task", args.strip())


def on_task_approved(task_id: int, db: EventsDB = None):
    """Callback: Governor approved a wake task → mark session as approved + execute."""
    db = db or EventsDB()
    session = db.get_wake_session_by_task(task_id)
    if not session:
        return
    if session["status"] == "pending":
        db.update_wake_session(session["id"], status="approved")
        log.info(f"wake: session #{session['id']} approved (task #{task_id})")
        _execute_task(task_id, db)


def on_task_denied(task_id: int, reason: str = "", db: EventsDB = None):
    """Callback: Governor denied a wake task → mark session as denied.

    R47 Archon steal: If reason is provided, it's a rejection with feedback.
    The session can be retried with the rejection reason fed back to the agent.
    """
    db = db or EventsDB()
    session = db.get_wake_session_by_task(task_id)
    if not session:
        return

    # Track rejection count for the rejection loop
    rejection_count = (session.get("rejection_count") or 0) + 1
    max_rejections = 3  # Archon default

    if rejection_count >= max_rejections:
        db.finish_wake_session(session["id"], status="denied")
        log.info(f"wake: session #{session['id']} denied after {rejection_count} rejections")
        _notify(session, "denied")
        return

    if reason:
        # Rejection with feedback — allow retry
        db.update_wake_session(
            session["id"],
            status="rejected",
            rejection_reason=reason,
            rejection_count=rejection_count,
        )
        log.info(f"wake: session #{session['id']} rejected ({rejection_count}/{max_rejections}): {reason[:100]}")
        _notify(session, "rejected", milestone={"msg": f"拒绝原因: {reason}\n可修改后重新提交 ({rejection_count}/{max_rejections})"})
    else:
        db.finish_wake_session(session["id"], status="denied")
        log.info(f"wake: session #{session['id']} denied (task #{task_id})")


def format_wake_notification(session: dict, event_type: str,
                             milestone: dict = None) -> str:
    """Format a wake notification message for TG/WX."""
    sid = session["id"]
    spot = session["spotlight"]

    if event_type == "started":
        return f"Wake #{sid} 开始执行\n{spot}"
    elif event_type == "milestone":
        return f"Wake #{sid}: {milestone.get('msg', '')}"
    elif event_type == "done":
        result = session.get("result", "")[:800]
        return f"Wake #{sid} 完成\n{spot}\n\n{result}"
    elif event_type == "failed":
        result = session.get("result", "")[:500]
        return f"Wake #{sid} 失败\n{result}"
    elif event_type == "cancelled":
        return f"Wake #{sid} 已取消"
    elif event_type == "denied":
        return f"Wake #{sid} 审批被拒"
    elif event_type == "approved":
        return f"Wake #{sid} 审批通过，排队执行中"
    return f"Wake #{sid}: {event_type}"


def _notify(session: dict, event_type: str, milestone: dict = None):
    """Push wake notification to all channels."""
    try:
        from src.channels.registry import get_channel_registry
        from src.channels.base import ChannelMessage
        text = format_wake_notification(session, event_type, milestone)
        reg = get_channel_registry()
        reg.broadcast(ChannelMessage(
            text=text, event_type=f"wake.{event_type}", priority="HIGH",
        ))
    except Exception as e:
        log.warning(f"wake: notification failed: {e}")
