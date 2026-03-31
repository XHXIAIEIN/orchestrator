"""TaskExecutor — Agent SDK session management and task execution.

Rollout-Attempt lifecycle (stolen from agent-lightning Round 8):
Each task execution is a Rollout. If it fails with a retryable condition,
a new Attempt (sub_run) is created automatically. This replaces the flat
"run once, fail once" model with structured retry + per-attempt tracking.

ExecutionStrategy (stolen from agent-lightning Round 8):
Same execution logic runs in two modes:
- Debug/SharedMemory: synchronous, in-process, state visible for inspection
- Production/ClientServer: async, isolated, crash-safe with timeout
"""
import asyncio
import json
import logging
import os
import re
import threading
import time
import uuid
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import anyio
from claude_agent_sdk import (
    query, ClaudeAgentOptions, ResultMessage,
    AssistantMessage, TaskStartedMessage, TaskProgressMessage,
)

from src.storage.events_db import EventsDB
from src.core.llm_router import get_router
from src.core.cost_tracking import CostTracker, CostLimitExceededError
from src.core.system_monitor import get_monitor
from src.governance.scrutiny import classify_cognitive_mode, estimate_blast_radius
from src.governance.policy.blueprint import load_blueprint, get_allowed_tools, AuthorityCeiling
from src.governance.safety.immutable_constraints import enforce_tool_constraint, enforce_timeout_constraint
from src.governance.context.prompts import (
    TASK_PROMPT_TEMPLATE, COGNITIVE_MODE_PROMPTS, DEPARTMENTS,
    load_department, find_git_bash,
)
from src.gateway.routing import resolve_route, get_policy_config
from src.gateway.complexity import classify_complexity, should_skip_scrutiny, get_recommended_turns

from src.governance.executor_prompt import build_execution_prompt
from src.governance.context.writer import ContextWriter
from src.governance.context.tiers import classify_task_tier
from src.governance.executor_session import AgentSessionRunner, MAX_AGENT_TURNS
from src.governance.execution_response import ExecutionResponse
from src.governance.pipeline.output_compress import compress_output
from src.governance.worktree import WorktreeManager
from src.governance.patch_manager import PatchManager

# ── Resilient Retry (stolen from ChatDev 2.0, Round 13) ──
# Exception chain traversal for deeper failure classification.
try:
    from src.core.resilient_retry import RetryPolicy, should_retry as resilient_should_retry
except ImportError:
    RetryPolicy = None
    resilient_should_retry = None


# ── Rollout Configuration (stolen from agent-lightning Round 8) ──

# Conditions that warrant automatic retry
RETRYABLE_CONDITIONS = {"timeout", "stuck", "unresponsive", "cost_limit", "rate_limited", "transient_server_error"}

@dataclass
class RolloutConfig:
    """Per-task retry policy. Can be set in blueprint.yaml under `rollout:` key."""
    max_attempts: int = 2
    retry_conditions: set[str] = field(default_factory=lambda: {"timeout", "stuck"})
    backoff_seconds: float = 5.0

    @classmethod
    def from_dict(cls, d: dict) -> "RolloutConfig":
        rc = d.get("rollout", {})
        if not rc:
            return cls()
        return cls(
            max_attempts=rc.get("max_attempts", 2),
            retry_conditions=set(rc.get("retry_conditions", ["timeout", "stuck"])),
            backoff_seconds=rc.get("backoff_seconds", 5.0),
        )


# ── Default Resilient Retry Policy (ChatDev 2.0, Round 13) ──
# Complements RolloutConfig's string-based _classify_failure with exception
# chain traversal. Used when execution raises an actual exception (not just
# a tagged output string).
_DEFAULT_RESILIENT_POLICY = None
if RetryPolicy is not None:
    _DEFAULT_RESILIENT_POLICY = RetryPolicy(
        enabled=True,
        max_attempts=3,  # Evaluated independently, but capped by RolloutConfig.max_attempts
        retry_on_types=["TimeoutError", "ConnectionError", "httpx.ReadTimeout"],
        no_retry_types=["KeyboardInterrupt", "SystemExit", "CostLimitExceededError"],
        retry_on_status_codes=[429, 502, 503, 529],
        retry_on_substrings=["rate limit", "overloaded", "capacity"],
    )


# ── Lifecycle Hooks (stolen from agent-lightning R12) ──
# Four hooks fire at key boundaries of the Rollout-Attempt lifecycle.
# Fire-and-forget: exceptions are logged but never block execution.

HookFn = Callable[[dict], None]


@dataclass
class LifecycleHooks:
    """Lifecycle hooks for execution rollouts.

    Each hook receives a context dict with relevant state.
    Hooks are fire-and-forget — exceptions are logged but don't block execution.
    """
    on_rollout_start: list[HookFn] = field(default_factory=list)
    on_attempt_start: list[HookFn] = field(default_factory=list)
    on_attempt_end: list[HookFn] = field(default_factory=list)
    on_rollout_end: list[HookFn] = field(default_factory=list)

    def fire(self, hook_name: str, context: dict):
        """Fire all registered hooks for the given lifecycle event."""
        hooks = getattr(self, hook_name, [])
        for hook in hooks:
            try:
                hook(context)
            except Exception as e:
                logging.getLogger(__name__).warning(
                    f"Hook {hook_name}/{getattr(hook, '__name__', repr(hook))} failed: {e}"
                )


