"""Growth Loops — Three-ring feedback system.

Stolen from proactive-agent v3.1.0 (Round 23 Pattern D), adapted for Orchestrator's
department architecture + learnings infrastructure.

Three independent loops that form a self-reinforcing flywheel:
  1. Curiosity Loop    — proactive questions to understand the user → user_profile
  2. Pattern Loop      — track repeated requests → suggest automation at ≥3
  3. Outcome Loop      — record decisions → follow up after 7 days

Each loop's output feeds the next: curiosity reveals patterns, patterns drive
decisions, decisions get tracked for outcomes, outcomes refine curiosity.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

log = logging.getLogger(__name__)


# ── Data types ─────────────────────────────────────────────

@dataclass
class CuriosityGap:
    """Something we don't know about the user that would improve service."""
    domain: str          # e.g., "workflow", "preferences", "goals", "tools"
    question: str        # The actual question to ask
    priority: str = "medium"  # high | medium | low
    rationale: str = ""  # Why this matters


@dataclass
class PatternSignal:
    """A repeated request pattern detected in task history."""
    pattern_key: str
    description: str
    occurrences: int
    first_seen: str
    last_seen: str
    examples: list[str] = field(default_factory=list)
    automation_suggestion: str = ""


@dataclass
class DecisionFollowup:
    """A decision due for outcome review."""
    decision_id: int
    decision: str
    context: str
    days_since: int
    alternatives: list[str] = field(default_factory=list)


@dataclass
class GrowthStatus:
    """Compact status of all three loops for SessionStart injection."""
    curiosity_pending: int = 0
    curiosity_total_answered: int = 0
    patterns_hot: int = 0
    decisions_due: int = 0
    decisions_pending: int = 0
    next_curiosity: str = ""
    top_pattern: str = ""
    top_decision_due: str = ""

    def format_injection(self) -> str:
        """Format as a compact block for SessionStart prompt injection."""
        lines = ["## Growth Loops Status"]

        # Curiosity
        if self.next_curiosity:
            lines.append(f"🔍 Curiosity: {self.curiosity_pending} pending | "
                         f"Next: {self.next_curiosity}")
        else:
            lines.append(f"🔍 Curiosity: {self.curiosity_total_answered} answered, "
                         f"no new questions queued")

        # Patterns
        if self.patterns_hot > 0:
            lines.append(f"🔄 Patterns: {self.patterns_hot} automation candidate(s) | "
                         f"Top: {self.top_pattern}")
        else:
            lines.append("🔄 Patterns: no hot patterns")

        # Decisions
        if self.decisions_due > 0:
            lines.append(f"📋 Decisions: {self.decisions_due} due for follow-up | "
                         f"Next: {self.top_decision_due}")
        elif self.decisions_pending > 0:
            lines.append(f"📋 Decisions: {self.decisions_pending} tracking (none due yet)")
        else:
            lines.append("📋 Decisions: none tracked")

        return "\n".join(lines)


# ── Curiosity Loop ─────────────────────────────────────────

# Knowledge domains and seed questions.
# These are NOT asked all at once — the loop picks 1 per session based on gaps.
CURIOSITY_DOMAINS = {
    "workflow": [
        "What's your typical daily workflow when starting a coding session?",
        "Which tasks do you find most tedious or repetitive?",
        "Do you prefer to work on one project deeply or switch between several?",
    ],
    "tools": [
        "Are there any tools or shortcuts you wish Orchestrator supported?",
        "What's your IDE setup beyond VS Code?",
        "Do you use any automation tools outside of Orchestrator?",
    ],
    "goals": [
        "What's the most important thing you want to accomplish this month?",
        "Which project is your current top priority?",
        "What would make Orchestrator 10x more useful to you?",
    ],
    "preferences": [
        "How do you prefer to review code changes — diff, PR, or inline?",
        "Morning or late-night coding sessions?",
        "Do you prefer detailed explanations or just the result?",
    ],
    "pain_points": [
        "What breaks most often in your workflow?",
        "What's the most annoying thing about the current Orchestrator setup?",
        "Which collector or feature disappoints you most?",
    ],
}


