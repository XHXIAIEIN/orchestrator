# src/governance/events/types.py
"""Typed event hierarchy for governance pipeline.

Phase 2: Types used at creation point (executor), serialized via to_dict()
for DB/fan-out. Consumers can use from_dict() for type-safe reads.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class EventSource(Enum):
    AGENT = "agent"
    USER = "user"
    GOVERNOR = "governor"
    SCRUTINY = "scrutiny"
    REVIEW = "review"
    SYSTEM = "system"


@dataclass
class GovernanceEvent:
    """Base event for all governance pipeline events."""
    task_id: int
    source: EventSource
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    cause_event_id: int | None = None  # causal link to triggering event

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if v is not None}
        if isinstance(d.get("source"), EventSource):
            d["source"] = d["source"].value
        d["event_class"] = self.__class__.__name__
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "GovernanceEvent":
        """Reconstruct from DB dict. Ignores unknown fields gracefully."""
        import copy
        import dataclasses
        d = copy.copy(d)
        d.pop("event_class", None)
        source_val = d.get("source")
        if isinstance(source_val, str):
            try:
                d["source"] = EventSource(source_val)
            except ValueError:
                d["source"] = EventSource.SYSTEM
        known = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in d.items() if k in known}
        return cls(**filtered)


# ── Actions (things that happen TO the system) ──

@dataclass
class TaskCreated(GovernanceEvent):
    action: str = ""
    department: str = ""
    priority: str = "medium"
    cognitive_mode: str = ""


@dataclass
class TaskDispatched(GovernanceEvent):
    complexity: str = ""
    scrutiny_result: str = ""
    learnings_injected: int = 0


@dataclass
class AgentTurn(GovernanceEvent):
    turn: int = 0
    tools: list[str] = field(default_factory=list)
    thinking_preview: str = ""
    text_preview: str = ""
    error: str | None = None


@dataclass
class AgentResult(GovernanceEvent):
    status: str = ""  # done | failed | stuck
    num_turns: int = 0
    duration_ms: int = 0
    cost_usd: float = 0.0
    output_preview: str = ""


@dataclass
class StuckDetected(GovernanceEvent):
    pattern: str = ""  # from StuckDetector
    turn: int = 0


# ── Observations (results from the system) ──

@dataclass
class ScrutinyVerdict(GovernanceEvent):
    approved: bool = False
    note: str = ""
    blast_radius: str = ""
    second_opinion: bool = False


@dataclass
class QualityVerdict(GovernanceEvent):
    passed: bool = False
    critical_count: int = 0
    high_count: int = 0
    summary: str = ""


@dataclass
class ReworkDispatched(GovernanceEvent):
    original_task_id: int = 0
    rework_count: int = 0
    feedback_preview: str = ""


@dataclass
class TaskEscalated(GovernanceEvent):
    reason: str = ""
    rework_count: int = 0


@dataclass
class DoomLoopDetected(GovernanceEvent):
    reason: str = ""
    turn: int = 0
    details: dict = field(default_factory=dict)


# ── System Events ──

@dataclass
class LearningRecorded(GovernanceEvent):
    pattern_key: str = ""
    rule: str = ""
    recurrence: int = 1


@dataclass
class ContextCondensed(GovernanceEvent):
    strategy: str = ""
    events_before: int = 0
    events_after: int = 0
    tokens_saved: int = 0
