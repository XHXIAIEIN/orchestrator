"""TaskHandoff — explicit department-to-department task transfer.

Stolen from OpenAI Swarm (R11): instead of implicit spec dict merging,
use a structured handoff object that captures from/to/reason/context.

Also incorporates context-filtering ideas from Agents SDK HandoffFilter
(formerly handoff.py): history compression and compression metrics.
"""
import logging
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# ── Department-specific context fields (from Agents SDK pattern) ──
# Used by compress_context() to strip fields irrelevant to the target department.
_DEPT_SPECIFIC_FIELDS: dict[str, set[str]] = {
    "engineering": {"code_diff", "file_list", "git_log", "implementation_notes"},
    "operations": {"docker_logs", "container_status", "deploy_config"},
    "quality": {"test_results", "coverage_report", "review_comments"},
    "security": {"vulnerability_scan", "taint_report", "secret_findings"},
    "personnel": {"performance_data", "skill_assessment"},
    "protocol": {"debt_inventory", "audit_trail"},
}

_UNIVERSAL_FIELDS: set[str] = {
    "department", "intent", "cognitive_mode", "priority",
    "problem", "expected", "summary", "source", "action",
    "observation", "importance",
}


@dataclass
class TaskHandoff:
    """Represents a structured handoff between departments."""
    from_dept: str
    to_dept: str
    handoff_type: str       # quality_review | rework | fact_layer | expression_layer | escalation
    task_id: int            # source task ID
    output: str = ""        # output being handed off
    artifact: dict = field(default_factory=dict)   # structured artifact from _extract_artifact
    context_updates: dict = field(default_factory=dict)  # context to carry forward
    reason: str = ""
    rework_count: int = 0
    timestamp: float = field(default_factory=time.time)
    context_before: int = 0   # chars before filtering (0 = no filtering applied)
    context_after: int = 0    # chars after filtering
    compression_ratio: float = 0.0

    def to_dict(self) -> dict:
        d = {
            "from_dept": self.from_dept,
            "to_dept": self.to_dept,
            "handoff_type": self.handoff_type,
            "task_id": self.task_id,
            "reason": self.reason,
            "rework_count": self.rework_count,
            "timestamp": self.timestamp,
            "artifact_keys": list(self.artifact.keys()),
            "context_keys": list(self.context_updates.keys()),
        }
        if self.compression_ratio > 0:
            d["compression_ratio"] = self.compression_ratio
        return d

    # ── Context filtering (Agents SDK pattern) ──

    def filter_context(self, spec: dict) -> dict:
        """Filter a task spec dict for the target department.

        Strips fields that belong to other departments, keeps universal
        fields and fields relevant to ``self.to_dept``.  Populates the
        compression metrics (context_before, context_after, compression_ratio).

        Returns the filtered spec (also stored in ``self.context_updates``).
        """
        self.context_before = len(str(spec))
        filtered: dict = {}

        # Universal fields always pass through
        for key in _UNIVERSAL_FIELDS:
            if key in spec:
                filtered[key] = spec[key]

        # Target-department fields pass through
        target_fields = _DEPT_SPECIFIC_FIELDS.get(self.to_dept, set())
        all_dept_fields: set[str] = set()
        for fields in _DEPT_SPECIFIC_FIELDS.values():
            all_dept_fields.update(fields)

        for key, value in spec.items():
            if key in filtered:
                continue
            if key in target_fields:
                filtered[key] = value
            elif key not in all_dept_fields:
                # Not department-specific → pass through
                filtered[key] = value

        filtered["department"] = self.to_dept
        filtered["source"] = f"handoff:{self.from_dept}→{self.to_dept}"

        self.context_after = len(str(filtered))
        if self.context_before > 0:
            self.compression_ratio = round(
                1.0 - (self.context_after / self.context_before), 2
            )

        self.context_updates = filtered
        log.info(
            "handoff: %s → %s, context %d → %d chars (%.0f%% reduction)",
            self.from_dept, self.to_dept,
            self.context_before, self.context_after,
            self.compression_ratio * 100,
        )
        return filtered

    @staticmethod
    def compress_history(history: str, from_dept: str, max_len: int = 500) -> str:
        """Compress conversation history into a tagged summary block.

        Stolen from Agents SDK nest_handoff_history pattern.
        """
        if len(history) <= max_len:
            return f"<HANDOFF_HISTORY from={from_dept}>\n{history}\n</HANDOFF_HISTORY>"

        truncated = history[:max_len].rsplit(" ", 1)[0]
        return (
            f"<HANDOFF_HISTORY from={from_dept} truncated=true "
            f"original_len={len(history)}>\n"
            f"{truncated}...\n"
            f"</HANDOFF_HISTORY>"
        )
