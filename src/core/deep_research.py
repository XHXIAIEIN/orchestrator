"""Deep Research — multi-round iterative search and synthesis.

Manages a research session: multiple rounds of queries, accumulated findings,
deduplication, and synthesis into a coherent result.
Inspired by Firecrawl's ResearchStateManager.
"""

import time
from dataclasses import dataclass, field
from enum import Enum


class ResearchStatus(Enum):
    PLANNING = "planning"
    SEARCHING = "searching"
    ANALYZING = "analyzing"
    SYNTHESIZING = "synthesizing"
    COMPLETE = "complete"


@dataclass
class Finding:
    """A single research finding."""
    text: str
    source: str
    confidence: float  # 0-1
    round_num: int
    tags: list[str] = field(default_factory=list)
    dedup_key: str = ""  # For deduplication

    def __post_init__(self):
        if not self.dedup_key:
            # Simple dedup: first 50 chars normalized
            self.dedup_key = self.text[:50].lower().strip()


@dataclass
class ResearchRound:
    """One round of research."""
    round_num: int
    queries: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    duration_s: float = 0.0


class ResearchSession:
    """Manage a multi-round research session.

    Usage:
        session = ResearchSession("How does X work?", max_rounds=5)

        while not session.is_complete:
            round = session.start_round()
            queries = session.suggest_queries()
            for q in queries:
                results = search(q)
                session.add_findings(results)
            session.end_round()

        synthesis = session.synthesize()
    """

    def __init__(
        self,
        question: str,
        max_rounds: int = 5,
        max_findings: int = 50,
        queries_per_round: int = 3,
    ):
        self.question = question
        self._max_rounds = max_rounds
        self._max_findings = max_findings
        self._queries_per_round = queries_per_round
        self._rounds: list[ResearchRound] = []
        self._all_findings: list[Finding] = []
        self._seen_dedup_keys: set[str] = set()
        self.status = ResearchStatus.PLANNING
        self._current_round: ResearchRound | None = None

    @property
    def is_complete(self) -> bool:
        return (
            self.status == ResearchStatus.COMPLETE
            or len(self._rounds) >= self._max_rounds
            or len(self._all_findings) >= self._max_findings
        )

    @property
    def round_count(self) -> int:
        return len(self._rounds)

    def start_round(self) -> ResearchRound:
        """Start a new research round."""
        if self.is_complete:
            raise RuntimeError("Research session is complete")

        round_num = len(self._rounds) + 1
        self._current_round = ResearchRound(round_num=round_num)
        self.status = ResearchStatus.SEARCHING
        return self._current_round

    def add_finding(self, text: str, source: str, confidence: float = 0.5, tags: list[str] | None = None):
        """Add a finding, with deduplication."""
        if not self._current_round:
            raise RuntimeError("No active round — call start_round() first")

        finding = Finding(
            text=text, source=source, confidence=confidence,
            round_num=self._current_round.round_num, tags=tags or [],
        )

        # Dedup
        if finding.dedup_key in self._seen_dedup_keys:
            return
        self._seen_dedup_keys.add(finding.dedup_key)

        self._current_round.findings.append(finding)
        self._all_findings.append(finding)

    def end_round(self):
        """End the current round."""
        if self._current_round:
            self._current_round.duration_s = round(time.time() - self._current_round.started_at, 2)
            self._rounds.append(self._current_round)
            self._current_round = None
            self.status = ResearchStatus.ANALYZING

        if self.is_complete:
            self.status = ResearchStatus.COMPLETE

    def suggest_queries(self) -> list[str]:
        """Suggest queries for the current round based on gaps.

        Returns placeholder queries — actual query generation needs LLM.
        """
        # First round: decompose the question
        if not self._rounds:
            return [self.question]

        # Subsequent rounds: return empty (LLM should generate based on gaps)
        return []

    def get_findings(self, min_confidence: float = 0.0) -> list[Finding]:
        """Get all findings above confidence threshold."""
        return [f for f in self._all_findings if f.confidence >= min_confidence]

    def get_summary(self) -> dict:
        return {
            "question": self.question,
            "status": self.status.value,
            "rounds": len(self._rounds),
            "total_findings": len(self._all_findings),
            "high_confidence": len([f for f in self._all_findings if f.confidence >= 0.8]),
            "sources": list(set(f.source for f in self._all_findings)),
        }