def _classify_failure(output: str, exc: BaseException | None = None) -> str:
    """Classify a failure output into a retry condition category.

    Enhanced with ChatDev 2.0 resilient_retry (Round 13): when an actual
    exception is provided, walks the __cause__/__context__ chain for deeper
    classification before falling back to string matching on output text.
    """
    # ── Phase 1: Exception chain traversal (ChatDev 2.0) ──
    if exc is not None and resilient_should_retry and _DEFAULT_RESILIENT_POLICY:
        from src.core.resilient_retry import _iter_exception_chain, _extract_status_code
        for error in _iter_exception_chain(exc):
            status = _extract_status_code(error)
            if status in (429, 529):
                return "rate_limited"
            if status in (502, 503):
                return "transient_server_error"
            type_name = type(error).__name__
            if "Timeout" in type_name:
                return "timeout"
            if "Connection" in type_name:
                return "transient_server_error"

    # ── Phase 2: Original string-based classification (preserved) ──
    lower = output.lower() if output else ""
    if "timeout" in lower or "[WATCHDOG:" in output:
        return "timeout"
    if "[STUCK:" in output:
        return "stuck"
    if "[DOOM LOOP:" in output:
        return "stuck"
    if "cost limit" in lower:
        return "cost_limit"
    if "unresponsive" in lower:
        return "unresponsive"
    if "rate limit" in lower:
        return "rate_limited"
    return "unknown"

# ── Execution Strategy (stolen from agent-lightning Round 8) ──
# Debug = in-process, state inspectable; Production = isolated, crash-safe.


class ExecutionStrategy(ABC):
    """Strategy for how agent execution is dispatched.

    Stolen from Agent Lightning (Round 8): same execution logic needs to run
    in debug (in-process, inspectable) and production (isolated, crash-safe).
    """

    @abstractmethod
    async def execute(self, runner: "AgentSessionRunner", task_id: int,
                      prompt: str, dept_prompt: str, allowed_tools: list,
                      task_cwd: str, max_turns: int,
                      timeout: float | None = None) -> ExecutionResponse:
        """Execute a task and return structured ExecutionResponse.

        Args:
            timeout: Per-task timeout override. Strategies may ignore or enforce it.
        """
        ...

    @abstractmethod
    def get_mode(self) -> str:
        """Return 'debug' or 'production'."""
        ...


class DebugStrategy(ExecutionStrategy):
    """In-process synchronous execution. State visible for debugging.

    No timeout enforcement — hangs are the developer's problem to Ctrl-C.
    Stores intermediate state so callers can call inspect() after execution.
    """

    def __init__(self):
        self._last_state: dict = {}

    async def execute(self, runner: "AgentSessionRunner", task_id: int,
                      prompt: str, dept_prompt: str, allowed_tools: list,
                      task_cwd: str, max_turns: int,
                      timeout: float | None = None) -> ExecutionResponse:
        result = await runner.run(task_id, prompt, dept_prompt, allowed_tools,
                                  task_cwd, max_turns=max_turns)
        self._last_state = {
            "task_id": task_id,
            "result": result.output,
            "events": getattr(runner, "_events", []),
        }
        return result

    def get_mode(self) -> str:
        return "debug"

    def inspect(self) -> dict:
        """Return the last execution's full state (debug only)."""
        return self._last_state


class ProductionStrategy(ExecutionStrategy):
    """Isolated execution with timeout and crash protection.

    Per-task timeout (from blueprint/policy) takes precedence over the
    default. Exceptions are caught and returned as tagged strings so the
    Rollout-Attempt loop can classify and retry.
    """

    def __init__(self, default_timeout: float = 300.0):
        self._default_timeout = default_timeout

    async def execute(self, runner: "AgentSessionRunner", task_id: int,
                      prompt: str, dept_prompt: str, allowed_tools: list,
                      task_cwd: str, max_turns: int,
                      timeout: float | None = None) -> ExecutionResponse:
        effective_timeout = timeout or self._default_timeout
        try:
            result = await asyncio.wait_for(
                runner.run(task_id, prompt, dept_prompt, allowed_tools,
                           task_cwd, max_turns=max_turns),
                timeout=effective_timeout,
            )
            return result
        except asyncio.TimeoutError:
            return ExecutionResponse(
                status="timeout",
                output=f"[WATCHDOG: execution timed out after {effective_timeout}s]",
                is_error=True,
            )
        except Exception as e:
            return ExecutionResponse(
                status="failed",
                output=f"[ERROR: {e}]",
                is_error=True,
            )

    def get_mode(self) -> str:
        return "production"


# Optional imports
try:
    from src.governance.budget.token_budget import TokenAccountant
except ImportError:
    TokenAccountant = None

try:
    from src.governance.safety.doom_loop import check_doom_loop
except ImportError:
    check_doom_loop = None

try:
    from src.governance.events.types import (
        AgentTurn as AgentTurnEvent, AgentResult as AgentResultEvent,
        StuckDetected as StuckDetectedEvent, DoomLoopDetected as DoomLoopDetectedEvent,
        EventSource,
    )
