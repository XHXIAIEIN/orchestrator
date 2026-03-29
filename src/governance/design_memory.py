"""Design Memory — stolen from gstack.

Accumulates aesthetic preferences and design decisions over time.
When touching frontend/UI code, these preferences are loaded as
context so the system develops consistent visual taste.

Stores:
- Color palette decisions (approved colors, rejected colors)
- Layout patterns (spacing, alignment conventions)
- Component styles (button styles, card patterns)
- Typography choices
- Anti-patterns (things explicitly rejected)
- Reference screenshots/descriptions of approved designs

Usage:
    memory = DesignMemory()
    memory.record_decision(
        category="color",
        decision="Use slate-800 for primary text, not pure black",
        reason="Pure black is too harsh on light backgrounds",
        approved=True,
    )
    memory.record_decision(
        category="layout",
        decision="Cards use 16px padding, 8px gap between elements",
        approved=True,
    )

    # When generating UI:
    context = memory.to_prompt_context(categories=["color", "layout"])
"""
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class DesignDecision:
    """A recorded design decision."""
    id: int
    category: str        # color, layout, typography, component, animation, anti-pattern
    decision: str        # what was decided
    reason: str = ""     # why
    approved: bool = True  # True = do this, False = don't do this
    source: str = ""     # where this came from (PR, review, user directive)
    tags: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    confidence: float = 1.0  # 0-1, decays if contradicted

    @property
    def is_anti_pattern(self) -> bool:
        return not self.approved or self.category == "anti-pattern"


VALID_CATEGORIES = {
    "color", "layout", "typography", "component",
    "animation", "spacing", "iconography", "anti-pattern",
    "general",
}


class DesignMemory:
    """Accumulate and retrieve design preferences."""

    def __init__(self):
        self._decisions: list[DesignDecision] = []
        self._counter = 0

    def record_decision(self, category: str, decision: str,
                        reason: str = "", approved: bool = True,
                        source: str = "", tags: list[str] = None,
                        confidence: float = 1.0) -> DesignDecision:
        """Record a design decision."""
        if category not in VALID_CATEGORIES:
            category = "general"

        self._counter += 1
        entry = DesignDecision(
            id=self._counter,
            category=category,
            decision=decision,
            reason=reason,
            approved=approved,
            source=source,
            tags=tags or [],
            confidence=confidence,
        )
        self._decisions.append(entry)
        action = "approved" if approved else "rejected"
        log.info(f"design_memory: {action} [{category}] {decision[:80]}")
        return entry

    def record_anti_pattern(self, description: str, reason: str = "",
                            source: str = "") -> DesignDecision:
        """Shortcut to record something to explicitly avoid."""
        return self.record_decision(
            category="anti-pattern",
            decision=description,
            reason=reason,
            approved=False,
            source=source,
        )

    def get_decisions(self, category: str = None,
                      approved_only: bool = False,
                      min_confidence: float = 0.0) -> list[DesignDecision]:
        """Query decisions with optional filters."""
        results = self._decisions
        if category:
            results = [d for d in results if d.category == category]
        if approved_only:
            results = [d for d in results if d.approved]
        if min_confidence > 0:
            results = [d for d in results if d.confidence >= min_confidence]
        return results

    def get_anti_patterns(self) -> list[DesignDecision]:
        """Get all things to explicitly avoid."""
        return [d for d in self._decisions if d.is_anti_pattern]

    def contradict(self, decision_id: int, reason: str = ""):
        """Mark a decision as contradicted (reduces confidence)."""
        for d in self._decisions:
            if d.id == decision_id:
                d.confidence = max(0, d.confidence - 0.3)
                if reason:
                    d.reason += f" [contradicted: {reason}]"
                log.info(f"design_memory: contradicted #{decision_id}, confidence now {d.confidence}")
                return

    def to_prompt_context(self, categories: list[str] = None,
                          max_items: int = 30) -> str:
        """Generate design context for prompt injection.

        Returns a structured block of design preferences suitable
        for injecting into agent prompts when doing UI work.
        """
        lines = ["## Design Memory — Accumulated Preferences", ""]

        cats = categories or list(VALID_CATEGORIES)
        count = 0

        for cat in cats:
            decisions = self.get_decisions(category=cat, min_confidence=0.3)
            if not decisions:
                continue

            lines.append(f"### {cat.title()}")
            dos = [d for d in decisions if d.approved]
            donts = [d for d in decisions if not d.approved]

            if dos:
                lines.append("**Do:**")
                for d in dos[:max_items]:
                    line = f"- {d.decision}"
                    if d.reason:
                        line += f" — {d.reason}"
                    lines.append(line)
                    count += 1

            if donts:
                lines.append("**Don't:**")
                for d in donts[:max_items]:
                    line = f"- ~~{d.decision}~~"
                    if d.reason:
                        line += f" — {d.reason}"
                    lines.append(line)
                    count += 1

            lines.append("")
            if count >= max_items:
                break

        if count == 0:
            return ""

        return "\n".join(lines)

    def save_to_file(self, path: str | Path):
        """Save design memory to a JSON file."""
        data = [{
            "id": d.id, "category": d.category,
            "decision": d.decision, "reason": d.reason,
            "approved": d.approved, "source": d.source,
            "tags": d.tags, "confidence": d.confidence,
            "created_at": d.created_at,
        } for d in self._decisions]

        Path(path).write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info(f"design_memory: saved {len(data)} decisions to {path}")

    def load_from_file(self, path: str | Path):
        """Load design memory from a JSON file."""
        p = Path(path)
        if not p.exists():
            return

        data = json.loads(p.read_text(encoding="utf-8"))
        for entry in data:
            self._counter += 1
            self._decisions.append(DesignDecision(
                id=entry.get("id", self._counter),
                category=entry.get("category", "general"),
                decision=entry.get("decision", ""),
                reason=entry.get("reason", ""),
                approved=entry.get("approved", True),
                source=entry.get("source", ""),
                tags=entry.get("tags", []),
                confidence=entry.get("confidence", 1.0),
                created_at=entry.get("created_at", time.time()),
            ))
        log.info(f"design_memory: loaded {len(data)} decisions from {path}")

    def get_stats(self) -> dict:
        approved = sum(1 for d in self._decisions if d.approved)
        anti = len(self.get_anti_patterns())
        cats = {}
        for d in self._decisions:
            cats[d.category] = cats.get(d.category, 0) + 1
        return {
            "total": len(self._decisions),
            "approved": approved,
            "anti_patterns": anti,
            "by_category": cats,
        }
