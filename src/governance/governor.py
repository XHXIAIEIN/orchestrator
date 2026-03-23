"""Governor — thin coordinator composing Scrutinizer/Dispatcher/Executor/ReviewManager."""
import json

from src.storage.events_db import EventsDB
from src.governance.scrutiny import Scrutinizer, classify_cognitive_mode, estimate_blast_radius
from src.governance.dispatcher import TaskDispatcher
from src.governance.executor import TaskExecutor
from src.governance.review import ReviewManager


class Governor:
    MAX_REWORK = ReviewManager.MAX_REWORK  # backward compat

    def __init__(self, db: EventsDB = None, db_path: str = "events.db"):
        self.db = db or EventsDB(db_path)
        self.scrutinizer = Scrutinizer(self.db)
        self.dispatcher = TaskDispatcher(self.db, self.scrutinizer)
        self.reviewer = ReviewManager(self.db, on_execute=self._execute_async)
        self.executor = TaskExecutor(self.db, on_finalize=self.reviewer.finalize_task)

    def _execute_async(self, task_id: int):
        self.executor.execute_task_async(task_id)

    # ── Scrutiny (backward compat) ──

    def scrutinize(self, task_id: int, task: dict) -> tuple[bool, str]:
        return self.scrutinizer.scrutinize(task_id, task)

    # ── Dispatch ──

    def run_batch(self, max_dispatch: int = 3) -> list[dict]:
        task_ids = self.dispatcher.run_batch(max_dispatch)
        for tid in task_ids:
            self.executor.execute_task_async(tid)
        return [self.db.get_task(tid) for tid in task_ids]

    def run_parallel_scenario(self, scenario_name: str, **kw) -> list[dict]:
        task_ids = self.dispatcher.run_parallel_scenario(scenario_name, **kw)
        for tid in task_ids:
            self.executor.execute_task_async(tid)
        return [self.db.get_task(tid) for tid in task_ids]

    # ── Execution ──

    def execute_task(self, task_id: int) -> dict:
        return self.executor.execute_task(task_id)

    def execute_task_async(self, task_id: int):
        return self.executor.execute_task_async(task_id)

    # ── Internal dispatch (backward compat for _dispatch_task callers) ──

    def _dispatch_task(self, spec: dict, action: str, reason: str,
                       priority: str = "high", source: str = "auto") -> dict | None:
        task_id = self.dispatcher.dispatch_task(spec, action, reason, priority, source)
        if task_id is None:
            return None
        self.executor.execute_task_async(task_id)
        return self.db.get_task(task_id)
