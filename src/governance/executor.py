"""TaskExecutor — Agent SDK session management and task execution."""
import json
import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import anyio
from claude_agent_sdk import (
    query, ClaudeAgentOptions, ResultMessage,
    AssistantMessage, TaskStartedMessage, TaskProgressMessage,
)

from src.storage.events_db import EventsDB
from src.core.llm_router import get_router
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

# Optional imports
try:
    from src.governance.budget.token_budget import TokenAccountant
except ImportError:
    TokenAccountant = None

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

log = logging.getLogger(__name__)

CLAUDE_TIMEOUT = 300
MAX_AGENT_TURNS = 25


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

    def __init__(self, db: EventsDB, on_finalize: Callable | None = None):
        self.db = db
        self.on_finalize = on_finalize
        self.accountant = TokenAccountant(db=self.db) if TokenAccountant else None
        self.semaphore = AgentSemaphore() if AgentSemaphore else None
        self.punch_clock = get_punch_clock() if get_punch_clock else None

    def execute_task_async(self, task_id: int):
        """在线程池中执行任务，不阻塞调用方。"""
        future = _task_pool.submit(self.execute_task, task_id)
        log.info(f"TaskExecutor: task #{task_id} submitted to thread pool")
        return future

    def _prepare_prompt(self, task: dict, dept_key: str, dept: dict,
                        task_cwd: str, project_name: str,
                        blueprint=None) -> str:
        """Assemble the full prompt: department identity + authority + cognitive mode + task + context."""
        base_prompt = TASK_PROMPT_TEMPLATE.format(
            cwd=task_cwd,
            project=project_name,
            problem=task.get("spec", {}).get("problem", ""),
            behavior_chain=task.get("spec", {}).get("behavior_chain", ""),
            observation=task.get("spec", {}).get("observation", ""),
            expected=task.get("spec", {}).get("expected", ""),
            action=task.get("action", ""),
            reason=task.get("reason", ""),
        )
        # 优先从 SKILL.md 加载部门 prompt，fallback 到内置 dict
        # Canary: 如果有 canary prompt 且该任务被分到 canary 组，用新 prompt
        task_id_for_canary = task.get("id", 0)
        if should_use_canary and should_use_canary(task_id_for_canary, dept_key):
            canary_prompt = get_canary_prompt(dept_key) if get_canary_prompt else None
            if canary_prompt:
                dept_prompt = canary_prompt
                log.info(f"TaskExecutor: task #{task_id_for_canary} using CANARY prompt for {dept_key}")
            else:
                skill_content = load_department(dept_key)
                dept_prompt = skill_content if skill_content else dept["prompt_prefix"]
        else:
            skill_content = load_department(dept_key)
            dept_prompt = skill_content if skill_content else dept["prompt_prefix"]

        # Authority ceiling 注入
        if blueprint:
            ceiling = blueprint.authority
            authority_prompt = (
                f"\n\n## Authority Ceiling: {ceiling.name}\n"
                f"你的权限等级为 {ceiling.name}（{ceiling.value}/4）。"
            )
            if ceiling <= AuthorityCeiling.READ:
                authority_prompt += "\n你只能观察和报告。不可修改任何文件。"
            elif ceiling <= AuthorityCeiling.PROPOSE:
                authority_prompt += "\n你可以写提案文件，不可修改已有源码。"
            elif ceiling <= AuthorityCeiling.MUTATE:
                authority_prompt += "\n你可以修改文件，但不可 git commit/push。提交由人类决定。"
            dept_prompt += authority_prompt

        # 认知模式注入
        cognitive_mode = classify_cognitive_mode(task)
        mode_prompt = COGNITIVE_MODE_PROMPTS.get(cognitive_mode, "")

        # 注入最近执行记录
        recent_runs = load_recent_runs(dept_key, n=5) if load_recent_runs else []
        runs_context = format_runs_for_context(recent_runs) if format_runs_for_context else ""

        # 组装最终 prompt
        prompt = dept_prompt
        if mode_prompt:
            prompt += "\n\n" + mode_prompt
        prompt += "\n\n" + base_prompt
        if runs_context:
            prompt += "\n\n" + runs_context

        # 动态上下文组装
        try:
            dynamic_ctx = assemble_context(dept_key, task)
            if dynamic_ctx:
                prompt += "\n\n" + dynamic_ctx
        except Exception as e:
            log.warning(f"TaskExecutor: context assembly failed ({e}), continuing without dynamic context")

        return prompt

    def _log_agent_event(self, task_id: int, event_type: str, data: dict):
        """Safe wrapper: log agent event without breaking execution on failure."""
        try:
            self.db.add_agent_event(task_id, event_type, data)
        except Exception:
            pass

    async def _run_agent_session(self, task_id: int, prompt: str, dept_prompt: str,
                                  allowed_tools: list, task_cwd: str,
                                  max_turns: int = MAX_AGENT_TURNS) -> str:
        """Run the Agent SDK session and stream events. Returns result text."""
        # Agent SDK 环境准备
        agent_env = {}
        if os.environ.get("CLAUDECODE"):
            agent_env["CLAUDECODE"] = ""
        if os.name == "nt" and not os.environ.get("CLAUDE_CODE_GIT_BASH_PATH"):
            bash_path = find_git_bash()
            if bash_path:
                agent_env["CLAUDE_CODE_GIT_BASH_PATH"] = bash_path

        result_text = ""
        turn = 0
        detector = StuckDetector() if StuckDetector else None
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                cwd=task_cwd,
                allowed_tools=allowed_tools,
                permission_mode="bypassPermissions",
                system_prompt=dept_prompt,
                max_turns=max_turns,
                **({"env": agent_env} if agent_env else {}),
            ),
        ):
            if isinstance(message, AssistantMessage):
                turn += 1
                thinking = []
                tool_calls = []
                text_parts = []
                for block in (message.content or []):
                    block_type = getattr(block, 'type', None)
                    if block_type == 'thinking':
                        thinking.append(getattr(block, 'thinking', '')[:300])
                    elif block_type == 'tool_use':
                        tool_calls.append({
                            'tool': getattr(block, 'name', ''),
                            'input_preview': str(getattr(block, 'input', {}))[:200],
                        })
                    elif block_type == 'text':
                        text_parts.append(getattr(block, 'text', '')[:300])

                event_data = {"turn": turn}
                if thinking:
                    event_data["thinking"] = thinking
                if tool_calls:
                    event_data["tools"] = tool_calls
                if text_parts:
                    event_data["text"] = text_parts
                if message.error:
                    event_data["error"] = message.error
                self._log_agent_event(task_id, "agent_turn", event_data)

                # ── Heartbeat: 从 PROGRESS 标记提取进度 ──
                if text_parts and parse_progress:
                    full_text = " ".join(text_parts)
                    pct = parse_progress(full_text)
                    if pct > 0:
                        try:
                            self.db.record_heartbeat(task_id, f"agent-{task_id}",
                                                      "alive", pct, full_text[:100])
                        except Exception:
                            pass

                # ── Stuck Detection: 每 3 轮检查一次 ──
                if detector:
                    tool_names = [tc.get("tool", "") for tc in tool_calls] if tool_calls else []
                    error_text = message.error or ""
                    detector.record({"data": {"tools": tool_names, "text": text_parts, "error": error_text}})

                    if turn > 0 and turn % 3 == 0:
                        stuck, pattern = detector.is_stuck()
                        if stuck:
                            log.warning(f"StuckDetector: task #{task_id} stuck — {pattern}")
                            self._log_agent_event(task_id, "stuck_detected", {
                                "pattern": pattern, "turn": turn,
                            })
                            result_text = f"[STUCK: {pattern}] Agent detected in loop after {turn} turns"
                            break

            elif isinstance(message, TaskProgressMessage):
                self._log_agent_event(task_id, "agent_progress", {
                    "description": message.description[:200],
                    "last_tool": message.last_tool_name,
                })

            elif isinstance(message, TaskStartedMessage):
                self._log_agent_event(task_id, "subtask_started", {
                    "sub_task_id": message.task_id,
                    "description": message.description[:200],
                })

            elif isinstance(message, ResultMessage):
                result_text = message.result or ""
                self._log_agent_event(task_id, "agent_result", {
                    "num_turns": message.num_turns,
                    "duration_ms": message.duration_ms,
                    "cost_usd": message.total_cost_usd,
                    "stop_reason": message.stop_reason,
                    "is_error": message.is_error,
                })

        return result_text

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

        # ── Blueprint resolution ──
        blueprint = load_blueprint(dept_key)

        prompt = self._prepare_prompt(task, dept_key, dept, task_cwd, project_name, blueprint=blueprint)
        skill_content = load_department(dept_key)
        dept_prompt = skill_content if skill_content else dept["prompt_prefix"]

        cognitive_mode = classify_cognitive_mode(task)
        bp_tag = f"bp=v{blueprint.version}" if blueprint else "bp=none"
        log.info(f"TaskExecutor: routing task #{task_id} to {dept['name']}({dept_key}), mode={cognitive_mode}, {bp_tag}, project={project_name}, cwd={task_cwd}")

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

        # ── Sub-run: 记录执行阶段 ──
        sub_run_id = None
        try:
            sub_run_id = self.db.create_sub_run(task_id, "execute")
        except Exception:
            pass

        # ── Heartbeat prompt injection ──
        if HEARTBEAT_PROMPT:
            prompt += "\n" + HEARTBEAT_PROMPT

        output = "(no output)"
        status = "failed"
        try:
            async def _agent_coro():
                return await self._run_agent_session(
                    task_id, prompt, dept_prompt, allowed_tools, task_cwd,
                    max_turns=task_max_turns,
                )
            # Background threads never own an event loop — always use anyio.run()
            output = anyio.run(_agent_coro)
            output = output[:2000] if output else "(no output)"
            status = "done" if output and output != "(no output)" else "failed"
        except TimeoutError:
            output = f"timeout after {task_timeout}s"
        except Exception as e:
            output = str(e)[:2000]
            log.error(f"TaskExecutor: Agent SDK error for task #{task_id}: {e}")
        finally:
            # Sub-run finish
            if sub_run_id:
                try:
                    duration_ms = 0
                    try:
                        d = (datetime.now(timezone.utc) - datetime.fromisoformat(now)).total_seconds()
                        duration_ms = int(d * 1000)
                    except Exception:
                        pass
                    self.db.finish_sub_run(sub_run_id, status, duration_ms=duration_ms,
                                            output_preview=output[:200])
                except Exception:
                    pass

            # Punch out
            if self.punch_clock:
                self.punch_clock.punch_out(task_id)

            # Semaphore release
            if self.semaphore:
                self.semaphore.release(dept_key, task_id)

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

