"""Agent Message Protocol — typed inter-agent communication.

Source: R61 Codex CLI (MultiAgentV2 message_tool.rs)

Two delivery modes:
  QueueOnly: enqueue message, target consumes when ready (non-interrupting)
  TriggerTurn: immediately wake target agent and start a new turn (interrupting)

Usage:
  mailbox = AgentMailbox("orchestrator")
  mailbox.send("worker-1", "your task is done", mode=DeliveryMode.QUEUE_ONLY)
  mailbox.send("worker-1", "URGENT: stop now", mode=DeliveryMode.TRIGGER_TURN)
  messages = mailbox.receive("worker-1")
"""
from __future__ import annotations

import threading
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


# ── Enums ─────────────────────────────────────────────────────────────────

class DeliveryMode(Enum):
    """How the message is delivered to the recipient."""
    QUEUE_ONLY = "queue_only"       # Enqueue; target reads when ready (non-interrupting)
    TRIGGER_TURN = "trigger_turn"   # Wake target immediately; starts a new turn (interrupting)


class DeliveryPhase(Enum):
    """Prevents late messages from being inserted mid-output.

    CURRENT_TURN: message is processed in the agent's active turn.
    NEXT_TURN:    message is held until the current turn completes.
    """
    CURRENT_TURN = "current_turn"
    NEXT_TURN = "next_turn"


# ── Core message type ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class AgentMessage:
    """Immutable inter-agent message."""
    sender: str
    recipient: str
    content: str
    mode: DeliveryMode
    timestamp: datetime
    message_id: str
    metadata: dict[str, Any]

    @staticmethod
    def create(
        sender: str,
        recipient: str,
        content: str,
        mode: DeliveryMode,
        metadata: Optional[dict[str, Any]] = None,
    ) -> AgentMessage:
        return AgentMessage(
            sender=sender,
            recipient=recipient,
            content=content,
            mode=mode,
            timestamp=datetime.now(timezone.utc),
            message_id=str(uuid.uuid4()),
            metadata=metadata or {},
        )

    @property
    def is_trigger(self) -> bool:
        return self.mode is DeliveryMode.TRIGGER_TURN


# ── Mailbox ───────────────────────────────────────────────────────────────

class AgentMailbox:
    """Thread-safe per-agent mailbox.

    Owns one queue per recipient.  The owning agent_id is the sender
    identity used in outbound messages.
    """

    def __init__(self, agent_id: str) -> None:
        self._agent_id = agent_id
        # recipient → list[AgentMessage]
        self._queues: dict[str, list[AgentMessage]] = defaultdict(list)
        self._lock = threading.Lock()

    # ── Outbound ──────────────────────────────────────────────────────────

    def send(
        self,
        recipient: str,
        content: str,
        mode: DeliveryMode = DeliveryMode.QUEUE_ONLY,
        metadata: Optional[dict[str, Any]] = None,
    ) -> AgentMessage:
        """Enqueue a message destined for *recipient*.

        Returns the created AgentMessage so callers can track message_id.
        """
        msg = AgentMessage.create(
            sender=self._agent_id,
            recipient=recipient,
            content=content,
            mode=mode,
            metadata=metadata,
        )
        with self._lock:
            self._queues[recipient].append(msg)
        return msg

    # ── Inbound ───────────────────────────────────────────────────────────

    def receive(
        self,
        from_agent: Optional[str] = None,
        phase: Optional[DeliveryPhase] = None,
    ) -> list[AgentMessage]:
        """Drain and return messages addressed to this mailbox's agent.

        from_agent: if given, only drain messages sent by that agent.
        phase:      if given, only drain messages whose metadata['phase'] matches.

        Messages are removed from the queue (destructive read).
        """
        with self._lock:
            return self._drain(
                recipient=self._agent_id,
                from_agent=from_agent,
                phase=phase,
                destructive=True,
            )

    def peek(self, from_agent: Optional[str] = None) -> list[AgentMessage]:
        """Non-destructive read of pending messages for this agent."""
        with self._lock:
            return self._drain(
                recipient=self._agent_id,
                from_agent=from_agent,
                phase=None,
                destructive=False,
            )

    def has_pending(self, from_agent: Optional[str] = None) -> bool:
        """True if there are any queued messages for this agent."""
        return len(self.peek(from_agent=from_agent)) > 0

    def get_trigger_messages(self) -> list[AgentMessage]:
        """Drain only TRIGGER_TURN messages for immediate processing."""
        with self._lock:
            queue = self._queues[self._agent_id]
            triggers = [m for m in queue if m.is_trigger]
            remaining = [m for m in queue if not m.is_trigger]
            self._queues[self._agent_id] = remaining
        return triggers

    def clear(self) -> int:
        """Clear all messages for this agent. Returns count cleared."""
        with self._lock:
            count = len(self._queues[self._agent_id])
            self._queues[self._agent_id] = []
        return count

    # ── Internal ──────────────────────────────────────────────────────────

    def _drain(
        self,
        recipient: str,
        from_agent: Optional[str],
        phase: Optional[DeliveryPhase],
        destructive: bool,
    ) -> list[AgentMessage]:
        queue = self._queues[recipient]
        matched: list[AgentMessage] = []
        kept: list[AgentMessage] = []

        for msg in queue:
            sender_ok = (from_agent is None) or (msg.sender == from_agent)
            phase_ok = (
                phase is None
                or msg.metadata.get("phase") == phase.value
            )
            if sender_ok and phase_ok:
                matched.append(msg)
            else:
                kept.append(msg)

        if destructive:
            self._queues[recipient] = kept

        return matched
