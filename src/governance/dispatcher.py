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
from src.governance.department_fsm import fsm as dept_fsm

try:
    from src.governance.pipeline.scout import ScoutMission, create_scout_spec, build_scout_prompt
except ImportError:
    ScoutMission = None

log = logging.getLogger(__name__)

# ── Synthesis Check: patterns that indicate vague dispatch ──
_VAGUE_PHRASES = [
    "based on your findings",
    "implement the changes",
    "fix the issues found",
    "apply the necessary modifications",
    "update as needed",
    "handle the edge cases",
    "make it work",
]

_SYNTHESIS_GUIDANCE = (
    "[Synthesis Warning] This dispatch lacks specific targets. "
    "Provide: (1) exact file paths, (2) function/class names, (3) specific changes. "
    "See SOUL/public/prompts/synthesis_discipline.md for the full protocol."
)


def _check_synthesis_quality(spec: dict, action: str) -> tuple[bool, str]:
    """Check if a task spec contains specific targets for dispatch.

    Returns (is_specific, warning_message). If is_specific is False,
    the warning should be logged and synthesis guidance injected.
    """
    combined = f"{action} {spec.get('problem', '')} {spec.get('summary', '')}".lower()

    # Check for banned vague phrases
    for phrase in _VAGUE_PHRASES:
        if phrase in combined:
            return False, f"Vague phrase detected: '{phrase}'"

    # Check for specificity signals: file paths, function names, line numbers
    specificity_patterns = [
        r'[\w/\\]+\.\w{1,4}',      # file paths (e.g., src/foo.py, config.yaml)
        r'[A-Z]\w+\.\w+\(\)',       # method calls (e.g., TaskDispatcher.dispatch())
        r'[Ll]ine\s*\d+',           # line references
        r'L\d+',                     # compact line references (L42)
        r'def\s+\w+',               # function definitions
        r'class\s+\w+',             # class definitions
    ]

    import re
    has_specifics = any(re.search(p, f"{action} {spec.get('problem', '')}") for p in specificity_patterns)

    if not has_specifics:
        return False, "No specific file paths, function names, or line numbers found in spec"

    return True, ""


# ── Fact-Expression Split: intents that benefit from two-phase dispatch ──
_SPLIT_INTENTS = {"answer", "review", "analyze", "report", "explain", "advise", "assess"}


