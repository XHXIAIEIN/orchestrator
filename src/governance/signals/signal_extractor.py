"""R72 Evolver: Three-Layer Signal Extraction + Stagnation Detection.

Layer 1 — Regex (deterministic, 0ms):
    Hand-written rules for error types, OS compat, path issues, tool abuse.
    CJK-aware patterns for feature requests and config issues.

Layer 2 — Keyword Scoring (statistical, 0ms):
    Weighted keyword profiles per signal type. Cumulative score must exceed
    threshold to fire. Single keyword hit is never enough → prevents false positives.

Layer 3 — LLM Semantic (expensive, every N cycles):
    Full semantic analysis of corpus summary. Only runs periodically
    to conserve API budget.

Post-processing pipeline:
    1. Priority filter (actionable signals suppress config-only signals)
    2. History dedup (same signal ≥3 times in 8 cycles → suppress)
    3. Force innovation (consecutive repair ≥3 → inject force_innovation)
    4. Empty cycle detection (blast_radius=0 for ≥4 cycles → inject signal)
    5. Saturation degradation (empty cycles ≥5 → switch to steady-state)

Source: yoyo-evolve signals.js (R72 deep steal)
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

log = logging.getLogger(__name__)


# ── Signal Result ──

@dataclass
class ExtractedSignal:
    """A signal extracted from any layer."""
    id: str                          # e.g. "error_loop", "perf_bottleneck"
    source_layer: int                # 1=regex, 2=keyword, 3=llm
    score: float                     # confidence/weight (0-1)
    context: str                     # snippet showing where it was found
    metadata: dict[str, Any] = field(default_factory=dict)
    extracted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def key(self) -> str:
        """Dedup key for history tracking."""
        return self.id


# ── Layer 1: Regex Patterns ──

_REGEX_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    # Error / failure patterns
    ("error_loop", re.compile(
        r"(?:error|exception|traceback|panic|fatal)\b.*\b(?:again|repeat|same|still)",
        re.IGNORECASE,
    ), "error"),
    ("import_error", re.compile(
        r"(?:ModuleNotFoundError|ImportError|cannot find module)",
        re.IGNORECASE,
    ), "error"),
    ("timeout_error", re.compile(
        r"(?:timeout|timed?\s*out|deadline exceeded|ETIMEDOUT)",
        re.IGNORECASE,
    ), "error"),
    ("permission_denied", re.compile(
        r"(?:permission denied|EACCES|403 forbidden|unauthorized)",
        re.IGNORECASE,
    ), "error"),

    # OS / path compatibility
    ("path_issue", re.compile(
        r"(?:FileNotFoundError|ENOENT|no such file|path.*not.*exist)",
        re.IGNORECASE,
    ), "compat"),
    ("encoding_issue", re.compile(
        r"(?:UnicodeDecodeError|UnicodeEncodeError|codec can't|charmap)",
        re.IGNORECASE,
    ), "compat"),

    # Tool abuse patterns
    ("excessive_reads", re.compile(
        r"(?:reading|read)\s+(?:all|every|each)\s+(?:file|line)",
        re.IGNORECASE,
    ), "abuse"),

    # CJK feature requests (zh-CN/zh-TW/ja)
    ("feature_request_cjk", re.compile(
        r"(?:加个功能|做个功能|追加|実装|新增|添加.*功能|能不能.*支持)",
    ), "request"),

    # Config missing
    ("config_missing", re.compile(
        r"(?:config.*not\s+found|missing.*config|no.*\.env|\.yml.*not\s+exist)",
        re.IGNORECASE,
    ), "config"),

    # Deprecation
    ("deprecation", re.compile(
        r"(?:deprecated|DeprecationWarning|will be removed)",
        re.IGNORECASE,
    ), "warning"),
]


def _extract_layer1(text: str) -> list[ExtractedSignal]:
    """Layer 1: Regex extraction — deterministic, ~0ms."""
    signals = []
    for signal_id, pattern, category in _REGEX_PATTERNS:
        for match in pattern.finditer(text):
            start = max(0, match.start() - 40)
            end = min(len(text), match.end() + 40)
            snippet = text[start:end].replace("\n", " ").strip()
            signals.append(ExtractedSignal(
                id=signal_id,
                source_layer=1,
                score=1.0,
                context=snippet,
                metadata={"category": category, "match": match.group()},
            ))
    return signals


# ── Layer 2: Keyword Scoring Profiles ──

@dataclass
class KeywordProfile:
    """Weighted keyword set for a signal type."""
    signal_id: str
    threshold: float
    keywords: dict[str, float]  # keyword → weight

    def score(self, text: str) -> float:
        """Compute cumulative score from keyword hits."""
        text_lower = text.lower()
        total = 0.0
        for kw, weight in self.keywords.items():
            if kw.lower() in text_lower:
                total += weight
        return total


_KEYWORD_PROFILES: list[KeywordProfile] = [
    KeywordProfile("perf_bottleneck", threshold=6.0, keywords={
        "slow": 3.0, "timeout": 4.0, "latency": 3.0, "bottleneck": 4.0,
        "memory": 2.0, "cpu": 2.0, "leak": 3.0, "oom": 5.0,
        "freeze": 4.0, "hang": 4.0, "unresponsive": 4.0,
    }),
    KeywordProfile("test_failure", threshold=5.0, keywords={
        "test": 2.0, "fail": 3.0, "assert": 3.0, "expect": 2.0,
        "broken": 3.0, "regression": 4.0, "flaky": 3.0,
    }),
    KeywordProfile("security_concern", threshold=7.0, keywords={
        "injection": 5.0, "xss": 5.0, "csrf": 5.0, "vulnerability": 4.0,
        "exposed": 3.0, "leak": 3.0, "secret": 4.0, "credential": 4.0,
        "token": 2.0, "password": 3.0,
    }),
    KeywordProfile("dependency_issue", threshold=5.0, keywords={
        "dependency": 3.0, "outdated": 3.0, "incompatible": 4.0,
        "conflict": 3.0, "version": 2.0, "breaking": 4.0, "upgrade": 2.0,
    }),
    KeywordProfile("architecture_smell", threshold=6.0, keywords={
        "circular": 4.0, "coupling": 3.0, "god class": 5.0, "spaghetti": 4.0,
        "monolith": 3.0, "refactor": 2.0, "tech debt": 4.0, "hack": 2.0,
    }),
    KeywordProfile("data_integrity", threshold=6.0, keywords={
        "corrupt": 5.0, "inconsistent": 3.0, "duplicate": 3.0,
        "missing": 2.0, "orphan": 3.0, "stale": 3.0, "drift": 3.0,
    }),
    KeywordProfile("resource_exhaustion", threshold=5.0, keywords={
        "disk full": 5.0, "no space": 5.0, "quota": 3.0, "limit": 2.0,
        "exceeded": 3.0, "exhausted": 4.0, "overflow": 4.0,
    }),
]


def _extract_layer2(text: str) -> list[ExtractedSignal]:
    """Layer 2: Weighted keyword scoring — statistical, ~0ms."""
    signals = []
    for profile in _KEYWORD_PROFILES:
        score = profile.score(text)
        if score >= profile.threshold:
            signals.append(ExtractedSignal(
                id=profile.signal_id,
                source_layer=2,
                score=min(1.0, score / (profile.threshold * 2)),
                context=f"Keyword score {score:.1f} (threshold {profile.threshold})",
                metadata={"cumulative_score": score, "threshold": profile.threshold},
            ))
    return signals


# ── Layer 3: LLM Semantic (stub — caller provides implementation) ──

# Type for LLM analysis callback:
#   fn(corpus_summary: str) -> list[dict] where each dict has {id, score, context}
LLMAnalyzerFn = Callable[[str], list[dict[str, Any]]]


def _extract_layer3(
    text: str,
    analyzer: LLMAnalyzerFn | None = None,
) -> list[ExtractedSignal]:
    """Layer 3: LLM semantic extraction — expensive, use sparingly.

    The actual LLM call is delegated to the caller via analyzer callback.
    This keeps the signal extractor LLM-agnostic.
    """
    if analyzer is None:
        return []

    try:
        results = analyzer(text[:8000])  # cap input to avoid token waste
    except Exception as exc:
        log.warning("layer3_llm_analysis failed: %s", exc)
        return []

    signals = []
    for item in results:
        signals.append(ExtractedSignal(
            id=item.get("id", "llm_signal"),
            source_layer=3,
            score=float(item.get("score", 0.5)),
            context=str(item.get("context", ""))[:200],
            metadata=item.get("metadata", {}),
        ))
    return signals


# ── Post-Processing Pipeline ──

@dataclass
class SignalHistory:
    """Tracks signal occurrences across cycles for dedup and stagnation detection.

    R72 Evolver insight: same signal appearing ≥3 times in 8 cycles is not
    "important" — it's "stuck". Consecutive repair ≥3 should force strategy switch.
    """
    max_cycles: int = 8
    stagnation_threshold: int = 3  # same signal N times → suppress
    repair_loop_threshold: int = 3  # consecutive repairs → force innovation

    _history: deque[set[str]] = field(default_factory=lambda: deque(maxlen=8))
    _consecutive_repairs: int = 0
    _consecutive_empty: int = 0

    def __post_init__(self):
        # deque maxlen must match max_cycles
        object.__setattr__(self, "_history", deque(maxlen=self.max_cycles))

    def record_cycle(
        self, signals: list[ExtractedSignal], blast_radius: int = -1
    ) -> None:
        """Record signals from one cycle."""
        self._history.append({s.key for s in signals})

        # Track consecutive empty cycles (blast_radius == 0)
        if blast_radius == 0:
            self._consecutive_empty += 1
        elif blast_radius > 0:
            self._consecutive_empty = 0

        # Track repair-type signals
        repair_ids = {"error_loop", "import_error", "test_failure"}
        has_repair = any(s.key in repair_ids for s in signals)
        if has_repair:
            self._consecutive_repairs += 1
        else:
            self._consecutive_repairs = 0

    def is_stagnant(self, signal_id: str) -> bool:
        """Check if a signal has appeared too frequently (stagnation)."""
        count = sum(1 for cycle in self._history if signal_id in cycle)
        return count >= self.stagnation_threshold

    @property
    def should_force_innovation(self) -> bool:
        """Consecutive repair signals exceed threshold → force strategy switch."""
        return self._consecutive_repairs >= self.repair_loop_threshold

    @property
    def empty_cycle_count(self) -> int:
        return self._consecutive_empty

    def get_frequency_map(self) -> dict[str, int]:
        """Return signal_id → occurrence count across recent history."""
        freq: dict[str, int] = {}
        for cycle in self._history:
            for sid in cycle:
                freq[sid] = freq.get(sid, 0) + 1
        return freq


def _postprocess(
    signals: list[ExtractedSignal],
    history: SignalHistory,
    blast_radius: int = -1,
) -> list[ExtractedSignal]:
    """Five-stage post-processing pipeline.

    1. Priority filter: actionable signals suppress config-only
    2. History dedup: stagnant signals suppressed
    3. Force innovation: consecutive repair loop detected
    4. Empty cycle detection: no progress for ≥4 cycles
    5. Saturation degradation: ≥5 empty cycles → steady-state signal
    """
    # Record this cycle
    history.record_cycle(signals, blast_radius)

    # Stage 1: Priority filter
    has_actionable = any(
        s.metadata.get("category") in ("error", "abuse") for s in signals
    )
    if has_actionable:
        signals = [
            s for s in signals
            if s.metadata.get("category") != "config"
        ]

    # Stage 2: History dedup — suppress stagnant signals
    fresh_signals = []
    suppressed = []
    for s in signals:
        if history.is_stagnant(s.key):
            suppressed.append(s.key)
        else:
            fresh_signals.append(s)

    if suppressed:
        log.info(
            "signal_postprocess: suppressed stagnant signals: %s",
            ", ".join(set(suppressed)),
        )
    signals = fresh_signals

    # Stage 3: Force innovation on repair loop
    if history.should_force_innovation:
        signals.append(ExtractedSignal(
            id="force_innovation_after_repair_loop",
            source_layer=0,  # synthetic
            score=1.0,
            context=(
                f"Consecutive repair signals for {history._consecutive_repairs} "
                f"cycles. Repair loop detected — switch to innovation strategy."
            ),
            metadata={"synthetic": True, "action": "switch_strategy"},
        ))
        log.warning(
            "signal_postprocess: repair loop detected (%d consecutive), "
            "injecting force_innovation",
            history._consecutive_repairs,
        )

    # Stage 4: Empty cycle detection
    if history.empty_cycle_count >= 4:
        signals.append(ExtractedSignal(
            id="empty_cycle_loop_detected",
            source_layer=0,
            score=0.8,
            context=(
                f"blast_radius=0 for {history.empty_cycle_count} consecutive "
                f"cycles. No meaningful changes being made."
            ),
            metadata={"synthetic": True, "empty_cycles": history.empty_cycle_count},
        ))

    # Stage 5: Saturation degradation
    if history.empty_cycle_count >= 5:
        signals.append(ExtractedSignal(
            id="saturation_steady_state",
            source_layer=0,
            score=0.9,
            context=(
                f"≥5 empty cycles detected. Recommend switching to "
                f"steady-state strategy (maintenance + exploration)."
            ),
            metadata={"synthetic": True, "action": "switch_to_steady_state"},
        ))

    return signals


# ── Main Extractor ──

class SignalExtractor:
    """Three-layer signal extractor with post-processing pipeline.

    Usage:
        extractor = SignalExtractor()

        # Each cycle:
        signals = extractor.extract(text_corpus, blast_radius=3)
        # signals is a list of ExtractedSignal, post-processed

        # Periodic deep analysis (every N cycles):
        signals = extractor.extract(text_corpus, llm_analyzer=my_llm_fn)
    """

    def __init__(
        self,
        history: SignalHistory | None = None,
        custom_regex: list[tuple[str, re.Pattern, str]] | None = None,
        custom_profiles: list[KeywordProfile] | None = None,
    ):
        self.history = history or SignalHistory()
        self._custom_regex = custom_regex or []
        self._custom_profiles = custom_profiles or []
        self._cycle_count = 0
        self._llm_interval = 5  # run LLM every N cycles

    def extract(
        self,
        text: str,
        blast_radius: int = -1,
        llm_analyzer: LLMAnalyzerFn | None = None,
        force_llm: bool = False,
    ) -> list[ExtractedSignal]:
        """Run three-layer extraction + post-processing.

        Args:
            text: The corpus/log/output to analyze.
            blast_radius: Number of files/lines changed this cycle (-1 = unknown).
            llm_analyzer: Optional callback for Layer 3 semantic analysis.
            force_llm: Force Layer 3 even if not on the N-cycle boundary.

        Returns:
            Post-processed list of ExtractedSignal.
        """
        self._cycle_count += 1

        # Layer 1: Regex (always)
        signals = _extract_layer1(text)

        # Add custom regex patterns
        for signal_id, pattern, category in self._custom_regex:
            for match in pattern.finditer(text):
                start = max(0, match.start() - 40)
                end = min(len(text), match.end() + 40)
                snippet = text[start:end].replace("\n", " ").strip()
                signals.append(ExtractedSignal(
                    id=signal_id, source_layer=1, score=1.0,
                    context=snippet,
                    metadata={"category": category, "match": match.group()},
                ))

        # Layer 2: Keyword scoring (always)
        signals.extend(_extract_layer2(text))

        # Add custom profiles
        for profile in self._custom_profiles:
            score = profile.score(text)
            if score >= profile.threshold:
                signals.append(ExtractedSignal(
                    id=profile.signal_id, source_layer=2,
                    score=min(1.0, score / (profile.threshold * 2)),
                    context=f"Custom keyword score {score:.1f}",
                    metadata={"cumulative_score": score},
                ))

        # Layer 3: LLM semantic (periodic or forced)
        if llm_analyzer and (force_llm or self._cycle_count % self._llm_interval == 0):
            signals.extend(_extract_layer3(text, llm_analyzer))

        # Deduplicate by signal ID (keep highest score per ID)
        best: dict[str, ExtractedSignal] = {}
        for s in signals:
            if s.key not in best or s.score > best[s.key].score:
                best[s.key] = s
        signals = list(best.values())

        # Post-processing pipeline
        signals = _postprocess(signals, self.history, blast_radius)

        return signals

    def get_stats(self) -> dict:
        """Return extractor state for diagnostics."""
        return {
            "cycle_count": self._cycle_count,
            "llm_interval": self._llm_interval,
            "history_frequency": self.history.get_frequency_map(),
            "consecutive_repairs": self.history._consecutive_repairs,
            "consecutive_empty": self.history._consecutive_empty,
        }
