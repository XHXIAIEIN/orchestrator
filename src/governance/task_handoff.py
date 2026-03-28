"""TaskHandoff — explicit department-to-department task transfer.

Stolen from OpenAI Swarm: instead of implicit spec dict merging,
use a structured handoff object that captures from/to/reason/context.
"""
from dataclasses import dataclass, field


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

    def to_dict(self) -> dict:
        return {
            "from_dept": self.from_dept,
            "to_dept": self.to_dept,
            "handoff_type": self.handoff_type,
            "task_id": self.task_id,
            "reason": self.reason,
            "rework_count": self.rework_count,
            "artifact_keys": list(self.artifact.keys()),
            "context_keys": list(self.context_updates.keys()),
        }
