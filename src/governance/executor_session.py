"""Executor Session — Agent SDK session runner with stuck/doom loop detection.

Components are wired via ComponentSpec (stolen from agent-lightning Round 8):
instead of hardcoded try/except ImportError blocks, components are resolved
through a registry. Pass overrides via `components={}` dict to swap any
component without changing code.
"""
import logging
import os
import re
from pathlib import Path

from claude_agent_sdk import (
    query, ClaudeAgentOptions, ResultMessage,
    AssistantMessage, TaskStartedMessage, TaskProgressMessage,
)

from src.governance.context.prompts import find_git_bash
from src.core.component_spec import build_component
from src.governance.audit.reasoning_trace import append_reasoning_trace
from src.governance.pipeline.phase_rollback import PipelineCheckpointer, RollbackDecision
from src.governance.execution_response import ExecutionResponse
from src.governance.freeze_breaker import FreezeBreaker

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

# WAL — Write-Ahead Log for session state persistence (Round 14 ClawHub)
try:
    from src.governance.audit.wal import scan_for_signals, write_wal_entry, load_session_state
    _WAL_STATE_PATH = str(Path(__file__).resolve().parent.parent.parent / "SOUL" / "private" / "session-state.md")
except (ImportError, Exception):
    scan_for_signals = None
    _WAL_STATE_PATH = None

# Session Repair — validate and repair event history before replay (OpenFang)
try:
    from src.governance.session_repair import SessionRepairer
except ImportError:
    SessionRepairer = None

# Session Manager — fork/inherit session lifecycle (OpenHands)
try:
    from src.governance.session_manager import SessionManager as _SessionManager
    _session_mgr = _SessionManager()
except ImportError:
    _SessionManager = None
    _session_mgr = None

log = logging.getLogger(__name__)

MAX_AGENT_TURNS = 25

# ── Phase Constants (VibeVoice Round 17: Disabled Unified Forward) ──
# AgentSessionRunner has three distinct phases. Callers should use
# the phase-specific methods rather than the monolithic run().
PHASE_PREFILL = "prefill"     # WAL scan, session creation, component resolution
PHASE_EXECUTE = "execute"     # Agent SDK streaming loop
PHASE_FINALIZE = "finalize"   # Status determination, cleanup, response assembly

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
    "context_ledger":     "context_ledger",        # R39: per-segment token tracking
    "doom_loop_checker":  "doom_loop_checker",
    "rate_limiter":       "rate_limiter",           # R39: RPM + TPM token bucket
    "artifact_store":     "artifact_store",         # R39: externalize large tool outputs
    "thinking_tracker":   "thinking_tracker",       # R39: reasoning token stats
    "trajectory_tracker": "trajectory_tracker",     # R39: eval trajectory capture
}


