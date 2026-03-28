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
from src.governance.scrutiny import classify_cognitive_mode
from src.governance.policy.blueprint import load_blueprint, get_allowed_tools, AuthorityCeiling
from src.governance.safety.immutable_constraints import enforce_tool_constraint, enforce_timeout_constraint
from src.governance.context.prompts import (
    TASK_PROMPT_TEMPLATE, COGNITIVE_MODE_PROMPTS, DEPARTMENTS,
    load_department, find_git_bash,
)
from src.governance.context.context_assembler import assemble_context
from src.gateway.routing import resolve_route, get_policy_config
from src.gateway.complexity import classify_complexity, should_skip_scrutiny, get_recommended_turns

from src.governance.executor_prompt import build_execution_prompt
from src.governance.executor_session import AgentSessionRunner, MAX_AGENT_TURNS
from src.governance.worktree import WorktreeManager
from src.governance.patch_manager import PatchManager


# ── Rollout Configuration (stolen from agent-lightning Round 8) ──

# Conditions that warrant automatic retry
RETRYABLE_CONDITIONS = {"timeout", "stuck", "unresponsive", "cost_limit"}

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


def _classify_failure(output: str) -> str:
    """Classify a failure output into a retry condition category."""
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
                      timeout: float | None = None) -> str:
        """Execute a task and return the result text.

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
                      timeout: float | None = None) -> str:
        result = await runner.run(task_id, prompt, dept_prompt, allowed_tools,
                                  task_cwd, max_turns=max_turns)
        self._last_state = {
            "task_id": task_id,
            "result": result,
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
                      timeout: float | None = None) -> str:
        effective_timeout = timeout or self._default_timeout
        try:
            result = await asyncio.wait_for(
                runner.run(task_id, prompt, dept_prompt, allowed_tools,
                           task_cwd, max_turns=max_turns),
                timeout=effective_timeout,
            )
            return result
        except asyncio.TimeoutError:
            return f"[WATCHDOG: execution timed out after {effective_timeout}s]"
        except Exception as e:
            return f"[ERROR: {e}]"

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
        self._worktree = WorktreeManager()
        self._patches = PatchManager()

    def execute_task_async(self, task_id: int):
        """在线程池中执行任务，不阻塞调用方。"""
        future = _task_pool.submit(self.execute_task, task_id)
        log.info(f"TaskExecutor: task #{task_id} submitted to thread pool")
        return future

    def _prepare_prompt(self, task: dict, dept_key: str, dept: dict,
                        task_cwd: str, project_name: str,
                        blueprint=None) -> str:
        """Assemble the full prompt: department identity + authority + cognitive mode + task + context."""
        return build_execution_prompt(task, dept_key, dept, task_cwd, project_name, blueprint=blueprint)

    def _log_agent_event(self, task_id: int, event_type: str, data: dict):
        """Safe wrapper: log agent event without breaking execution on failure."""
        try:
            self.db.add_agent_event(task_id, event_type, data)
        except Exception:
            pass

    async def _run_agent_session(self, task_id: int, prompt: str, dept_prompt: str,
                                  allowed_tools: list, task_cwd: str,
                                  max_turns: int = MAX_AGENT_TURNS,
                                  timeout: float | None = None) -> str:
        """Run the Agent SDK session via the active ExecutionStrategy. Returns result text."""
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

        # ── Patch Restore (stolen from Cline Kanban) ──
        if self._patches.has_patch(task_id):
            restored = self._patches.restore(task_id, task_cwd)
            if restored:
                log.info(f"TaskExecutor: restored saved patch for task #{task_id}")
            else:
                log.warning(f"TaskExecutor: patch restore failed for task #{task_id}")

        # ── Blueprint resolution ──
        blueprint = load_blueprint(dept_key)

        prompt = self._prepare_prompt(task, dept_key, dept, task_cwd, project_name, blueprint=blueprint)
        skill_content = load_department(dept_key)
        dept_prompt = skill_content if skill_content else dept["prompt_prefix"]

        cognitive_mode = classify_cognitive_mode(task)
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

        log.info(f"TaskExecutor: task #{task_id} policy={route.profile.value} "
                 f"model={effective_model} timeout={task_timeout}s max_turns={task_max_turns}")

        # ── Punch Clock: 声明操作区域 ──
        punch_files = _extract_target_files(spec)
        if punch_files and self.punch_clock:
            ok, conflict = self.punch_clock.checkout(task_id, punch_files, dept_key)
            if not ok:
                log.warning(f"TaskExecutor: task #{task_id} file conflict: {conflict}")

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

        cost_limit = float(os.environ.get("TASK_COST_LIMIT", "0"))  # 0 = 不限
        router = get_router()

        output = "(no output)"
        status = "failed"
        attempt = 0

        # ── Lifecycle: rollout_start ──
        self._hooks.fire("on_rollout_start", {
            "task_id": task_id,
            "task": task,
            "spec": spec,
            "dept_key": dept_key,
            "max_attempts": rollout_cfg.max_attempts,
            "strategy": self._strategy.get_mode(),
        })

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

            try:
                async def _agent_coro():
                    return await self._run_agent_session(
                        task_id, prompt, dept_prompt, allowed_tools, task_cwd,
                        max_turns=task_max_turns, timeout=task_timeout,
                    )
                output = anyio.run(_agent_coro)
                output = output[:2000] if output else "(no output)"
                status = "done" if output and output != "(no output)" else "failed"
            except CostLimitExceededError as e:
                output = f"cost limit exceeded: {e}"
                log.warning(f"TaskExecutor: task #{task_id} attempt #{attempt}: {e}")
            except TimeoutError:
                output = f"timeout after {task_timeout}s"
            except Exception as e:
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

            failure_type = _classify_failure(output)
            if failure_type not in rollout_cfg.retry_conditions:
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

        # ── Cleanup (once, after all attempts) ──
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