class CuriosityLoop:
    """Generates and manages proactive questions about the user."""

    def __init__(self, db):
        self.db = db

    def get_next_question(self) -> CuriosityGap | None:
        """Pick the best next curiosity question to ask.

        Strategy: check which domains have the fewest answers,
        then pick from pending questions in the least-covered domain.
        """
        pending = self.db.get_pending_curiosity(limit=1)
        if pending:
            q = pending[0]
            return CuriosityGap(
                domain=q["domain"],
                question=q["question"],
                priority="medium",
            )
        return None

    def seed_questions(self, exclude_domains: list[str] | None = None) -> int:
        """Seed the curiosity queue with questions from under-represented domains."""
        stats = self._domain_coverage()
        exclude = set(exclude_domains or [])
        seeded = 0

        # Find domains with zero coverage first, then lowest
        for domain in sorted(stats, key=lambda d: stats[d]):
            if domain in exclude:
                continue
            if stats[domain] >= 2:
                continue  # Already have enough from this domain
            for q in CURIOSITY_DOMAINS.get(domain, []):
                result = self.db.add_curiosity_question(q, domain=domain)
                if result is not None:
                    seeded += 1
                    break  # One per domain per seed round
        return seeded

    def _domain_coverage(self) -> dict[str, int]:
        """Count answered questions per domain."""
        coverage = {d: 0 for d in CURIOSITY_DOMAINS}
        with self.db._connect() as conn:
            rows = conn.execute(
                "SELECT domain, COUNT(*) as cnt FROM growth_curiosity "
                "WHERE status = 'answered' GROUP BY domain"
            ).fetchall()
        for r in rows:
            if r["domain"] in coverage:
                coverage[r["domain"]] = r["cnt"]
        return coverage


# ── Pattern Recognition Loop ──────────────────────────────

class PatternRecognitionLoop:
    """Detects repeated request patterns and suggests automation.

    Leverages the existing learnings table with entry_type='request_pattern'.
    The key insight: we DON'T try to do NLP clustering here — we let the
    agent (or Stop hook) tag requests with pattern keys, and we just count.
    """

    AUTOMATION_THRESHOLD = 3

    def __init__(self, db):
        self.db = db

    def record_request(self, pattern_key: str, description: str, detail: str = "") -> int:
        """Record a request pattern occurrence. Uses learnings infrastructure."""
        return self.db.add_learning(
            pattern_key=f"req:{pattern_key}",
            rule=description,
            detail=detail,
            area="growth",
            source_type="request",
            entry_type="request_pattern",
        )

    def get_hot_patterns(self) -> list[PatternSignal]:
        """Get patterns that have crossed the automation threshold."""
        raw = self.db.get_request_patterns(threshold=self.AUTOMATION_THRESHOLD)
        return [
            PatternSignal(
                pattern_key=r["pattern_key"],
                description=r["rule"],
                occurrences=r["recurrence"],
                first_seen=r.get("first_seen", ""),
                last_seen=r.get("last_seen", ""),
            )
            for r in raw
        ]

    def get_candidates(self) -> list[PatternSignal]:
        """Get automation candidates — hot patterns not yet actioned."""
        raw = self.db.get_automation_candidates(threshold=self.AUTOMATION_THRESHOLD)
        return [
            PatternSignal(
                pattern_key=r["pattern_key"],
                description=r["rule"],
                occurrences=r["recurrence"],
                first_seen=r.get("first_seen", ""),
                last_seen=r.get("last_seen", ""),
            )
            for r in raw
        ]

    def dismiss_pattern(self, pattern_key: str) -> None:
        """Mark a pattern as dismissed (user said don't automate this)."""
        with self.db._connect() as conn:
            conn.execute(
                "UPDATE learnings SET status = 'retired' "
                "WHERE pattern_key = ? AND entry_type = 'request_pattern'",
                (pattern_key,),
            )

    def mark_automated(self, pattern_key: str) -> None:
        """Mark a pattern as automated (skill/hook/cron was created)."""
        with self.db._connect() as conn:
            conn.execute(
                "UPDATE learnings SET status = 'promoted' "
                "WHERE pattern_key = ? AND entry_type = 'request_pattern'",
                (pattern_key,),
            )


