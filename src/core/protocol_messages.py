"""
Structured Protocol Messages — typed message system for agent communication.

Stolen from: Claude Code teammateMailbox.ts (10 message types)
            + Orchestrator adaptation (task_assignment, heartbeat, status_update)

All agent-to-agent and agent-to-governor communication uses these types.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class MessageType(Enum):
    # Governor → Agent
    TASK_ASSIGNMENT = "task_assignment"
    SHUTDOWN = "shutdown"
    MODE_SET = "mode_set"          # Switch collaboration mode

    # Agent → Governor
    TASK_RESULT = "task_result"
    HEARTBEAT = "heartbeat"
    IDLE_NOTIFICATION = "idle"

    # Agent ↔ Approval System (Claw/TG/Dashboard)
    PERMISSION_REQUEST = "permission_request"
    PERMISSION_RESPONSE = "permission_response"

    # Agent → Dashboard
    STATUS_UPDATE = "status_update"

    # Governor → All
    PERMISSION_BROADCAST = "permission_broadcast"


@dataclass(frozen=True)
class ProtocolMessage:
    """Immutable structured message for agent communication."""
    type: MessageType
    from_addr: str           # Sender address (unified scheme)
    to_addr: str             # Receiver address (unified scheme)
    payload: dict[str, Any]  # Type-specific data
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: Optional[str] = None  # For request-response pairing

    def is_structured(self) -> bool:
        """Protocol messages vs plain text."""
        return self.type != MessageType.STATUS_UPDATE

    @staticmethod
    def task_assignment(
        from_addr: str, to_addr: str,
        task_id: str, spec: str, department: str,
        correlation_id: Optional[str] = None,
    ) -> ProtocolMessage:
        return ProtocolMessage(
            type=MessageType.TASK_ASSIGNMENT,
            from_addr=from_addr, to_addr=to_addr,
            payload={"task_id": task_id, "spec": spec, "department": department},
            correlation_id=correlation_id,
        )

    @staticmethod
    def task_result(
        from_addr: str, to_addr: str,
        task_id: str, status: str, summary: str,
        correlation_id: Optional[str] = None,
    ) -> ProtocolMessage:
        return ProtocolMessage(
            type=MessageType.TASK_RESULT,
            from_addr=from_addr, to_addr=to_addr,
            payload={"task_id": task_id, "status": status, "summary": summary},
            correlation_id=correlation_id,
        )

    @staticmethod
    def heartbeat(from_addr: str, to_addr: str = "local:governor") -> ProtocolMessage:
        return ProtocolMessage(
            type=MessageType.HEARTBEAT,
            from_addr=from_addr, to_addr=to_addr,
            payload={},
        )

    @staticmethod
    def permission_request(
        from_addr: str, to_addr: str,
        tool_name: str, tool_args: dict, reason: str,
        correlation_id: Optional[str] = None,
    ) -> ProtocolMessage:
        return ProtocolMessage(
            type=MessageType.PERMISSION_REQUEST,
            from_addr=from_addr, to_addr=to_addr,
            payload={"tool_name": tool_name, "tool_args": tool_args, "reason": reason},
            correlation_id=correlation_id,
        )

    @staticmethod
    def permission_response(
        from_addr: str, to_addr: str,
        approved: bool, updated_input: Optional[dict] = None,
        correlation_id: Optional[str] = None,
    ) -> ProtocolMessage:
        return ProtocolMessage(
            type=MessageType.PERMISSION_RESPONSE,
            from_addr=from_addr, to_addr=to_addr,
            payload={"approved": approved, "updated_input": updated_input},
            correlation_id=correlation_id,
        )