except ImportError:
    AgentTurnEvent = None

try:
    from src.governance.stuck_detector import StuckDetector
except ImportError:
    StuckDetector = None

try:
    from src.governance.audit.heartbeat import parse_progress, HEARTBEAT_PROMPT
except ImportError:
    parse_progress = None
    HEARTBEAT_PROMPT = ""

try:
    from src.governance.audit.punch_clock import get_punch_clock
except ImportError:
    get_punch_clock = None

try:
    from src.governance.audit.run_logger import format_runs_for_context, load_recent_runs
except ImportError:
    format_runs_for_context = None
    load_recent_runs = None

try:
    from src.governance.policy.prompt_canary import should_use_canary, get_canary_prompt
except ImportError:
    should_use_canary = None
    get_canary_prompt = None

try:
    from src.governance.safety.agent_semaphore import AgentSemaphore
except ImportError:
    AgentSemaphore = None

try:
    from src.governance.approval import get_approval_gateway
except ImportError:
    get_approval_gateway = None

# InterventionChecker — three-layer tool safety (Round 16 LobeHub)
try:
    from src.governance.safety.intervention_checker import InterventionChecker
    _intervention_checker = InterventionChecker.from_yaml("config/intervention_rules.yaml")
except (ImportError, FileNotFoundError):
    _intervention_checker = None

# DualVerify — cross-model verification for HIGH risk post-execution review
try:
    from src.governance.safety.dual_verify import cross_verify as dual_cross_verify
except ImportError:
    dual_cross_verify = None

# DriftDetector — detect agent straying from assigned task
try:
    from src.governance.safety.drift_detector import DriftDetector
except ImportError:
    DriftDetector = None

# Permission Checker — 3-tier tool permission model (OpenAkita)
try:
    from src.governance.permissions import get_permission_checker
except ImportError:
    get_permission_checker = None

# Plan Executor — plan-then-execute dual mode (OpenHands)
try:
    from src.governance.plan_executor import PlanExecutor
except ImportError:
    PlanExecutor = None

# Concurrency Pool — unified concurrency limiter (Firecrawl)
try:
    from src.core.concurrency_pool import get_concurrency_pool
except ImportError:
    get_concurrency_pool = None

# ExecutionSnapshot — incremental execution snapshots (Round 16 LobeHub)
try:
    from src.governance.audit.execution_snapshot import ExecutionSnapshot, SnapshotStore
    _snapshot_store = SnapshotStore()
except (ImportError, Exception):
    ExecutionSnapshot = None
    _snapshot_store = None

# Global Lifecycle Hook Registry (stolen from Hermes, Round 3-7)
# System-wide hooks (pre_llm_call, on_session_start, etc.) complement
# the rollout-specific LifecycleHooks above. Rollout events are bridged
# to the global registry via on_task_dispatch and on_session_start/end.
try:
    from src.core.lifecycle_hooks import get_lifecycle_hooks as _get_global_hooks
except ImportError:
    _get_global_hooks = None

log = logging.getLogger(__name__)

CLAUDE_TIMEOUT = 300


# Thread pool for task execution — reuses threads, avoids WinError 50 from
# excessive thread creation, and keeps OS thread count bounded.
_task_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="governor-task")


from src.governance.scrutiny import _resolve_project_cwd  # shared utility


def _extract_target_files(spec: dict) -> list[str]:
    """Extract likely target files from task spec for punch clock."""
    files = []
    for field in ("problem", "observation", "summary", "expected"):
        text = spec.get(field, "")
        if text:
            import re as _re
            found = _re.findall(r'(?:src|departments|SOUL|dashboard|tests)/[\w/.-]+\.\w+', text)
            files.extend(found)
    return list(set(files))[:10]


