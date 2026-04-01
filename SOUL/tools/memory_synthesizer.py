"""
Memory Synthesizer — daily LLM-driven synthesis of observation archive.

Source: yoyo-evolve Two-Layer Memory (Round 30) + Codex Memory 2-Phase (Round 28c)

Architecture:
    data/observations.jsonl (append-only, from instinct_pipeline.py)
        ↓ daily batch
    LLM synthesis (time-weighted compression)
        ↓
    data/active_context.md (human-readable, loaded into session)

The key insight: raw observations are immutable truth, but too noisy for context.
Synthesized context is lossy but usable. Keep both layers.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OBSERVATIONS_PATH = REPO_ROOT / "data" / "observations.jsonl"
ACTIVE_CONTEXT_PATH = REPO_ROOT / "data" / "active_context.md"
SYNTHESIS_LOCK = REPO_ROOT / "data" / ".synthesis_lock"

WEIGHT_DECAY_DAYS = 7


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


def build_synthesis_prompt(observations: list[dict]) -> str:
    """Build a prompt for LLM to synthesize observations into active context."""
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
    """Write synthesized context to active_context.md."""
    ACTIVE_CONTEXT_PATH.parent.mkdir(parents=True, exist_ok=True)
    header = f"<!-- Auto-synthesized: {time.strftime('%Y-%m-%d %H:%M')} -->\n"
    ACTIVE_CONTEXT_PATH.write_text(header + content, encoding="utf-8")
    log.info(f"synthesizer: saved active context ({len(content)} chars)")