# ── Outcome Tracking Loop ─────────────────────────────────

class OutcomeTrackingLoop:
    """Tracks major decisions and schedules follow-up reviews.

    The idea: when a significant decision is made (architecture choice,
    tool selection, approach pivot), record it. 7 days later, check:
    did it work out? Did reality match expectations?
    """

    def __init__(self, db):
        self.db = db

    def record_decision(
        self,
        decision: str,
        context: str = "",
        alternatives: list[str] | None = None,
        followup_days: int = 7,
        source_session: str = "",
    ) -> int:
        return self.db.add_decision(
            decision=decision,
            context=context,
            alternatives=alternatives,
            followup_days=followup_days,
            source_session=source_session,
        )

    def get_due_followups(self) -> list[DecisionFollowup]:
        """Get decisions that are past their follow-up date."""
        raw = self.db.get_decisions_due()
        now = datetime.now(timezone.utc)
        results = []
        for r in raw:
            created = datetime.fromisoformat(r["created_at"])
            days_since = (now - created).days
            alts = []
            try:
                alts = json.loads(r.get("alternatives", "[]"))
            except (json.JSONDecodeError, TypeError):
                pass
            results.append(DecisionFollowup(
                decision_id=r["id"],
                decision=r["decision"],
                context=r.get("context", ""),
                days_since=days_since,
                alternatives=alts,
            ))
        return results

    def complete_followup(self, decision_id: int, outcome: str, confirmed: bool = True) -> None:
        status = "confirmed" if confirmed else "revised"
        self.db.followup_decision(decision_id, outcome, new_status=status)

    def get_recent_decisions(self, days: int = 30) -> list[dict]:
        return self.db.get_recent_decisions(days=days)


# ── Orchestrator (combines all three) ─────────────────────

class GrowthLoops:
    """Top-level coordinator for all three growth loops."""

    def __init__(self, db):
        self.db = db
        self.curiosity = CuriosityLoop(db)
        self.patterns = PatternRecognitionLoop(db)
        self.outcomes = OutcomeTrackingLoop(db)

    def get_status(self) -> GrowthStatus:
        """Build a compact status for SessionStart injection."""
        summary = self.db.get_growth_summary()
        status = GrowthStatus(
            curiosity_pending=summary["curiosity"]["pending"],
            curiosity_total_answered=summary["curiosity"]["answered"],
            patterns_hot=summary["patterns"]["automation_candidates"],
            decisions_due=summary["decisions"]["due"],
            decisions_pending=summary["decisions"]["pending"],
        )

        # Enrich with specifics
        next_q = self.curiosity.get_next_question()
        if next_q:
            status.next_curiosity = next_q.question

        candidates = self.patterns.get_candidates()
        if candidates:
            top = candidates[0]
            status.top_pattern = f"{top.description} (×{top.occurrences})"

        due = self.outcomes.get_due_followups()
        if due:
            top = due[0]
            status.top_decision_due = f"{top.decision} ({top.days_since}d ago)"

        return status

    def session_start_injection(self) -> str:
        """Generate the text block to inject at SessionStart.

        Returns empty string if all loops are idle (no noise).
        """
        status = self.get_status()
        has_activity = (
            status.curiosity_pending > 0
            or status.patterns_hot > 0
            or status.decisions_due > 0
        )
        if not has_activity:
            return ""
        return status.format_injection()

    def seed_if_empty(self) -> int:
        """Seed curiosity questions if the queue is empty. Called on first boot."""
        pending = self.db.get_pending_curiosity(limit=1)
        if not pending:
            return self.curiosity.seed_questions()
        return 0
