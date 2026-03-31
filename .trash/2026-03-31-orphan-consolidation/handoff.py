"""Handoff Filter — stolen from OpenAI Agents SDK.

When a task is handed from one department to another (e.g. engineering → quality),
the handoff filter:
1. Trims context irrelevant to the receiving department
2. Compresses conversation history into a summary (nest_handoff_history)
3. Fires on_handoff callbacks for audit logging
4. Checks is_enabled before allowing handoff

Usage:
    handoff = HandoffFilter()
    handoff.on_handoff(my_audit_callback)
    filtered_spec = handoff.filter(
        spec=task_spec,
        from_dept="engineering",
        to_dept="quality",
    )
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

log = logging.getLogger(__name__)


@dataclass
class HandoffRecord:
    """Record of a department handoff."""
    from_dept: str
    to_dept: str
    task_id: str
    timestamp: float = field(default_factory=time.time)
    context_before: int = 0  # chars before filtering
    context_after: int = 0   # chars after filtering
    compression_ratio: float = 0.0
    reason: str = ""


# Context fields that are department-specific and should be trimmed
_DEPT_SPECIFIC_FIELDS = {
    "engineering": {"code_diff", "file_list", "git_log", "implementation_notes"},
    "operations": {"docker_logs", "container_status", "deploy_config"},
    "quality": {"test_results", "coverage_report", "review_comments"},
    "security": {"vulnerability_scan", "taint_report", "secret_findings"},
    "personnel": {"performance_data", "skill_assessment"},
    "protocol": {"debt_inventory", "audit_trail"},
}

# Fields that should always be passed through
_UNIVERSAL_FIELDS = {
    "department", "intent", "cognitive_mode", "priority",
    "problem", "expected", "summary", "source", "action",
    "observation", "importance",
}


def _flatten_all_dept_fields() -> set:
    """All department-specific fields across all departments."""
    all_fields: set[str] = set()
    for fields in _DEPT_SPECIFIC_FIELDS.values():
        all_fields.update(fields)
    return all_fields


class HandoffFilter:
    """Filter and transform context during department handoffs."""

    def __init__(self):
        self._callbacks: list[tuple[str, Callable]] = []
        self._disabled_routes: set[tuple[str, str]] = set()  # (from, to) pairs
        self._history: list[HandoffRecord] = []

    def on_handoff(self, callback: Callable, name: str = ""):
        """Register an on_handoff callback. Called with HandoffRecord."""
        hook_name = name or getattr(callback, "__name__", "anonymous")
        self._callbacks.append((hook_name, callback))

    def disable_route(self, from_dept: str, to_dept: str):
        """Disable a specific handoff route."""
        self._disabled_routes.add((from_dept, to_dept))
        log.info(f"handoff: disabled route {from_dept} → {to_dept}")

    def enable_route(self, from_dept: str, to_dept: str):
        """Re-enable a handoff route."""
        self._disabled_routes.discard((from_dept, to_dept))

    def is_enabled(self, from_dept: str, to_dept: str) -> bool:
        """Check if a handoff route is enabled."""
        return (from_dept, to_dept) not in self._disabled_routes

    def filter(self, spec: dict, from_dept: str, to_dept: str,
               history_text: str = "") -> dict:
        """Filter task spec for handoff between departments.

        Args:
            spec: Task specification dict
            from_dept: Source department
            to_dept: Target department
            history_text: Optional conversation history to compress

        Returns:
            Filtered spec with irrelevant context removed.
        """
        if not self.is_enabled(from_dept, to_dept):
            log.warning(f"handoff: route {from_dept} → {to_dept} is disabled")
            return spec

        context_before = len(str(spec))
        filtered = {}

        # Always pass universal fields
        for key in _UNIVERSAL_FIELDS:
            if key in spec:
                filtered[key] = spec[key]

        # Pass fields relevant to the target department
        target_fields = _DEPT_SPECIFIC_FIELDS.get(to_dept, set())
        all_dept_fields = _flatten_all_dept_fields()
        for key, value in spec.items():
            if key in filtered:
                continue
            if key in target_fields:
                filtered[key] = value
            elif key not in all_dept_fields:
                # Not department-specific → pass through
                filtered[key] = value

        # Compress history if provided (nest_handoff_history pattern)
        if history_text:
            compressed = self._compress_history(history_text, from_dept)
            filtered["handoff_history"] = compressed

        # Update department
        filtered["department"] = to_dept
        filtered["source"] = f"handoff:{from_dept}→{to_dept}"

        context_after = len(str(filtered))
        ratio = 1.0 - (context_after / context_before) if context_before > 0 else 0.0

        # Record
        record = HandoffRecord(
            from_dept=from_dept,
            to_dept=to_dept,
            task_id=spec.get("task_id", ""),
            context_before=context_before,
            context_after=context_after,
            compression_ratio=round(ratio, 2),
        )
        self._history.append(record)

        # Fire callbacks
        for name, cb in self._callbacks:
            try:
                cb(record)
            except Exception as e:
                log.debug(f"handoff: callback {name} failed: {e}")

        log.info(
            f"handoff: {from_dept} → {to_dept}, "
            f"context {context_before} → {context_after} chars "
            f"({ratio:.0%} reduction)"
        )
        return filtered

    def _compress_history(self, history: str, from_dept: str,
                          max_len: int = 500) -> str:
        """Compress conversation history into a summary block.

        Stolen from Agents SDK nest_handoff_history pattern.
        """
        if len(history) <= max_len:
            return f"<HANDOFF_HISTORY from={from_dept}>\n{history}\n</HANDOFF_HISTORY>"

        # Truncate and mark
        truncated = history[:max_len].rsplit(" ", 1)[0]
        return (
            f"<HANDOFF_HISTORY from={from_dept} truncated=true "
            f"original_len={len(history)}>\n"
            f"{truncated}...\n"
            f"</HANDOFF_HISTORY>"
        )

    def get_history(self, limit: int = 20) -> list[HandoffRecord]:
        return self._history[-limit:]

    def get_stats(self) -> dict:
        if not self._history:
            return {"total_handoffs": 0, "avg_compression": 0.0}
        avg_comp = sum(r.compression_ratio for r in self._history) / len(self._history)
        return {
            "total_handoffs": len(self._history),
            "avg_compression": round(avg_comp, 2),
            "disabled_routes": list(self._disabled_routes),
        }


# Singleton
_filter: Optional[HandoffFilter] = None


def get_handoff_filter() -> HandoffFilter:
    global _filter
    if _filter is None:
        _filter = HandoffFilter()
    return _filter
