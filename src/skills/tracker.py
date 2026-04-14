# src/skills/tracker.py
"""Skill Execution Tracker — R51 (stolen from HKUDS/OpenSpace).

Append-only JSONL ledger recording every skill selection/application event.
Data lands in SOUL/public/skill_executions.jsonl.

Stats derived from the ledger:
    selection_rate  = selected / total invocations
    applied_rate    = applied / selected
    success_rate    = task_succeeded / applied
    completion_rate = task_succeeded / total invocations

Degraded skills: completion_rate < threshold (default 0.35).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EXECUTIONS_PATH = REPO_ROOT / "SOUL" / "public" / "skill_executions.jsonl"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class SkillExecution:
    skill_id: str
    task_id: str
    selected: bool       # was this skill selected for the task?
    applied: bool        # was the skill content actually used?
    task_succeeded: bool
    timestamp: str


# ---------------------------------------------------------------------------
# JSONL helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_executions() -> list[dict]:
    """Read all execution records from skill_executions.jsonl."""
    if not EXECUTIONS_PATH.exists():
        return []
    records = []
    for line in EXECUTIONS_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                log.warning("tracker: skipping malformed line: %s", exc)
    return records


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_execution(
    skill_id: str,
    task_id: str,
    selected: bool,
    applied: bool,
    task_succeeded: bool,
    *,
    timestamp: str | None = None,
) -> None:
    """Append a skill execution record to skill_executions.jsonl."""
    EXECUTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "skill_id": skill_id,
        "task_id": task_id,
        "selected": selected,
        "applied": applied,
        "task_succeeded": task_succeeded,
        "timestamp": timestamp or _now_iso(),
    }
    with EXECUTIONS_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    log.debug(
        "tracker: recorded skill_id=%s task_id=%s selected=%s applied=%s succeeded=%s",
        skill_id, task_id, selected, applied, task_succeeded,
    )


def get_skill_stats(skill_id: str) -> dict:
    """Compute execution stats for a skill from the JSONL ledger.

    Returns:
        {
            "skill_id": str,
            "total": int,
            "selected": int,
            "applied": int,
            "succeeded": int,
            "selection_rate": float,   # selected / total
            "applied_rate": float,     # applied / selected
            "success_rate": float,     # succeeded / applied
            "completion_rate": float,  # succeeded / total
        }
    """
    records = [r for r in _read_executions() if r.get("skill_id") == skill_id]
    total = len(records)
    if total == 0:
        return {
            "skill_id": skill_id,
            "total": 0,
            "selected": 0,
            "applied": 0,
            "succeeded": 0,
            "selection_rate": 0.0,
            "applied_rate": 0.0,
            "success_rate": 0.0,
            "completion_rate": 0.0,
        }

    selected = sum(1 for r in records if r.get("selected"))
    applied = sum(1 for r in records if r.get("applied"))
    succeeded = sum(1 for r in records if r.get("task_succeeded"))

    return {
        "skill_id": skill_id,
        "total": total,
        "selected": selected,
        "applied": applied,
        "succeeded": succeeded,
        "selection_rate": selected / total,
        "applied_rate": applied / selected if selected else 0.0,
        "success_rate": succeeded / applied if applied else 0.0,
        "completion_rate": succeeded / total,
    }


def get_degraded_skills(threshold: float = 0.35) -> list[dict]:
    """Return stats for all skills whose completion_rate < threshold.

    Only considers skills with at least one execution record.
    Results sorted by completion_rate ascending (worst first).
    """
    records = _read_executions()
    if not records:
        return []

    all_ids = {r["skill_id"] for r in records if r.get("skill_id")}
    degraded = []
    for sid in all_ids:
        stats = get_skill_stats(sid)
        if stats["total"] > 0 and stats["completion_rate"] < threshold:
            degraded.append(stats)

    degraded.sort(key=lambda s: s["completion_rate"])
    return degraded
