"""Semantic Intent — structured intent representation for Governor dispatch.

Moves beyond string-based intent matching to a structured semantic representation
that captures what the user wants, constraints, and expected output format.
"""

from dataclasses import dataclass, field
from enum import Enum


class IntentType(Enum):
    QUERY = "query"           # Information retrieval
    MUTATE = "mutate"         # Change something
    ANALYZE = "analyze"       # Examine and report
    CREATE = "create"         # Generate new content
    REVIEW = "review"         # Evaluate existing content
    MONITOR = "monitor"       # Ongoing observation
    AUTOMATE = "automate"     # Set up recurring task


@dataclass
class SemanticIntent:
    """Structured representation of user intent."""

    type: IntentType
    subject: str              # What is the intent about? ("codebase", "database", "UI")
    action: str               # Specific action ("fix bug", "add feature", "check health")
    constraints: list[str] = field(default_factory=list)  # "no breaking changes", "under 100ms"
    output_format: str = "text"  # "text", "code", "json", "table", "chart"
    urgency: str = "normal"   # "critical", "high", "normal", "low"
    confidence: float = 1.0   # How confident are we in this classification?
    raw_text: str = ""        # Original user input

    @classmethod
    def from_text(cls, text: str) -> "SemanticIntent":
        """Classify intent from free-form text (heuristic, no LLM).

        This is a fast first-pass. Complex cases should use LLM classification.
        """
        text_lower = text.lower()

        # Type detection
        if any(w in text_lower for w in ["fix", "bug", "error", "broken", "修复", "修"]):
            intent_type = IntentType.MUTATE
            action = "fix"
        elif any(w in text_lower for w in ["add", "create", "new", "build", "写", "创建", "新建"]):
            intent_type = IntentType.CREATE
            action = "create"
        elif any(w in text_lower for w in ["review", "check", "audit", "检查", "审查"]):
            intent_type = IntentType.REVIEW
            action = "review"
        elif any(w in text_lower for w in ["analyze", "why", "how", "分析", "为什么"]):
            intent_type = IntentType.ANALYZE
            action = "analyze"
        elif any(w in text_lower for w in ["monitor", "watch", "alert", "监控"]):
            intent_type = IntentType.MONITOR
            action = "monitor"
        elif any(w in text_lower for w in ["what", "where", "show", "list", "查", "看", "显示"]):
            intent_type = IntentType.QUERY
            action = "query"
        else:
            intent_type = IntentType.MUTATE
            action = "execute"

        # Urgency
        if any(w in text_lower for w in ["urgent", "asap", "critical", "紧急", "马上"]):
            urgency = "critical"
        elif any(w in text_lower for w in ["important", "soon", "重要"]):
            urgency = "high"
        else:
            urgency = "normal"

        return cls(
            type=intent_type,
            subject="",
            action=action,
            urgency=urgency,
            confidence=0.6,  # Heuristic = lower confidence
            raw_text=text,
        )

    def matches_department(self, dept_intents: list[str]) -> bool:
        """Check if this intent matches a department's declared intents."""
        return self.action in dept_intents or self.type.value in dept_intents
