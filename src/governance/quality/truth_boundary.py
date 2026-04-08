"""Truth Boundary Guard — paragraph-level evidence provenance audit.

Stolen from DocMason (R45b-P4). Tracks evidence source for every segment
of agent output, detects grounding violations (missing sources, path leakage,
scope mismatches), and produces machine-readable quality reports.

Complements verify_gate.py (task-level gate) with content-level auditing.

Usage:
    from src.governance.quality.truth_boundary import (
        TruthAuditor, GroundingStatus, ScopeMode,
    )

    auditor = TruthAuditor()
    report = auditor.audit(answer_text, sources=[...])
    if report.issue_codes:
        # Answer has grounding problems
        for code in report.issue_codes:
            log.warning(f"Grounding issue: {code}")
"""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

log = logging.getLogger(__name__)


# ── Enums ──

class GroundingStatus(str, Enum):
    """How well-grounded is this segment of text."""
    GROUNDED = "grounded"                    # Fully supported by cited sources
    PARTIALLY_GROUNDED = "partially-grounded"  # Some claims lack sources
    UNRESOLVED = "unresolved"                # No supporting evidence found
    ABSTAINED = "abstained"                  # Explicitly declined to answer


class ScopeMode(str, Enum):
    """How broadly should evidence be drawn."""
    GLOBAL = "global"                  # Any source is acceptable
    SOURCE_SCOPED_HARD = "source-scoped-hard"  # Must use specified source (strict)
    SOURCE_SCOPED_SOFT = "source-scoped-soft"  # Inferred source (permissive)
    COMPARE = "compare"                # Comparison: requires ≥2 sources


# ── Issue codes — machine-readable quality signals ──

ISSUE_CODES = {
    "published-artifacts-gap": "Published sources insufficient to answer the question",
    "source-scope-missing-target-support": "Required source not found in evidence",
    "compare-source-coverage-missing": "Comparison question but <2 sources cited",
    "trace-answer-state-mismatch": "Answer claims grounded but has unresolved segments",
    "absolute-path-leaked": "Local filesystem path exposed in output",
    "no-sources-cited": "Answer makes claims but cites no sources",
    "stale-reference": "Source referenced may be outdated",
}


# ── Data structures ──

@dataclass
class SegmentTrace:
    """Evidence trace for a single paragraph/segment of output."""
    segment_index: int
    text_preview: str           # First 100 chars
    grounding_status: str       # GroundingStatus value
    source_ids: list[str] = field(default_factory=list)
    confidence: float = 0.0     # 0.0-1.0

    @property
    def is_grounded(self) -> bool:
        return self.grounding_status == GroundingStatus.GROUNDED.value


@dataclass
class SourceRecord:
    """A citable source of evidence."""
    source_id: str
    source_type: str            # "file", "database", "api", "user-input", "git-history"
    path_or_ref: str            # Where to find it
    retrieved_at: str = ""      # When it was accessed
    content_hash: str = ""      # For staleness detection


@dataclass
class AuditReport:
    """Complete truth boundary audit of an answer."""
    scope_mode: str
    overall_status: str         # GroundingStatus value
    segment_traces: list[SegmentTrace] = field(default_factory=list)
    sources_used: list[str] = field(default_factory=list)
    issue_codes: list[str] = field(default_factory=list)
    path_leaks: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return len(self.issue_codes) == 0 and len(self.path_leaks) == 0

    @property
    def grounded_ratio(self) -> float:
        if not self.segment_traces:
            return 0.0
        grounded = sum(1 for s in self.segment_traces if s.is_grounded)
        return grounded / len(self.segment_traces)

    def summary(self) -> str:
        """One-line human summary."""
        ratio = self.grounded_ratio
        issues = len(self.issue_codes)
        leaks = len(self.path_leaks)
        return (
            f"Grounding: {ratio:.0%} ({len(self.segment_traces)} segments), "
            f"{issues} issue(s), {leaks} path leak(s)"
        )


# ── Path leakage detection ──

