"""
Dispatcher — 终端对话直接调用 Governor 的桥梁。

使用场景：在 Claude Code 终端里，Orchestrator 实例识别到用户想派活，
直接调这个模块创建 Governor 任务。不走 Dashboard，不走 HTTP。

用法：
    from src.gateway.dispatcher import dispatch_from_text
    result = dispatch_from_text("帮我看看为什么 Steam 采集器是 0 数据")
    # → {"task_id": 42, "status": "created", "action": "...", "department": "..."}
"""
import logging
from pathlib import Path

from src.gateway.intent import IntentGateway, TaskIntent
from src.storage.events_db import EventsDB

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent
DB_PATH = str(BASE_DIR / "data" / "events.db")


def dispatch_user_intent(intent: TaskIntent, db: EventsDB = None) -> dict:
    """把解析好的 TaskIntent 变成 Governor 任务。

    返回:
    - {"task_id": int, "status": "created", "action": ..., "department": ...}
    - {"status": "needs_clarification", "question": ...}
    """
    if intent.needs_clarification:
        return {
            "status": "needs_clarification",
            "question": intent.clarification_question or "能再说具体一点吗？",
        }

    db = db or EventsDB(DB_PATH)
    spec = intent.to_governor_spec()

    # source='auto' 让任务进入 pending → Governor 自动执行流程
    # 如果用 'user_intent' 会变成 awaiting_approval，需要手动批准，不符合终端交互预期
    task_id = db.create_task(
        action=intent.action,
        reason=f"用户指令（终端）",
        priority=intent.priority,
        spec=spec,
        source="auto",
    )

    db.write_log(
        f"前门派单: #{task_id} → {intent.department}: {intent.action}",
        "INFO", "gateway",
    )

    log.info(f"dispatcher: created task #{task_id} [{intent.department}] {intent.action}")

    return {
        "task_id": task_id,
        "status": "created",
        "action": intent.action,
        "department": intent.department,
        "priority": intent.priority,
        "cognitive_mode": intent.cognitive_mode,
    }


def dispatch_from_text(text: str, context: dict = None, db: EventsDB = None) -> dict:
    """一步到位：自然语言 → 解析 → 派单。

    终端对话里直接调用这个。
    """
    gateway = IntentGateway()
    intent = gateway.parse(text, context=context)
    return dispatch_user_intent(intent, db=db)