def _needs_fact_expression_split(spec: dict) -> bool:
    """Determine if a task should use the Fact-Expression Split pipeline.

    Triggers when task involves both fact-judgment AND user-facing output.
    Examples: answering questions, producing reports, reviewing code with feedback.
    Counter-examples: pure code generation, file operations, data collection.
    """
    intent = spec.get("intent", "")
    department = spec.get("department", "")

    # Already specialized — don't re-split
    if department and dept_fsm.is_terminal(department, "approved"):
        return False

    return intent in _SPLIT_INTENTS


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

    def dispatch_with_fact_expression_split(
        self, spec: dict, action: str, reason: str,
        priority: str = "high", source: str = "auto",
    ) -> list[int]:
        """Two-phase dispatch: Fact Layer (刑部) → Expression Layer (礼部).

        Phase 1: Send to quality dept with neutral prompt, get confidence-tagged facts.
        Phase 2: Send to protocol dept with persona, rewrite for tone without changing facts.

        Returns list of task_ids created (0–2 depending on success).
        """
        original_department = spec.get("department", "engineering")
        dispatched: list[int] = []

        # Phase 1: Fact Layer — route to quality dept
        fact_spec = {
            **spec,
            "department": dept_fsm.get_next_department(original_department, "fact_layer") or "quality",
            "phase": "fact_layer",
            "original_department": original_department,
            "extra_instructions": (
                "Output ONLY verified facts. Tag each with [HIGH], [MEDIUM], or [UNVERIFIED]. "
                "List uncertain items separately. Do not fill gaps with guesses. "
                "No persona, no humor, no style — just facts."
            ),
        }
        fact_task_id = self.dispatch_task(
            fact_spec, action=f"[Fact Layer] {action}", reason=reason,
            priority=priority, source=source,
        )
        if fact_task_id is None:
            log.warning("Fact-Expression Split: fact layer dispatch failed, aborting split")
            return dispatched
        dispatched.append(fact_task_id)

        # Phase 2: Expression Layer — route to protocol dept
        expression_spec = {
            **spec,
            "department": dept_fsm.get_next_department("quality", "expression_layer") or "protocol",
            "phase": "expression_layer",
            "original_department": original_department,
            "fact_layer_task_id": fact_task_id,
            "extra_instructions": (
                "Rewrite the fact layer output with appropriate tone and persona. "
                "You MUST NOT add, remove, or modify any facts. "
                "You MUST preserve all confidence tags ([HIGH]/[MEDIUM]/[UNVERIFIED]). "
                "Uncertain items MUST remain visibly marked."
            ),
        }
        expr_task_id = self.dispatch_task(
            expression_spec, action=f"[Expression Layer] {action}", reason=reason,
            priority=priority, source=source,
        )
        if expr_task_id is not None:
            dispatched.append(expr_task_id)
        else:
            log.warning("Fact-Expression Split: expression layer dispatch failed")

        return dispatched

    def needs_group_orchestration(self, spec: dict) -> bool:
        """Detect if a task requires multi-department group orchestration.

        Triggers when:
          - spec has 'departments' key (explicit multi-dept)
          - complexity is HIGH/COMPLEX and task text signals cross-dept work
          - spec has 'multi_department' flag set explicitly

        Does NOT trigger for:
          - Tasks already inside a group orchestration round
          - Single-department tasks with normal complexity
        """
        # Already in a group orchestration round — don't recurse
        if spec.get("orchestration_round"):
            return False

        # Explicit multi-department spec
        if spec.get("departments"):
            depts = spec["departments"]
            if isinstance(depts, str):
                depts = [d.strip() for d in depts.split(",")]
            return len(depts) > 1

        # Explicit flag
        if spec.get("multi_department"):
            return True

        # Complexity-based detection
        complexity_name = spec.get("complexity", "")
        if complexity_name in ("COMPLEX",):
            action_text = f"{spec.get('problem', '')} {spec.get('summary', '')} {spec.get('action', '')}".lower()
            cross_dept_signals = [
                "跨部门", "cross-department", "multi-department", "多部门",
                "协作", "collaborate", "联合", "joint",
                "security review", "安全审查", "质量审查", "quality review",
            ]
            return any(sig in action_text for sig in cross_dept_signals)

        return False

    def dispatch_task(self, spec: dict, action: str, reason: str,
                      priority: str = "high", source: str = "auto") -> int | None:
        """Atomic dispatch pipeline: create → classify → preflight → scrutinize.

        Returns task_id on success, None if preflight/scrutiny rejects.
        NOTE: Does NOT execute the task — caller is responsible for execution."""

        # ── Fact-Expression Split: two-phase dispatch for judgment+presentation tasks ──
        if spec.get("phase") is None and _needs_fact_expression_split(spec):
            self.db.write_log(
                f"Fact-Expression Split triggered for intent={spec.get('intent', '?')}",
                "INFO", "governor",
            )
            log.info(f"TaskDispatcher: routing to fact-expression split (intent={spec.get('intent')})")
            task_ids = self.dispatch_with_fact_expression_split(
                spec, action=action, reason=reason, priority=priority, source=source,
            )
            # Return the last task_id (expression layer) as the "main" result
            return task_ids[-1] if task_ids else None

        # ── Extract depends_on from spec (if provided by caller) ──
        depends_on = spec.pop("depends_on", None)

        task_id = self.db.create_task(
            action=action, reason=reason, priority=priority, spec=spec, source=source,
            depends_on=depends_on,
        )
        summary = spec.get("summary", "")
        dept = spec.get("department", "?")

        # ── Blocked tasks skip pipeline — they'll be processed when unblocked ──
        if depends_on:
            dep_str = ", ".join(f"#{d}" for d in depends_on)
            self.db.write_log(
                f"任务 #{task_id} 等待依赖完成: {dep_str}", "INFO", "governor"
            )
            log.info(f"TaskDispatcher: task #{task_id} blocked on dependencies: {dep_str}")
            return task_id
        log.info(f"TaskDispatcher: created task #{task_id}: {summary} [{dept}]")

        # ── Synthesis Quality Check ──
        is_specific, synth_warning = _check_synthesis_quality(spec, action)
        if not is_specific:
            log.warning(f"TaskDispatcher: task #{task_id} synthesis check failed: {synth_warning}")
            self.db.write_log(
                f"任务 #{task_id} 综合检查不通过：{synth_warning}",
                "WARNING", "governor",
            )
            # Inject synthesis guidance into spec so executor sees it
            extra = spec.get("extra_instructions", "")
            spec["extra_instructions"] = f"{extra}\n{_SYNTHESIS_GUIDANCE}".strip()
            self.db.update_task(task_id, spec=json.dumps(spec, ensure_ascii=False, default=str))

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

        # ── Learnings Injection ──
        try:
            relevant = self.db.get_learnings_for_dispatch(department=dept)
            if relevant:
                warnings = [f"- {l['rule']} (x{l['recurrence']})" for l in relevant[:5]]
                spec["learnings"] = warnings
                self.db.update_task(task_id, spec=json.dumps(spec, ensure_ascii=False, default=str))
                log.info(f"TaskDispatcher: injected {len(warnings)} learnings into task #{task_id}")
        except Exception as e:
            log.warning(f"TaskDispatcher: learnings injection failed ({e}), continuing")

        # ── Scout pre-dispatch: designer mode gets recon first ──
        if spec.get("cognitive_mode") == "designer" and ScoutMission:
            try:
                problem = spec.get("problem", action)
                cwd = spec.get("cwd", "") or _resolve_project_cwd(
                    spec.get("project", "orchestrator"), "")
                scout_spec = create_scout_spec(
                    ScoutMission(question=problem, search_scope=cwd),
                    project=spec.get("project", "orchestrator"), cwd=cwd,
                )
                scout_id = self.db.create_task(
                    action=f"Scout: {problem[:80]}",
                    reason=f"Pre-recon for designer task #{task_id}",
                    priority="medium", spec=scout_spec, source="scout",
                )
                spec["scout_task_id"] = scout_id
                self.db.update_task(task_id, spec=json.dumps(spec, ensure_ascii=False, default=str))
                log.info(f"TaskDispatcher: dispatched scout #{scout_id} for designer task #{task_id}")
            except Exception as e:
                log.debug(f"TaskDispatcher: scout dispatch failed ({e}), continuing without recon")

        # ── Complexity Classification ──
        # Respect pre-set complexity (e.g. from --skip-scrutiny) or tier override
        if spec.get("complexity") == "trivial" or spec.get("tier") == "light":
            from src.gateway.complexity import Complexity
            complexity = Complexity.TRIVIAL
        else:
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