class AgentSessionRunner:
    """Runs an Agent SDK session with event logging, stuck detection, and doom loop handling.

    Components are resolved via ComponentSpec:
        runner = AgentSessionRunner(db, components={"stuck_detector": None})  # disable stuck detection
        runner = AgentSessionRunner(db, components={"stuck_detector": MyCustomDetector()})  # custom impl
    """

    def __init__(self, db, log_event_fn=None, components: dict = None, approval_gateway=None):
        """
        Args:
            db: EventsDB instance.
            log_event_fn: Callable(task_id, event_type, data) for logging agent events.
            components: Optional overrides for default component specs. Keys:
                stuck_detector, runtime_supervisor, taint_tracker, context_budget, doom_loop_checker
            approval_gateway: Optional ApprovalGateway for mid-session interrupt-resume (R43).
        """
        self.db = db
        self._log_event = log_event_fn or self._default_log_event
        self._approval_gateway = approval_gateway

        # ── ComponentSpec: merge defaults with overrides ──
        specs = {**_DEFAULT_COMPONENTS, **(components or {})}
        self._component_specs = specs

    def _default_log_event(self, task_id: int, event_type: str, data: dict):
        """Safe wrapper: log agent event without breaking execution on failure."""
        try:
            self.db.add_agent_event(task_id, event_type, data)
        except Exception:
            pass

    async def interrupt(self, task_id: int, node_id: str, value) -> any:
        """Request a mid-session interrupt and wait for human resume (R43).

        Unlike pre-task approval, this can be called at any point during agent
        execution to pause and request arbitrary human input.

        Args:
            task_id: Current task being executed
            node_id: Identifier for the current execution node/step
            value: Payload to send to human (question, options, etc.)

        Returns:
            The human-provided resume value, or None on timeout.
        """
        if not self._approval_gateway:
            log.warning("AgentSessionRunner.interrupt() called without approval_gateway")
            return None

        point = self._approval_gateway.request_interrupt(
            task_id=str(task_id), node_id=node_id, value=value
        )
        self._log_event(task_id, "interrupt_requested", {
            "interrupt_id": point.interrupt_id,
            "node_id": node_id,
            "value": str(value)[:500],
        })

        resume_value = await self._approval_gateway.await_interrupt_resume(
            point.interrupt_id
        )
        self._log_event(task_id, "interrupt_resumed", {
            "interrupt_id": point.interrupt_id,
            "resume_value": str(resume_value)[:500],
        })
        return resume_value

    def prefill(self, task_id: int, prompt: str, task_cwd: str) -> dict:
        """Phase 1: Prepare execution context — WAL scan, session creation, env setup.

        Stolen from VibeVoice (Round 17): Disabled Unified Forward pattern.
        Instead of one monolithic run(), expose phase-specific entry points
        so callers can compose or skip phases explicitly.

        Returns:
            dict with keys: agent_env, session, wal_signals
        """
        # CRITICAL: unset CLAUDECODE to prevent nesting error
        saved_claudecode = os.environ.pop("CLAUDECODE", None)
        agent_env = {}
        if os.name == "nt" and not os.environ.get("CLAUDE_CODE_GIT_BASH_PATH"):
            bash_path = find_git_bash()
            if bash_path:
                agent_env["CLAUDE_CODE_GIT_BASH_PATH"] = bash_path

        # WAL: scan prompt for signals
        wal_signals = []
        if scan_for_signals and _WAL_STATE_PATH:
            try:
                signals = scan_for_signals(prompt)
                if signals:
                    from pathlib import Path as _P
                    if _P(_WAL_STATE_PATH).exists():
                        for sig in signals:
                            write_wal_entry(
                                _WAL_STATE_PATH, "Active Tasks",
                                f"[task#{task_id}] signal={sig.signal_type}: {sig.matched_text[:80]}",
                            )
                        wal_signals = signals
                        log.debug(f"WAL: wrote {len(signals)} signal(s) for task #{task_id}")
            except Exception as e:
                log.debug(f"WAL: pre-exec scan failed ({e})")

        # Session Manager: create session
        session = None
        if _session_mgr:
            try:
                session = _session_mgr.create(task_id=str(task_id), cwd=task_cwd)
            except Exception as e:
                log.debug(f"SessionManager: create failed ({e})")

        return {
            "agent_env": agent_env,
            "session": session,
            "wal_signals": wal_signals,
            "_saved_claudecode": saved_claudecode,
        }

    def finalize(self, task_id: int, result_text: str, turn: int,
                 num_turns: int, total_cost_usd: float, total_duration_ms: int,
                 stop_reason: str, is_error: bool, tool_count: int,
                 prefill_ctx: dict) -> ExecutionResponse:
        """Phase 3: Determine final status, cleanup, assemble response.

        Stolen from VibeVoice (Round 17): explicit phase boundary
        ensures cleanup always runs regardless of execution path.
        """
        # Determine final status
        if result_text.startswith("[STUCK:"):
            final_status = "stuck"
        elif result_text.startswith("[DOOM LOOP:"):
            final_status = "doom_loop"
        elif result_text.startswith("[SUPERVISOR:"):
            final_status = "terminated"
        elif result_text.startswith("[FROZEN:"):
            final_status = "frozen"
        elif is_error:
            final_status = "failed"
        else:
            final_status = "done"

        # WAL: post-execution checkpoint
        if scan_for_signals and _WAL_STATE_PATH:
            try:
                from pathlib import Path as _P
                if _P(_WAL_STATE_PATH).exists():
                    write_wal_entry(
                        _WAL_STATE_PATH, "Active Tasks",
                        f"[task#{task_id}] completed status={final_status} turns={num_turns or turn}",
                    )
            except Exception as e:
                log.debug(f"WAL: post-exec write failed ({e})")

        # Session Manager: complete/fail session
        session = prefill_ctx.get("session")
        if _session_mgr and session:
            try:
                if final_status == "done":
                    _session_mgr.complete(session.id, cost_usd=total_cost_usd)
                else:
                    _session_mgr.fail(session.id, reason=final_status)
            except Exception as e:
                log.debug(f"SessionManager: finalize failed ({e})")

        # Restore CLAUDECODE env var
        saved = prefill_ctx.get("_saved_claudecode")
        if saved is not None:
            os.environ["CLAUDECODE"] = saved

        # Extract structured JSON blocks
        ctx_vars: dict = {}
        if result_text:
            import json as _json
            for m in re.finditer(r'```json\s*\n(.*?)\n```', result_text, re.DOTALL):
                try:
                    blob = _json.loads(m.group(1))
                    if isinstance(blob, dict):
                        ctx_vars.update(blob)
                    elif isinstance(blob, list) and blob:
                        ctx_vars.setdefault("_json_blocks", []).append(blob)
                except (ValueError, TypeError):
                    pass

        return ExecutionResponse(
            status=final_status,
            output=result_text,
            turns_taken=num_turns or turn,
            cost_usd=total_cost_usd,
            duration_ms=total_duration_ms,
            stop_reason=stop_reason,
            is_error=is_error or final_status != "done",
            tool_calls_count=tool_count,
            context_variables=ctx_vars,
        )

    async def run(self, task_id: int, prompt: str, dept_prompt: str,
                  allowed_tools: list, task_cwd: str,
                  max_turns: int = MAX_AGENT_TURNS) -> ExecutionResponse:
        """Run the full Agent SDK session (prefill → execute → finalize).

        For phase-specific control, use prefill() and finalize() directly.
        This method composes all three phases for backwards compatibility.
        """
        # ── Phase 1: Prefill ──
        prefill_ctx = self.prefill(task_id, prompt, task_cwd)
        agent_env = prefill_ctx["agent_env"]

        # ── Phase 2: Execute (streaming loop) ──
        result_text = ""
        turn = 0
        total_cost_usd = 0.0
        total_duration_ms = 0
        num_turns = 0
        stop_reason_final = ""
        is_error_final = False

        # ── Resolve components via ComponentSpec ──
        detector = build_component(self._component_specs.get("stuck_detector"))
        supervisor = build_component(self._component_specs.get("runtime_supervisor"))
        taint = build_component(self._component_specs.get("taint_tracker"))
        budget = build_component(self._component_specs.get("context_budget"))
        ledger = build_component(self._component_specs.get("context_ledger"))
        check_doom_loop = build_component(self._component_specs.get("doom_loop_checker"))
        rate_limiter = build_component(self._component_specs.get("rate_limiter"))
        artifact_store = build_component(self._component_specs.get("artifact_store"))
        thinking_tracker = build_component(self._component_specs.get("thinking_tracker"))
        # R39: Trajectory capture — TrajectoryTracker needs task_id at init,
        # so we can't use build_component's zero-arg constructor. Check if enabled
        # (spec is not None), then construct directly.
        traj_tracker = None
        if self._component_specs.get("trajectory_tracker") is not None:
            try:
                from src.governance.eval.trajectory import TrajectoryTracker as _TT
                traj_tracker = _TT(task_id=task_id)
            except Exception as e:
                log.debug(f"TrajectoryTracker init failed: {e}")
        checkpointer = PipelineCheckpointer(task_id=task_id)
        freeze_breaker = FreezeBreaker(idle_threshold=5)
        tool_count = 0

        # ── R39: Rate Limiter — acquire before LLM call ──
        if rate_limiter:
            # Estimate initial token cost from prompt length
            prompt_tokens = max(1, len(prompt) // 4)
            if not rate_limiter.try_acquire(tokens=prompt_tokens):
                rate_limiter.acquire(tokens=prompt_tokens, max_wait=30.0)

        # ── R39: ContextLedger — record system prompt segment ──
        if ledger:
            ledger.set_usage("system", max(1, len(dept_prompt) // 4))
            ledger.set_usage("history", max(1, len(prompt) // 4))

        # ── R39: ThinkingTracker — start tracking ──
        if thinking_tracker:
            # Rough complexity estimate from prompt length
            from src.governance.budget.thinking_budget import ThinkingBudget
            complexity = min(1.0, len(prompt) / 50_000)  # normalize: 50K chars ≈ max complexity
            tb = ThinkingBudget.adaptive(complexity=complexity)
            thinking_tracker.start(str(task_id), tb)
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
                # Full-fidelity copies for reasoning trace (P8: OpenClaw steal)
                thinking_full = []
                tool_calls_full = []
                text_full = []
                for block in (message.content or []):
                    # Agent SDK uses typed blocks (ThinkingBlock, ToolUseBlock, TextBlock)
                    # — match by class name, not a 'type' string attribute.
                    cls_name = type(block).__name__
                    if cls_name == 'ThinkingBlock':
                        raw = getattr(block, 'thinking', '')
                        thinking_full.append(raw)
                        thinking.append(raw[:300])
                    elif cls_name == 'ToolUseBlock':
                        name = getattr(block, 'name', '')
                        inp = getattr(block, 'input', {})
                        tool_calls_full.append({'tool': name, 'input': inp})
                        tool_calls.append({
                            'tool': name,
                            'input_preview': str(inp)[:200],
                        })
                    elif cls_name == 'TextBlock':
                        raw = getattr(block, 'text', '')
                        text_full.append(raw)
                        text_parts.append(raw[:300])

                # ── P8: Reasoning Trace — full-fidelity JSONL (OpenClaw steal) ──
                append_reasoning_trace(
                    task_id=task_id, turn=turn,
                    thinking=thinking_full,
                    tool_calls=tool_calls_full,
                    text=text_full,
                    error=message.error or None,
                )

                # ── Hallucinated Action Detection ──
                text_content = " ".join(text_parts)
                hallucination_warnings = detect_hallucinated_actions(text_content, tool_calls)
                if hallucination_warnings:
                    for w in hallucination_warnings:
                        self._log_event(task_id, "hallucination_warning", {
                            "warning": w, "turn": turn,
                        })

                # ── Supervisor: 记��工具调用 ──
                if supervisor and tool_calls:
                    for tc in tool_calls:
                        supervisor.record_tool_call(
                            tc.get("tool", ""),
                            {"_preview": tc.get("input_preview", "")},
                        )

                # ── R39: Trajectory — record each tool call ──
                if traj_tracker and tool_calls:
                    for tc in tool_calls:
                        traj_tracker.record_tool_call(
                            tool_name=tc.get("tool", ""),
                            tool_args={"_preview": tc.get("input_preview", "")},
                            success=not bool(message.error),
                            error_message=(message.error or "")[:200],
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

                # ── Checkpoint: save after successful tool execution ──
                if tool_calls:
                    tool_count += len(tool_calls)
                    result_summary = text_parts[0][:200] if text_parts else ""
                    checkpointer.save(
                        stage_name="execute",
                        stage_index=turn,
                        task_state={"turn": turn, "tool_calls": tool_count},
                        outputs={"last_result": result_summary},
                    )

                # ── R39: Artifact Store — externalize large tool outputs ──
                if artifact_store and text_parts:
                    for i, tp in enumerate(text_parts):
                        externalized = artifact_store.maybe_externalize(tp, tool_name=f"turn-{turn}")
                        if externalized != tp:
                            text_parts[i] = externalized
                            self._log_event(task_id, "artifact_externalized", {
                                "turn": turn, "original_chars": len(tp),
                                "ref_chars": len(externalized),
                            })

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

                # ── R39: ContextLedger — 逐段追踪 tool_outputs ──
                if ledger and text_parts:
                    tool_tokens = sum(max(1, len(tp) // 4) for tp in text_parts)
                    ledger.record("tool_outputs", tool_tokens)
                    overflow_warnings = ledger.check_overflow()
                    if overflow_warnings:
                        self._log_event(task_id, "context_ledger_overflow", {
                            "turn": turn, "warnings": overflow_warnings,
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

                            # ── Phase Rollback: try recovery before aborting ──
                            decision = checkpointer.decide_rollback(
                                failed_stage="execute",
                                error=pattern,
                            )
                            if decision.should_rollback:
                                self._log_event(task_id, "rollback_attempt", {
                                    "target_stage": decision.target_stage,
                                    "strategy": decision.alternative_strategy,
                                    "reason": decision.reason,
                                    "turn": turn,
                                })
                                checkpointer.save(
                                    stage_name="execute",
                                    stage_index=turn,
                                    task_state={"turn": turn, "tool_calls": tool_count},
                                    success=False,
                                )
                                detector.reset()
                                log.info(f"PhaseRollback: task #{task_id} rolling back to {decision.target_stage} (strategy={decision.alternative_strategy})")
                                continue  # Retry the loop

                            result_text = f"[STUCK: {pattern}] Agent detected in loop after {turn} turns"
                            break

                # ── Doom Loop: 每 6 轮深度检查（补 StuckDetector 没覆盖的模式） ──
                if check_doom_loop and turn > 0 and turn % 6 == 0:
                    try:
                        events = self.db.get_agent_events(task_id, limit=30)
                        # ── Session Repair: validate/repair events before doom loop analysis ──
                        if SessionRepairer and events:
                            try:
                                repairer = SessionRepairer()
                                events, repair_report = repairer.repair(events)
                                if not repair_report.clean:
                                    self._log_event(task_id, "session_repair", {
                                        "turn": turn,
                                        "summary": repair_report.summary(),
                                        "events_removed": repair_report.events_removed,
                                        "events_repaired": repair_report.events_repaired,
                                    })
                            except Exception as e:
                                log.debug(f"SessionRepair: skipped ({e})")
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
                        intervention = supervisor.evaluate_worst(iteration=turn)
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

                # ── Auto-Freeze: idle spin detection (stolen from OpenAkita) ──
                freeze_breaker.record_turn(
                    tool_calls=len(tool_calls),
                    text_len=sum(len(tp) for tp in text_parts),
                )
                if freeze_breaker.should_freeze():
                    log.warning(f"FreezeBreaker: task #{task_id} frozen — {freeze_breaker.reason}")
                    self._log_event(task_id, "freeze_breaker", {
                        "reason": freeze_breaker.reason,
                        "turn": turn,
                        **freeze_breaker.get_status(),
                    })
                    result_text = f"[FROZEN: {freeze_breaker.reason}] Agent idle-spinning after {turn} turns"
                    break

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
                num_turns = message.num_turns or 0
                total_duration_ms = message.duration_ms or 0
                total_cost_usd = message.total_cost_usd or 0.0
                stop_reason_final = message.stop_reason or ""
                is_error_final = message.is_error or False
                result_data = (AgentResultEvent(
                    task_id=task_id, source=EventSource.AGENT,
                    status="failed" if message.is_error else "done",
                    num_turns=num_turns,
                    duration_ms=total_duration_ms,
                    cost_usd=total_cost_usd,
                ).to_dict() if AgentTurnEvent else {
                    "num_turns": num_turns,
                    "duration_ms": total_duration_ms,
                    "cost_usd": total_cost_usd,
                    "stop_reason": stop_reason_final,
                    "is_error": is_error_final,
                })
                self._log_event(task_id, "agent_result", result_data)

        # ── R39: ThinkingTracker — finish tracking ──
        if thinking_tracker:
            # Estimate actual thinking tokens from total cost (~$3/M input, ~$15/M output for Sonnet)
            # Rough heuristic: output_tokens ≈ total_chars / 4
            est_output_tokens = max(1, len(result_text) // 4) if result_text else 0
            thinking_tracker.finish(str(task_id), actual_tokens=est_output_tokens)

        # ── R39: ContextLedger — final summary log ──
        if ledger:
            self._log_event(task_id, "context_ledger_summary", ledger.summary)

        # ── R39: Trajectory — finish and build summary ──
        trajectory_summary = {}
        if traj_tracker:
            traj_tracker.finish()
            traj = traj_tracker.trajectory
            try:
                from src.governance.eval.trajectory import score_trajectory
                traj_score = score_trajectory(traj)
                trajectory_summary = {
                    **traj.to_dict(),
                    "score": traj_score.to_dict(),
                }
                self._log_event(task_id, "trajectory_score", traj_score.to_dict())
            except Exception as e:
                trajectory_summary = traj.to_dict()
                log.debug(f"Trajectory scoring failed: {e}")

        # ── Phase 3: Finalize ──
        response = self.finalize(
            task_id=task_id,
            result_text=result_text,
            turn=turn,
            num_turns=num_turns,
            total_cost_usd=total_cost_usd,
            total_duration_ms=total_duration_ms,
            stop_reason=stop_reason_final,
            is_error=is_error_final,
            tool_count=tool_count,
            prefill_ctx=prefill_ctx,
        )
        response.trajectory_summary = trajectory_summary
        return response
