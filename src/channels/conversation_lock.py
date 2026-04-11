"""R47 (Archon): Conversation Lock Manager.

Non-blocking lock + per-conversation queue + global concurrency cap.
Prevents message overlap when multiple messages arrive for the same conversation.

Returns lock status: 'started', 'queued-conversation', 'queued-capacity'.
"""
import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock

log = logging.getLogger(__name__)

MAX_GLOBAL_CONCURRENT = 5
MAX_QUEUE_PER_CONVERSATION = 3


@dataclass
class LockStatus:
    """Result of attempting to acquire a conversation lock."""
    status: str  # 'started' | 'queued-conversation' | 'queued-capacity' | 'rejected'
    position: int = 0  # queue position (0 = running now)
    conversation_id: str = ""


class ConversationLockManager:
    """Non-blocking conversation lock with per-conversation queuing.

    Ensures only one message is processed per conversation at a time.
    Additional messages queue up (up to MAX_QUEUE_PER_CONVERSATION).
    Global concurrency cap prevents resource exhaustion.
    """

    def __init__(self, max_concurrent: int = MAX_GLOBAL_CONCURRENT,
                 max_queue: int = MAX_QUEUE_PER_CONVERSATION):
        self._lock = Lock()
        self._active: dict[str, float] = {}  # conversation_id → start_time
        self._queues: dict[str, list[float]] = defaultdict(list)  # conversation_id → [enqueue_times]
        self._max_concurrent = max_concurrent
        self._max_queue = max_queue

    def try_acquire(self, conversation_id: str) -> LockStatus:
        """Try to acquire lock for a conversation. Non-blocking.

        Returns LockStatus indicating whether the message can proceed,
        was queued, or was rejected.
        """
        with self._lock:
            # Already processing this conversation?
            if conversation_id in self._active:
                queue = self._queues[conversation_id]
                if len(queue) >= self._max_queue:
                    return LockStatus("rejected", conversation_id=conversation_id)
                queue.append(time.monotonic())
                return LockStatus("queued-conversation",
                                  position=len(queue),
                                  conversation_id=conversation_id)

            # Global capacity check
            if len(self._active) >= self._max_concurrent:
                return LockStatus("queued-capacity", conversation_id=conversation_id)

            # Acquire
            self._active[conversation_id] = time.monotonic()
            return LockStatus("started", conversation_id=conversation_id)

    def release(self, conversation_id: str) -> str | None:
        """Release lock. Returns next queued conversation_id if any."""
        with self._lock:
            self._active.pop(conversation_id, None)

            # Check if this conversation has queued messages
            queue = self._queues.get(conversation_id, [])
            if queue:
                queue.pop(0)
                if not queue:
                    del self._queues[conversation_id]
                # Re-acquire for next queued message
                self._active[conversation_id] = time.monotonic()
                return conversation_id

            # Clean up empty queue
            self._queues.pop(conversation_id, None)
            return None

    def get_stats(self) -> dict:
        with self._lock:
            return {
                "active": len(self._active),
                "queued": sum(len(q) for q in self._queues.values()),
                "conversations_with_queue": len(self._queues),
                "max_concurrent": self._max_concurrent,
            }

    def is_locked(self, conversation_id: str) -> bool:
        with self._lock:
            return conversation_id in self._active


# ── Singleton ──
_instance: ConversationLockManager | None = None


def get_conversation_lock() -> ConversationLockManager:
    global _instance
    if _instance is None:
        _instance = ConversationLockManager()
    return _instance
