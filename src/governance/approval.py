"""
ApprovalGateway — multi-channel human approval for authority escalation.

When an agent task needs APPROVE-level authority (commit, push, merge),
the gateway broadcasts an approval request to all available channels:
  - Claw (Windows Toast via WebSocket)
  - Telegram bot (inline keyboard)
  - WeChat bot

First response wins. Timeout = auto-deny.

## 5-Decision Model (R38 — stolen from Inspect AI)

Decisions:
  - approve   — proceed as-is
  - modify    — change tool arguments, then execute
  - reject    — deny this specific action, agent may try alternatives
  - terminate — abort the entire task (not just this action)
  - escalate  — pass to next approver in the chain (Claw → TG → human)

## Approval Policies (YAML-configurable)

Glob-match tool names to approver strategies:
  - "read_file", "grep", "glob" → auto approve
  - "bash*" → allowlist check
  - "desktop_*", "send_*" → escalate to human

Usage in executor:
    gateway = ApprovalGateway(broadcast_fn, channel_registry)
    decision = await gateway.request_approval(task_id, description, authority_level)
    if decision.action == "approve":
        ... proceed with elevated authority ...
    elif decision.action == "modify":
        ... apply decision.modifications, then proceed ...
"""
import asyncio
import fnmatch
import hashlib
import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

from src.governance.trust_ladder import TrustLadder

# Smart Approvals — command-level trust learning (Hermes)
try:
    from src.governance.smart_approvals import SmartApprovals
    _smart_approvals = SmartApprovals()
except ImportError:
    SmartApprovals = None
    _smart_approvals = None

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 300  # 5 minutes

# Module-level hash chain state — tracks last approval step hash
_last_approval_hash: str = ""


# ── 5-Decision Model (R38: Inspect AI) ──────────────────────


class ApprovalAction(str, Enum):
    """Five possible approval decisions (stolen from Inspect AI, R38)."""
    APPROVE = "approve"       # proceed as-is
    MODIFY = "modify"         # change tool arguments, then execute
    REJECT = "reject"         # deny this action, agent may try alternatives
    TERMINATE = "terminate"   # abort the entire task
    ESCALATE = "escalate"     # pass to next approver in chain


@dataclass
class ApprovalDecision:
    """Structured approval decision with optional modifications."""
    action: ApprovalAction
    source: str = ""                     # who decided: "claw" / "telegram" / "auto" / ...
    modifications: dict = field(default_factory=dict)  # for MODIFY: changed tool args
    reason: str = ""                     # optional explanation
    decided_at: str = ""

    @property
    def is_proceed(self) -> bool:
        """Should the tool call proceed (approve or modify)?"""
        return self.action in (ApprovalAction.APPROVE, ApprovalAction.MODIFY)

    def to_legacy(self) -> str:
        """Backward-compat: map to legacy 'approve'/'deny'/'timeout' strings."""
        if self.action in (ApprovalAction.APPROVE, ApprovalAction.MODIFY):
            return "approve"
        return "deny"


# ── Approval Policy (R38: Inspect AI glob matching) ────────


@dataclass
class ApprovalPolicy:
    """One rule in the approval policy chain.

    tools: glob pattern(s) to match tool names ("bash*", "desktop_*")
    decision: default decision for matched tools (None = ask human)
    allowed_args: optional allowlist for tool arguments (e.g. bash commands)
    """
    name: str
    tools: list[str]                           # glob patterns
    decision: Optional[ApprovalAction] = None  # None = human review
    allowed_args: dict = field(default_factory=dict)  # e.g. {"allowed_commands": ["ls","cat"]}
    priority: int = 100                        # lower = checked first

    def matches(self, tool_name: str) -> bool:
        return any(fnmatch.fnmatch(tool_name, pat) for pat in self.tools)


