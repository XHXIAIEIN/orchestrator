"""ExecutionContext — unified dependency injection bundle.

Stolen from ChatDev 2.0's runtime/node/executor/base.py.
One dataclass carries all runtime services. Every executor receives
this single parameter instead of scattered globals.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExecutionContext:
    task_id: int
    department: str
    cwd: str = ""
    timeout_s: float = 300.0
    max_turns: int = 25
    model: str = "claude-sonnet-4-6"
    global_state: dict[str, Any] = field(default_factory=dict)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    cancel_reason: str = ""
    db: Any = None
    cost_tracker: Any = None
    token_accountant: Any = None
    log_event_fn: Any = None

    @property
    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def cancel(self, reason: str = ""):
        self.cancel_reason = reason
        self.cancel_event.set()


class ExecutionContextBuilder:
    def __init__(self, task_id: int, department: str):
        self._task_id = task_id
        self._department = department
        self._cwd = ""
        self._timeout_s = 300.0
        self._max_turns = 25
        self._model = "claude-sonnet-4-6"
        self._global_state: dict[str, Any] = {}
        self._db = None
        self._cost_tracker = None
        self._token_accountant = None
        self._log_event_fn = None

    def with_cwd(self, cwd: str) -> "ExecutionContextBuilder":
        self._cwd = cwd
        return self

    def with_timeout(self, timeout_s: float) -> "ExecutionContextBuilder":
        self._timeout_s = timeout_s
        return self

    def with_max_turns(self, max_turns: int) -> "ExecutionContextBuilder":
        self._max_turns = max_turns
        return self

    def with_model(self, model: str) -> "ExecutionContextBuilder":
        self._model = model
        return self

    def with_db(self, db: Any) -> "ExecutionContextBuilder":
        self._db = db
        return self

    def with_cost_tracker(self, tracker: Any) -> "ExecutionContextBuilder":
        self._cost_tracker = tracker
        return self

    def with_token_accountant(self, accountant: Any) -> "ExecutionContextBuilder":
        self._token_accountant = accountant
        return self

    def with_log_event_fn(self, fn: Any) -> "ExecutionContextBuilder":
        self._log_event_fn = fn
        return self

    def build(self) -> ExecutionContext:
        return ExecutionContext(
            task_id=self._task_id, department=self._department,
            cwd=self._cwd, timeout_s=self._timeout_s, max_turns=self._max_turns,
            model=self._model, global_state=self._global_state,
            db=self._db, cost_tracker=self._cost_tracker,
            token_accountant=self._token_accountant, log_event_fn=self._log_event_fn,
        )
