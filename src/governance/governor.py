"""Governor — thin coordinator composing Scrutinizer/Dispatcher/Executor/ReviewManager."""
import json

from src.storage.events_db import EventsDB
from src.governance.scrutiny import Scrutinizer, classify_cognitive_mode, estimate_blast_radius
from src.governance.dispatcher import TaskDispatcher
from src.governance.executor import TaskExecutor
from src.governance.review import ReviewManager


class Governor:
    MAX_REWORK = ReviewManager.MAX_REWORK  # backward compat

    def __init__(self, db: EventsDB = None, db_path: str = None):
        self.db = db or (EventsDB(db_path) if db_path else EventsDB())

        # ── DB Migration: add depends_on column if needed ──
        try:
            self.db.migrate_depends_on()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Governor: depends_on migration failed: {e}")

        self.scrutinizer = Scrutinizer(self.db)
        self.dispatcher = TaskDispatcher(self.db, self.scrutinizer)
        self.reviewer = ReviewManager(self.db, on_execute=self._scrutinize_and_execute)
        self.executor = TaskExecutor(self.db, on_finalize=self.reviewer.finalize_task)

    def _scrutinize_and_execute(self, task_id: int):
        """Callback for ReviewManager: scrutinize rework tasks, then execute if approved."""
        from datetime import datetime, timezone
        task = self.db.get_task(task_id)
        if not task:
            return
        self.db.update_task(task_id, status="scrutinizing")
        try:
            approved, note = self.scrutinizer.scrutinize(task_id, task)
        except Exception as e:
            approved, note = True, f"审查异常，默认放行：{e}"
        if approved:
            self.db.update_task(task_id, scrutiny_note=f"准奏：{note}")
            self.executor.execute_task_async(task_id)
        else:
            self.db.update_task(task_id, status="scrutiny_failed", scrutiny_note=note,
                                finished_at=datetime.now(timezone.utc).isoformat())

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
        # ── Multi-department detection → route to group orchestration ──
        try:
            if self.dispatcher.needs_group_orchestration(spec):
                import logging
                logging.getLogger(__name__).info(
                    f"Governor: multi-dept task detected, routing to group orchestration"
                )
                output = self.run_group(
                    {"action": action, "spec": spec, "reason": reason},
                    max_rounds=5,
                )
                # Create a record task for the group orchestration result
                task_id = self.db.create_task(
                    action=action, reason=reason, priority=priority,
                    spec=spec, source="group_orchestration",
                )
                from datetime import datetime, timezone
                self.db.update_task(
                    task_id, status="completed", output=output,
                    finished_at=datetime.now(timezone.utc).isoformat(),
                )
                return self.db.get_task(task_id)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                f"Governor: group orchestration failed ({e}), falling back to single dispatch"
            )

        task_id = self.dispatcher.dispatch_task(spec, action, reason, priority, source)
        if task_id is None:
            return None
        self.executor.execute_task_async(task_id)
        return self.db.get_task(task_id)

    # ── Group Orchestration (Round 16 LobeHub: Supervisor-Executor) ──

    def run_group(self, task: dict, max_rounds: int = 5) -> str:
        """Run a complex multi-department task via GroupOrchestrationSupervisor.

        Use this instead of run_batch() when a task needs iterative
        cross-department collaboration (e.g. engineering builds → quality reviews → engineering fixes).

        Returns aggregated output from all rounds.
        """
        from src.governance.group_orchestration import GroupOrchestrationSupervisor
        supervisor = GroupOrchestrationSupervisor(max_rounds=max_rounds)
        return supervisor.run(task)

    def dispatch_chain(self, tasks: list[dict]) -> list[int]:
        """Dispatch a sequence of tasks as a dependency chain.

        Each task in the list depends on the previous one.
        First task runs immediately, subsequent tasks block until predecessor completes.

        Args:
            tasks: List of dicts, each with keys: spec, action, reason, priority (optional)

        Returns: List of created task_ids.
        """
        task_ids = []
        for i, t in enumerate(tasks):
            spec = t.get("spec", {})
            if task_ids:
                spec["depends_on"] = [task_ids[-1]]

            task_id = self.dispatcher.dispatch_task(
                spec,
                action=t.get("action", ""),
                reason=t.get("reason", ""),
                priority=t.get("priority", "medium"),
            )
            if task_id is not None:
                task_ids.append(task_id)
                if i == 0:
                    self.executor.execute_task_async(task_id)

        return task_ids
