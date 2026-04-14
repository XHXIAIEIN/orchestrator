"""
Memory Synthesizer — daily LLM-driven synthesis of observation archive.

Source: yoyo-evolve Two-Layer Memory (Round 30) + Codex Memory 2-Phase (Round 28c)
Enhanced: R66 yoyo-evolve Three-Tier Time-Layered Compression (Round deep-rescan)

Architecture:
    data/observations.jsonl (append-only, from instinct_pipeline.py)
    SOUL/private/experiences.jsonl (append-only, key milestones)
        ↓ daily batch
    LLM synthesis (three-tier time-layered compression)
        ↓
    data/active_context.md (human-readable, loaded into session)

Three-tier compression (R66 yoyo-evolve):
    Recent  (last 2 weeks):  full text, all fields preserved
    Medium  (2-8 weeks):     1-2 sentence summary per entry
    Old     (8+ weeks):      grouped by theme into "Wisdom" sections
    Target: active_context.md ≤ 200 lines

The key insight: raw observations are immutable truth, but too noisy for context.
Synthesized context is lossy but usable. Keep both layers.
"""
from __future__ import annotations

import json
import logging
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OBSERVATIONS_PATH = REPO_ROOT / "data" / "observations.jsonl"
EXPERIENCES_PATH = REPO_ROOT / "SOUL" / "private" / "experiences.jsonl"
ACTIVE_CONTEXT_PATH = REPO_ROOT / "data" / "active_context.md"
SYNTHESIS_LOCK = REPO_ROOT / "data" / ".synthesis_lock"

WEIGHT_DECAY_DAYS = 7

# R66 time tier boundaries
RECENT_DAYS = 14      # full text
MEDIUM_DAYS = 56      # 2-8 weeks → summarize
# Older than MEDIUM_DAYS → theme-grouped wisdom
TARGET_MAX_LINES = 200


def _parse_date(entry: dict) -> datetime | None:
    """Extract datetime from an entry (multiple format support)."""
    for key in ("date", "timestamp", "created_at", "occurred_at"):
        val = entry.get(key)
        if val is None:
            continue
        if isinstance(val, (int, float)):
            try:
                return datetime.fromtimestamp(val, tz=timezone.utc)
            except (OSError, ValueError):
                continue
        if isinstance(val, str):
            for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ",
                        "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S"):
                try:
                    dt = datetime.strptime(val, fmt)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt
                except ValueError:
                    continue
    return None


def _load_jsonl(path: Path) -> list[dict]:
    """Load all entries from a JSONL file."""
    if not path.exists():
        return []
    results = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    results.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        log.warning("synthesizer: failed to load %s: %s", path, e)
    return results


