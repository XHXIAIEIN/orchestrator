"""
入站命令路由 — 把 Channel 层收到的命令接到 Governor / Health 等系统。

Telegram /run 命令 → publish channel.command.run 事件 → 这里订阅并调用 Governor。
闭环：命令结果通过 Fan-out → Channel 层推回给用户。
"""
import logging
import threading

from src.core.event_bus import get_event_bus, Event

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

        # 在后台线程执行，避免阻塞 Event Bus
        thread = threading.Thread(
            target=_execute_run,
            args=(scenario, db_path),
            name=f"inbound-run-{scenario}",
            daemon=True,
        )
        thread.start()

    bus.subscribe("channel.command.run", _handle_run)
    log.info("inbound: registered handler for channel.command.run")


def _execute_run(scenario: str, db_path: str):
    """执行场景（在后台线程）。"""
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
        db.write_log(
            f"Channel 触发任务 #{task_id}: {scenario}",
            "INFO", "channels",
        )

    except Exception as e:
        log.error(f"inbound: /run '{scenario}' failed: {e}")
        try:
            from src.storage.events_db import EventsDB
            db = EventsDB(db_path) if db_path else EventsDB()
            db.write_log(f"Channel 命令执行失败: {scenario} — {e}", "ERROR", "channels")
        except Exception:
            pass
