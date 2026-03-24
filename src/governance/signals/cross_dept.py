# src/governance/signals/cross_dept.py
"""A→B Signal Protocol + Sibling Rule — cross-department structured signals.

When one department discovers something that another department needs to act on,
it sends a typed Signal through this protocol instead of creating ad-hoc tasks.

Example flows:
  security → engineering:  "CVE found in dependency X, patch needed"
  quality  → engineering:  "Pattern Y keeps failing review, add to guidelines"
  engineering → quality:   "Refactored module Z, re-verify all tests"
  operations → engineering: "Collector X failing, needs code fix"

Signal lifecycle:
  CREATED → ACKNOWLEDGED → ACTED → RESOLVED
                        └→ REJECTED (with reason)

Sibling Rule:
  Signals between departments at the same hierarchy level (e.g., engineering ↔ quality)
  require no escalation. Signals TO a higher-authority department require governor approval.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

log = logging.getLogger(__name__)


class SignalType(Enum):
    """Typed signal categories for structured cross-department communication."""
    VULNERABILITY = "vulnerability"         # security → engineering
    PATTERN_FAILURE = "pattern_failure"     # quality → engineering
    RETEST_NEEDED = "retest_needed"         # engineering → quality
    COLLECTOR_BROKEN = "collector_broken"   # operations → engineering
    GUIDELINE_UPDATE = "guideline_update"   # quality → all
    PERFORMANCE_ALERT = "performance_alert" # operations → engineering
    DEPENDENCY_RISK = "dependency_risk"     # security → engineering
    ESCALATION = "escalation"              # any → governor (human)


class SignalStatus(Enum):
    CREATED = "created"
    ACKNOWLEDGED = "acknowledged"
    ACTED = "acted"
    RESOLVED = "resolved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class SignalPriority(Enum):
    CRITICAL = "critical"   # Act immediately
    HIGH = "high"           # Act within current cycle
    NORMAL = "normal"       # Act when convenient
    LOW = "low"             # FYI, no action required


@dataclass
class Signal:
    """A cross-department signal."""
    signal_id: str = ""
    signal_type: SignalType = SignalType.ESCALATION
    priority: SignalPriority = SignalPriority.NORMAL
    source_dept: str = ""          # originating department
    target_dept: str = ""          # target department
    title: str = ""
    description: str = ""
    evidence: str = ""             # file paths, error logs, etc.
    suggested_action: str = ""     # what the sender thinks should be done
    related_task_id: int = 0       # task that triggered this signal
    status: SignalStatus = SignalStatus.CREATED
    created_at: str = ""
    acknowledged_at: str = ""
    resolved_at: str = ""
    resolution_note: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.signal_id:
            import hashlib
            raw = f"{self.source_dept}:{self.target_dept}:{self.created_at}:{self.title[:50]}"
            self.signal_id = hashlib.md5(raw.encode()).hexdigest()[:12]

    def to_dict(self) -> dict:
        return {
            "signal_id": self.signal_id,
            "type": self.signal_type.value,
            "priority": self.priority.value,
            "source": self.source_dept,
            "target": self.target_dept,
            "title": self.title,
            "description": self.description,
            "evidence": self.evidence,
            "suggested_action": self.suggested_action,
            "related_task_id": self.related_task_id,
            "status": self.status.value,
            "created_at": self.created_at,
        }


# ── Authority Hierarchy for Sibling Rule ──

DEPARTMENT_TIER: dict[str, int] = {
    "engineering": 2,
    "quality": 2,
    "security": 2,
    "operations": 2,
    "protocol": 1,      # higher authority (礼部 sets standards)
    "personnel": 1,     # higher authority (吏部 manages performance)
}


def check_sibling_rule(source: str, target: str) -> tuple[bool, str]:
    """Check if a signal can be sent directly or needs governor approval.

    Sibling Rule:
    - Same tier → direct signal (no approval needed)
    - Lower tier → higher tier → needs governor approval
    - Higher tier → lower tier → direct signal (directive)

    Returns (can_send_direct, reason).
    """
    source_tier = DEPARTMENT_TIER.get(source, 2)
    target_tier = DEPARTMENT_TIER.get(target, 2)

    if source_tier == target_tier:
        return True, f"Sibling departments (tier {source_tier})"
    if source_tier < target_tier:
        return True, f"Directive from higher tier ({source_tier} → {target_tier})"
    return False, f"Signal to higher tier requires governor approval ({source_tier} → {target_tier})"


# ── Signal Router ──

# Predefined routing rules: signal_type → default target department
SIGNAL_ROUTES: dict[SignalType, str] = {
    SignalType.VULNERABILITY: "engineering",
    SignalType.PATTERN_FAILURE: "engineering",
    SignalType.RETEST_NEEDED: "quality",
    SignalType.COLLECTOR_BROKEN: "engineering",
    SignalType.GUIDELINE_UPDATE: "quality",  # quality owns guidelines
    SignalType.PERFORMANCE_ALERT: "engineering",
    SignalType.DEPENDENCY_RISK: "engineering",
    SignalType.ESCALATION: "",  # governor handles
}


class SignalBus:
    """Cross-department signal bus.

    Manages signal lifecycle: create → route → acknowledge → act → resolve.
    Persists signals to a JSONL file for audit trail.
    """

    def __init__(self, persist_path: str = ""):
        self._signals: dict[str, Signal] = {}
        self._handlers: dict[str, list] = {}  # target_dept → [handler_fn]
        if persist_path:
            self._persist_path = Path(persist_path)
        else:
            root = Path(__file__).resolve().parent
            while root != root.parent and not ((root / "departments").is_dir() and (root / "src").is_dir()):
                root = root.parent
            self._persist_path = root / "tmp" / "signals.jsonl"

    def send(self, signal: Signal) -> tuple[bool, str]:
        """Send a cross-department signal.

        Checks sibling rule, routes to target, persists, and notifies handlers.
        Returns (sent, reason).
        """
        # Auto-route if no target specified
        if not signal.target_dept:
            signal.target_dept = SIGNAL_ROUTES.get(signal.signal_type, "")
            if not signal.target_dept:
                return False, f"No route for signal type {signal.signal_type.value}"

        # Check sibling rule
        can_send, reason = check_sibling_rule(signal.source_dept, signal.target_dept)
        if not can_send:
            log.warning(f"Signal blocked by sibling rule: {signal.source_dept} → {signal.target_dept}: {reason}")
            # Route to governor instead
            signal.target_dept = ""
            signal.signal_type = SignalType.ESCALATION
            signal.description = f"[ESCALATED] {signal.description}\nOriginal: {signal.source_dept} → blocked by sibling rule"

        self._signals[signal.signal_id] = signal
        self._persist(signal)

        # Notify handlers
        handlers = self._handlers.get(signal.target_dept, [])
        for handler in handlers:
            try:
                handler(signal)
            except Exception as e:
                log.error(f"Signal handler error: {e}")

        log.info(f"Signal sent: [{signal.signal_type.value}] {signal.source_dept} → {signal.target_dept}: {signal.title}")
        return True, f"Signal {signal.signal_id} sent to {signal.target_dept}"

    def acknowledge(self, signal_id: str) -> bool:
        """Mark a signal as acknowledged by the target department."""
        signal = self._signals.get(signal_id)
        if not signal:
            return False
        signal.status = SignalStatus.ACKNOWLEDGED
        signal.acknowledged_at = datetime.now(timezone.utc).isoformat()
        self._persist(signal)
        return True

    def resolve(self, signal_id: str, note: str = "") -> bool:
        """Mark a signal as resolved."""
        signal = self._signals.get(signal_id)
        if not signal:
            return False
        signal.status = SignalStatus.RESOLVED
        signal.resolved_at = datetime.now(timezone.utc).isoformat()
        signal.resolution_note = note
        self._persist(signal)
        log.info(f"Signal resolved: {signal_id} — {note[:100]}")
        return True

    def reject(self, signal_id: str, reason: str = "") -> bool:
        """Reject a signal (target dept declines to act)."""
        signal = self._signals.get(signal_id)
        if not signal:
            return False
        signal.status = SignalStatus.REJECTED
        signal.resolved_at = datetime.now(timezone.utc).isoformat()
        signal.resolution_note = f"REJECTED: {reason}"
        self._persist(signal)
        log.info(f"Signal rejected: {signal_id} — {reason[:100]}")
        return True

    def register_handler(self, department: str, handler) -> None:
        """Register a handler function for signals targeting a department."""
        if department not in self._handlers:
            self._handlers[department] = []
        self._handlers[department].append(handler)

    def get_pending(self, department: str = "") -> list[Signal]:
        """Get unresolved signals, optionally filtered by target department."""
        pending = []
        for s in self._signals.values():
            if s.status in (SignalStatus.CREATED, SignalStatus.ACKNOWLEDGED):
                if not department or s.target_dept == department:
                    pending.append(s)
        return sorted(pending, key=lambda s: (
            0 if s.priority == SignalPriority.CRITICAL else
            1 if s.priority == SignalPriority.HIGH else
            2 if s.priority == SignalPriority.NORMAL else 3
        ))

    def get_signal(self, signal_id: str) -> Signal | None:
        return self._signals.get(signal_id)

    def _persist(self, signal: Signal) -> None:
        """Append signal state to JSONL audit log."""
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._persist_path, "a", encoding="utf-8") as f:
                entry = signal.to_dict()
                entry["_persisted_at"] = datetime.now(timezone.utc).isoformat()
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            log.debug(f"Signal persist failed: {e}")

    def format_dashboard(self, department: str = "") -> str:
        """Format signal status for dashboard display."""
        pending = self.get_pending(department)
        if not pending:
            return f"📡 No pending signals{' for ' + department if department else ''}"

        lines = [f"📡 Pending signals{' for ' + department if department else ''}: {len(pending)}"]
        for s in pending[:10]:
            icon = "🔴" if s.priority == SignalPriority.CRITICAL else "🟡" if s.priority == SignalPriority.HIGH else "⚪"
            lines.append(f"  {icon} [{s.signal_type.value}] {s.source_dept}→{s.target_dept}: {s.title[:60]}")
        return "\n".join(lines)


# ── Convenience Factory Functions ──

def signal_vulnerability(source_dept: str, title: str, description: str,
                         evidence: str = "", task_id: int = 0) -> Signal:
    """Create a vulnerability signal (typically security → engineering)."""
    return Signal(
        signal_type=SignalType.VULNERABILITY,
        priority=SignalPriority.HIGH,
        source_dept=source_dept,
        title=title,
        description=description,
        evidence=evidence,
        suggested_action="Review and patch the vulnerability",
        related_task_id=task_id,
    )


def signal_pattern_failure(source_dept: str, pattern: str, occurrences: int,
                            suggestion: str = "", task_id: int = 0) -> Signal:
    """Create a pattern failure signal (typically quality → engineering)."""
    return Signal(
        signal_type=SignalType.PATTERN_FAILURE,
        priority=SignalPriority.NORMAL,
        source_dept=source_dept,
        title=f"Recurring pattern failure: {pattern}",
        description=f"Pattern '{pattern}' has failed review {occurrences} times",
        suggested_action=suggestion or f"Add '{pattern}' to department guidelines",
        related_task_id=task_id,
    )


def signal_retest(source_dept: str, module: str, reason: str, task_id: int = 0) -> Signal:
    """Create a retest request (typically engineering → quality)."""
    return Signal(
        signal_type=SignalType.RETEST_NEEDED,
        priority=SignalPriority.NORMAL,
        source_dept=source_dept,
        title=f"Retest needed: {module}",
        description=reason,
        related_task_id=task_id,
    )
