"""TaskDispatcher — dispatch pipeline: create → classify → preflight → scrutinize → queue."""
import json
import logging
from datetime import datetime, timezone

from src.storage.events_db import EventsDB
from src.governance.scrutiny import Scrutinizer, classify_cognitive_mode, _resolve_project_cwd
from src.governance.policy.blueprint import load_blueprint, run_preflight, preflight_passed
from src.governance.context.prompts import PARALLEL_SCENARIOS
from src.governance.policy.novelty_policy import check_novelty, get_recent_failures
from src.governance.policy.deterministic_resolver import get_deterministic_fallback
from src.governance.safety.agent_semaphore import AgentSemaphore
from src.gateway.complexity import classify_complexity, should_skip_scrutiny

log = logging.getLogger(__name__)

CLAUDE_TIMEOUT = 300
STALE_THRESHOLD = CLAUDE_TIMEOUT + 120
MAX_CONCURRENT = 3


class TaskDispatcher:
    """Dispatch pipeline: zombie reaping, slot management, preflight/scrutiny, task creation."""

    def __init__(self, db: EventsDB, scrutinizer: Scrutinizer):
        self.db = db
        self.scrutinizer = scrutinizer
        self.semaphore = AgentSemaphore()

    def _reap_zombie_tasks(self):
        """收割僵尸任务：如果 running/scrutinizing 状态超过 STALE_THRESHOLD，标记为 failed。
        防止进程崩溃后僵尸任务永久阻塞管线。支持并行模式下的多任务收割。"""
        running = self.db.get_running_tasks()
        if not running:
            return
        for stale in running:
            started = stale.get("started_at")
            if not started:
                self.db.update_task(stale["id"], status="failed",
                                    output="zombie: never started, cleaned up",
                                    finished_at=datetime.now(timezone.utc).isoformat())
                self.db.write_log(f"收割僵尸任务 #{stale['id']}（无启动时间）", "WARNING", "governor")
                log.warning(f"TaskDispatcher: reaped zombie task #{stale['id']} (no started_at)")
                continue
            try:
                started_dt = datetime.fromisoformat(started)
                age = (datetime.now(timezone.utc) - started_dt).total_seconds()
            except (ValueError, TypeError):
                age = STALE_THRESHOLD + 1
            if age > STALE_THRESHOLD:
                self.db.update_task(stale["id"], status="failed",
                                    output=f"zombie: stuck for {int(age)}s, reaped by governor",
                                    finished_at=datetime.now(timezone.utc).isoformat())
                self.db.write_log(f"收割僵尸任务 #{stale['id']}（卡了 {int(age)}s）", "WARNING", "governor")
                log.warning(f"TaskDispatcher: reaped zombie task #{stale['id']} (stuck {int(age)}s)")

    def _get_available_slots(self, max_dispatch: int = MAX_CONCURRENT) -> tuple[int, set]:
        """Return (available_slot_count, busy_slot_keys) after reaping zombies."""
        self._reap_zombie_tasks()
        running_count = self.db.count_running_tasks()
        slots = min(max_dispatch, MAX_CONCURRENT - running_count)

        busy_slots = set()
        for t in self.db.get_running_tasks():
            try:
                spec = json.loads(t.get("spec", "{}"))
                dept = spec.get("department", "")
                cwd = spec.get("cwd", "") or spec.get("project", "")
                busy_slots.add((dept, cwd))
            except (json.JSONDecodeError, TypeError):
                pass
        return slots, busy_slots

    def dispatch_task(self, spec: dict, action: str, reason: str,
                      priority: str = "high", source: str = "auto") -> int | None:
        """Atomic dispatch pipeline: create → classify → preflight → scrutinize.

        Returns task_id on success, None if preflight/scrutiny rejects.
        NOTE: Does NOT execute the task — caller is responsible for execution."""
        task_id = self.db.create_task(
            action=action, reason=reason, priority=priority, spec=spec, source=source,
        )
        summary = spec.get("summary", "")
        dept = spec.get("department", "?")
        log.info(f"TaskDispatcher: created task #{task_id}: {summary} [{dept}]")

        # Cognitive mode
        task_dict = self.db.get_task(task_id)
        spec["cognitive_mode"] = classify_cognitive_mode(task_dict)
        self.db.update_task(task_id, spec=json.dumps(spec, ensure_ascii=False, default=str))

        # ── Preflight verification (Blueprint) ──
        blueprint = load_blueprint(dept) if dept != "?" else None
        if blueprint:
            task_cwd = _resolve_project_cwd(
                spec.get("project", "orchestrator"), spec.get("cwd", ""))
            pf_results = run_preflight(blueprint, task_dict, task_cwd)
            passed, pf_reason = preflight_passed(pf_results)
            if not passed:
                self.db.update_task(task_id, status="preflight_failed",
                                    scrutiny_note=f"预检失败：{pf_reason}",
                                    finished_at=datetime.now(timezone.utc).isoformat())
                self.db.write_log(f"任务 #{task_id} 预检失败：{pf_reason}", "WARNING", "governor")
                log.info(f"TaskDispatcher: task #{task_id} failed preflight: {pf_reason}")
                return None
            log.info(f"TaskDispatcher: task #{task_id} preflight passed ({len(pf_results)} checks)")

        # ── Novelty Policy: 防止重试已失败路径 ──
        if not spec.get("rework_count"):
            try:
                failures = get_recent_failures(self.db, dept)
                novel, novelty_reason = check_novelty(action, spec, failures)
                if not novel:
                    self.db.update_task(task_id, status="scrutiny_failed",
                                        scrutiny_note=f"Novelty Policy: {novelty_reason}",
                                        finished_at=datetime.now(timezone.utc).isoformat())
                    self.db.write_log(f"任务 #{task_id} 被 Novelty Policy 拦截：{novelty_reason}",
                                      "WARNING", "governor")
                    log.info(f"TaskDispatcher: task #{task_id} blocked by novelty policy")
                    return None
            except Exception as e:
                log.warning(f"TaskDispatcher: novelty check failed ({e}), continuing")

        # ── Complexity Classification ──
        complexity = classify_complexity(action, spec)
        spec["complexity"] = complexity.name
        self.db.update_task(task_id, spec=json.dumps(spec, ensure_ascii=False, default=str))
        log.info(f"TaskDispatcher: task #{task_id} complexity={complexity.name}")

        # ── Semaphore: 分级并发控制 ──
        acquired, sem_reason = self.semaphore.try_acquire(dept, task_id)
        if not acquired:
            self.db.update_task(task_id, status="blocked",
                                scrutiny_note=f"并发限制：{sem_reason}",
                                finished_at=datetime.now(timezone.utc).isoformat())
            self.db.write_log(f"任务 #{task_id} 被并发限制阻塞：{sem_reason}", "INFO", "governor")
            log.info(f"TaskDispatcher: task #{task_id} blocked by semaphore: {sem_reason}")
            return None

        # ── Scrutiny (门下省审查) ──
        if should_skip_scrutiny(complexity):
            log.info(f"TaskDispatcher: task #{task_id} TRIVIAL, skipping scrutiny")
            self.db.update_task(task_id, scrutiny_note="免审：TRIVIAL 复杂度")
        else:
            self.db.update_task(task_id, status="scrutinizing")
            self.db.write_log(f"门下省审查任务 #{task_id}：{summary[:50]}", "INFO", "governor")

            approved, note = None, ""
            try:
                approved, note = self.scrutinizer.scrutinize(task_id, self.db.get_task(task_id))
            except Exception as e:
                log.warning(f"TaskDispatcher: scrutiny LLM failed ({e}), trying deterministic fallback")
                fb = get_deterministic_fallback("task.scrutiny", spec)
                if fb:
                    approved = fb["verdict"] == "APPROVE"
                    note = fb["reason"]
                else:
                    approved = True
                    note = f"审查异常，默认放行：{e}"

            if not approved:
                self.semaphore.release(dept, task_id)
                self.db.update_task(task_id, status="scrutiny_failed", scrutiny_note=note,
                                    finished_at=datetime.now(timezone.utc).isoformat())
                self.db.write_log(f"任务 #{task_id} 被门下省驳回：{note}", "WARNING", "governor")
                log.info(f"TaskDispatcher: task #{task_id} rejected by scrutiny")
                return None

            self.db.update_task(task_id, scrutiny_note=f"准奏：{note}")

        return task_id

    def run_batch(self, max_dispatch: int = MAX_CONCURRENT) -> list[int]:
        """Pick high-priority recommendations and dispatch in parallel.

        Returns list of task_ids (not task dicts). Caller handles execution."""
        slots, busy_slots = self._get_available_slots(max_dispatch)
        if slots <= 0:
            log.info(f"TaskDispatcher: all slots busy (max {MAX_CONCURRENT}), skipping")
            return []

        insights = self.db.get_latest_insights()
        recs = insights.get("recommendations", [])
        high = [r for r in recs if r.get("priority") == "high"]
        if not high:
            log.info("TaskDispatcher: no high-priority recommendations, skipping")
            return []

        dispatched = []
        dispatched_slots = set()

        for rec in high:
            if len(dispatched) >= slots:
                break

            dept = rec.get("department", "engineering")
            cwd = rec.get("cwd", "") or rec.get("project", "")
            slot_key = (dept, cwd)

            if slot_key in busy_slots or slot_key in dispatched_slots:
                log.info(f"TaskDispatcher: skipping rec for {dept}@{cwd} (slot busy)")
                continue

            spec = {
                "department":     dept,
                "project":        rec.get("project", "orchestrator"),
                "cwd":            rec.get("cwd", ""),
                "problem":        rec.get("problem", ""),
                "behavior_chain": rec.get("behavior_chain", ""),
                "observation":    rec.get("observation", ""),
                "expected":       rec.get("expected", ""),
                "summary":        rec.get("summary", ""),
                "importance":     rec.get("importance", ""),
            }
            task_id = self.dispatch_task(
                spec, action=rec.get("action", ""),
                reason=rec.get("reason", ""), priority=rec.get("priority", "high"),
            )
            if task_id is not None:
                dispatched_slots.add(slot_key)
                dispatched.append(task_id)

        if dispatched:
            slot_list = ", ".join(f"{d}@{c}" for d, c in dispatched_slots)
            self.db.write_log(
                f"Governor batch: dispatched {len(dispatched)} tasks to [{slot_list}]",
                "INFO", "governor"
            )
        return dispatched

    def run_parallel_scenario(self, scenario_name: str, project: str = "orchestrator",
                              cwd: str = "", action_prefix: str = "") -> list[int]:
        """Dispatch a predefined parallel scenario. Returns list of task_ids."""
        scenario = PARALLEL_SCENARIOS.get(scenario_name)
        if not scenario:
            available = ", ".join(PARALLEL_SCENARIOS.keys())
            log.error(f"TaskDispatcher: unknown scenario '{scenario_name}'. Available: {available}")
            return []

        slots, _ = self._get_available_slots()
        if slots <= 0:
            log.info(f"TaskDispatcher: no slots available for scenario '{scenario_name}'")
            return []

        if not cwd:
            cwd = _resolve_project_cwd(project)

        dispatched = []
        for dept in scenario["departments"][:slots]:
            action = f"{action_prefix}{scenario['description']}" if action_prefix else scenario["description"]
            spec = {
                "department": dept,
                "project": project,
                "cwd": cwd,
                "problem": f"Parallel scenario: {scenario_name}",
                "summary": f"{dept} — {scenario['description']}",
            }
            task_id = self.dispatch_task(
                spec, action=action,
                reason=f"Parallel scenario dispatch: {scenario_name}", priority="medium",
            )
            if task_id is not None:
                dispatched.append(task_id)

        if dispatched:
            self.db.write_log(
                f"Governor scenario '{scenario_name}': dispatched {len(dispatched)} tasks",
                "INFO", "governor"
            )
            log.info(f"TaskDispatcher: scenario '{scenario_name}' dispatched {len(dispatched)} tasks")
        return dispatched