# Match absolute paths: C:\..., D:\..., /home/..., /Users/..., /tmp/...
_ABSOLUTE_PATH_PATTERN = re.compile(
    r'(?<![a-zA-Z])(?:'
    r'[A-Z]:\\[\w\\.\-]+'             # Windows: C:\Users\... (no spaces, no /)
    r'|/(?:home|Users|tmp|var|etc|opt|usr|mnt|d|c)/[\w/.\-]+'  # Unix-like
    r')',
    re.IGNORECASE,
)

# Exclude patterns that look like paths but aren't (URLs, examples)
_PATH_EXCLUDE_PATTERNS = [
    re.compile(r'https?://'),          # URLs
    re.compile(r'ftp://'),
    re.compile(r'file://'),
    re.compile(r'```'),                # Inside code blocks (heuristic)
]


def detect_path_leaks(text: str) -> list[str]:
    """Detect absolute filesystem paths leaked in output text.

    Returns list of leaked path strings. Excludes URLs and code block content.
    """
    leaks = []
    for match in _ABSOLUTE_PATH_PATTERN.finditer(text):
        candidate = match.group(0)
        start = max(0, match.start() - 10)
        context = text[start:match.start()]

        # Skip if preceded by URL scheme
        if any(p.search(context + candidate) for p in _PATH_EXCLUDE_PATTERNS):
            continue

        # Validate it looks like a real path
        try:
            if '\\' in candidate:
                p = PureWindowsPath(candidate)
            else:
                p = PurePosixPath(candidate)
            if p.is_absolute():
                leaks.append(candidate)
        except (ValueError, TypeError):
            continue

    return leaks


# ── Scope mode inference ──

_COMPARE_SIGNALS = [
    "compare", "versus", "vs", "difference between", "how does .* differ",
    "对比", "比较", "和.*的区别", "与.*相比",
]

_SOURCE_SCOPED_SIGNALS = [
    "according to", "from the", "based on the", "in the .* docs",
    "根据", "按照", "来自",
]


def infer_scope_mode(
    question: str,
    *,
    explicit_source: str | None = None,
) -> ScopeMode:
    """Infer the appropriate evidence scope from the question.

    Rules:
    - Compare signals → ScopeMode.COMPARE
    - Explicit source provided → SOURCE_SCOPED_HARD
    - Source-scoping signals in question → SOURCE_SCOPED_SOFT
    - Default → GLOBAL
    """
    q_lower = question.lower()

    # Check comparison signals
    for signal in _COMPARE_SIGNALS:
        if re.search(signal, q_lower):
            return ScopeMode.COMPARE

    # Explicit source
    if explicit_source:
        return ScopeMode.SOURCE_SCOPED_HARD

    # Implicit source scoping
    for signal in _SOURCE_SCOPED_SIGNALS:
        if re.search(signal, q_lower):
            return ScopeMode.SOURCE_SCOPED_SOFT

    return ScopeMode.GLOBAL


# ── Main Auditor ──

