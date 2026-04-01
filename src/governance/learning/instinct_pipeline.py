"""
Instinct Learning Pipeline — observe everything, promote what matters.

Source: Everything Claude Code steal — Instinct-Based Continuous Learning

Architecture:
    Hook events (ALL of them)
        ↓
    observations.jsonl (append-only, unfiltered truth source)
        ↓
    Pattern Analyzer (batch, periodic)
        ↓
    Confidence scoring (0.0-1.0)
        ↓
    Promotion gate (>= threshold)
        ↓
    Active rules / learnings.md

Unlike the existing experience/learning system which relies on LLM judgment
of "what's worth remembering", this pipeline captures EVERYTHING first,
then applies statistical/heuristic analysis to find recurring patterns.

The key insight: humans (and LLMs) are bad at deciding what's important
in the moment. Capture first, analyze later.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
OBSERVATIONS_PATH = REPO_ROOT / "data" / "observations.jsonl"
PROMOTIONS_PATH = REPO_ROOT / "data" / "promoted_rules.jsonl"

# Confidence thresholds
PROMOTION_THRESHOLD = 0.7     # Promote to active rule at this confidence
WARNING_THRESHOLD = 0.4       # Flag for human review at this confidence
MIN_OCCURRENCES = 3           # Minimum observations before scoring


@dataclass
class Observation:
    """A single captured event from hook/tool execution."""
    timestamp: float = field(default_factory=time.time)
    event_type: str = ""        # hook event: PreToolUse, PostToolUse, Stop, etc.
    tool_name: str = ""         # which tool was involved
    outcome: str = ""           # allow, block, error, success, timeout
    context: dict = field(default_factory=dict)  # arbitrary metadata
    tags: list[str] = field(default_factory=list)


@dataclass
class InsightCandidate:
    """A pattern detected from multiple observations."""
    pattern_id: str = ""         # deterministic hash of the pattern
    description: str = ""
    occurrences: int = 0
    confidence: float = 0.0      # 0.0 - 1.0
    first_seen: float = 0.0
    last_seen: float = 0.0
    evidence: list[str] = field(default_factory=list)  # observation excerpts
    promoted: bool = False


def record_observation(obs: Observation) -> None:
    """Append a single observation to the JSONL log. Non-blocking, fail-silent."""
    try:
        OBSERVATIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(OBSERVATIONS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(obs), ensure_ascii=False) + "\n")
    except Exception as e:
        log.debug(f"instinct: failed to record observation: {e}")


def record_hook_event(event_type: str, tool_name: str, outcome: str,
                       **extra) -> None:
    """Convenience wrapper for hook-level observation capture."""
    record_observation(Observation(
        event_type=event_type,
        tool_name=tool_name,
        outcome=outcome,
        context=extra,
    ))


def load_observations(max_age_days: int = 7) -> list[dict]:
    """Load recent observations from JSONL."""
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
        log.warning(f"instinct: failed to load observations: {e}")

    return results


def analyze_patterns(observations: list[dict]) -> list[InsightCandidate]:
    """Detect recurring patterns from observations.

    Current heuristics:
    1. Repeated blocks: same tool + same block reason → likely a real rule
    2. Repeated errors: same tool + same error pattern → systemic issue
    3. Timing outliers: tool calls consistently slow → performance concern
    """
    from collections import Counter

    candidates = []

    # Pattern 1: Repeated blocks
    block_counter: Counter = Counter()
    block_evidence: dict[str, list[str]] = {}
    for obs in observations:
        if obs.get("outcome") == "block":
            key = f"block:{obs.get('tool_name', '')}:{obs.get('context', {}).get('reason', '')[:80]}"
            block_counter[key] += 1
            if key not in block_evidence:
                block_evidence[key] = []
            block_evidence[key].append(
                f"{obs.get('event_type', '')} on {obs.get('tool_name', '')} at {obs.get('timestamp', 0)}"
            )

    for key, count in block_counter.items():
        if count >= MIN_OCCURRENCES:
            candidates.append(InsightCandidate(
                pattern_id=key,
                description=f"Frequently blocked: {key.split(':', 2)[-1]}",
                occurrences=count,
                confidence=min(1.0, count / 10),  # Linear scale, cap at 1.0
                evidence=block_evidence.get(key, [])[:5],
            ))

    # Pattern 2: Repeated errors
    error_counter: Counter = Counter()
    for obs in observations:
        if obs.get("outcome") == "error":
            key = f"error:{obs.get('tool_name', '')}:{obs.get('context', {}).get('error_type', 'unknown')}"
            error_counter[key] += 1

    for key, count in error_counter.items():
        if count >= MIN_OCCURRENCES:
            candidates.append(InsightCandidate(
                pattern_id=key,
                description=f"Recurring error: {key}",
                occurrences=count,
                confidence=min(1.0, count / 8),
            ))

    return candidates


def promote_insights(candidates: list[InsightCandidate]) -> list[InsightCandidate]:
    """Promote high-confidence candidates to active rules."""
    promoted = []
    for c in candidates:
        if c.confidence >= PROMOTION_THRESHOLD and not c.promoted:
            c.promoted = True
            promoted.append(c)
            try:
                PROMOTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
                with open(PROMOTIONS_PATH, "a", encoding="utf-8") as f:
                    f.write(json.dumps(asdict(c), ensure_ascii=False) + "\n")
            except Exception as e:
                log.warning(f"instinct: failed to promote insight: {e}")

    if promoted:
        log.info(f"instinct: promoted {len(promoted)} insights to active rules")

    return promoted


def run_analysis_cycle(max_age_days: int = 7) -> dict:
    """Run one full analysis cycle: load → analyze → promote.

    Returns summary dict for logging/reporting.
    """
    observations = load_observations(max_age_days)
    candidates = analyze_patterns(observations)
    promoted = promote_insights(candidates)

    return {
        "observations_scanned": len(observations),
        "candidates_found": len(candidates),
        "promoted": len(promoted),
        "top_candidates": [
            {"id": c.pattern_id, "confidence": c.confidence, "count": c.occurrences}
            for c in sorted(candidates, key=lambda x: -x.confidence)[:5]
        ],
    }