class TaskExecutor:
    """Execute tasks via Agent SDK with Blueprint-aware policy resolution."""

    def __init__(self, db: EventsDB, on_finalize: Callable | None = None,
                 strategy: ExecutionStrategy | None = None,
                 hooks: LifecycleHooks | None = None):
        self.db = db
        self.on_finalize = on_finalize
        self.accountant = TokenAccountant(db=self.db) if TokenAccountant else None
        self.semaphore = AgentSemaphore() if AgentSemaphore else None
        self.punch_clock = get_punch_clock() if get_punch_clock else None
        self._session_runner = AgentSessionRunner(db=self.db, log_event_fn=self._log_agent_event)
        self._strategy = strategy or ProductionStrategy()
        self._hooks = hooks or LifecycleHooks()
        self._plan_executor = PlanExecutor() if PlanExecutor else None
        self._worktree = WorktreeManager()
        self._patches = PatchManager()

    def execute_task_async(self, task_id: int):
        """在线程池中执行任务，不阻塞调用方。"""
        future = _task_pool.submit(self.execute_task, task_id)
        log.info(f"TaskExecutor: task #{task_id} submitted to thread pool")
        return future

    def _prepare_prompt(self, task: dict, dept_key: str, dept: dict,
                        task_cwd: str, project_name: str,
                        blueprint=None, session_id: str = "", tier=None) -> str:
        """Assemble the full prompt: department identity + authority + cognitive mode + task + context."""
        return build_execution_prompt(task, dept_key, dept, task_cwd, project_name,
                                      blueprint=blueprint, session_id=session_id, tier=tier)

    def _log_agent_event(self, task_id: int, event_type: str, data: dict):
        """Safe wrapper: log agent event without breaking execution on failure."""
        try:
            self.db.add_agent_event(task_id, event_type, data)
        except Exception:
            pass

    async def _run_agent_session(self, task_id: int, prompt: str, dept_prompt: str,
                                  allowed_tools: list, task_cwd: str,
                                  max_turns: int = MAX_AGENT_TURNS,
                                  timeout: float | None = None) -> ExecutionResponse:
        """Run the Agent SDK session via the active ExecutionStrategy. Returns ExecutionResponse."""
        return await self._strategy.execute(
            self._session_runner, task_id, prompt, dept_prompt,
            allowed_tools, task_cwd, max_turns, timeout=timeout,
        )

    def execute_task(self, task_id: int) -> dict:
        """Execute task by ID — routes to department based on spec.department.

        Blueprint-aware: if blueprint.yaml exists, uses its policy for tools/timeout/max_turns.
        Falls back to DEPARTMENTS dict for backwards compatibility.
        """
        task = self.db.get_task(task_id)
        if not task:
            log.error(f"TaskExecutor: task #{task_id} not found")
            return {}

        spec = task.get("spec", {})
        dept_key = spec.get("department", "engineering")
        dept = DEPARTMENTS.get(dept_key, DEPARTMENTS["engineering"])
        project_name = spec.get("project", "orchestrator")
        task_cwd = _resolve_project_cwd(project_name, spec.get("cwd", ""))

        # ── Worktree Isolation (stolen from Cline Kanban) ──
        use_worktree = spec.get("isolation", False)
        if not use_worktree:
            running_count = self.db.count_running_tasks()
            if running_count >= 1:
                use_worktree = True

        worktree_path = None
        if use_worktree:
            worktree_path = self._worktree.create(task_id)
            if worktree_path:
                task_cwd = str(worktree_path)
                log.info(f"TaskExecutor: task #{task_id} using worktree at {task_cwd}")
            else:
                log.warning(f"TaskExecutor: worktree creation failed for task #{task_id}, using shared cwd")

        # ── Session ID + Context Store (progressive disclosure) ──
        session_id = f"task-{task_id}-{uuid.uuid4().hex[:8]}"
        tier = classify_task_tier(task.get("action", ""), spec)
        log.info(f"TaskExecutor: task #{task_id} tier={tier.name}, session={session_id}")

        ctx_writer = ContextWriter(self.db, session_id)
        # L1: chain outputs from predecessor tasks
        chain_from = spec.get("chain_from")
        if chain_from:
            prev_task = self.db.get_task(int(chain_from))
            if prev_task and prev_task.get("output"):
                ctx_writer.write_chain_output(int(chain_from), prev_task["output"])
        # L1: conversation summary if provided
        conv_summary = spec.get("conversation_summary", "")
        if conv_summary:
            ctx_writer.write_layer1(conversation_summary=conv_summary)
        # L0: identity + catalog (written last so catalog includes L1 entries)
        ctx_writer.write_layer0(task, dept_key)

        # Store tier info in spec for downstream use
        spec["context_budget"] = tier.context_budget
        spec["session_id"] = session_id
        self.db.update_task(task_id, spec=json.dumps(spec, ensure_ascii=False, default=str))

        # ── Patch Restore (stolen from Cline Kanban) ──
        if self._patches.has_patch(task_id):
            restored = self._patches.restore(task_id, task_cwd)
            if restored:
                log.info(f"TaskExecutor: restored saved patch for task #{task_id}")
            else:
                log.warning(f"TaskExecutor: patch restore failed for task #{task_id}")

        # ── Blueprint resolution ──
        blueprint = load_blueprint(dept_key)

        prompt = self._prepare_prompt(task, dept_key, dept, task_cwd, project_name,
                                      blueprint=blueprint, session_id=session_id, tier=tier)
        skill_content = load_department(dept_key)
        dept_prompt = skill_content if skill_content else dept["prompt_prefix"]

        cognitive_mode = classify_cognitive_mode(task)
        blast_radius = estimate_blast_radius(spec)
        bp_tag = f"bp=v{blueprint.version}" if blueprint else "bp=none"
        log.info(f"TaskExecutor: routing task #{task_id} to {dept['name']}({dept_key}), mode={cognitive_mode}, {bp_tag}, strategy={self._strategy.get_mode()}, project={project_name}, cwd={task_cwd}")

        now = datetime.now(timezone.utc).isoformat()
        self.db.update_task(task_id, status="running", started_at=now)
        self.db.write_log(f"开始执行任务 #{task_id}（{project_name}）：{task.get('action','')[:50]}", "INFO", "governor")

        # ── Resolve tools from Blueprint or fallback ──
        if blueprint:
            allowed_tools = get_allowed_tools(blueprint)
        else:
            tools_str = dept.get("tools", "")
            allowed_tools = [t.strip() for t in tools_str.split(",") if t.strip()]

        # ── Apply Policy Profile (intent-based) → Blueprint → defaults ──
        intent_key = spec.get("intent", "")
        route = resolve_route(intent=intent_key, department=dept_key)
        policy_cfg = get_policy_config(route)

        task_timeout = blueprint.timeout_s if blueprint else policy_cfg.timeout_s
        task_max_turns = blueprint.max_turns if blueprint else policy_cfg.max_turns

        # ── TokenAccountant: 预算检查 + 模型降级 ──
        preferred_model = blueprint.model if blueprint else policy_cfg.model
        if self.accountant:
            effective_model = self.accountant.recommend_model(dept_key, preferred_model)
            if effective_model != preferred_model:
                log.info(f"TaskExecutor: task #{task_id} budget downgrade: {preferred_model} → {effective_model}")
        else:
            effective_model = preferred_model

        # ── Complexity-based turns override ──
        complexity = spec.get("complexity", "")
        if complexity:
            from src.gateway.complexity import Complexity as _C
            try:
                rec_turns = get_recommended_turns(_C[complexity])
                task_max_turns = min(task_max_turns, rec_turns)
            except (KeyError, ValueError):
                pass

        # ── Immutable Constraints: timeout cap ──
        ok, reason = enforce_timeout_constraint(task_timeout)
        if not ok:
            log.warning(f"TaskExecutor: {reason}, capping to 900s")
            task_timeout = 900

        # ── Immutable Constraints: tool check ──
        allowed_tools = [t for t in allowed_tools if enforce_tool_constraint(t)[0]]

        # ── Permission Checker: 3-tier tool permission filter (OpenAkita) ──
        if get_permission_checker:
            try:
                perm_checker = get_permission_checker()
                allowed_tools = perm_checker.filter_tools(dept_key, allowed_tools)
                log.debug(f"TaskExecutor: task #{task_id} tools after permission filter: {allowed_tools}")
            except Exception as e:
                log.debug(f"TaskExecutor: permission check skipped ({e})")

        # ── InterventionChecker: three-layer tool pre-screening (Round 16 LobeHub) ──
        if _intervention_checker:
            screened_tools = []
            for tool in allowed_tools:
                result = _intervention_checker.check(tool, {})
                if result.allowed:
                    screened_tools.append(tool)
                elif result.policy.value == "never":
                    log.warning(f"TaskExecutor: task #{task_id} tool '{tool}' blocked by InterventionChecker: {result.reason}")
                else:
                    screened_tools.append(tool)  # REQUIRED/CUSTOM: allow but log
                    log.info(f"TaskExecutor: task #{task_id} tool '{tool}' flagged ({result.policy.value}): {result.reason}")
            allowed_tools = screened_tools

        log.info(f"TaskExecutor: task #{task_id} policy={route.profile.value} "
                 f"model={effective_model} timeout={task_timeout}s max_turns={task_max_turns}")

        # ── Punch Clock: 声明操作区域 ──
        punch_files = _extract_target_files(spec)
        if punch_files and self.punch_clock:
            ok, conflict = self.punch_clock.checkout(task_id, punch_files, dept_key)
            if not ok:
                log.warning(f"TaskExecutor: task #{task_id} file conflict: {conflict}")

        # ── Plan Executor: register plan if spec defines plan_steps (OpenHands) ──
        if self._plan_executor and spec.get("plan_steps"):
            try:
                plan = self._plan_executor.create_plan(
                    task_id=str(task_id),
                    title=task.get("action", "")[:80],
                    goal=spec.get("summary", spec.get("problem", "")),
                    steps=spec["plan_steps"],
                )
                self._plan_executor.approve_plan(str(task_id))
                plan_md = plan.to_markdown()
                prompt += f"\n\n## Execution Plan\n{plan_md}"
                log.info(f"TaskExecutor: task #{task_id} plan registered ({len(plan.steps)} steps)")
            except Exception as e:
                log.debug(f"TaskExecutor: plan registration skipped ({e})")

        # ── Heartbeat prompt injection ──
        if HEARTBEAT_PROMPT:
            prompt += "\n" + HEARTBEAT_PROMPT

        # ── Approval Gate: tasks requiring APPROVE authority need human sign-off ──
        needs_approval = False
        if blueprint and blueprint.authority >= AuthorityCeiling.APPROVE:
            needs_approval = True
        elif spec.get("requires_approval"):
            needs_approval = True

        if needs_approval and get_approval_gateway:
            gateway = get_approval_gateway()
            description = f"[{dept_key}] {task.get('action', '')[:120]}"
            auth_level = blueprint.authority.value if blueprint else 4
            log.info(f"TaskExecutor: task #{task_id} requires approval (authority={auth_level})")
            self.db.write_log(f"任务 #{task_id} 等待人工审批", "INFO", "governor")

            async def _await_approval():
                return await gateway.request_approval(
                    task_id=str(task_id),
                    description=description,
                    authority_level=auth_level,
                    timeout=300,
                )
            decision = anyio.run(_await_approval)

            if decision != "approve":
                log.warning(f"TaskExecutor: task #{task_id} {decision} by human")
                self.db.update_task(task_id, status="denied", output=f"Human decision: {decision}")
                self.db.write_log(f"任务 #{task_id} 被人工{decision}", "WARN", "governor")
                if self.punch_clock and punch_files:
                    self.punch_clock.release(task_id)
                return {"task_id": task_id, "status": "denied", "decision": decision}

            log.info(f"TaskExecutor: task #{task_id} approved, proceeding")
            self.db.write_log(f"任务 #{task_id} 已获人工批准，开始执行", "INFO", "governor")

        # ── System Monitor: 背压控制（偷自 Firecrawl system-monitor.ts）──
        monitor = get_monitor()
        backpressure_wait = 0
        while not monitor.can_accept():
            import time as _time
            _time.sleep(2)
            backpressure_wait += 2
            if backpressure_wait >= 60:  # 最多等 60 秒
                log.warning(f"TaskExecutor: task #{task_id} backpressure timeout after {backpressure_wait}s")
                break
        if backpressure_wait > 0:
            log.info(f"TaskExecutor: task #{task_id} waited {backpressure_wait}s for backpressure")

        # ── Rollout-Attempt Loop (stolen from agent-lightning Round 8) ──
        # Instead of flat "run once, fail once", we wrap execution in an attempt loop.
        # Each attempt gets its own sub_run record for traceability.
        rollout_cfg = RolloutConfig.from_dict(blueprint.__dict__ if blueprint else {})
        if blueprint and hasattr(blueprint, 'rollout'):
            rollout_cfg = RolloutConfig.from_dict({"rollout": blueprint.rollout})

        # ── DriftDetector: initialize for this task (monitors execution drift) ──
        drift_detector = None
        if DriftDetector:
            try:
                writable = blueprint.writable_paths if blueprint and hasattr(blueprint, 'writable_paths') else []
                drift_detector = DriftDetector(task_spec=spec, writable_paths=writable)
                log.debug(f"TaskExecutor: drift detector initialized for task #{task_id}")
            except Exception as e:
                log.debug(f"TaskExecutor: drift detector init skipped ({e})")

        cost_limit = float(os.environ.get("TASK_COST_LIMIT", "0"))  # 0 = 不限
        router = get_router()

        output = "(no output)"
        status = "failed"
        attempt = 0

        # ── ExecutionSnapshot: create snapshot for this rollout ──
        snapshot = None
        if ExecutionSnapshot:
            try:
                snapshot = ExecutionSnapshot(task_id=task_id, department=dept_key)
                snapshot.record("turn_start", {
                    "turn": 0,
                    "event": "rollout_start",
                    "dept_key": dept_key,
                    "project": project_name,
                    "max_attempts": rollout_cfg.max_attempts,
                    "strategy": self._strategy.get_mode(),
                })
            except Exception as e:
                log.debug(f"TaskExecutor: snapshot init failed ({e})")
                snapshot = None

        # ── Lifecycle: rollout_start ──
        self._hooks.fire("on_rollout_start", {
            "task_id": task_id,
            "task": task,
            "spec": spec,
            "dept_key": dept_key,
            "max_attempts": rollout_cfg.max_attempts,
            "strategy": self._strategy.get_mode(),
        })
        # Bridge to global lifecycle registry (Hermes)
        if _get_global_hooks:
            try:
                _get_global_hooks().fire("on_task_dispatch",
                    task_id=task_id, department=dept_key,
                    intent=spec.get("intent", ""), priority=spec.get("priority", "medium"))
                _get_global_hooks().fire("on_session_start",
                    task_id=task_id, department=dept_key,
                    strategy=self._strategy.get_mode())
            except Exception:
                pass

        # ── Concurrency Pool: acquire slot before execution (Firecrawl) ──
        _pool_slot = None
        if get_concurrency_pool:
            try:
                pool = get_concurrency_pool()
                _pool_slot = pool.acquire(
                    owner=f"task:{task_id}:{dept_key}",
                    ttl=int(task_timeout) + 60,
                    metadata={"task_id": task_id, "department": dept_key},
                )
                if not _pool_slot:
                    log.warning(f"TaskExecutor: task #{task_id} concurrency pool full, proceeding anyway")
            except Exception as e:
                log.debug(f"TaskExecutor: concurrency pool acquire failed ({e})")

        while attempt < rollout_cfg.max_attempts:
            attempt += 1
            attempt_label = f"attempt_{attempt}" if rollout_cfg.max_attempts > 1 else "execute"

            # ── Lifecycle: attempt_start ──
            self._hooks.fire("on_attempt_start", {
                "task_id": task_id,
                "task": task,
                "attempt": attempt,
                "max_attempts": rollout_cfg.max_attempts,
            })

            # ── Sub-run: 每个 Attempt 独立记录 ──
            sub_run_id = None
            try:
                sub_run_id = self.db.create_sub_run(task_id, attempt_label)
            except Exception:
                pass

            attempt_start = datetime.now(timezone.utc)

            # ── CostTracker: 每个 attempt 一个实例 ──
            tracker = CostTracker(
                limit=cost_limit if cost_limit > 0 else None,
                source=f"task#{task_id}/attempt#{attempt}",
            )
            router.set_tracker(tracker)

            _last_exc = None  # Track exception for resilient_retry classification
            try:
                async def _agent_coro():
                    return await self._run_agent_session(
                        task_id, prompt, dept_prompt, allowed_tools, task_cwd,
                        max_turns=task_max_turns, timeout=task_timeout,
                    )
                response = anyio.run(_agent_coro)
                if response.output:
                    compressed = compress_output(response.output)
                    output = compressed.content
                    # Store output for chain continuity
                    if session_id:
                        ctx_writer.write_chain_output(task_id, output)
                    if compressed.strategy != "passthrough":
                        log.info(
                            f"TaskExecutor: task #{task_id} output compressed "
                            f"({compressed.strategy}: {compressed.original_length} → {compressed.compressed_length} chars, "
                            f"ratio={compressed.compression_ratio:.0%})"
                        )
                else:
                    output = "(no output)"
                status = "done" if response.status == "done" else "failed"
                # Preserve structured data (e.g. exam nextBatch) in task spec
                if response.context_variables:
                    try:
                        existing_spec = task.get("spec", {})
                        existing_spec["context_variables"] = response.context_variables
                        self.db.update_task(task_id, spec=json.dumps(
                            existing_spec, ensure_ascii=False, default=str))
                        log.info(f"TaskExecutor: task #{task_id} stored context_variables keys={list(response.context_variables.keys())}")
                    except Exception as e:
                        log.warning(f"TaskExecutor: task #{task_id} failed to store context_variables: {e}")
                if hasattr(response, 'to_dict'):
                    self._log_agent_event(task_id, "execution_response", response.to_dict())
            except CostLimitExceededError as e:
                _last_exc = e
                output = f"cost limit exceeded: {e}"
                log.warning(f"TaskExecutor: task #{task_id} attempt #{attempt}: {e}")
            except TimeoutError as e:
                _last_exc = e
                output = f"timeout after {task_timeout}s"
            except Exception as e:
                _last_exc = e
                output = str(e)[:2000]
                log.error(f"TaskExecutor: task #{task_id} attempt #{attempt} error: {e}")
            finally:
                # CostTracker cleanup per attempt
                router.clear_tracker()
                if tracker.call_count > 0:
                    log.info(f"TaskExecutor: task #{task_id} attempt #{attempt} cost: {tracker.summary()}")
                    try:
                        self.db.add_agent_event(task_id, "cost_summary", {
                            **tracker.to_dict(), "attempt": attempt,
                        })
                    except Exception:
                        pass

                # Finish sub-run for this attempt
                if sub_run_id:
                    try:
                        d_ms = int((datetime.now(timezone.utc) - attempt_start).total_seconds() * 1000)
                        self.db.finish_sub_run(sub_run_id, status, duration_ms=d_ms,
                                                output_preview=output[:200])
                    except Exception:
                        pass

            # ── ExecutionSnapshot: record attempt result ──
            if snapshot:
                try:
                    snapshot.record("progress", {
                        "event": "attempt_end",
                        "attempt": attempt,
                        "status": status,
                        "result_preview": output[:200],
                    }, tokens=getattr(tracker, 'total_tokens', 0),
                       cost=getattr(tracker, 'total_cost', 0.0))
                except Exception:
                    pass

            # ── Lifecycle: attempt_end ──
            self._hooks.fire("on_attempt_end", {
                "task_id": task_id,
                "task": task,
                "attempt": attempt,
                "success": status == "done",
                "status": status,
                "result": output[:500],
            })

            # ── Retry Decision ──
            if status == "done":
                break  # Success, no retry needed

            failure_type = _classify_failure(output, exc=_last_exc)

            # Two-layer retry gate (Round 13 enhancement):
            # 1. Original: check failure_type against rollout_cfg.retry_conditions
            # 2. ChatDev 2.0: if the exception exists, also consult resilient_should_retry
            is_retryable = failure_type in rollout_cfg.retry_conditions
            if not is_retryable and _last_exc and resilient_should_retry and _DEFAULT_RESILIENT_POLICY:
                is_retryable = resilient_should_retry(_last_exc, _DEFAULT_RESILIENT_POLICY)
                if is_retryable:
                    log.info(f"TaskExecutor: task #{task_id} resilient_retry says retryable "
                             f"(exception chain: {type(_last_exc).__name__})")

            if not is_retryable:
                log.info(f"TaskExecutor: task #{task_id} failed with '{failure_type}' — not retryable")
                break

            if attempt >= rollout_cfg.max_attempts:
                log.info(f"TaskExecutor: task #{task_id} exhausted {attempt}/{rollout_cfg.max_attempts} attempts")
                break

            # Backoff before retry
            log.info(f"TaskExecutor: task #{task_id} attempt #{attempt} failed ({failure_type}), "
                     f"retrying in {rollout_cfg.backoff_seconds}s...")
            self._log_agent_event(task_id, "rollout_retry", {
                "attempt": attempt,
                "failure_type": failure_type,
                "output_preview": output[:200],
                "next_attempt": attempt + 1,
            })
            time.sleep(rollout_cfg.backoff_seconds)

        # ── ExecutionSnapshot: finalize and save ──
        if snapshot:
            try:
                snapshot.record("progress", {
                    "event": "rollout_end",
                    "total_attempts": attempt,
                    "final_status": status,
                })
                if _snapshot_store:
                    _snapshot_store.save_snapshot(snapshot)
                    log.debug(f"TaskExecutor: snapshot saved for task #{task_id}")
            except Exception as e:
                log.debug(f"TaskExecutor: snapshot save failed ({e})")

        # ── Lifecycle: rollout_end ──
        self._hooks.fire("on_rollout_end", {
            "task_id": task_id,
            "task": task,
            "total_attempts": attempt,
            "max_attempts": rollout_cfg.max_attempts,
            "final_success": status == "done",
            "final_status": status,
            "final_result": output[:500],
        })
        # Bridge to global lifecycle registry (Hermes)
        if _get_global_hooks:
            try:
                _get_global_hooks().fire("on_session_end",
                    task_id=task_id, department=dept_key,
                    status=status, attempts=attempt)
                if status != "done":
                    _get_global_hooks().fire("on_error",
                        task_id=task_id, department=dept_key,
                        error=output[:200], status=status)
            except Exception:
                pass

        # ── DriftDetector: post-execution drift check ──
        if drift_detector:
            try:
                # Feed accumulated agent events into drift detector
                agent_events = self.db.get_agent_events(task_id, limit=50)
                for evt in (agent_events or []):
                    drift_detector.record_turn(evt)
                drift_report = drift_detector.check(task_id=task_id)
                if drift_report.is_drifting:
                    log.warning(
                        f"TaskExecutor: task #{task_id} drift detected "
                        f"(score={drift_report.drift_score:.2f}, signals={len(drift_report.signals)})"
                    )
                    self._log_agent_event(task_id, "drift_detected", drift_report.to_dict())
            except Exception as e:
                log.debug(f"TaskExecutor: drift check skipped ({e})")

        # ── DualVerify: cross-model review for HIGH risk completed tasks ──
        if dual_cross_verify and status == "done" and blast_radius.startswith("HIGH"):
            try:
                review_prompt = (
                    f"Review this task execution output for correctness and safety.\n"
                    f"Task: {task.get('action', '')[:200]}\n"
                    f"Output: {output[:800]}\n\n"
                    f"VERDICT: PASS or FAIL\nFINDINGS: list any issues"
                )
                router = get_router()
                verification = dual_cross_verify(
                    task_id=task_id,
                    verification_type="quality",
                    prompt=review_prompt,
                    model_a_fn=lambda p: router.generate(p, task_type="review"),
                    model_b_fn=lambda p: router.generate(p, task_type="review"),
                )
                log.info(
                    f"TaskExecutor: task #{task_id} dual verify → {verification.agreement.value} "
                    f"(confidence={verification.confidence:.0%})"
                )
                self._log_agent_event(task_id, "dual_verify", verification.to_dict())
            except Exception as e:
                log.debug(f"TaskExecutor: dual verify skipped ({e})")

        # ── Cleanup (once, after all attempts) ──
        # Concurrency Pool: release slot
        if _pool_slot and get_concurrency_pool:
            try:
                get_concurrency_pool().release(_pool_slot)
            except Exception:
                pass

        # Punch out
        if self.punch_clock:
            self.punch_clock.punch_out(task_id)

        # Semaphore release
        if self.semaphore:
            self.semaphore.release(dept_key, task_id)

        # Log attempt summary if we retried
        if attempt > 1:
            self._log_agent_event(task_id, "rollout_summary", {
                "total_attempts": attempt,
                "final_status": status,
                "max_attempts": rollout_cfg.max_attempts,
            })

        # ── Patch: save on failure, cleanup on success ──
        if status == "done":
            self._patches.cleanup(task_id)
        elif status == "failed":
            self._patches.save(task_id, task_cwd)

        # ── Worktree: cleanup after execution ──
        if worktree_path:
            self._worktree.cleanup(task_id)

        # Finalize via callback
        if self.on_finalize:
            self.on_finalize(task_id, task, dept_key, status, output, task_cwd, project_name, now)

        return self.db.get_task(task_id)

    def _visual_verify(self, task_id: int, task_cwd: str, spec: dict) -> str:
        """可选视觉验证：检查约定路径是否有截图，有则用 vision 模型验证。"""
        verify_dir = Path(task_cwd) / ".governor-verify"
        if not verify_dir.exists():
            return ""

        images = list(verify_dir.glob("*.png")) + list(verify_dir.glob("*.jpg"))
        if not images:
            return ""

        image_paths = [str(p) for p in images[:3]]
        expected = spec.get("expected", "任务完成")

        try:
            result = get_router().generate(
                f"这是任务执行后的截图。预期结果是：{expected}\n\n"
                f"请判断截图是否符合预期，用一句话回答。",
                task_type="vision",
                images=image_paths,
            )
            if result:
                log.info(f"TaskExecutor: visual verify task #{task_id}: {result[:80]}")
                for p in images:
                    p.unlink(missing_ok=True)
                verify_dir.rmdir()
            return result
        except Exception as e:
            log.warning(f"TaskExecutor: visual verify failed: {e}")
            return ""
