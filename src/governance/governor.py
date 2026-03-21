"""
Governor — picks top-priority insight recommendation and executes it via Agent SDK.
Auto-triggered after InsightEngine; also called by dashboard approve endpoint.

Flow (auto path):  pending → scrutinizing → running → done/failed
                                          ↘ scrutiny_failed
Flow (manual path): awaiting_approval → running → done/failed
"""
import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

import anyio
from claude_agent_sdk import (
    query, ClaudeAgentOptions, ResultMessage,
    AssistantMessage, TaskStartedMessage, TaskProgressMessage,
)

from src.storage.events_db import EventsDB
from src.core.llm_router import get_router
from src.governance.run_logger import append_run_log, load_recent_runs, format_runs_for_context
from src.governance.context_assembler import assemble_context
from src.governance.prompts import (
    TASK_PROMPT_TEMPLATE, SCRUTINY_PROMPT, COGNITIVE_MODE_PROMPTS,
    DEPARTMENTS, PARALLEL_SCENARIOS, SECOND_OPINION_MODEL,
    load_department, find_git_bash,
)
from src.governance.blueprint import (
    load_blueprint, run_preflight, preflight_passed, get_allowed_tools,
    AuthorityCeiling,
)
from src.governance.policy_advisor import observe_task_execution

log = logging.getLogger(__name__)

CLAUDE_TIMEOUT = 300  # seconds
STALE_THRESHOLD = CLAUDE_TIMEOUT + 120  # seconds — if a task is "running" longer than this, it's a zombie
MAX_CONCURRENT = 3  # 最多同时跑几个 sub-agent
MAX_AGENT_TURNS = 25  # Agent SDK 最大交互轮数（防止无限循环）


# ── 认知模式 ──

def classify_cognitive_mode(task: dict) -> str:
    """根据任务特征选择认知模式。

    - direct: 简单任务，直接执行
    - react: 中等复杂，边做边想 (Think-Act-Observe)
    - hypothesis: 诊断类，先假设后验证
    - designer: 大型改动，先设计后实现
    """
    action = (task.get("action") or "").lower()
    spec = task.get("spec", {})
    problem = (spec.get("problem") or "").lower()
    summary = (spec.get("summary") or "").lower()
    combined = f"{action} {problem} {summary}"

    # 诊断类关键词 → hypothesis
    diagnostic_signals = ["为什么", "why", "原因", "cause", "失败率",
                          "不工作", "not working", "异常", "anomaly",
                          "诊断", "diagnose", "排查", "investigate"]
    if any(s in combined for s in diagnostic_signals):
        return "hypothesis"

    # 大型改动 → designer
    designer_signals = ["重构", "refactor", "新增子系统", "redesign", "架构",
                       "architecture", "新模块", "new module", "迁移", "migrate"]
    if any(s in combined for s in designer_signals):
        return "designer"

    # 简单操作 → direct
    simple_signals = ["typo", "改名", "rename", "删除", "清理", "cleanup",
                      "更新版本", "bump", "调整参数", "config", "格式化",
                      "format", "注释", "comment"]
    if any(s in combined for s in simple_signals):
        return "direct"

    # 默认 → react
    return "react"


def estimate_blast_radius(spec: dict) -> str:
    """评估任务的爆炸半径——出错时影响范围有多大。"""
    problem = (spec.get("problem") or "").lower()
    action = (spec.get("action") or "").lower() if spec.get("action") else ""
    combined = f"{problem} {action}"

    high_risk = ["schema", "migration", "database", "events.db", "docker",
                 "重启", "restart", "删除", "delete", "清理数据", "credentials", "密钥"]
    if any(k in combined for k in high_risk):
        return "HIGH — 数据/基础设施级别，不可逆或难以恢复"

    medium_risk = ["重构", "refactor", "多个文件", "接口", "api", "config"]
    if any(k in combined for k in medium_risk):
        return "MEDIUM — 多文件改动，可能引入回归"

    return "LOW — 局部改动，容易回滚"


def _in_async_context() -> bool:
    """检测当前是否已在 async event loop 中（线程池 vs 主线程）。"""
    try:
        import sniffio
        sniffio.current_async_library()
        return True
    except (ImportError, sniffio.AsyncLibraryNotFoundError):
        return False