# Default policies (overridden by YAML config if present)
_DEFAULT_POLICIES: list[ApprovalPolicy] = [
    ApprovalPolicy(
        name="auto_safe",
        tools=["read_file", "grep", "glob", "ls", "cat"],
        decision=ApprovalAction.APPROVE,
        priority=10,
    ),
    ApprovalPolicy(
        name="bash_allowlist",
        tools=["bash*"],
        decision=None,  # needs review unless command is in allowlist
        allowed_args={"allowed_commands": [
            "ls", "cat", "grep", "git status", "git diff", "git log",
            "docker ps", "docker logs", "nvidia-smi", "python -c",
        ]},
        priority=20,
    ),
    ApprovalPolicy(
        name="escalate_dangerous",
        tools=["desktop_*", "send_*", "wake_*", "push_*"],
        decision=ApprovalAction.ESCALATE,
        priority=30,
    ),
]


def load_approval_policies(config_path: str | Path | None = None) -> list[ApprovalPolicy]:
    """Load approval policies from YAML config, falling back to defaults.

    Config format:
        approvers:
          - name: auto_safe
            tools: ["read_file", "grep", "glob"]
            decision: approve
          - name: bash_allowlist
            tools: ["bash*"]
            allowed_commands: [ls, cat, grep, "git status"]
          - name: escalate_dangerous
            tools: ["desktop_*", "send_*"]
            decision: escalate
    """
    if config_path is None:
        # Look in standard locations
        candidates = [
            Path("config/approval_policies.yaml"),
            Path("config/approval_policies.yml"),
        ]
        for c in candidates:
            if c.exists():
                config_path = c
                break

    if config_path is None:
        return list(_DEFAULT_POLICIES)

    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        policies = []
        for i, entry in enumerate(data.get("approvers", [])):
            tools = entry.get("tools", [])
            if isinstance(tools, str):
                tools = [tools]
            decision_str = entry.get("decision")
            decision = ApprovalAction(decision_str) if decision_str else None
            allowed_args = {}
            if "allowed_commands" in entry:
                allowed_args["allowed_commands"] = entry["allowed_commands"]

            policies.append(ApprovalPolicy(
                name=entry.get("name", f"policy_{i}"),
                tools=tools,
                decision=decision,
                allowed_args=allowed_args,
                priority=entry.get("priority", (i + 1) * 10),
            ))

        policies.sort(key=lambda p: p.priority)
        log.info(f"Loaded {len(policies)} approval policies from {config_path}")
        return policies

    except Exception as e:
        log.warning(f"Failed to load approval policies from {config_path}: {e}, using defaults")
        return list(_DEFAULT_POLICIES)


def evaluate_tool_against_policies(
    tool_name: str,
    tool_args: dict,
    policies: list[ApprovalPolicy],
) -> ApprovalDecision | None:
    """Check a tool call against policies. Returns decision or None (= ask human).

    Walks policies in priority order. First match wins.
    """
    for policy in sorted(policies, key=lambda p: p.priority):
        if not policy.matches(tool_name):
            continue

        # Policy has a fixed decision → return it
        if policy.decision is not None:
            return ApprovalDecision(
                action=policy.decision,
                source=f"policy:{policy.name}",
                reason=f"matched policy '{policy.name}' for tool '{tool_name}'",
                decided_at=datetime.now(timezone.utc).isoformat(),
            )

        # Policy requires checking args (e.g. bash allowlist)
        allowed_cmds = policy.allowed_args.get("allowed_commands", [])
        if allowed_cmds:
            cmd = tool_args.get("command", "")
            # Check if command starts with any allowed command
            for allowed in allowed_cmds:
                if cmd.strip().startswith(allowed):
                    return ApprovalDecision(
                        action=ApprovalAction.APPROVE,
                        source=f"policy:{policy.name}:allowlist",
                        reason=f"command '{cmd[:50]}' matches allowlist entry '{allowed}'",
                        decided_at=datetime.now(timezone.utc).isoformat(),
                    )
            # Command not in allowlist → needs human review
            return None

        # Policy matched but has no decision and no args check → ask human
        return None

    # No policy matched → default to human review
    return None


