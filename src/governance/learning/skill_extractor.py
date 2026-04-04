"""
Skill Extraction Pipeline (R23 — stolen from gpyangyoujun/self-improving-agent).

Scans learnings DB for clusters of related entries. When a topic has >=5 entries
with recurrence >= 2, generates a SKILL.md skeleton for review.

Does NOT auto-install skills — writes to `departments/<dept>/skill-suggestions/`
for human approval (same pattern as skill_evolver.py).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent
while _REPO_ROOT != _REPO_ROOT.parent and not ((_REPO_ROOT / "departments").is_dir() and (_REPO_ROOT / "src").is_dir()):
    _REPO_ROOT = _REPO_ROOT.parent

DEFAULT_OUTPUT_DIR = _REPO_ROOT / "departments" / "engineering" / "skill-suggestions"


@dataclass
class SkillCandidate:
    """A cluster of learnings that could become a skill."""
    area: str
    entry_count: int
    recurrence: int
    pattern_keys: list[str] = field(default_factory=list)
    summary: str = ""
    suggested_filename: str = ""


def scan_for_skill_candidates(
    db=None,
    min_entries: int = 5,
    min_recurrence: int = 2,
) -> list[SkillCandidate]:
    """Query learnings DB for areas with enough entries to warrant a skill.

    Groups by area, filters by count >= min_entries and max recurrence >= min_recurrence.
    Returns sorted by entry_count descending.
    """
    if db is None:
        try:
            from src.storage.events_db import EventsDB
            db = EventsDB()
        except Exception as exc:
            log.warning("skill_extractor: cannot open DB — %s", exc)
            return []

    try:
        with db._connect() as conn:
            rows = conn.execute(
                "SELECT area, COUNT(*) as cnt, MAX(recurrence) as max_rec "
                "FROM learnings "
                "WHERE status != 'retired' "
                "GROUP BY area "
                "HAVING cnt >= ? AND max_rec >= ? "
                "ORDER BY cnt DESC",
                (min_entries, min_recurrence),
            ).fetchall()
    except Exception as exc:
        log.warning("skill_extractor: query failed — %s", exc)
        return []

    candidates: list[SkillCandidate] = []
    for row in rows:
        area = row["area"] if hasattr(row, "keys") else row[0]
        cnt = row["cnt"] if hasattr(row, "keys") else row[1]
        max_rec = row["max_rec"] if hasattr(row, "keys") else row[2]

        # Fetch pattern_keys and top rules for this area
        try:
            with db._connect() as conn:
                detail_rows = conn.execute(
                    "SELECT pattern_key, rule FROM learnings "
                    "WHERE area = ? AND status != 'retired' "
                    "ORDER BY recurrence DESC LIMIT 10",
                    (area,),
                ).fetchall()
        except Exception:
            detail_rows = []

        pattern_keys = []
        summaries = []
        for dr in detail_rows:
            pk = dr["pattern_key"] if hasattr(dr, "keys") else dr[0]
            rl = dr["rule"] if hasattr(dr, "keys") else dr[1]
            pattern_keys.append(pk)
            summaries.append(rl)

        summary = " | ".join(summaries[:5]) if summaries else area
        safe_name = area.replace(" ", "-").replace("/", "-").lower()
        filename = f"skill-{safe_name}.md"

        candidates.append(SkillCandidate(
            area=area,
            entry_count=cnt,
            recurrence=max_rec,
            pattern_keys=pattern_keys,
            summary=summary,
            suggested_filename=filename,
        ))

    log.info("skill_extractor: found %d candidates (min_entries=%d, min_rec=%d)",
             len(candidates), min_entries, min_recurrence)
    return candidates


def generate_skill_skeleton(candidate: SkillCandidate) -> str:
    """Generate a SKILL.md skeleton from a SkillCandidate."""
    patterns_list = "\n".join(f"- `{pk}`" for pk in candidate.pattern_keys[:10])
    return f"""---
name: {candidate.area}
description: Auto-extracted skill from {candidate.entry_count} learnings (max recurrence {candidate.recurrence})
status: draft
---

# {candidate.area}

> Auto-generated skill skeleton. Review and edit before promoting.

## Summary

{candidate.summary}

## Patterns ({candidate.entry_count} entries)

{patterns_list}

## When to Apply

<!-- Describe the conditions under which this skill should be loaded -->

## Instructions

<!-- Concrete instructions extracted from learnings -->

## Examples

<!-- Add concrete examples from past runs -->
"""


def extract_and_save(
    output_dir: Path = None,
    db=None,
) -> list[Path]:
    """Run scan -> generate -> save. Returns paths of generated files.

    Skips candidates that already have a generated file.
    """
    if output_dir is None:
        output_dir = DEFAULT_OUTPUT_DIR

    output_dir.mkdir(parents=True, exist_ok=True)

    candidates = scan_for_skill_candidates(db=db)
    saved: list[Path] = []

    for candidate in candidates:
        target = output_dir / candidate.suggested_filename
        if target.exists():
            log.debug("skill_extractor: skip %s (already exists)", target.name)
            continue

        skeleton = generate_skill_skeleton(candidate)
        try:
            target.write_text(skeleton, encoding="utf-8")
            saved.append(target)
            log.info("skill_extractor: wrote %s", target)
        except Exception as exc:
            log.warning("skill_extractor: failed to write %s — %s", target, exc)

    return saved
