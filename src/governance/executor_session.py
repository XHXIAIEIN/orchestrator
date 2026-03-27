"""Executor Session — Agent SDK session runner with stuck/doom loop detection.

Components are wired via ComponentSpec (stolen from agent-lightning Round 8):
instead of hardcoded try/except ImportError blocks, components are resolved
through a registry. Pass overrides via `components={}` dict to swap any
component without changing code.
"""
import logging
import os
import re

from claude_agent_sdk import (
    query, ClaudeAgentOptions, ResultMessage,
    AssistantMessage, TaskStartedMessage, TaskProgressMessage,
)

from src.governance.context.prompts import find_git_bash
from src.core.component_spec import build_component

# Event types — still needed for structured logging
try:
    from src.governance.events.types import (
        AgentTurn as AgentTurnEvent, AgentResult as AgentResultEvent,
        StuckDetected as StuckDetectedEvent, DoomLoopDetected as DoomLoopDetectedEvent,
        EventSource,
    )
except ImportError:
    AgentTurnEvent = None

# InterventionLevel enum needed for comparison
try:
    from src.governance.supervisor import InterventionLevel
except ImportError:
    InterventionLevel = None

# parse_progress is a function, not a class — keep direct import
try:
    from src.governance.audit.heartbeat import parse_progress
except ImportError:
    parse_progress = None

log = logging.getLogger(__name__)

MAX_AGENT_TURNS = 25

# ── Hallucinated Action Detection (stolen from OpenFang Round 6) ──
# Patterns that suggest the model claims it performed an action
_ACTION_CLAIM_PATTERNS = [
    r"(?:I'?ve|I have|I just|Already|Done|Completed|Finished|已经|已完成|已保存|已修改|已删除|已创建)\s+(?:saved|written|created|modified|deleted|updated|fixed|installed|ran|executed|committed|pushed|moved|renamed|copied)",
    r"(?:文件已|代码已|修改已|删除已|提交已|推送已)",
    r"(?:successfully|成功)\s+(?:saved|created|updated|deleted|写入|创建|更新|删除)",
]


def detect_hallucinated_actions(text: str, tool_calls: list) -> list:
    """Detect claims of actions not backed by actual tool calls.

    Returns list of suspicious claims found in text.
    Only flags when there are ZERO tool calls in the turn —
    if the model made any tool calls, give benefit of the doubt.
    """
    if tool_calls:  # Model did make tool calls, don't second-guess
        return []

    warnings = []
    for pattern in _ACTION_CLAIM_PATTERNS:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            warnings.append(f"Claimed action '{match}' but no tool calls in this turn")

    return warnings


# Default component specs — can be overridden via constructor
_DEFAULT_COMPONENTS = {
    "stuck_detector":     "stuck_detector",       # registry key
    "runtime_supervisor": "runtime_supervisor",
    "taint_tracker":      "taint_tracker",
    "context_budget":     "context_budget",
    "doom_loop_checker":  "doom_loop_checker",
}


