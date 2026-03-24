"""
ApprovalGateway — multi-channel human approval for authority escalation.

When an agent task needs APPROVE-level authority (commit, push, merge),
the gateway broadcasts an approval request to all available channels:
  - Claw (Windows Toast via WebSocket)
  - Telegram bot (inline keyboard)
  - WeChat bot

First response wins. Timeout = auto-deny.

Usage in executor:
    gateway = ApprovalGateway(broadcast_fn, channel_registry)
    decision = await gateway.request_approval(task_id, description, authority_level)
    if decision == "approve":
        ... proceed with elevated authority ...
"""
import asyncio
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 300  # 5 minutes


@dataclass
class ApprovalRequest:
    task_id: str
    description: str
    authority_level: int
    requested_at: str
    decision: Optional[str] = None  # "approve" / "deny" / "timeout"
    decided_by: Optional[str] = None  # "claw" / "telegram" / "wechat" / "api"
    decided_at: Optional[str] = None


class ApprovalGateway:
    """Publish approval requests, wait for first response from any channel."""

    def __init__(
        self,
        broadcast_fn: Optional[Callable] = None,
        channel_registry=None,
    ):
        self._broadcast = broadcast_fn  # server.js broadcast via WebSocket
        self._channels = channel_registry
        self._pending: dict[str, asyncio.Event] = {}
        self._requests: dict[str, ApprovalRequest] = {}
        self._lock = threading.Lock()
        self._yolo = False  # /yolo mode: auto-approve everything
        self._yolo_by: Optional[str] = None

    def set_yolo(self, enabled: bool, source: str = "unknown"):
        """Toggle YOLO mode — auto-approve all requests without asking."""
        self._yolo = enabled
        self._yolo_by = source if enabled else None
        action = "enabled" if enabled else "disabled"
        log.info(f"ApprovalGateway: YOLO mode {action} by {source}")

        # If enabling, approve all pending requests immediately
        if enabled:
            with self._lock:
                for tid, req in self._requests.items():
                    if req.decision is None:
                        req.decision = "approve"
                        req.decided_by = f"yolo:{source}"
                        req.decided_at = datetime.now(timezone.utc).isoformat()
                        evt = self._pending.get(tid)
                        if evt:
                            evt.set()
            log.info("ApprovalGateway: YOLO — all pending requests auto-approved")

    @property
    def is_yolo(self) -> bool:
        return self._yolo

    async def request_approval(
        self,
        task_id: str,
        description: str,
        authority_level: int = 4,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> str:
        """Request human approval. Returns 'approve', 'deny', or 'timeout'."""

        # YOLO mode: instant approve, no notification
        if self._yolo:
            log.info(f"YOLO: auto-approved {task_id}")
            return "approve"

        req = ApprovalRequest(
            task_id=task_id,
            description=description,
            authority_level=authority_level,
            requested_at=datetime.now(timezone.utc).isoformat(),
        )

        event = asyncio.Event()
        with self._lock:
            self._pending[task_id] = event
            self._requests[task_id] = req

        # Broadcast to all channels
        self._notify_all(req)

        # Wait for response (any channel)
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            req.decision = "timeout"
            req.decided_by = "system"
            req.decided_at = datetime.now(timezone.utc).isoformat()
            log.warning(f"approval timeout for task {task_id} after {timeout}s")
        finally:
            with self._lock:
                self._pending.pop(task_id, None)

        decision = req.decision or "timeout"
        log.info(f"approval for {task_id}: {decision} (by {req.decided_by})")
        return decision

    def submit_decision(self, task_id: str, decision: str, source: str = "unknown"):
        """Called when a channel receives an approval/denial response."""
        with self._lock:
            req = self._requests.get(task_id)
            event = self._pending.get(task_id)

        if not req:
            log.warning(f"approval decision for unknown task {task_id}")
            return

        if req.decision is not None:
            log.info(f"approval for {task_id} already decided, ignoring {source}")
            return

        req.decision = decision
        req.decided_by = source
        req.decided_at = datetime.now(timezone.utc).isoformat()

        if event:
            event.set()

        # Notify all channels of the outcome
        self._notify_outcome(req)

    def get_pending(self) -> list[ApprovalRequest]:
        """Return all pending approval requests."""
        with self._lock:
            return [r for r in self._requests.values() if r.decision is None]

    def _notify_all(self, req: ApprovalRequest):
        """Push approval request to all channels."""

        risk = "LOW" if req.authority_level <= 3 else (
            "MEDIUM" if req.authority_level <= 6 else "HIGH"
        )

        # 1. WebSocket broadcast (Claw picks this up)
        if self._broadcast:
            try:
                self._broadcast({
                    "type": "approval_request",
                    "task_id": req.task_id,
                    "description": req.description,
                    "authority_level": req.authority_level,
                    "risk": risk,
                })
            except Exception as e:
                log.debug(f"ws broadcast failed: {e}")

        # 2. Telegram / WeChat via Channel registry
        if self._channels:
            try:
                from src.channels.base import ChannelMessage
                risk_label = {"LOW": "低风险", "MEDIUM": "中风险", "HIGH": "高风险"}.get(risk, risk)
                msg = ChannelMessage(
                    text=(
                        f"*需要审批* ({risk_label})\n\n"
                        f"{req.description}\n\n"
                        f"权限等级: {req.authority_level}/4\n"
                        f"Task: `{req.task_id}`"
                    ),
                    event_type="approval.request",
                    priority="CRITICAL",
                )
                self._channels.broadcast(msg)
            except Exception as e:
                log.debug(f"channel broadcast failed: {e}")

    def _notify_outcome(self, req: ApprovalRequest):
        """Notify channels of the decision."""
        if self._channels:
            try:
                from src.channels.base import ChannelMessage
                emoji = "Approved" if req.decision == "approve" else "Denied"
                msg = ChannelMessage(
                    text=f"*{emoji}* — {req.description}\n(by {req.decided_by})",
                    event_type="approval.result",
                    priority="HIGH",
                )
                self._channels.broadcast(msg)
            except Exception:
                pass


# ── Singleton ──

_gateway: Optional[ApprovalGateway] = None


def get_approval_gateway() -> ApprovalGateway:
    global _gateway
    if _gateway is None:
        _gateway = ApprovalGateway()
    return _gateway


def init_approval_gateway(broadcast_fn=None, channel_registry=None) -> ApprovalGateway:
    global _gateway
    _gateway = ApprovalGateway(broadcast_fn, channel_registry)
    return _gateway
