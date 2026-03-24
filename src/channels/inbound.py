"""
入站命令路由 — 把 Channel 层收到的命令接到 Governor / Health 等系统。

Telegram /run 命令 → publish channel.command.run 事件 → 这里订阅并调用 Governor。
执行完成/失败后通过 Channel registry 广播结果。
"""
import logging
import threading

from src.core.event_bus import get_event_bus, Event
from src.channels.base import ChannelMessage

log = logging.getLogger(__name__)


def register_inbound_handlers(db_path: str = ""):
    """在 Event Bus 上注册入站命令的 handler。"""
    bus = get_event_bus()

    def _handle_run(event: Event):
        """处理 /run <scenario> 命令。"""
        scenario = event.payload.get("scenario", "").strip()
        source = event.payload.get("source", "unknown")
        if not scenario:
            return

        log.info(f"inbound: /run '{scenario}' from {source}")

        thread = threading.Thread(
            target=_execute_run,
            args=(scenario, db_path),
            name=f"inbound-run-{scenario}",
            daemon=True,
        )
        thread.start()

    def _handle_approve(event: Event):
        """处理 /approve <task_id> 命令。"""
        task_id = event.payload.get("task_id", "").strip()
        source = event.payload.get("source", "channel")
        if not task_id:
            return
        log.info(f"inbound: /approve '{task_id}' from {source}")
        try:
            from src.governance.approval import get_approval_gateway
            gw = get_approval_gateway()
            gw.submit_decision(task_id, "approve", source)
        except Exception as e:
            log.error(f"inbound: approve failed: {e}")

    def _handle_deny(event: Event):
        """处理 /deny <task_id> 命令。"""
        task_id = event.payload.get("task_id", "").strip()
        source = event.payload.get("source", "channel")
        if not task_id:
            return
        log.info(f"inbound: /deny '{task_id}' from {source}")
        try:
            from src.governance.approval import get_approval_gateway
            gw = get_approval_gateway()
            gw.submit_decision(task_id, "deny", source)
        except Exception as e:
            log.error(f"inbound: deny failed: {e}")

    bus.subscribe("channel.command.run", _handle_run)
    bus.subscribe("channel.command.approve", _handle_approve)
    bus.subscribe("channel.command.deny", _handle_deny)
    log.info("inbound: registered handlers for run/approve/deny")


def _notify(text: str):
    """通过 Channel registry 广播通知。"""
    try:
        from src.channels.registry import get_channel_registry
        reg = get_channel_registry()
        reg.broadcast(ChannelMessage(text=text, event_type="inbound.result", priority="HIGH"))
    except Exception:
        pass


def _execute_run(scenario: str, db_path: str):
    """执行场景（在后台线程），完成后通知。"""
    try:
        from src.storage.events_db import EventsDB
        from src.governance.governor import Governor

        db = EventsDB(db_path) if db_path else EventsDB()
        gov = Governor(db=db)

        # 先尝试 parallel scenario
        results = gov.run_parallel_scenario(scenario)
        if results:
            db.write_log(
                f"Channel 触发场景 '{scenario}': 派发 {len(results)} 个任务",
                "INFO", "channels",
            )
            _notify(f"场景 {scenario} 已派发 {len(results)} 个任务")
            return

        # 不是预定义 scenario → 当作单任务执行
        task_id = db.create_task(
            action=scenario,
            reason="Channel 入站命令触发",
            priority="medium",
            spec={
                "summary": scenario,
                "problem": f"用户通过消息平台请求: {scenario}",
                "source": "channel",
            },
            source="channel",
        )
        gov.execute_task(task_id)

        # 查结果通知
        row = db.query(f"SELECT status, output FROM tasks WHERE id={task_id}")
        if row:
            status, output = row[0][0], (row[0][1] or "")[:200]
            if status == "done":
                _notify(f"任务 #{task_id} 完成: {output}")
            else:
                _notify(f"任务 #{task_id} {status}: {output}")
        else:
            db.write_log(f"Channel 触发任务 #{task_id}: {scenario}", "INFO", "channels")

    except Exception as e:
        log.error(f"inbound: /run '{scenario}' failed: {e}")
        _notify(f"场景 {scenario} 执行失败: {e}")
        try:
            from src.storage.events_db import EventsDB
            db = EventsDB(db_path) if db_path else EventsDB()
            db.write_log(f"Channel 命令执行失败: {scenario} — {e}", "ERROR", "channels")
        except Exception:
            pass