@dataclass
class ApprovalRequest:
    task_id: str
    description: str
    authority_level: int
    requested_at: str
    decision: Optional[str] = None  # "approve" / "deny" / "timeout" (legacy compat)
    decided_by: Optional[str] = None  # "claw" / "telegram" / "wechat" / "api"
    decided_at: Optional[str] = None
    step_hash: str = ""       # SHA-256(prev_step_hash + canonical request)
    prev_step_hash: str = ""  # Previous step's hash, empty = chain start
    # R38: structured decision (coexists with legacy fields for backward compat)
    structured_decision: Optional[ApprovalDecision] = None
    tool_name: str = ""       # tool being approved (for policy matching)
    tool_args: dict = field(default_factory=dict)


# ── R43: Interrupt-Resume (LangGraph steal) ─────────────────


@dataclass
class InterruptPoint:
    """A point where agent execution pauses for human input.

    Unlike ApprovalRequest (binary approve/deny), InterruptPoint supports
    arbitrary payload exchange: agent sends a value, human responds with a value.
    This enables mid-session interrupts at any node, not just pre-task approval.
    """
    interrupt_id: str           # hash of (task_id, node_id, counter)
    task_id: str
    node_id: str                # which agent/step triggered the interrupt
    counter: int                # nth interrupt in this node
    value: Any                  # payload sent to human
    timestamp: str
    resume_value: Any = None    # filled when human resumes


