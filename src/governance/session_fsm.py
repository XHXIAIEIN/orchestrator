"""R47 (Archon): Session State Machine.

5 states, 5 transition triggers, parent_session_id chain for audit trail.
Plan-to-execute creates a new child session automatically.

States: idle → planning → executing → reviewing → completed/failed
Transitions: start, plan_ready, execute, review, complete/fail
"""
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

log = logging.getLogger(__name__)


class SessionState(Enum):
    IDLE = "idle"
    PLANNING = "planning"
    EXECUTING = "executing"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    FAILED = "failed"


# Valid transitions: (from_state, trigger) → to_state
_TRANSITIONS = {
    (SessionState.IDLE, "start"): SessionState.PLANNING,
    (SessionState.PLANNING, "plan_ready"): SessionState.EXECUTING,
    (SessionState.PLANNING, "fail"): SessionState.FAILED,
    (SessionState.EXECUTING, "review"): SessionState.REVIEWING,
    (SessionState.EXECUTING, "complete"): SessionState.COMPLETED,
    (SessionState.EXECUTING, "fail"): SessionState.FAILED,
    (SessionState.REVIEWING, "complete"): SessionState.COMPLETED,
    (SessionState.REVIEWING, "fail"): SessionState.FAILED,
    (SessionState.REVIEWING, "execute"): SessionState.EXECUTING,  # review → re-execute
}


@dataclass
class Session:
    """A tracked session with state machine transitions."""
    session_id: str
    state: SessionState = SessionState.IDLE
    parent_session_id: Optional[str] = None
    created_at: float = field(default_factory=time.monotonic)
    transitions: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def transition(self, trigger: str) -> bool:
        """Apply a trigger. Returns True if transition was valid."""
        key = (self.state, trigger)
        new_state = _TRANSITIONS.get(key)
        if new_state is None:
            log.warning("session_fsm: invalid transition %s + '%s' for session %s",
                        self.state.value, trigger, self.session_id)
            return False
        old_state = self.state
        self.state = new_state
        self.transitions.append({
            "from": old_state.value,
            "trigger": trigger,
            "to": new_state.value,
            "at": time.monotonic(),
        })
        log.info("session_fsm: %s → %s (trigger: %s) for %s",
                 old_state.value, new_state.value, trigger, self.session_id)
        return True

    @property
    def is_terminal(self) -> bool:
        return self.state in (SessionState.COMPLETED, SessionState.FAILED)

    def audit_trail(self) -> list[dict]:
        return self.transitions


class SessionFSMRegistry:
    """Registry of session state machines. Provides audit chain via parent_session_id."""

    def __init__(self):
        self._sessions: dict[str, Session] = {}
        self._counter = 0

    def create(self, parent_id: str | None = None, **metadata) -> Session:
        self._counter += 1
        session_id = f"session-{self._counter}-{int(time.monotonic())}"
        session = Session(
            session_id=session_id,
            parent_session_id=parent_id,
            metadata=metadata,
        )
        self._sessions[session_id] = session
        log.info("session_fsm: created %s (parent=%s)", session_id, parent_id or "none")
        return session

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def transition(self, session_id: str, trigger: str) -> bool:
        session = self._sessions.get(session_id)
        if not session:
            log.warning("session_fsm: unknown session %s", session_id)
            return False
        return session.transition(trigger)

    def create_child_on_plan_ready(self, parent_id: str) -> Session | None:
        """Auto-create execution session when plan is ready (plan→execute pattern)."""
        parent = self._sessions.get(parent_id)
        if not parent or parent.state != SessionState.PLANNING:
            return None
        parent.transition("plan_ready")
        return self.create(parent_id=parent_id, origin="plan_to_execute")

    def get_chain(self, session_id: str) -> list[Session]:
        """Get the full parent→child chain for audit."""
        chain = []
        current = self._sessions.get(session_id)
        while current:
            chain.append(current)
            current = self._sessions.get(current.parent_session_id) if current.parent_session_id else None
        return list(reversed(chain))

    def get_active(self) -> list[Session]:
        return [s for s in self._sessions.values() if not s.is_terminal]

    def cleanup_terminal(self, max_age_s: float = 3600) -> int:
        """Remove completed/failed sessions older than max_age_s."""
        now = time.monotonic()
        to_remove = [
            sid for sid, s in self._sessions.items()
            if s.is_terminal and (now - s.created_at) > max_age_s
        ]
        for sid in to_remove:
            del self._sessions[sid]
        return len(to_remove)


# ── Singleton ──
_instance: SessionFSMRegistry | None = None


def get_session_registry() -> SessionFSMRegistry:
    global _instance
    if _instance is None:
        _instance = SessionFSMRegistry()
    return _instance
