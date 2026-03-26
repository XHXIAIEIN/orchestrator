"""Executor Session — Agent SDK session runner with stuck/doom loop detection."""
import logging
import os

from claude_agent_sdk import (
    query, ClaudeAgentOptions, ResultMessage,
    AssistantMessage, TaskStartedMessage, TaskProgressMessage,
)

from src.governance.context.prompts import find_git_bash

# Optional imports
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
    from src.governance.safety.doom_loop import check_doom_loop
except ImportError:
    check_doom_loop = None

try:
    from src.governance.audit.heartbeat import parse_progress
except ImportError:
    parse_progress = None

try:
    from src.governance.supervisor import RuntimeSupervisor, InterventionLevel
except ImportError:
    RuntimeSupervisor = None

log = logging.getLogger(__name__)

MAX_AGENT_TURNS = 25


class AgentSessionRunner:
    """Runs an Agent SDK session with event logging, stuck detection, and doom loop handling."""

    def __init__(self, db, log_event_fn=None):
        """
        Args:
            db: EventsDB instance (used for doom loop event retrieval and heartbeat recording).
            log_event_fn: Callable(task_id, event_type, data) for logging agent events.
        """
        self.db = db
        self._log_event = log_event_fn or self._default_log_event

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
        detector = StuckDetector() if StuckDetector else None
        supervisor = RuntimeSupervisor() if RuntimeSupervisor else None
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

                # ── Stuck Detection: 每 3 轮检查一次 ──
                if detector:
                    tool_names = [tc.get("tool", "") for tc in tool_calls] if tool_calls else []
                    error_text = message.error or ""
                    detector.record({"data": {"tools": tool_names, "text": text_parts, "error": error_text}})

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