def _hash_approval_step(request: "ApprovalRequest", prev_hash: str = "") -> str:
    """Compute step hash for approval chain integrity."""
    entry = {
        "task_id": request.task_id,
        "description": request.description,
        "authority_level": request.authority_level,
        "requested_at": request.requested_at,
    }
    canonical = json.dumps(entry, sort_keys=True, ensure_ascii=False)
    payload = f"{prev_hash}:{canonical}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ApprovalGateway:
    """Publish approval requests, wait for first response from any channel.

    R38: Supports 5-decision model (approve/modify/reject/terminate/escalate)
    and YAML-configurable approval policies with glob tool matching.
    """

    def __init__(
        self,
        broadcast_fn: Optional[Callable] = None,
        channel_registry=None,
        policies: list[ApprovalPolicy] | None = None,
    ):
        self._broadcast = broadcast_fn  # server.js broadcast via WebSocket
        self._channels = channel_registry
        self._pending: dict[str, asyncio.Event] = {}
        self._requests: dict[str, ApprovalRequest] = {}
        self._lock = threading.Lock()
        self._yolo = False  # /yolo mode: auto-approve everything
        self._yolo_by: Optional[str] = None
        self._trust_ladder = TrustLadder()
        # R43: Interrupt-Resume state
        self._interrupt_counter: dict[tuple[str, str], int] = {}  # (task_id, node_id) -> count
        self._interrupts: dict[str, InterruptPoint] = {}           # interrupt_id -> InterruptPoint
        self._interrupt_events: dict[str, asyncio.Event] = {}      # interrupt_id -> resume signal
        # R38: approval policies (loaded from YAML or defaults)
        self._policies = policies if policies is not None else load_approval_policies()

    def set_yolo(self, enabled: bool, source: str = "unknown"):
        """Toggle YOLO mode — auto-approve all requests without asking."""
        self._yolo = enabled
        self._yolo_by = source if enabled else None
        action = "enabled" if enabled else "disabled"
        log.info(f"ApprovalGateway: YOLO mode {action} by {source}")

        # If enabling, approve all pending requests immediately
        if enabled:
            with self._lock:
                for tid, req in self._requests.items():
                    if req.decision is None:
                        req.decision = "approve"
                        req.decided_by = f"yolo:{source}"
                        req.decided_at = datetime.now(timezone.utc).isoformat()
                        evt = self._pending.get(tid)
                        if evt:
                            evt.set()
            log.info("ApprovalGateway: YOLO — all pending requests auto-approved")

    @property
    def is_yolo(self) -> bool:
        return self._yolo

    async def approve_tool_call(
        self,
        task_id: str,
        tool_name: str,
        tool_args: dict,
        description: str = "",
        timeout: int = DEFAULT_TIMEOUT,
    ) -> ApprovalDecision:
        """R38: Evaluate a tool call against policies, escalate to human if needed.

        Returns ApprovalDecision with one of 5 actions.
        This is the preferred entry point for tool-level approval.
        """
        # Check policies first (fast path, no human involvement)
        policy_decision = evaluate_tool_against_policies(tool_name, tool_args, self._policies)
        if policy_decision is not None:
            log.info(f"policy_approval: {tool_name} → {policy_decision.action.value} ({policy_decision.source})")
            return policy_decision

        # No policy match → fall through to human approval
        if not description:
            args_preview = json.dumps(tool_args, ensure_ascii=False, default=str)[:100]
            description = f"Tool: {tool_name}({args_preview})"

        legacy_result = await self.request_approval(
            task_id=task_id,
            description=description,
            authority_level=4,
            timeout=timeout,
        )

        # Check if structured decision was captured
        with self._lock:
            req = self._requests.get(task_id)
        if req and req.structured_decision:
            return req.structured_decision

        # Map legacy result to ApprovalDecision
        action_map = {
            "approve": ApprovalAction.APPROVE,
            "deny": ApprovalAction.REJECT,
            "timeout": ApprovalAction.REJECT,
        }
        return ApprovalDecision(
            action=action_map.get(legacy_result, ApprovalAction.REJECT),
            source=req.decided_by if req else "unknown",
            reason=f"human decision: {legacy_result}",
            decided_at=datetime.now(timezone.utc).isoformat(),
        )

    async def request_approval(
        self,
        task_id: str,
        description: str,
        authority_level: int = 4,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> str:
        """Request human approval. Returns 'approve', 'deny', or 'timeout'.

        Legacy interface — prefer approve_tool_call() for R38 5-decision model.
        """

        # YOLO mode: instant approve, no notification
        if self._yolo:
            log.info(f"YOLO: auto-approved {task_id}")
            return "approve"

        # Trust Ladder: auto-approve previously trusted operations
        operation_key = f"auth_level_{authority_level}"
        if self._trust_ladder.auto_approve_if_trusted(operation_key, description):
            log.info(f"trust_ladder: auto-approved {task_id} (previously trusted)")
            return "approve"

        # Smart Approvals: command-level trust learning (Hermes)
        if _smart_approvals and _smart_approvals.should_auto_approve(description):
            log.info(f"smart_approvals: auto-approved {task_id} (learned trust)")
            return "approve"

        global _last_approval_hash
        prev_hash = _last_approval_hash
        req = ApprovalRequest(
            task_id=task_id,
            description=description,
            authority_level=authority_level,
            requested_at=datetime.now(timezone.utc).isoformat(),
            prev_step_hash=prev_hash,
        )
        req.step_hash = _hash_approval_step(req, prev_hash)

        event = asyncio.Event()
        with self._lock:
            self._pending[task_id] = event
            self._requests[task_id] = req

        # Broadcast to all channels
        self._notify_all(req)

        # Wait for response (any channel)
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            req.decision = "timeout"
            req.decided_by = "system"
            req.decided_at = datetime.now(timezone.utc).isoformat()
            log.warning(f"approval timeout for task {task_id} after {timeout}s")
        finally:
            with self._lock:
                self._pending.pop(task_id, None)

        # Record trust on approval
        if req.decision == "approve":
            operation_key = f"auth_level_{authority_level}"
            self._trust_ladder.record_approval(operation_key, description)

        decision = req.decision or "timeout"
        _last_approval_hash = req.step_hash
        log.info(f"approval for {task_id}: {decision} (by {req.decided_by})")
        return decision

    def submit_decision(self, task_id: str, decision: str, source: str = "unknown",
                        modifications: dict | None = None, reason: str = ""):
        """Called when a channel receives an approval/denial response.

        R38: decision can be any of the 5 ApprovalAction values.
        For backward compat, "deny" maps to "reject".
        modifications: for "modify" decisions, the changed tool args.
        """
        with self._lock:
            req = self._requests.get(task_id)
            event = self._pending.get(task_id)

        if not req:
            log.warning(f"approval decision for unknown task {task_id}")
            return

        if req.decision is not None:
            log.info(f"approval for {task_id} already decided, ignoring {source}")
            return

        # R38: normalize decision string and build structured decision
        decision_normalized = decision.lower().strip()
        if decision_normalized == "deny":
            decision_normalized = "reject"  # legacy compat

        # Map to ApprovalAction (fallback to reject for unknown values)
        try:
            action = ApprovalAction(decision_normalized)
        except ValueError:
            log.warning(f"unknown approval action '{decision}', treating as reject")
            action = ApprovalAction.REJECT

        req.structured_decision = ApprovalDecision(
            action=action,
            source=source,
            modifications=modifications or {},
            reason=reason,
            decided_at=datetime.now(timezone.utc).isoformat(),
        )

        # Legacy compat fields
        req.decision = req.structured_decision.to_legacy()
        req.decided_by = source
        req.decided_at = req.structured_decision.decided_at

        if event:
            event.set()

        # Notify all channels of the outcome
        self._notify_outcome(req)

        # Smart Approvals: record decision for learning (Hermes)
        if _smart_approvals and req.description:
            try:
                _smart_approvals.record(req.description, req.decision)
            except Exception:
                pass

        # Wake session callback — update session status on approve/deny
        try:
            from src.channels.wake import on_task_approved, on_task_denied
            if req.decision == "approve":
                on_task_approved(task_id)
            elif req.decision == "deny":
                on_task_denied(task_id)
        except Exception:
            pass

    def get_pending(self) -> list[ApprovalRequest]:
        """Return all pending approval requests."""
        with self._lock:
            return [r for r in self._requests.values() if r.decision is None]

    # ── R43: Interrupt-Resume (LangGraph steal) ──────────────

    def request_interrupt(
        self, task_id: str, node_id: str, value: Any
    ) -> InterruptPoint:
        """Create an interrupt point for mid-session human input.

        Unlike request_approval (pre-task gate), this can be called at any
        point during agent execution to pause and request arbitrary input.

        Returns InterruptPoint with a unique interrupt_id for resume matching.
        """
        key = (task_id, node_id)
        with self._lock:
            counter = self._interrupt_counter.get(key, 0) + 1
            self._interrupt_counter[key] = counter

            # Generate deterministic interrupt_id
            raw = f"{task_id}:{node_id}:{counter}"
            interrupt_id = hashlib.sha256(raw.encode()).hexdigest()[:16]

            point = InterruptPoint(
                interrupt_id=interrupt_id,
                task_id=task_id,
                node_id=node_id,
                counter=counter,
                value=value,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            self._interrupts[interrupt_id] = point
            self._interrupt_events[interrupt_id] = asyncio.Event()

        log.info(
            f"ApprovalGateway: interrupt requested — id={interrupt_id}, "
            f"task={task_id}, node={node_id}, counter={counter}"
        )

        # Broadcast interrupt to channels
        self._notify_interrupt(point)
        return point

    def resume_interrupt(self, interrupt_id: str, value: Any) -> None:
        """Resume a previously interrupted execution with a human-provided value.

        Args:
            interrupt_id: The interrupt_id from InterruptPoint
            value: The human's response value
        """
        with self._lock:
            point = self._interrupts.get(interrupt_id)
            if not point:
                log.warning(f"ApprovalGateway: unknown interrupt_id={interrupt_id}")
                return
            point.resume_value = value
            event = self._interrupt_events.get(interrupt_id)

        if event:
            event.set()
            log.info(f"ApprovalGateway: interrupt {interrupt_id} resumed")

    async def await_interrupt_resume(
        self, interrupt_id: str, timeout: float = DEFAULT_TIMEOUT
    ) -> Any:
        """Wait for an interrupt to be resumed. Returns the resume value.

        Called by AgentSessionRunner.interrupt() to block until human responds.
        """
        event = self._interrupt_events.get(interrupt_id)
        if not event:
            raise ValueError(f"No interrupt event for {interrupt_id}")

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            log.warning(f"ApprovalGateway: interrupt {interrupt_id} timed out")
            return None

        point = self._interrupts.get(interrupt_id)
        return point.resume_value if point else None

    def get_pending_interrupts(self, task_id: str | None = None) -> list[InterruptPoint]:
        """Return all pending (un-resumed) interrupts, optionally filtered by task."""
        with self._lock:
            points = [
                p for p in self._interrupts.values()
                if p.resume_value is None
            ]
            if task_id:
                points = [p for p in points if p.task_id == task_id]
            return points

    def _notify_interrupt(self, point: InterruptPoint):
        """Push interrupt notification to all channels."""
        msg = (
            f"🔴 Interrupt [{point.interrupt_id[:8]}]\n"
            f"Task: {point.task_id} | Node: {point.node_id}\n"
            f"Value: {str(point.value)[:200]}\n"
            f"Reply with interrupt_id to resume."
        )
        if self._broadcast:
            try:
                self._broadcast({
                    "type": "interrupt",
                    "interrupt_id": point.interrupt_id,
                    "task_id": point.task_id,
                    "node_id": point.node_id,
                    "value": point.value,
                })
            except Exception as e:
                log.debug(f"Interrupt broadcast failed: {e}")

        if self._channels:
            try:
                self._channels.notify_all(msg)
            except Exception as e:
                log.debug(f"Interrupt channel notify failed: {e}")

    def _notify_all(self, req: ApprovalRequest):
        """Push approval request to all channels.

        R38: notifications now include 5 decision options.
        """
        risk = "LOW" if req.authority_level <= 3 else (
            "MEDIUM" if req.authority_level <= 6 else "HIGH"
        )

        # R38: available actions for this request
        actions = ["approve", "modify", "reject", "terminate", "escalate"]

        # 1. WebSocket broadcast (Claw picks this up)
        if self._broadcast:
            try:
                self._broadcast({
                    "type": "approval_request",
                    "task_id": req.task_id,
                    "description": req.description,
                    "authority_level": req.authority_level,
                    "risk": risk,
                    "tool_name": req.tool_name,
                    "actions": actions,
                })
            except Exception as e:
                log.debug(f"ws broadcast failed: {e}")

        # 2. Telegram / WeChat via Channel registry
        if self._channels:
            try:
                from src.channels.base import ChannelMessage
                risk_label = {"LOW": "低风险", "MEDIUM": "中风险", "HIGH": "高风险"}.get(risk, risk)
                tool_line = f"\n工具: <code>{req.tool_name}</code>" if req.tool_name else ""
                msg = ChannelMessage(
                    text=(
                        f"<b>需要审批</b> ({risk_label})\n\n"
                        f"{req.description}{tool_line}\n\n"
                        f"权限等级: {req.authority_level}/4\n"
                        f"Task: <code>{req.task_id}</code>\n\n"
                        f"操作: ✅approve | ✏️modify | ❌reject | 🛑terminate | ⬆️escalate"
                    ),
                    event_type="approval.request",
                    priority="CRITICAL",
                )
                self._channels.broadcast(msg)
            except Exception as e:
                log.debug(f"channel broadcast failed: {e}")

    def _notify_outcome(self, req: ApprovalRequest):
        """Notify channels of the decision."""
        if self._channels:
            try:
                from src.channels.base import ChannelMessage
                # R38: richer outcome labels
                _labels = {
                    "approve": "✅ Approved",
                    "deny": "❌ Rejected",
                    "reject": "❌ Rejected",
                    "modify": "✏️ Modified",
                    "terminate": "🛑 Terminated",
                    "escalate": "⬆️ Escalated",
                    "timeout": "⏰ Timeout",
                }
                sd = req.structured_decision
                action_str = sd.action.value if sd else (req.decision or "unknown")
                label = _labels.get(action_str, action_str)
                extra = ""
                if sd and sd.modifications:
                    extra = f"\n修改: {json.dumps(sd.modifications, ensure_ascii=False, default=str)[:200]}"
                if sd and sd.reason:
                    extra += f"\n原因: {sd.reason[:200]}"
                msg = ChannelMessage(
                    text=f"*{label}* — {req.description}\n(by {req.decided_by}){extra}",
                    event_type="approval.result",
                    priority="HIGH",
                )
                self._channels.broadcast(msg)
            except Exception:
                pass


# ── R47: Workflow Approval Gate (Archon steal) ──────────────


@dataclass
class WorkflowGateResult:
    """Result of a workflow-level approval gate.

    Unlike tool-level approval (single tool call), workflow gates
    pause an entire multi-step workflow until human decision.
    On rejection, the rejection_reason is fed back so the agent
    can revise its approach.
    """
    approved: bool
    rejection_reason: str = ""        # human's feedback on why rejected
    attempt: int = 1                  # which attempt this is (1-based)
    max_attempts: int = 3             # fail after this many rejections
    exhausted: bool = False           # True if max_attempts reached


async def workflow_approval_gate(
    gateway: "ApprovalGateway",
    task_id: str,
    gate_message: str,
    on_reject_prompt: str = "",
    max_attempts: int = 3,
    timeout: int = DEFAULT_TIMEOUT,
) -> WorkflowGateResult:
    """Pause a workflow for human approval with rejection loop.

    Archon-inspired pattern (R47):
    1. Send gate_message to user, pause and wait for approve/reject
    2. If approved → return approved=True
    3. If rejected with reason → return with rejection_reason
       Caller should run on_reject_prompt (with $REJECTION_REASON substituted),
       then call this gate again with attempt incremented
    4. If max_attempts reached → return exhausted=True

    Usage in executor:
        for attempt in range(1, max_attempts + 1):
            result = await workflow_approval_gate(
                gateway, task_id, "Review the implementation?",
                on_reject_prompt="User rejected because: $REJECTION_REASON. Revise.",
                max_attempts=3,
            )
            if result.approved:
                break
            if result.exhausted:
                # give up
                break
            # Handle rejection: run on_reject_prompt with reason
            revised_prompt = on_reject_prompt.replace("$REJECTION_REASON", result.rejection_reason)
            # ... execute revised_prompt ...
    """
    decision = await gateway.request_approval(
        task_id=task_id,
        description=gate_message,
        authority_level=4,
        timeout=timeout,
    )

    # Check for structured decision with reason
    with gateway._lock:
        req = gateway._requests.get(task_id)

    reason = ""
    if req and req.structured_decision:
        reason = req.structured_decision.reason

    if decision == "approve":
        return WorkflowGateResult(approved=True, attempt=1, max_attempts=max_attempts)

    # Rejected or timed out
    return WorkflowGateResult(
        approved=False,
        rejection_reason=reason or "no reason provided",
        attempt=1,  # caller tracks actual attempt number
        max_attempts=max_attempts,
        exhausted=False,  # caller checks attempt >= max_attempts
    )


# ── Singleton ──

_gateway: Optional[ApprovalGateway] = None


def get_approval_gateway() -> ApprovalGateway:
    global _gateway
    if _gateway is None:
        _gateway = ApprovalGateway()
    return _gateway


def init_approval_gateway(broadcast_fn=None, channel_registry=None,
                          policies: list[ApprovalPolicy] | None = None) -> ApprovalGateway:
    global _gateway
    _gateway = ApprovalGateway(broadcast_fn, channel_registry, policies=policies)
    return _gateway
