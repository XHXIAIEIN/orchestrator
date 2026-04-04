"""
Dispatcher — 终端对话直接调用 Governor 的桥梁。

三路分流 Gateway：
  1. NO_TOKEN — 状态查询，直接返回 DB 数据，零 LLM 消耗
  2. DIRECT   — 单轮问答，一次 LLM 调用
  3. AGENT    — 多步任务，走完整 Governor → Agent SDK 流程

Clarification loop (DeerFlow P1-5):
  当 dispatch 结果为 needs_clarification 时，caller 可携带用户回答再次调用
  dispatch_from_text()，通过 clarification_history 传递上下文。

用法：
    from src.gateway.dispatcher import dispatch_from_text
    result = dispatch_from_text("帮我看看为什么 Steam 采集器是 0 数据")
    # → {"task_id": 42, "status": "created", "action": "...", "department": "..."}

    # Multi-round clarification:
    result = dispatch_from_text("优化一下", context={"project": "orchestrator"})
    # → {"status": "needs_clarification", "question": "...", "clarification_type": "..."}
    result = dispatch_from_text(
        "优化 dashboard 的加载速度，目标 < 2s",
        context={"clarification_history": [{"q": "...", "a": "..."}]},
    )
"""
import json
import logging
from pathlib import Path

from src.gateway.intent import IntentGateway, TaskIntent
from src.gateway.classifier import classify, RequestTier
from src.gateway.handlers import execute_no_token
from src.storage.events_db import EventsDB

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent
DB_PATH = str(BASE_DIR / "data" / "events.db")

# Max clarification rounds before force-proceeding
MAX_CLARIFICATION_ROUNDS = 3


def dispatch_user_intent(intent: TaskIntent, db: EventsDB = None,
                         clarification_history: list = None) -> dict:
    """把解析好的 TaskIntent 变成 Governor 任务。

    返回:
    - {"task_id": int, "status": "created", "action": ..., "department": ...}
    - {"status": "needs_clarification", "question": ..., "clarification_type": ..., "round": int}
    """
    history = clarification_history or []
    round_num = len(history)

    if intent.needs_clarification:
        # Force-proceed after MAX rounds to avoid infinite loop
        if round_num >= MAX_CLARIFICATION_ROUNDS:
            log.warning(f"dispatcher: max clarification rounds ({MAX_CLARIFICATION_ROUNDS}) reached, "
                        f"force-proceeding with best available info")
            # Fall through to task creation with what we have
        else:
            return {
                "status": "needs_clarification",
                "question": intent.clarification_question or "能再说具体一点吗？",
                "clarification_type": "missing_info",  # intent-level is always missing_info
                "round": round_num + 1,
                "clarification_history": history,
            }

    db = db or EventsDB(DB_PATH)
    spec = intent.to_governor_spec()

    # Inject clarification history into spec so downstream gates can see it
    if history:
        spec["clarification_history"] = history

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

    Supports multi-round clarification via context["clarification_history"].
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
    ctx = context or {}
    clarification_history = ctx.get("clarification_history", [])

    gateway = IntentGateway()
    intent = gateway.parse(text, context=ctx)
    result = dispatch_user_intent(intent, db=db, clarification_history=clarification_history)
    result["tier"] = "agent"
    return result
