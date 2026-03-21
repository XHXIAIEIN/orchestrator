"""
Dispatcher — 终端对话直接调用 Governor 的桥梁。

三路分流 Gateway：
  1. NO_TOKEN — 状态查询，直接返回 DB 数据，零 LLM 消耗
  2. DIRECT   — 单轮问答，一次 LLM 调用
  3. AGENT    — 多步任务，走完整 Governor → Agent SDK 流程

用法：
    from src.gateway.dispatcher import dispatch_from_text
    result = dispatch_from_text("帮我看看为什么 Steam 采集器是 0 数据")
    # → {"task_id": 42, "status": "created", "action": "...", "department": "..."}
"""
import logging
from pathlib import Path

from src.gateway.intent import IntentGateway, TaskIntent
from src.gateway.classifier import classify, RequestTier
from src.gateway.handlers import execute_no_token
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

    task_id = db.create_task(
        action=intent.action,
        reason="用户指令（终端）",
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
    """三路分流入口：自然语言 → 分类 → 路由。

    NO_TOKEN → 直接返回数据
    DIRECT   → 单轮 LLM（TODO: 待实现，暂走 AGENT 路径）
    AGENT    → IntentGateway 解析 → Governor 派单
    """
    classified = classify(text)
    log.info(f"dispatcher: classified '{text[:50]}' → {classified.tier.value} "
             f"(handler={classified.handler}, confidence={classified.confidence})")

    # ── NO_TOKEN: 零成本数据查询 ──
    if classified.tier == RequestTier.NO_TOKEN:
        result = execute_no_token(classified.handler, classified.extracted_params)
        result["tier"] = "no_token"
        return result

    # ── DIRECT: 单轮 LLM（暂 fallthrough 到 AGENT） ──
    # TODO Phase 2: 实现 direct handler，单次 LLM 调用无 agent 工具

    # ── AGENT: 完整 Governor 流程 ──
    gateway = IntentGateway()
    intent = gateway.parse(text, context=context)
    result = dispatch_user_intent(intent, db=db)
    result["tier"] = "agent"
    return result
