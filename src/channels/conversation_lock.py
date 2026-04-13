"""R47 (Archon) + R49 (Qwen Code): Conversation Lock Manager.

Non-blocking lock + per-conversation queue + global concurrency cap.
Prevents message overlap when multiple messages arrive for the same conversation.

R49 upgrade: Three dispatch modes stolen from Qwen Code ChannelBase:
  - collect: buffer new messages, coalesce when active finishes
  - steer: cancel current, inject [cancelled] context, process new message
  - followup: serial queue (original R47 behavior)

Returns lock status: 'started', 'queued-conversation', 'queued-capacity',
                     'buffered' (collect), 'steering' (steer).
"""
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from threading import Lock

log = logging.getLogger(__name__)

MAX_GLOBAL_CONCURRENT = 5
MAX_QUEUE_PER_CONVERSATION = 3


class DispatchMode(Enum):
    """How to handle concurrent messages for the same conversation.

    Stolen from Qwen Code ChannelBase.ts:308-348.
    """
    COLLECT = "collect"      # buffer → coalesce when active finishes
    STEER = "steer"          # cancel active → prepend [cancelled] note → new prompt
    FOLLOWUP = "followup"    # serial queue (wait for current to finish)


@dataclass
class LockStatus:
    """Result of attempting to acquire a conversation lock."""
    status: str  # 'started' | 'queued-conversation' | 'queued-capacity' | 'rejected'
                 # | 'buffered' (collect mode) | 'steering' (steer mode)
    position: int = 0  # queue position (0 = running now)
    conversation_id: str = ""


class ConversationLockManager:
    """Non-blocking conversation lock with per-conversation queuing.

    Ensures only one message is processed per conversation at a time.
    Behavior when a message arrives while one is already processing
    depends on the dispatch mode:

    - COLLECT: buffer the new message, coalesce when current finishes
    - STEER: mark current as cancelled, let caller handle the new message
    - FOLLOWUP: queue the new message (up to MAX_QUEUE_PER_CONVERSATION)
    """

    def __init__(self, max_concurrent: int = MAX_GLOBAL_CONCURRENT,
                 max_queue: int = MAX_QUEUE_PER_CONVERSATION):
        self._lock = Lock()
        self._active: dict[str, float] = {}  # conversation_id → start_time
        self._queues: dict[str, list[float]] = defaultdict(list)  # conversation_id → [enqueue_times]
        self._max_concurrent = max_concurrent
        self._max_queue = max_queue

        # R49: Dispatch mode support
        self._collect_buffers: dict[str, list[str]] = defaultdict(list)
        self._cancel_flags: dict[str, bool] = {}  # conversation_id → cancelled

    def try_acquire(self, conversation_id: str,
                    mode: DispatchMode = DispatchMode.FOLLOWUP,
                    message_text: str = "") -> LockStatus:
        """Try to acquire lock for a conversation. Non-blocking.

        Args:
            conversation_id: Unique conversation identifier.
            mode: Dispatch mode for concurrent message handling.
            message_text: The message text (used by collect mode for buffering).

        Returns LockStatus indicating the outcome.
        """
        with self._lock:
            # Already processing this conversation?
            if conversation_id in self._active:
                if mode == DispatchMode.COLLECT:
                    # Buffer the message for later coalescing
                    self._collect_buffers[conversation_id].append(message_text)
                    return LockStatus("buffered",
                                      position=len(self._collect_buffers[conversation_id]),
                                      conversation_id=conversation_id)

                elif mode == DispatchMode.STEER:
                    # Mark current as cancelled — caller should cancel running task
                    self._cancel_flags[conversation_id] = True
                    return LockStatus("steering", conversation_id=conversation_id)

                else:  # FOLLOWUP — original R47 behavior
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
            self._cancel_flags[conversation_id] = False
            return LockStatus("started", conversation_id=conversation_id)

    def release(self, conversation_id: str) -> str | None:
        """Release lock. Returns next queued conversation_id if any."""
        with self._lock:
            self._active.pop(conversation_id, None)
            self._cancel_flags.pop(conversation_id, None)

            # Check if this conversation has queued messages (followup mode)
            queue = self._queues.get(conversation_id, [])
            if queue:
                queue.pop(0)
                if not queue:
                    del self._queues[conversation_id]
                # Re-acquire for next queued message
                self._active[conversation_id] = time.monotonic()
                self._cancel_flags[conversation_id] = False
                return conversation_id

            # Clean up empty queue
            self._queues.pop(conversation_id, None)
            return None

    def is_cancelled(self, conversation_id: str) -> bool:
        """Check if the active task for this conversation has been cancelled (steer mode)."""
        with self._lock:
            return self._cancel_flags.get(conversation_id, False)

    def drain_buffer(self, conversation_id: str) -> str | None:
        """Drain collect buffer and return coalesced text, or None if empty.

        Called after releasing a lock to check if buffered messages need processing.
        Stolen from Qwen Code ChannelBase.ts:404-418 (collect buffer drain).
        """
        with self._lock:
            buffer = self._collect_buffers.pop(conversation_id, [])
            if not buffer:
                return None
            return "\n\n".join(buffer)

    def get_stats(self) -> dict:
        with self._lock:
            return {
                "active": len(self._active),
                "queued": sum(len(q) for q in self._queues.values()),
                "buffered": sum(len(b) for b in self._collect_buffers.values()),
                "cancelled": sum(1 for v in self._cancel_flags.values() if v),
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
