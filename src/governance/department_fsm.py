"""DepartmentFSM — explicit department transition rules.

Stolen from OpenAI Swarm's implicit agent routing: instead of hardcoded
department names in dispatcher/review code, define valid transitions in
a data structure. Supports wildcard (*) for transitions from any department.
"""
import logging

log = logging.getLogger(__name__)

# (from_dept, trigger) → to_dept
# Empty string = terminal state (no further handoff)
TRANSITIONS: dict[tuple[str, str], str] = {
    # Standard pipeline: engineering → quality review
    ("engineering", "quality_review"): "quality",
    ("operations", "quality_review"): "quality",
    ("security", "quality_review"): "quality",

    # Quality outcomes
    ("quality", "rework"): "engineering",
    ("quality", "approved"): "",           # terminal

    # Fact-Expression Split
    ("*", "fact_layer"): "quality",
    ("quality", "expression_layer"): "protocol",
    ("protocol", "approved"): "",          # terminal

    # Escalation
    ("*", "escalation"): "",               # governor handles

    # Self-loops (department retries itself)
    ("*", "retry"): "__self__",
}


class DepartmentFSM:
    """Manages valid department transitions."""

    def __init__(self, transitions: dict | None = None, strict: bool = False):
        self._transitions = transitions or TRANSITIONS
        self._strict = strict

    def get_next_department(self, from_dept: str, trigger: str) -> str | None:
        """Return next department for a transition, or None if invalid.

        Checks exact match first, then wildcard (*).
        Returns "__self__" sentinel if the department should retry itself.
        """
        # Exact match
        key = (from_dept, trigger)
        if key in self._transitions:
            result = self._transitions[key]
            return from_dept if result == "__self__" else result

        # Wildcard match
        wildcard_key = ("*", trigger)
        if wildcard_key in self._transitions:
            result = self._transitions[wildcard_key]
            return from_dept if result == "__self__" else result

        if self._strict:
            log.warning(f"DepartmentFSM: invalid transition ({from_dept}, {trigger})")
            return None

        # Non-strict: allow unknown transitions with warning
        log.debug(f"DepartmentFSM: unregistered transition ({from_dept}, {trigger})")
        return None

    def is_valid_transition(self, from_dept: str, to_dept: str, trigger: str) -> bool:
        """Check if a specific transition is valid."""
        expected = self.get_next_department(from_dept, trigger)
        return expected == to_dept

    def is_terminal(self, from_dept: str, trigger: str) -> bool:
        """Check if transition leads to terminal state (empty string)."""
        result = self.get_next_department(from_dept, trigger)
        return result == ""

    def get_valid_triggers(self, from_dept: str) -> list[str]:
        """List all valid triggers from a department."""
        triggers = []
        for (dept, trigger), _ in self._transitions.items():
            if dept == from_dept or dept == "*":
                triggers.append(trigger)
        return list(set(triggers))

    def can_review(self, from_dept: str) -> bool:
        """Check if a department's output should go through quality review."""
        return self.get_next_department(from_dept, "quality_review") == "quality"


# Singleton instance
fsm = DepartmentFSM()
