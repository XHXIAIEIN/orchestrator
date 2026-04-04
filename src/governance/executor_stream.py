"""AsyncGenerator-based streaming wrapper for TaskExecutor.

Stolen from Claude Code v2.1.88 query.ts — AsyncGenerator agent loop.
The core insight: execution is a lazy-evaluated state machine where consumers
pull events at their own pace, and .return() provides native cancellation.

Instead of modifying executor.py, this module wraps TaskExecutor and bridges
its synchronous lifecycle hooks into an async event stream via asyncio.Queue.
Callers (Dashboard, TG bot) subscribe to real-time events during execution.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import AsyncGenerator

log = logging.getLogger(__name__)

# ── Event Types ──

# All valid event_type strings. Kept as a set for O(1) validation.
EVENT_TYPES = frozenset({
    "rollout_start", "attempt_start", "attempt_end", "rollout_end",
    "tool_start", "tool_result", "progress", "approval_required",
    "compaction_triggered", "retry", "escalation", "checkpoint",
    "status_change",
})


@dataclass
class ExecutionEvent:
    """Base event yielded by the execution stream.

    Lightweight envelope — all specifics live in ``data``.
    ``event_type`` is one of EVENT_TYPES (not enforced at construction
    for performance, but validated by stream internals).
    """
    event_type: str
    task_id: int
    timestamp: float  # time.time()
    data: dict = field(default_factory=dict)


# ── Checkpoint helper ──

def checkpoint(name: str, task_id: int, queue: asyncio.Queue) -> None:
    """Lightweight checkpoint profiling — stolen from Claude Code query.ts.

    Records name + timestamp for post-hoc latency analysis.
    Non-blocking: uses put_nowait so it never suspends the caller.
    """
    queue.put_nowait(ExecutionEvent(
        event_type="checkpoint",
        task_id=task_id,
        timestamp=time.time(),
        data={"name": name},
    ))


def _make_event(event_type: str, task_id: int, data: dict | None = None) -> ExecutionEvent:
    """Convenience factory — fills timestamp automatically."""
    return ExecutionEvent(
        event_type=event_type,
        task_id=task_id,
        timestamp=time.time(),
        data=data or {},
    )


# ── Sentinel ──

_STREAM_END = object()


# ── ExecutionStream ──

class ExecutionStream:
    """AsyncGenerator wrapper around TaskExecutor for streaming execution events.

    Stolen from Claude Code v2.1.88 query.ts — AsyncGenerator agent loop.
    The core insight: execution is a lazy-evaluated state machine where consumers
    pull events at their own pace, and .return() provides native cancellation.

    Usage::

        stream = ExecutionStream(executor)
        async for event in stream.execute(task_id):
            if event.event_type == "approval_required":
                # Handle approval
            elif event.event_type == "checkpoint":
                dashboard.update(event)

    Cancellation: breaking out of the ``async for`` (or calling ``.athrow()``)
    sets an internal stop flag that the executor thread checks between steps.
    """

    def __init__(self, executor, *, queue_size: int = 256):
        """
        Parameters
        ----------
        executor : TaskExecutor
            The real executor instance to wrap.
        queue_size : int
            Max buffered events before back-pressure (put blocks).
        """
        self._executor = executor
        self._queue_size = queue_size

    # ── Public API ──

    async def execute(self, task_id: int) -> AsyncGenerator[ExecutionEvent, None]:
        """Stream execution events for *task_id* as an async generator.

        Internally spins up the synchronous ``executor.execute_task`` in a
        thread, bridged to the caller via an ``asyncio.Queue``.
        """
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._queue_size)
        stop_flag = asyncio.Event()
        loop = asyncio.get_running_loop()

        # ── Hook registration (R38: unified registry, no swap) ──
        # Register streaming hooks on the global lifecycle registry.
        # No more swapping executor._hooks — thread-safe by design.
        registered_hooks = self._register_stream_hooks(task_id, queue, loop)

        checkpoint("stream_setup", task_id, queue)

        try:
            # Run the blocking execute_task in a thread
            task = loop.run_in_executor(
                None,
                self._run_sync,
                task_id,
                queue,
                loop,
                stop_flag,
            )

            # Yield events until the sentinel arrives
            while True:
                event = await queue.get()
                if event is _STREAM_END:
                    break
                yield event

            # Ensure the thread has finished
            await task

        except GeneratorExit:
            # Consumer cancelled — signal the thread to stop
            stop_flag.set()
            # Drain queue to unblock any pending puts
            while not queue.empty():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
        finally:
            # Unregister streaming hooks
            self._unregister_stream_hooks(registered_hooks)

    # ── Internals ──

    def _run_sync(self, task_id: int, queue: asyncio.Queue,
                  loop: asyncio.AbstractEventLoop, stop_flag: asyncio.Event) -> None:
        """Blocking wrapper around execute_task. Runs in a thread."""
        try:
            checkpoint("execute_start", task_id, queue)

            result = self._executor.execute_task(task_id)

            # Emit final status_change based on result
            status = result.get("status", "unknown") if isinstance(result, dict) else "unknown"
            _put_safe(queue, _make_event("status_change", task_id, {
                "status": status,
                "result_keys": list(result.keys()) if isinstance(result, dict) else [],
            }))

            checkpoint("execute_end", task_id, queue)

        except Exception as exc:
            log.error(f"ExecutionStream: task #{task_id} raised: {exc}", exc_info=True)
            _put_safe(queue, _make_event("status_change", task_id, {
                "status": "failed",
                "error": str(exc),
            }))
        finally:
            # Signal end-of-stream
            _put_safe(queue, _STREAM_END)

    def _register_stream_hooks(self, task_id: int, queue: asyncio.Queue,
                               loop: asyncio.AbstractEventLoop) -> list[tuple[str, str]]:
        """Register streaming hooks on the global lifecycle registry.

        Returns list of (point, name) tuples for cleanup via unregister.
        """
        try:
            from src.core.lifecycle_hooks import get_lifecycle_hooks
            hooks = get_lifecycle_hooks()
        except ImportError:
            return []

        registered = []
        stream_id = f"stream_{task_id}"

        for point, event_type in [
            ("on_rollout_start", "rollout_start"),
            ("on_attempt_start", "attempt_start"),
            ("on_attempt_end", "attempt_end"),
            ("on_rollout_end", "rollout_end"),
        ]:
            def _make_push(evt=event_type):
                def hook(**kwargs):
                    _put_safe(queue, _make_event(evt, task_id, kwargs))
                return hook

            hook_name = f"{stream_id}_{event_type}"
            hooks.register(point, _make_push(), name=hook_name)
            registered.append((point, hook_name))

        return registered

    def _unregister_stream_hooks(self, registered: list[tuple[str, str]]):
        """Unregister streaming hooks after execution completes."""
        try:
            from src.core.lifecycle_hooks import get_lifecycle_hooks
            hooks = get_lifecycle_hooks()
        except ImportError:
            return
        for point, name in registered:
            hooks.unregister(point, name)


# ── Utilities ──

def _put_safe(queue: asyncio.Queue, item) -> None:
    """Non-blocking put — drops the event if queue is full (better than deadlock)."""
    try:
        queue.put_nowait(item)
    except asyncio.QueueFull:
        if isinstance(item, ExecutionEvent):
            log.warning(f"ExecutionStream: queue full, dropped {item.event_type} for task #{item.task_id}")