class AgentSessionRunner:
    """Runs an Agent SDK session with event logging, stuck detection, and doom loop handling.

    Components are resolved via ComponentSpec:
        runner = AgentSessionRunner(db, components={"stuck_detector": None})  # disable stuck detection
        runner = AgentSessionRunner(db, components={"stuck_detector": MyCustomDetector()})  # custom impl
    """

    def __init__(self, db, log_event_fn=None, components: dict = None):
        """
        Args:
            db: EventsDB instance.
            log_event_fn: Callable(task_id, event_type, data) for logging agent events.
            components: Optional overrides for default component specs. Keys:
                stuck_detector, runtime_supervisor, taint_tracker, context_budget, doom_loop_checker
        """
        self.db = db
        self._log_event = log_event_fn or self._default_log_event

        # ── ComponentSpec: merge defaults with overrides ──
        specs = {**_DEFAULT_COMPONENTS, **(components or {})}
        self._component_specs = specs

    def _default_log_event(self, task_id: int, event_type: str, data: dict):
        """Safe wrapper: log agent event without breaking execution on failure."""
        try:
            self.db.add_agent_event(task_id, event_type, data)
        except Exception:
            pass

    async def run(self, task_id: int, prompt: str, dept_prompt: str,
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

        # ── Resolve components via ComponentSpec ──
        detector = build_component(self._component_specs.get("stuck_detector"))
        supervisor = build_component(self._component_specs.get("runtime_supervisor"))
        taint = build_component(self._component_specs.get("taint_tracker"))
        budget = build_component(self._component_specs.get("context_budget"))
        check_doom_loop = build_component(self._component_specs.get("doom_loop_checker"))
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

                # ── Hallucinated Action Detection ──
                text_content = " ".join(text_parts)
                hallucination_warnings = detect_hallucinated_actions(text_content, tool_calls)
                if hallucination_warnings:
                    for w in hallucination_warnings:
                        self._log_event(task_id, "hallucination_warning", {
                            "warning": w, "turn": turn,
                        })

                # ── Supervisor: 记录工具调用 ──
                if supervisor and tool_calls:
                    for tc in tool_calls:
                        supervisor.record_tool_call(
                            tc.get("tool", ""),
                            {"_preview": tc.get("input_preview", "")},
                        )

                if AgentTurnEvent:
                    evt = AgentTurnEvent(
                        task_id=task_id, source=EventSource.AGENT, turn=turn,
                        tools=[tc.get("tool", "") for tc in tool_calls] if tool_calls else [],
                        thinking_preview=thinking[0][:200] if thinking else "",
                        text_preview=text_parts[0][:200] if text_parts else "",
                        error=message.error or None,
                    )
                    event_data = evt.to_dict()
                    # Preserve rich tool data for doom_loop detection
                    if tool_calls:
                        event_data["tools_detail"] = tool_calls
                else:
                    event_data = {"turn": turn}
                    if thinking:
                        event_data["thinking"] = thinking
                    if tool_calls:
                        event_data["tools"] = tool_calls
                    if text_parts:
                        event_data["text"] = text_parts
                    if message.error:
                        event_data["error"] = message.error
                self._log_event(task_id, "agent_turn", event_data)

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

                # ── Taint Tracking: 标记工具输出 ──
                if taint and tool_calls:
                    for tc in tool_calls:
                        tool_name = tc.get("tool", "")
                        output_preview = tc.get("input_preview", "")
                        try:
                            taint.tag_from_tool(tool_name, output_preview)
                        except Exception:
                            pass

                # ── Context Budget: 记录工具输出 ──
                if budget:
                    budget.advance_turn()
                    for tp in text_parts:
                        budget.record_output("assistant", tp)
                    compressed = budget.compress_if_needed()
                    if compressed:
                        self._log_event(task_id, "context_budget_compress", {
                            "turn": turn, "compressed": compressed,
                        })

                # ── Stuck Detection: 每 3 轮检查一次 ──
                if detector:
                    tool_names = [tc.get("tool", "") for tc in tool_calls] if tool_calls else []
                    error_text = message.error or ""
                    tool_result_text = " ".join(text_parts) if text_parts else ""
                    detector.record(
                        {"data": {"tools": tool_names, "text": text_parts,
                                  "error": error_text, "tools_detail": tool_calls}},
                        tool_result=tool_result_text,
                    )

                    if turn > 0 and turn % 3 == 0:
                        stuck, pattern = detector.is_stuck()
                        if stuck:
                            log.warning(f"StuckDetector: task #{task_id} stuck — {pattern}")
                            stuck_data = (StuckDetectedEvent(
                                task_id=task_id, source=EventSource.GOVERNOR,
                                pattern=pattern, turn=turn,
                            ).to_dict() if AgentTurnEvent else {"pattern": pattern, "turn": turn})
                            self._log_event(task_id, "stuck_detected", stuck_data)
                            result_text = f"[STUCK: {pattern}] Agent detected in loop after {turn} turns"
                            break

                # ── Doom Loop: 每 6 轮深度检查（补 StuckDetector 没覆盖的模式） ──
                if check_doom_loop and turn > 0 and turn % 6 == 0:
                    try:
                        events = self.db.get_agent_events(task_id, limit=30)
                        doom = check_doom_loop(events)
                        if doom.triggered:
                            log.warning(f"DoomLoop: task #{task_id} — {doom.reason}")
                            doom_data = (DoomLoopDetectedEvent(
                                task_id=task_id, source=EventSource.GOVERNOR,
                                reason=doom.reason, turn=turn, details=doom.details,
                            ).to_dict() if AgentTurnEvent else {
                                "reason": doom.reason, "turn": turn, **doom.details,
                            })
                            self._log_event(task_id, "doom_loop_detected", doom_data)
                            result_text = f"[DOOM LOOP: {doom.reason}] Agent terminated after {turn} turns"
                            break
                    except Exception as e:
                        log.debug(f"DoomLoop check error: {e}")

                # ── Supervisor: 每轮评估 ──
                if supervisor:
                    supervisor.end_turn()
                    if turn > 0 and turn % 3 == 0:
                        intervention = supervisor.evaluate(iteration=turn)
                        if intervention:
                            self._log_event(task_id, "supervisor_intervention", {
                                "level": intervention.level.name,
                                "pattern": intervention.pattern,
                                "message": intervention.message,
                                "turn": turn,
                                **intervention.details,
                            })
                            if intervention.level >= InterventionLevel.TERMINATE:
                                log.warning(f"Supervisor TERMINATE: task #{task_id} — {intervention.message}")
                                result_text = f"[SUPERVISOR: {intervention.pattern}] {intervention.message}"
                                break
                            elif intervention.level >= InterventionLevel.NUDGE:
                                log.info(f"Supervisor NUDGE: task #{task_id} — {intervention.message}")

            elif isinstance(message, TaskProgressMessage):
                self._log_event(task_id, "agent_progress", {
                    "description": message.description[:200],
                    "last_tool": message.last_tool_name,
                })

            elif isinstance(message, TaskStartedMessage):
                self._log_event(task_id, "subtask_started", {
                    "sub_task_id": message.task_id,
                    "description": message.description[:200],
                })

            elif isinstance(message, ResultMessage):
                result_text = message.result or ""
                result_data = (AgentResultEvent(
                    task_id=task_id, source=EventSource.AGENT,
                    status="failed" if message.is_error else "done",
                    num_turns=message.num_turns or 0,
                    duration_ms=message.duration_ms or 0,
                    cost_usd=message.total_cost_usd or 0.0,
                ).to_dict() if AgentTurnEvent else {
                    "num_turns": message.num_turns,
                    "duration_ms": message.duration_ms,
                    "cost_usd": message.total_cost_usd,
                    "stop_reason": message.stop_reason,
                    "is_error": message.is_error,
                })
                self._log_event(task_id, "agent_result", result_data)

        return result_text
