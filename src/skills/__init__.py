# src/skills/__init__.py
"""Skill tracking infrastructure — R51 (stolen from HKUDS/OpenSpace).

Public API:
    lineage.register_skill       — read/create .skill_id, emit IMPORTED event
    lineage.record_evolution     — emit FIXED / DERIVED / CAPTURED event
    lineage.get_lineage          — fetch all events for a skill_id

    tracker.record_execution     — log selection/application/outcome
    tracker.get_skill_stats      — compute rates from JSONL ledger
    tracker.get_degraded_skills  — find skills below completion threshold
"""
from .lineage import (
    SkillLineage,
    get_lineage,
    record_evolution,
    register_skill,
)
from .tracker import (
    SkillExecution,
    get_degraded_skills,
    get_skill_stats,
    record_execution,
)

__all__ = [
    # lineage
    "SkillLineage",
    "register_skill",
    "record_evolution",
    "get_lineage",
    # tracker
    "SkillExecution",
    "record_execution",
    "get_skill_stats",
    "get_degraded_skills",
]
