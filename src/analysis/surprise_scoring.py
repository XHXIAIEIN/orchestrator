"""
Surprise Scoring — systematic multi-factor novelty detection.

R45c steal from graphify's surprise scoring. Replaces LLM free-form
blind_spots with structured, reproducible scoring.

Five factors (adapted from graphify's graph domain to behavioral domain):
    1. Confidence weight: AMBIGUOUS edges are more surprising than EXTRACTED
    2. Cross-time:       night activity vs day, weekday vs weekend
    3. Cross-project:    behavior from project A appearing in project B
    4. Frequency shift:  low-freq pattern suddenly becoming high-freq (or reverse)
    5. Peripheral→hub:   minor topic suddenly connecting to core activity

Each surprise carries a mandatory `why` explanation — not just "this is unusual"
but specifically what makes it surprising and what it might mean.
"""

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SurpriseSignal:
    """A single surprising observation with structured evidence."""
    factor: str          # Which factor triggered: confidence|cross_time|cross_project|freq_shift|peripheral_hub
    score: float         # 0.0-1.0, higher = more surprising
    description: str     # What was observed
    why: str             # Why it's surprising (mandatory, not decoration)
    evidence: dict = field(default_factory=dict)  # Raw data backing the claim


@dataclass
class SurpriseReport:
    """Aggregated surprise analysis for a time period."""
    signals: list[SurpriseSignal]
    top_surprises: list[SurpriseSignal]  # Sorted by score, deduped
    period: str  # "daily" or "periodic"
    computed_at: str = ""

    def to_dict(self) -> dict:
        return {
            "period": self.period,
            "computed_at": self.computed_at,
            "total_signals": len(self.signals),
            "top_surprises": [
                {
                    "factor": s.factor,
                    "score": round(s.score, 3),
                    "description": s.description,
                    "why": s.why,
                }
                for s in self.top_surprises
            ],
        }


# ---------------------------------------------------------------------------
# Factor scoring functions
# ---------------------------------------------------------------------------

def score_cross_time(events: list[dict]) -> list[SurpriseSignal]:
    """Detect unusual time-of-day patterns.

    Surprising when: activity concentrated in atypical hours
    (e.g., coding at 3am when usually 9-6, or sudden weekend burst).
    """
    signals = []
    if not events:
        return signals

    hour_counts = Counter()
    weekend_count = 0
    weekday_count = 0

    for e in events:
        try:
            dt = datetime.fromisoformat(e.get("occurred_at", ""))
            hour_counts[dt.hour] += 1
            if dt.weekday() >= 5:
                weekend_count += 1
            else:
                weekday_count += 1
        except (ValueError, TypeError):
            continue

    total = sum(hour_counts.values())
    if total < 5:
        return signals

    # Night owl detection (0-5am activity)
    night_hours = sum(hour_counts.get(h, 0) for h in range(0, 6))
    night_ratio = night_hours / total if total else 0
    if night_ratio > 0.15:
        signals.append(SurpriseSignal(
            factor="cross_time",
            score=min(1.0, night_ratio * 2),
            description=f"凌晨活动占比 {night_ratio:.0%}（{night_hours}/{total} 条事件在 0-5 点）",
            why="正常作息下凌晨活动应低于 10%，高占比可能意味着赶工期、失眠、或时区切换",
            evidence={"night_hours": night_hours, "total": total, "ratio": night_ratio},
        ))

    # Weekend surge detection
    if weekday_count > 0:
        # Expected weekend ratio is ~2/7 ≈ 0.286
        weekend_ratio = weekend_count / (weekend_count + weekday_count)
        if weekend_ratio > 0.5:
            signals.append(SurpriseSignal(
                factor="cross_time",
                score=min(1.0, (weekend_ratio - 0.286) * 2),
                description=f"周末活动占比 {weekend_ratio:.0%}（通常应为 ~29%）",
                why="周末活动远超工作日，可能是紧急项目、个人项目冲刺、或工作节奏异常",
                evidence={"weekend": weekend_count, "weekday": weekday_count},
            ))

    return signals