def load_recent_observations(max_age_days: int = 7) -> list[dict]:
    """Load observations from JSONL, newest first."""
    if not OBSERVATIONS_PATH.exists():
        return []

    cutoff = time.time() - (max_age_days * 86400)
    results = []
    try:
        with open(OBSERVATIONS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("timestamp", 0) >= cutoff:
                        results.append(entry)
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        log.warning(f"synthesizer: failed to load observations: {e}")

    return sorted(results, key=lambda x: -x.get("timestamp", 0))


def classify_by_time_tier(entries: list[dict]) -> dict[str, list[dict]]:
    """R66: Split entries into Recent / Medium / Old tiers.

    Returns:
        {"recent": [...], "medium": [...], "old": [...]}
    """
    now = datetime.now(tz=timezone.utc)
    recent_cutoff = now - timedelta(days=RECENT_DAYS)
    medium_cutoff = now - timedelta(days=MEDIUM_DAYS)

    tiers: dict[str, list[dict]] = {"recent": [], "medium": [], "old": []}

    for entry in entries:
        dt = _parse_date(entry)
        if dt is None:
            tiers["old"].append(entry)  # undated → treat as old
            continue
        if dt >= recent_cutoff:
            tiers["recent"].append(entry)
        elif dt >= medium_cutoff:
            tiers["medium"].append(entry)
        else:
            tiers["old"].append(entry)

    # Sort each tier newest-first
    for tier in tiers.values():
        tier.sort(key=lambda e: _parse_date(e) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    return tiers


def _format_entry_full(entry: dict) -> str:
    """Format a single entry at full detail (Recent tier)."""
    dt = _parse_date(entry)
    date_str = dt.strftime("%Y-%m-%d") if dt else "?"

    # Handle both observation and experience formats
    if "summary" in entry:
        return f"- **{date_str}** [{entry.get('type', '?')}] {entry['summary']}"
    elif "event_type" in entry:
        return (f"- **{date_str}** [{entry.get('event_type', '?')}] "
                f"{entry.get('tool_name', '?')}: {entry.get('outcome', '?')}")
    else:
        content = json.dumps(entry, ensure_ascii=False)[:150]
        return f"- **{date_str}** {content}"


def _format_entry_summary(entry: dict) -> str:
    """Format a single entry as 1-sentence summary (Medium tier)."""
    dt = _parse_date(entry)
    date_str = dt.strftime("%m-%d") if dt else "?"

    if "summary" in entry:
        text = entry["summary"][:80]
    elif "outcome" in entry:
        text = f"{entry.get('tool_name', '?')}: {entry['outcome']}"[:80]
    else:
        text = json.dumps(entry, ensure_ascii=False)[:80]

    return f"- {date_str}: {text}"


def build_tiered_synthesis_prompt(
    tiers: dict[str, list[dict]],
) -> str:
    """R66: Build synthesis prompt with three-tier time compression.

    The prompt instructs the LLM to:
    - Render Recent tier in full
    - Summarize Medium tier to 1-2 sentences each
    - Group Old tier by theme into Wisdom sections
    """
    recent_text = "\n".join(_format_entry_full(e) for e in tiers["recent"][:30])
    medium_text = "\n".join(_format_entry_summary(e) for e in tiers["medium"][:30])

    # Pre-format old entries for the LLM to group by theme
    old_text = "\n".join(_format_entry_summary(e) for e in tiers["old"][:50])

    return f"""Synthesize these entries into a time-layered active context document.

Apply time-weighted compression tiers:

## Recent Patterns (last 2 weeks) — FULL DETAIL
Render each entry as a bullet with date, type, and full description.
{recent_text if recent_text else "(no recent entries)"}

## Medium-Term Summary (2-8 weeks) — 1-2 SENTENCES EACH
Compress each entry into a single actionable sentence.
{medium_text if medium_text else "(no medium-term entries)"}

## Wisdom (older than 8 weeks) — GROUP BY THEME
Group these old entries into 3-5 thematic sections.
Each section: "## Wisdom: [Theme]" with 2-3 sentences distilling the pattern.
{old_text if old_text else "(no old entries)"}

CONSTRAINTS:
- Total output must be ≤ 200 lines
- Recent section gets 40% of space, Medium 30%, Wisdom 30%
- If entries are sparse, output shorter. Never pad.
- Each wisdom theme must have at least 2 supporting entries; otherwise keep as medium.
- Quality filter: only include entries that would change behavior in a future session.
  Ask: "Would this change how I act?" — if not, skip it."""


def build_synthesis_prompt(observations: list[dict]) -> str:
    """Build a prompt for LLM to synthesize observations into active context.

    Falls back to simple prompt if not enough data for tiered synthesis.
    """
    # Try tiered synthesis first (R66 enhancement)
    all_entries = observations[:]
    experiences = _load_jsonl(EXPERIENCES_PATH)
    all_entries.extend(experiences)

    if len(all_entries) >= 5:
        tiers = classify_by_time_tier(all_entries)
        if any(tiers.values()):
            return build_tiered_synthesis_prompt(tiers)

    # Fallback: simple synthesis for sparse data
    obs_text = "\n".join(
        f"- [{o.get('event_type', '?')}] {o.get('tool_name', '?')}: "
        f"{o.get('outcome', '?')} — {json.dumps(o.get('context', {}), ensure_ascii=False)[:200]}"
        for o in observations[:100]
    )

    return f"""Synthesize these raw observations into a concise active context summary.

Rules:
- Group by theme (security blocks, common errors, usage patterns)
- Include counts: "Edit blocked 5x on config files" not just "Edit was blocked"
- Time-weight: recent patterns matter more than old ones
- Output as markdown sections, max 500 words total
- If no meaningful patterns exist, output "No significant patterns detected."

Raw observations ({len(observations)} total, showing up to 100):
{obs_text}

Output format:
## Active Patterns
[grouped patterns with counts]

## Recurring Issues
[errors or blocks that keep happening]

## Usage Summary
[tool usage distribution, peak times]"""


def should_synthesize() -> bool:
    """Check if enough time has passed since last synthesis (24h minimum)."""
    if not SYNTHESIS_LOCK.exists():
        return True
    try:
        mtime = SYNTHESIS_LOCK.stat().st_mtime
        hours_since = (time.time() - mtime) / 3600
        return hours_since >= 24.0
    except Exception:
        return True


def mark_synthesized():
    """Touch the lock file to record synthesis time."""
    SYNTHESIS_LOCK.parent.mkdir(parents=True, exist_ok=True)
    SYNTHESIS_LOCK.touch()


def save_active_context(content: str):
    """Write synthesized context to active_context.md with backup.

    R66: backup before overwrite, restore on failure.
    """
    ACTIVE_CONTEXT_PATH.parent.mkdir(parents=True, exist_ok=True)
    backup_path = ACTIVE_CONTEXT_PATH.with_suffix(".md.bak")

    # Backup existing file before overwrite
    if ACTIVE_CONTEXT_PATH.exists():
        try:
            shutil.copy2(ACTIVE_CONTEXT_PATH, backup_path)
        except Exception as e:
            log.warning("synthesizer: backup failed: %s", e)

    header = f"<!-- Auto-synthesized: {time.strftime('%Y-%m-%d %H:%M')} -->\n"
    try:
        ACTIVE_CONTEXT_PATH.write_text(header + content, encoding="utf-8")

        # Validate output size
        line_count = content.count("\n") + 1
        if line_count > TARGET_MAX_LINES:
            log.warning(
                "synthesizer: output %d lines exceeds target %d — consider tighter compression",
                line_count, TARGET_MAX_LINES,
            )

        log.info("synthesizer: saved active context (%d chars, %d lines)", len(content), line_count)
    except Exception as e:
        log.error("synthesizer: write failed: %s — restoring backup", e)
        if backup_path.exists():
            try:
                shutil.copy2(backup_path, ACTIVE_CONTEXT_PATH)
                log.info("synthesizer: restored from backup")
            except Exception:
                pass
        raise
