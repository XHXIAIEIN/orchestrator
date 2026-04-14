# src/skills/lineage.py
"""Skill Lineage Tracker — R51 (stolen from HKUDS/OpenSpace).

Append-only JSONL ledger recording skill origin and evolution events.
Each skill gets a deterministic .skill_id sidecar, events land in
SOUL/public/skill_store.jsonl.

Event types:
    IMPORTED  — skill first registered from existing SKILL.md
    FIXED     — bug fix or patch applied to existing skill
    DERIVED   — new skill forked/composed from one or more parent skills
    CAPTURED  — skill extracted from execution trace / replay
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILL_STORE_PATH = REPO_ROOT / "SOUL" / "public" / "skill_store.jsonl"
SKILLS_DIR = REPO_ROOT / ".claude" / "skills"

VALID_ORIGINS = {"IMPORTED", "FIXED", "DERIVED", "CAPTURED"}


# ---------------------------------------------------------------------------
# Deterministic ID generation
# ---------------------------------------------------------------------------

def _skill_id(skill_name: str) -> str:
    """Generate a deterministic skill ID from the skill name.

    Format: ``<name>__imp_<8-char-hash>``
    The hash is the first 8 hex chars of SHA-256(skill_name).
    """
    h = hashlib.sha256(skill_name.encode()).hexdigest()[:8]
    return f"{skill_name}__imp_{h}"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class SkillLineage:
    """Describes a single lineage event for a skill."""

    origin: str                         # IMPORTED / FIXED / DERIVED / CAPTURED
    generation: int                     # depth from root (IMPORTED = 0)
    parent_skill_ids: list[str] = field(default_factory=list)
    change_summary: str = ""
    content_diff: str = ""              # unified diff, may be empty for IMPORTED


# ---------------------------------------------------------------------------
# JSONL helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _append_event(event: dict) -> None:
    """Append a JSON line to skill_store.jsonl (create if missing)."""
    SKILL_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SKILL_STORE_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")


def _read_events() -> list[dict]:
    """Read all events from skill_store.jsonl."""
    if not SKILL_STORE_PATH.exists():
        return []
    events = []
    for line in SKILL_STORE_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as exc:
                log.warning("lineage: skipping malformed line: %s", exc)
    return events


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def register_skill(skill_dir: Path) -> str:
    """Read or create .skill_id for a skill directory, append IMPORTED event.

    If .skill_id already exists the ID is reused (idempotent).
    Returns the skill_id string.
    """
    skill_name = skill_dir.name
    id_file = skill_dir / ".skill_id"

    if id_file.exists():
        skill_id = id_file.read_text(encoding="utf-8").strip()
    else:
        skill_id = _skill_id(skill_name)
        id_file.write_text(skill_id + "\n", encoding="utf-8")
        log.debug("lineage: wrote .skill_id for '%s' → %s", skill_name, skill_id)

    # Check if we already have an IMPORTED event for this skill_id
    existing = [e for e in _read_events() if e.get("skill_id") == skill_id]
    if not existing:
        _append_event({
            "event": "IMPORTED",
            "skill_id": skill_id,
            "name": skill_name,
            "timestamp": _now_iso(),
            "generation": 0,
        })
        log.info("lineage: IMPORTED '%s' (%s)", skill_name, skill_id)

    return skill_id


def record_evolution(
    skill_id: str,
    origin: str,
    change_summary: str,
    diff: str,
    *,
    parent_skill_ids: list[str] | None = None,
) -> str:
    """Append an evolution event (FIXED / DERIVED / CAPTURED) to the ledger.

    Returns the skill_id (unchanged — evolution doesn't create a new ID).
    """
    if origin not in VALID_ORIGINS:
        raise ValueError(f"origin must be one of {VALID_ORIGINS}, got {origin!r}")

    # Compute generation from existing events for this skill_id
    existing = [e for e in _read_events() if e.get("skill_id") == skill_id]
    generation = max((e.get("generation", 0) for e in existing), default=0) + 1

    event: dict = {
        "event": origin,
        "skill_id": skill_id,
        "timestamp": _now_iso(),
        "generation": generation,
        "parent_skill_ids": parent_skill_ids or [],
        "change_summary": change_summary,
        "content_diff": diff,
    }
    _append_event(event)
    log.info("lineage: %s '%s' gen=%d", origin, skill_id, generation)
    return skill_id


def get_lineage(skill_id: str) -> list[dict]:
    """Return all ledger events for a skill_id, in chronological order."""
    return [e for e in _read_events() if e.get("skill_id") == skill_id]