def score_cross_project(events: list[dict]) -> list[SurpriseSignal]:
    """Detect cross-project behavioral leaks.

    Surprising when: a pattern typical of project A appears in project B,
    or a new source/domain suddenly appears.
    """
    signals = []
    if not events:
        return signals

    # Group by source
    by_source: dict[str, int] = Counter()
    by_source_recent: dict[str, int] = Counter()  # Last 25% of events

    for e in events:
        src = e.get("source", "unknown")
        by_source[src] += 1

    if len(events) > 8:
        recent_slice = events[len(events) * 3 // 4:]
        for e in recent_slice:
            by_source_recent[e.get("source", "unknown")] += 1

    total = sum(by_source.values())
    if total < 5:
        return signals

    # New source detection: source appears only in recent slice
    for src, recent_count in by_source_recent.items():
        full_count = by_source.get(src, 0)
        # If >80% of this source's events are in the recent 25%, it's "new"
        if full_count >= 3 and recent_count / full_count > 0.8:
            signals.append(SurpriseSignal(
                factor="cross_project",
                score=0.7,
                description=f"新数据源 '{src}' 突然出现（{recent_count}/{full_count} 条集中在最近）",
                why=f"'{src}' 之前几乎没有活动，突然集中出现可能意味着新项目启动或兴趣转向",
                evidence={"source": src, "recent": recent_count, "total": full_count},
            ))

    # Source diversity shift
    source_count = len(by_source)
    if source_count >= 5:
        # High source diversity might indicate scattered attention
        top_source_ratio = max(by_source.values()) / total
        if top_source_ratio < 0.25:
            signals.append(SurpriseSignal(
                factor="cross_project",
                score=0.5,
                description=f"注意力分散：{source_count} 个数据源，最大占比仅 {top_source_ratio:.0%}",
                why="没有明确主线，可能处于探索期或多任务切换过于频繁",
                evidence={"sources": source_count, "top_ratio": top_source_ratio},
            ))

    return signals


def score_frequency_shift(events: list[dict]) -> list[SurpriseSignal]:
    """Detect sudden frequency changes in activity patterns.

    Surprising when: something that was rare becomes frequent, or vice versa.
    Splits event window into halves and compares source distributions.
    """
    signals = []
    if len(events) < 10:
        return signals

    mid = len(events) // 2
    first_half = Counter(e.get("source", "unknown") for e in events[:mid])
    second_half = Counter(e.get("source", "unknown") for e in events[mid:])

    all_sources = set(first_half) | set(second_half)
    first_total = sum(first_half.values()) or 1
    second_total = sum(second_half.values()) or 1

    for src in all_sources:
        r1 = first_half.get(src, 0) / first_total
        r2 = second_half.get(src, 0) / second_total

        # Significant increase
        if r2 > 0.15 and r1 < 0.05:
            signals.append(SurpriseSignal(
                factor="freq_shift",
                score=min(1.0, (r2 - r1) * 3),
                description=f"'{src}' 从占比 {r1:.0%} 飙升至 {r2:.0%}",
                why=f"'{src}' 活动突然密集，前半段几乎没有、后半段成为主力——可能是新需求驱动或紧急应对",
                evidence={"source": src, "ratio_before": r1, "ratio_after": r2},
            ))

        # Significant decrease
        if r1 > 0.15 and r2 < 0.05:
            signals.append(SurpriseSignal(
                factor="freq_shift",
                score=min(1.0, (r1 - r2) * 3),
                description=f"'{src}' 从占比 {r1:.0%} 骤降至 {r2:.0%}",
                why=f"'{src}' 活动突然消失——可能是完成了、放弃了、或被更紧急的事打断",
                evidence={"source": src, "ratio_before": r1, "ratio_after": r2},
            ))

    return signals


def score_peripheral_to_hub(events: list[dict]) -> list[SurpriseSignal]:
    """Detect when a minor topic suddenly becomes central.

    Uses title/content keyword frequency: a keyword that was low-frequency
    suddenly appearing in many events is a peripheral→hub transition.
    """
    signals = []
    if len(events) < 10:
        return signals

    # Extract keywords from titles
    mid = len(events) // 2
    first_keywords: Counter = Counter()
    second_keywords: Counter = Counter()

    for e in events[:mid]:
        title = e.get("title", "")
        words = _extract_significant_words(title)
        first_keywords.update(words)

    for e in events[mid:]:
        title = e.get("title", "")
        words = _extract_significant_words(title)
        second_keywords.update(words)

    first_total = sum(first_keywords.values()) or 1
    second_total = sum(second_keywords.values()) or 1

    # Find keywords that jumped from peripheral to central
    for word, count2 in second_keywords.most_common(20):
        count1 = first_keywords.get(word, 0)
        r1 = count1 / first_total
        r2 = count2 / second_total

        if r2 > 0.05 and r1 < 0.01 and count2 >= 3:
            signals.append(SurpriseSignal(
                factor="peripheral_hub",
                score=min(1.0, r2 * 5),
                description=f"关键词 '{word}' 从边缘变核心（{count1}→{count2} 次出现）",
                why=f"'{word}' 之前几乎没被提到，现在成为高频词——可能反映了新的关注点或突发事件",
                evidence={"word": word, "before": count1, "after": count2},
            ))

    return signals


def score_confidence_weight(triples: list[dict]) -> list[SurpriseSignal]:
    """Score based on knowledge graph confidence tags (R45c P0#1 integration).

    AMBIGUOUS edges connecting important entities are the most surprising —
    they represent uncertain knowledge that might reveal hidden patterns.
    """
    signals = []
    if not triples:
        return signals

    ambiguous = [t for t in triples if t.get("confidence_tag") == "AMBIGUOUS"]
    if not ambiguous:
        return signals

    total = len(triples)
    amb_ratio = len(ambiguous) / total

    if amb_ratio > 0.3:
        signals.append(SurpriseSignal(
            factor="confidence",
            score=min(1.0, amb_ratio * 1.5),
            description=f"知识图谱中 {amb_ratio:.0%} 的关系标记为 AMBIGUOUS（{len(ambiguous)}/{total}）",
            why="高比例的模糊关系说明系统对这段时间的行为理解不足——要么数据质量差，要么行为本身在变化",
            evidence={"ambiguous": len(ambiguous), "total": total},
        ))

    # Individual high-value ambiguous edges
    for t in ambiguous[:3]:
        subj = t.get("subject", "?")
        pred = t.get("predicate", "?")
        obj = t.get("object", "?")
        signals.append(SurpriseSignal(
            factor="confidence",
            score=0.6,
            description=f"模糊关系: {subj} --{pred}--> {obj}",
            why=f"这条关系被标记为 AMBIGUOUS，意味着 '{subj}' 和 '{obj}' 之间的 '{pred}' 关系不确定——值得进一步验证",
            evidence={"subject": subj, "predicate": pred, "object": obj},
        ))

    return signals


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Common words to skip in keyword extraction
_SKIP_WORDS = frozenset(
    "的 了 在 是 我 有 和 就 不 人 都 一 上 也 很 到 说 要 去 你 会 着 "
    "the a an is are was were be to of in for on with at by from as "
    "and or but not this that it its".split()
)


def _extract_significant_words(text: str) -> list[str]:
    """Extract meaningful words from text for keyword analysis."""
    import re
    tokens = re.findall(r"[a-zA-Z0-9_\-]+|[\u4e00-\u9fff]{2,}", text.lower())
    return [t for t in tokens if t not in _SKIP_WORDS and len(t) > 1]


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------

def compute_surprise_report(
    events: list[dict],
    triples: list[dict] | None = None,
    period: str = "periodic",
    top_k: int = 5,
) -> SurpriseReport:
    """Run all 5 surprise factors and produce a ranked report.

    Args:
        events: Recent events from EventsDB
        triples: Optional KG triples for confidence-weight scoring
        period: "daily" or "periodic"
        top_k: Max number of top surprises to return

    Returns:
        SurpriseReport with all signals and top-k ranked surprises
    """
    all_signals: list[SurpriseSignal] = []

    # Run all factors
    all_signals.extend(score_cross_time(events))
    all_signals.extend(score_cross_project(events))
    all_signals.extend(score_frequency_shift(events))
    all_signals.extend(score_peripheral_to_hub(events))
    if triples:
        all_signals.extend(score_confidence_weight(triples))

    # Deduplicate: same factor + similar description → keep highest score
    deduped = _deduplicate_signals(all_signals)

    # Sort by score descending
    deduped.sort(key=lambda s: s.score, reverse=True)

    report = SurpriseReport(
        signals=all_signals,
        top_surprises=deduped[:top_k],
        period=period,
        computed_at=datetime.now().isoformat(),
    )

    log.info(
        "Surprise scoring: %d signals → %d deduped, top score %.3f",
        len(all_signals),
        len(deduped),
        deduped[0].score if deduped else 0,
    )

    return report


def _deduplicate_signals(signals: list[SurpriseSignal]) -> list[SurpriseSignal]:
    """Deduplicate signals by factor + evidence overlap.

    Same factor about the same source/word → keep the higher-scored one.
    Prevents god-node flooding (graphify's community pair dedup).
    """
    seen: dict[str, SurpriseSignal] = {}

    for s in signals:
        # Build dedup key from factor + primary evidence
        key_parts = [s.factor]
        if "source" in s.evidence:
            key_parts.append(str(s.evidence["source"]))
        elif "word" in s.evidence:
            key_parts.append(str(s.evidence["word"]))
        elif "subject" in s.evidence:
            key_parts.append(f"{s.evidence['subject']}_{s.evidence.get('predicate', '')}")

        key = "|".join(key_parts)

        if key not in seen or s.score > seen[key].score:
            seen[key] = s

    return list(seen.values())