def _resolve_project_cwd(project_name: str, fallback_cwd: str = "") -> str:
    """Resolve a project name to a working directory path."""
    if fallback_cwd:
        return fallback_cwd
    from src.core.project_registry import resolve_project
    resolved = resolve_project(project_name)
    if resolved:
        return resolved
    return os.environ.get("ORCHESTRATOR_ROOT", str(Path(__file__).parent.parent))


def _parse_scrutiny_verdict(text: str) -> tuple[bool, str]:
    """Parse VERDICT and REASON from scrutiny model output."""
    approved = "VERDICT: APPROVE" in text
    reason_line = next((l for l in text.splitlines() if l.startswith("REASON:")), "")
    reason = reason_line.replace("REASON:", "").strip() or text[:80]
    return approved, reason


class Governor:
    MAX_REWORK = 1  # 最多打回重做 1 次，防止工部↔刑部死循环

    def __init__(self, db: EventsDB = None, db_path: str = "events.db"):
        self.db = db or EventsDB(db_path)

    def scrutinize(self, task_id: int, task: dict) -> tuple[bool, str]:
        """门下省审查。LOW/MEDIUM 单模型审查，HIGH 双模型交叉验证。"""
        spec = task.get("spec", {})
        project_name = spec.get("project", "orchestrator")
        task_cwd = _resolve_project_cwd(project_name, spec.get("cwd", ""))

        cognitive_mode = classify_cognitive_mode(task)
        blast_radius = estimate_blast_radius(spec)
        prompt = SCRUTINY_PROMPT.format(
            summary=spec.get("summary", task.get("action", "")),
            project=project_name,
            cwd=task_cwd,
            problem=spec.get("problem", ""),
            observation=spec.get("observation", ""),
            expected=spec.get("expected", ""),
            action=task.get("action", ""),
            reason=task.get("reason", ""),
            cognitive_mode=cognitive_mode,
            blast_radius=blast_radius,
        )

        is_high_risk = blast_radius.startswith("HIGH")

        try:
            # First opinion (primary model via router)
            text1 = get_router().generate(prompt, task_type="scrutiny")
            approved1, reason1 = _parse_scrutiny_verdict(text1)

            if not is_high_risk:
                log.info(f"Governor: scrutiny #{task_id} → {'APPROVE' if approved1 else 'REJECT'}: {reason1}")
                return approved1, reason1

            # HIGH risk: get second opinion from a different model
            log.info(f"Governor: HIGH risk task #{task_id}, requesting second opinion")
            try:
                from src.core.config import get_anthropic_client
                client = get_anthropic_client()
                resp = client.messages.create(
                    model=SECOND_OPINION_MODEL,
                    max_tokens=256,
                    messages=[{"role": "user", "content": prompt}],
                )
                text2 = resp.content[0].text if resp.content else ""
                approved2, reason2 = _parse_scrutiny_verdict(text2)
            except Exception as e2:
                log.warning(f"Governor: second opinion failed ({e2}), using first opinion only")
                return approved1, reason1

            # Cross-validate
            if approved1 and approved2:
                log.info(f"Governor: scrutiny #{task_id} HIGH → APPROVE (both models agree)")
                return True, f"双审通过：{reason1}"
            elif not approved1 and not approved2:
                log.info(f"Governor: scrutiny #{task_id} HIGH → REJECT (both models agree)")
                return False, f"双审驳回：{reason1} / {reason2}"
            else:
                dissent = f"模型分歧 [M1:{'通过' if approved1 else '驳回'}={reason1}] [M2:{'通过' if approved2 else '驳回'}={reason2}]"
                log.warning(f"Governor: scrutiny #{task_id} HIGH → DISAGREEMENT, blocking: {dissent}")
                self.db.write_log(f"门下省分歧：#{task_id} {dissent}", "WARNING", "governor")
                return False, f"需人工决定：{dissent}"

        except Exception as e:
            log.warning(f"Governor: scrutiny failed ({e}), defaulting to APPROVE")
            return True, f"审查异常，默认放行：{e}"

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
                log.warning(f"Governor: reaped zombie task #{stale['id']} (no started_at)")
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
                log.warning(f"Governor: reaped zombie task #{stale['id']} (stuck {int(age)}s)")

    # ── Dispatch pipeline ──────────────────────────────────────────────

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

    def _dispatch_task(self, spec: dict, action: str, reason: str,
                       priority: str = "high", source: str = "auto") -> dict | None:
        """Atomic dispatch pipeline: create → classify → preflight → scrutinize → execute.

        NemoClaw-inspired five-stage lifecycle:
          Resolve (dept lookup) → Verify (preflight) → Plan (scrutiny) → Apply (execute) → Status (finalize)

        Returns the task dict on success, None if preflight/scrutiny rejects."""
        task_id = self.db.create_task(
            action=action, reason=reason, priority=priority, spec=spec, source=source,
        )
        summary = spec.get("summary", "")
        dept = spec.get("department", "?")
        log.info(f"Governor: created task #{task_id}: {summary} [{dept}]")

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
                log.info(f"Governor: task #{task_id} failed preflight: {pf_reason}")
                return None
            log.info(f"Governor: task #{task_id} preflight passed ({len(pf_results)} checks)")

        # ── Scrutiny (门下省审查) ──
        self.db.update_task(task_id, status="scrutinizing")
        self.db.write_log(f"门下省审查任务 #{task_id}：{summary[:50]}", "INFO", "governor")
        approved, note = self.scrutinize(task_id, self.db.get_task(task_id))

        if not approved:
            self.db.update_task(task_id, status="scrutiny_failed", scrutiny_note=note,
                                finished_at=datetime.now(timezone.utc).isoformat())
            self.db.write_log(f"任务 #{task_id} 被门下省驳回：{note}", "WARNING", "governor")
            log.info(f"Governor: task #{task_id} rejected by scrutiny")
            return None

        self.db.update_task(task_id, scrutiny_note=f"准奏：{note}")
        self.execute_task_async(task_id)
        return self.db.get_task(task_id)

    # ── Public dispatch methods ──────────────────────────────────────

    def run_batch(self, max_dispatch: int = MAX_CONCURRENT) -> list[dict]:
        """Pick high-priority recommendations and dispatch in parallel.

        Rules:
        - Respects MAX_CONCURRENT global limit
        - Same department + same project/cwd cannot run in parallel (file conflict risk)
        - Same department + different projects CAN run in parallel
        """
        slots, busy_slots = self._get_available_slots(max_dispatch)
        if slots <= 0:
            log.info(f"Governor: all slots busy (max {MAX_CONCURRENT}), skipping")
            return []

        insights = self.db.get_latest_insights()
        recs = insights.get("recommendations", [])
        high = [r for r in recs if r.get("priority") == "high"]
        if not high:
            log.info("Governor: no high-priority recommendations, skipping")
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
                log.info(f"Governor: skipping rec for {dept}@{cwd} (slot busy)")
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
            result = self._dispatch_task(
                spec, action=rec.get("action", ""),
                reason=rec.get("reason", ""), priority=rec.get("priority", "high"),
            )
            if result:
                dispatched_slots.add(slot_key)
                dispatched.append(result)

        if dispatched:
            slot_list = ", ".join(f"{d}@{c}" for d, c in dispatched_slots)
            self.db.write_log(
                f"Governor batch: dispatched {len(dispatched)} tasks to [{slot_list}]",
                "INFO", "governor"
            )
        return dispatched

    def run_parallel_scenario(self, scenario_name: str, project: str = "orchestrator",
                              cwd: str = "", action_prefix: str = "") -> list[dict]:
        """Dispatch a predefined parallel scenario — multiple departments at once."""
        scenario = PARALLEL_SCENARIOS.get(scenario_name)
        if not scenario:
            available = ", ".join(PARALLEL_SCENARIOS.keys())
            log.error(f"Governor: unknown scenario '{scenario_name}'. Available: {available}")
            return []

        slots, _ = self._get_available_slots()
        if slots <= 0:
            log.info(f"Governor: no slots available for scenario '{scenario_name}'")
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
            result = self._dispatch_task(
                spec, action=action,
                reason=f"Parallel scenario dispatch: {scenario_name}", priority="medium",
            )
            if result:
                dispatched.append(result)

        if dispatched:
            dept_list = ", ".join(d["spec"].get("department", "?") if isinstance(d.get("spec"), dict)
                                 else json.loads(d.get("spec", "{}")).get("department", "?")
                                 for d in dispatched)
            self.db.write_log(
                f"Governor scenario '{scenario_name}': dispatched {len(dispatched)} tasks [{dept_list}]",
                "INFO", "governor"
            )
            log.info(f"Governor: scenario '{scenario_name}' dispatched {len(dispatched)} tasks")
        return dispatched

    # ── Task execution ───────────────────────────────────────────────

    def execute_task_async(self, task_id: int):
        """在后台线程中执行任务，不阻塞调用方。"""
        t = threading.Thread(
            target=self.execute_task,
            args=(task_id,),
            name=f"governor-task-{task_id}",
            daemon=True,
        )
        t.start()
        log.info(f"Governor: task #{task_id} dispatched to background thread")
        return t

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
        recent_runs = load_recent_runs(dept_key, n=5)
        runs_context = format_runs_for_context(recent_runs)

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
            log.warning(f"Governor: context assembly failed ({e}), continuing without dynamic context")

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

    def _finalize_task(self, task_id: int, task: dict, dept_key: str,
                       status: str, output: str, task_cwd: str, project_name: str, now: str):
        """Post-execution: visual verify, update status, write run log, dispatch collaboration."""
        spec = task.get("spec", {})

        # 视觉验证
        if status == "done":
            verification = self._visual_verify(task_id, task_cwd, spec)
            if verification:
                output = f"{output}\n\n[visual_verify] {verification}"

        finished = datetime.now(timezone.utc).isoformat()
        try:
            self.db.update_task(task_id, status=status, output=output, finished_at=finished)
        except Exception as e:
            log.error(f"Governor: failed to update task #{task_id} status: {e}")
        self.db.write_log(f"任务 #{task_id}（{project_name}）{status}：{output[:80]}", "INFO" if status == "done" else "ERROR", "governor")
        log.info(f"Governor: task #{task_id} {status}")

        # 部门执行记忆
        try:
            duration_s = 0
            try:
                started_dt = datetime.fromisoformat(task.get("started_at") or now)
                finished_dt = datetime.fromisoformat(finished)
                duration_s = int((finished_dt - started_dt).total_seconds())
            except (ValueError, TypeError):
                pass
            commit_hash = ""
            commit_match = re.search(r'\b([0-9a-f]{7,40})\b', output) if "commit" in output.lower() else None
            if commit_match:
                commit_hash = commit_match.group(1)
            append_run_log(
                department=dept_key,
                task_id=task_id,
                mode=task.get("source", "auto"),
                summary=task.get("action", "")[:200],
                commit=commit_hash,
                status=status,
                duration_s=duration_s,
                notes=output[:200] if status == "failed" else "",
            )
        except Exception as e:
            log.warning(f"Governor: failed to write run-log for task #{task_id}: {e}")

        # ── Policy Advisor: observe execution for denial patterns ──
        try:
            blueprint = load_blueprint(dept_key)
            if blueprint:
                agent_events = self.db.get_agent_events(task_id, limit=50)
                observe_task_execution(
                    department=dept_key, task_id=task_id,
                    agent_events=agent_events, task_output=output,
                    task_status=status, blueprint=blueprint,
                )
        except Exception as e:
            log.warning(f"Governor: policy advisor observation failed for task #{task_id}: {e}")

        # 部门协作
        if status == "done":
            if dept_key == "engineering":
                task["output"] = output
                self._dispatch_quality_review(task_id, task, task_cwd, project_name)
            elif dept_key == "quality" and "VERDICT: FAIL" in output:
                self._dispatch_rework(task_id, task, task_cwd, project_name, output)

    def execute_task(self, task_id: int) -> dict:
        """Execute task by ID — routes to department based on spec.department.

        Blueprint-aware: if blueprint.yaml exists, uses its policy for tools/timeout/max_turns.
        Falls back to DEPARTMENTS dict for backwards compatibility.
        """
        task = self.db.get_task(task_id)
        if not task:
            log.error(f"Governor: task #{task_id} not found")
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
        log.info(f"Governor: routing task #{task_id} to {dept['name']}({dept_key}), mode={cognitive_mode}, {bp_tag}, project={project_name}, cwd={task_cwd}")

        now = datetime.now(timezone.utc).isoformat()
        self.db.update_task(task_id, status="running", started_at=now)
        self.db.write_log(f"开始执行任务 #{task_id}（{project_name}）：{task.get('action','')[:50]}", "INFO", "governor")

        # ── Resolve tools from Blueprint or fallback ──
        if blueprint:
            allowed_tools = get_allowed_tools(blueprint)
        else:
            tools_str = dept.get("tools", "")
            allowed_tools = [t.strip() for t in tools_str.split(",") if t.strip()]

        # ── Apply Blueprint overrides ──
        task_timeout = blueprint.timeout_s if blueprint else CLAUDE_TIMEOUT
        task_max_turns = blueprint.max_turns if blueprint else MAX_AGENT_TURNS

        output = "(no output)"
        status = "failed"
        try:
            run_fn = self._run_agent_session(
                task_id, prompt, dept_prompt, allowed_tools, task_cwd,
                max_turns=task_max_turns,
            )
            output = anyio.from_thread.run(run_fn) if _in_async_context() else anyio.run(run_fn)
            output = output[:2000] if output else "(no output)"
            status = "done" if output and output != "(no output)" else "failed"
        except TimeoutError:
            output = f"timeout after {task_timeout}s"
        except Exception as e:
            output = str(e)[:2000]
            log.error(f"Governor: Agent SDK error for task #{task_id}: {e}")
        finally:
            self._finalize_task(task_id, task, dept_key, status, output, task_cwd, project_name, now)

        return self.db.get_task(task_id)

    # ── Post-execution helpers ───────────────────────────────────────

    @staticmethod
    def _extract_artifact(task: dict) -> dict:
        """Extract structured handoff artifact from completed task."""
        try:
            output = task.get("output") or ""

            commit_match = re.search(r'(?:commit|committed|提交)[:\s]*([0-9a-f]{7,40})', output, re.IGNORECASE)
            commit = commit_match.group(1) if commit_match else ""

            file_patterns = re.findall(r'(?:src|departments|SOUL|dashboard|tests|data|docs|bin)/[\w/.-]+\.\w+', output)
            files_changed = list(set(file_patterns))[:10]

            done_match = re.search(r'DONE:\s*(.+)', output)
            summary = done_match.group(1).strip() if done_match else task.get("action", "")[:100]

            remaining = re.findall(r'(?:TODO|FIXME|remaining|still need|未完成)[:\s]*(.+)', output, re.IGNORECASE)
            remaining = [r.strip()[:100] for r in remaining[:5]]

            found = []
            for pattern in [r'(?:found|discovered|noticed|发现)[:\s]*(.+)',
                           r'(?:note|warning|注意)[:\s]*(.+)']:
                found.extend(re.findall(pattern, output, re.IGNORECASE))
            found = [f.strip()[:100] for f in found[:5]]

            return {
                "task_id": task.get("id", 0),
                "status": task.get("status", ""),
                "done": summary,
                "found": found,
                "remaining": remaining,
                "files_changed": files_changed,
                "commit": commit,
            }
        except Exception:
            return {
                "task_id": task.get("id", 0),
                "status": task.get("status", ""),
                "done": task.get("action", "")[:100],
                "found": [],
                "remaining": [],
                "files_changed": [],
                "commit": "",
            }

    def _dispatch_quality_review(self, parent_id: int, parent_task: dict, task_cwd: str, project_name: str):
        """工部完成任务后，自动创建刑部验收任务。跳过门下省审查（验收本身就是审查）。"""
        parent_spec = parent_task.get("spec", {})
        parent_action = parent_task.get("action", "")
        if parent_spec.get("department") == "quality":
            return

        artifact = self._extract_artifact(parent_task)
        files_str = ", ".join(artifact["files_changed"]) if artifact["files_changed"] else "未检测到"
        commit_str = artifact["commit"] or "未检测到"

        if artifact["commit"]:
            observation = (
                f"工部执行摘要：{artifact['done']}\n"
                f"改动文件：{files_str}\n"
                f"Commit: {commit_str}\n\n"
                f"请自行运行 git diff {artifact['commit']}~1..{artifact['commit']} 查看实际代码改动，不要依赖上述摘要做判断。"
            )
        else:
            observation = (
                f"工部执行摘要：{artifact['done']}\n"
                f"改动文件：{files_str}\n"
                f"Commit: {commit_str}\n\n"
                f"未检测到 commit hash，请运行 git log --oneline -3 查看最近提交，然后用 git diff 查看实际改动。"
            )

        review_spec = {
            "department": "quality",
            "project": project_name,
            "cwd": task_cwd,
            "problem": f"验收工部任务 #{parent_id} 的执行结果",
            "observation": observation,
            "expected": parent_spec.get("expected", "任务正确完成，无引入新问题"),
            "summary": f"刑部验收：{parent_action[:40]}",
        }
        review_id = self.db.create_task(
            action=f"Review 工部任务 #{parent_id} 的代码改动：检查 git diff、跑测试（如有）、确认无逻辑错误",
            reason=f"工部任务 #{parent_id} 已完成，需刑部验收",
            priority="medium",
            spec=review_spec,
            source="auto",
            parent_task_id=parent_id,
        )
        self.db.write_log(f"工部任务 #{parent_id} 完成 → 派刑部验收任务 #{review_id}", "INFO", "governor")
        log.info(f"Governor: dispatched quality review #{review_id} for engineering task #{parent_id}")

        # 跳过门下省审查（验收本身就是审查），直接执行
        self.db.update_task(review_id, scrutiny_note="免审：工部→刑部验收链自动派单")
        self.execute_task_async(review_id)

    def _dispatch_rework(self, review_task_id: int, review_task: dict,
                         task_cwd: str, project_name: str, review_output: str):
        """刑部验收失败，打回工部重做。追溯原始工部任务，携带刑部反馈。"""
        parent_id = review_task.get("parent_task_id")
        if not parent_id:
            log.warning(f"Governor: review #{review_task_id} has no parent_task_id, skip rework")
            return

        original = self.db.get_task(parent_id)
        if not original:
            return
        original_spec = original.get("spec", {})
        rework_count = original_spec.get("rework_count", 0)
        if rework_count >= self.MAX_REWORK:
            self.db.write_log(
                f"刑部验收任务 #{review_task_id} FAIL，但原任务 #{parent_id} 已重做 {rework_count} 次，不再打回",
                "WARNING", "governor")
            log.warning(f"Governor: task #{parent_id} hit max rework ({rework_count}), not dispatching")
            return

        issue_lines = [
            l for l in review_output.splitlines()
            if l.strip().startswith(('\U0001f534', '\U0001f7e1', '[CRITICAL]', '[BUG]', '[WARN]'))
        ]
        if issue_lines:
            feedback = "\n".join(issue_lines[:10])
        else:
            feedback_lines = []
            for line in review_output.splitlines():
                if line.startswith("VERDICT:"):
                    break
                feedback_lines.append(line)
            feedback = "\n".join(feedback_lines[-10:])

        rework_spec = {
            "department": "engineering",
            "project": project_name,
            "cwd": task_cwd,
            "problem": f"刑部验收任务 #{review_task_id} 驳回了工部任务 #{parent_id}，需要返工修复",
            "observation": f"刑部反馈：\n{feedback}",
            "expected": original_spec.get("expected", "修复刑部指出的问题"),
            "summary": f"返工：{original.get('action', '')[:30]}（刑部驳回）",
            "rework_count": rework_count + 1,
        }
        rework_id = self.db.create_task(
            action=f"根据刑部反馈修复任务 #{parent_id} 的问题：{feedback[:100]}",
            reason=f"刑部验收 #{review_task_id} FAIL，需返工",
            priority="high",
            spec=rework_spec,
            source="auto",
            parent_task_id=review_task_id,
        )
        self.db.write_log(
            f"刑部验收 #{review_task_id} FAIL → 打回工部，创建返工任务 #{rework_id}（第 {rework_count + 1} 次）",
            "WARNING", "governor")
        log.info(f"Governor: dispatched rework #{rework_id} for failed review #{review_task_id}")

        # 返工任务走正常门下省审查后执行
        self.db.update_task(rework_id, status="scrutinizing")
        approved, note = self.scrutinize(rework_id, self.db.get_task(rework_id))
        if approved:
            self.db.update_task(rework_id, scrutiny_note=f"准奏：{note}")
            self.execute_task_async(rework_id)
        else:
            self.db.update_task(rework_id, status="scrutiny_failed", scrutiny_note=note,
                                finished_at=datetime.now(timezone.utc).isoformat())

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
                log.info(f"Governor: visual verify task #{task_id}: {result[:80]}")
                for p in images:
                    p.unlink(missing_ok=True)
                verify_dir.rmdir()
            return result
        except Exception as e:
            log.warning(f"Governor: visual verify failed: {e}")
            return ""
