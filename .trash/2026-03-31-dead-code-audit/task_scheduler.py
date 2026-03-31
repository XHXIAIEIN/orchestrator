"""Task Scheduler — priority-based sub-task scheduling.

Tasks can be IMMEDIATE (run now) or SCHEDULED (run at specific time).
Scheduler polls every interval, dequeues by priority, and dispatches.
"""

import time
import threading
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Any

logger = logging.getLogger(__name__)


class TaskPriority(Enum):
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3


class TaskTiming(Enum):
    IMMEDIATE = "immediate"
    SCHEDULED = "scheduled"


@dataclass
class ScheduledTask:
    task_id: str
    intent: str
    arguments: dict = field(default_factory=dict)
    priority: TaskPriority = TaskPriority.NORMAL
    timing: TaskTiming = TaskTiming.IMMEDIATE
    scheduled_at: float | None = None  # Unix timestamp for SCHEDULED tasks
    created_at: float = field(default_factory=time.time)
    parent_task_id: str | None = None
    status: str = "pending"  # pending, running, completed, failed
    result: Any = None


class TaskScheduler:
    """Priority-based task scheduler with polling loop."""

    def __init__(self, poll_interval: float = 5.0):
        self._poll_interval = poll_interval
        self._queue: list[ScheduledTask] = []
        self._lock = threading.Lock()
        self._stop_evt = threading.Event()
        self._thread: threading.Thread | None = None
        self._dispatcher: Callable[[ScheduledTask], Any] | None = None
        self._history: list[ScheduledTask] = []
        self._max_history = 500

    def set_dispatcher(self, fn: Callable[[ScheduledTask], Any]):
        """Set the function that actually executes tasks."""
        self._dispatcher = fn

    def create_task(
        self,
        task_id: str,
        intent: str,
        arguments: dict | None = None,
        priority: str = "NORMAL",
        timing: str = "immediate",
        scheduled_at: float | None = None,
        parent_task_id: str | None = None,
    ) -> ScheduledTask:
        """Create and enqueue a task."""
        task = ScheduledTask(
            task_id=task_id,
            intent=intent,
            arguments=arguments or {},
            priority=TaskPriority[priority.upper()],
            timing=TaskTiming(timing.lower()),
            scheduled_at=scheduled_at,
            parent_task_id=parent_task_id,
        )
        with self._lock:
            self._queue.append(task)
            self._queue.sort(key=lambda t: (t.priority.value, t.created_at))
        logger.info(f"Task created: {task_id} ({intent}) priority={priority}")
        return task

    def start(self):
        """Start the polling loop."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="task-scheduler")
        self._thread.start()

    def stop(self):
        """Stop the polling loop."""
        self._stop_evt.set()
        if self._thread:
            self._thread.join(timeout=10)

    def _poll_loop(self):
        """Poll for ready tasks and dispatch them."""
        while not self._stop_evt.is_set():
            task = self._dequeue_ready()
            if task:
                self._execute(task)
            self._stop_evt.wait(self._poll_interval)

    def _dequeue_ready(self) -> ScheduledTask | None:
        """Get the next ready task (highest priority, due now)."""
        now = time.time()
        with self._lock:
            for i, task in enumerate(self._queue):
                if task.status != "pending":
                    continue
                if task.timing == TaskTiming.SCHEDULED and task.scheduled_at and task.scheduled_at > now:
                    continue
                task.status = "running"
                return task
        return None

    def _execute(self, task: ScheduledTask):
        """Execute a task via the dispatcher."""
        if not self._dispatcher:
            logger.warning(f"No dispatcher set, task {task.task_id} skipped")
            task.status = "failed"
            return

        try:
            result = self._dispatcher(task)
            task.result = result
            task.status = "completed"
        except Exception as e:
            logger.error(f"Task {task.task_id} failed: {e}")
            task.status = "failed"
            task.result = str(e)
        finally:
            with self._lock:
                self._history.append(task)
                if len(self._history) > self._max_history:
                    self._history = self._history[-self._max_history:]

    def get_pending(self) -> list[ScheduledTask]:
        with self._lock:
            return [t for t in self._queue if t.status == "pending"]

    def get_history(self, n: int = 20) -> list[ScheduledTask]:
        with self._lock:
            return self._history[-n:]

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            for task in self._queue:
                if task.task_id == task_id and task.status == "pending":
                    task.status = "failed"
                    task.result = "cancelled"
                    return True
        return False