class TruthAuditor:
    """Audit agent output for evidence grounding and safety."""

    def audit(
        self,
        answer_text: str,
        *,
        sources: list[SourceRecord] | None = None,
        question: str = "",
        explicit_source: str | None = None,
        segment_traces: list[SegmentTrace] | None = None,
    ) -> AuditReport:
        """Run a full truth boundary audit.

        If segment_traces are provided (from an LLM-based grounding check),
        uses them directly. Otherwise, performs heuristic checks only.

        Args:
            answer_text: The agent's answer to audit.
            sources: Evidence sources that were available.
            question: The original question (for scope inference).
            explicit_source: If the question targeted a specific source.
            segment_traces: Pre-computed per-segment grounding (from LLM).

        Returns:
            AuditReport with issues, traces, and path leaks.
        """
        sources = sources or []
        scope_mode = infer_scope_mode(question, explicit_source=explicit_source)

        # Path leak detection
        path_leaks = detect_path_leaks(answer_text)

        # Build or use segment traces
        if segment_traces is None:
            segment_traces = self._heuristic_segment_traces(answer_text, sources)

        # Detect issue codes
        issue_codes = self._detect_issues(
            scope_mode=scope_mode,
            segment_traces=segment_traces,
            sources=sources,
            path_leaks=path_leaks,
            explicit_source=explicit_source,
        )

        # Determine overall status
        overall = self._overall_status(segment_traces)

        return AuditReport(
            scope_mode=scope_mode.value,
            overall_status=overall.value,
            segment_traces=segment_traces,
            sources_used=[s.source_id for s in sources],
            issue_codes=issue_codes,
            path_leaks=path_leaks,
        )

    def _heuristic_segment_traces(
        self,
        text: str,
        sources: list[SourceRecord],
    ) -> list[SegmentTrace]:
        """Create basic segment traces by splitting on paragraphs.

        Without LLM-based grounding, we can only check:
        - Whether sources exist at all
        - Whether the segment is trivially short (likely grounded)
        """
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        traces = []

        for i, para in enumerate(paragraphs):
            # Heuristic: if we have sources and paragraph is non-trivial,
            # mark as partially-grounded (we can't verify without LLM)
            if not sources:
                status = GroundingStatus.UNRESOLVED
                confidence = 0.0
            elif len(para) < 50:
                # Very short paragraphs (headings, transitions) get a pass
                status = GroundingStatus.GROUNDED
                confidence = 0.8
            else:
                status = GroundingStatus.PARTIALLY_GROUNDED
                confidence = 0.5

            traces.append(SegmentTrace(
                segment_index=i,
                text_preview=para[:100],
                grounding_status=status.value,
                source_ids=[s.source_id for s in sources],
                confidence=confidence,
            ))

        return traces

    def _detect_issues(
        self,
        *,
        scope_mode: ScopeMode,
        segment_traces: list[SegmentTrace],
        sources: list[SourceRecord],
        path_leaks: list[str],
        explicit_source: str | None,
    ) -> list[str]:
        """Detect grounding issue codes."""
        issues = []

        # Path leakage
        if path_leaks:
            issues.append("absolute-path-leaked")

        # No sources at all
        if not sources and segment_traces:
            non_trivial = [s for s in segment_traces if len(s.text_preview) > 50]
            if non_trivial:
                issues.append("no-sources-cited")

        # Source scope violations
        if scope_mode in (ScopeMode.SOURCE_SCOPED_HARD, ScopeMode.SOURCE_SCOPED_SOFT):
            if explicit_source:
                source_ids = {s.source_id for s in sources}
                if explicit_source not in source_ids:
                    issues.append("source-scope-missing-target-support")

        # Comparison coverage
        if scope_mode == ScopeMode.COMPARE:
            if len(sources) < 2:
                issues.append("compare-source-coverage-missing")

        # Self-contradiction: overall says grounded but has unresolved segments
        grounded_count = sum(1 for s in segment_traces if s.is_grounded)
        unresolved_count = sum(
            1 for s in segment_traces
            if s.grounding_status == GroundingStatus.UNRESOLVED.value
        )
        if grounded_count > 0 and unresolved_count > 0:
            # Mixed grounding — not necessarily an issue unless we claim fully grounded
            total = len(segment_traces)
            if grounded_count > total * 0.7 and unresolved_count > 0:
                issues.append("trace-answer-state-mismatch")

        return issues

    def _overall_status(self, traces: list[SegmentTrace]) -> GroundingStatus:
        """Determine overall grounding status from segment traces."""
        if not traces:
            return GroundingStatus.ABSTAINED

        statuses = {t.grounding_status for t in traces}

        if statuses == {GroundingStatus.GROUNDED.value}:
            return GroundingStatus.GROUNDED
        elif GroundingStatus.UNRESOLVED.value in statuses:
            if GroundingStatus.GROUNDED.value in statuses:
                return GroundingStatus.PARTIALLY_GROUNDED
            return GroundingStatus.UNRESOLVED
        else:
            return GroundingStatus.PARTIALLY_GROUNDED


# ── Convenience functions ──

def quick_audit(text: str, question: str = "") -> AuditReport:
    """One-liner audit for simple cases."""
    return TruthAuditor().audit(text, question=question)


def check_path_safety(text: str) -> tuple[bool, list[str]]:
    """Quick check: does this text leak filesystem paths?

    Returns (is_safe, leaked_paths).
    """
    leaks = detect_path_leaks(text)
    return len(leaks) == 0, leaks
