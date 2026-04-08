"""ClarificationGate — pre-dispatch clarity check.

Inserted between task creation and preflight in the dispatch pipeline.
Evaluates whether a task spec has enough information to execute successfully.

Two-tier evaluation:
  1. Deterministic checks (zero tokens) — catches obvious gaps
  2. LLM evaluation (optional) — catches subtle ambiguity

Five clarification types (priority order):
  missing_info > ambiguous_requirement > approach_choice > risk_confirmation > suggestion
"""
import json
import logging
import re
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)


# ── Clarification Types (priority order) ──

CLARIFICATION_TYPES = [
    "missing_info",
    "ambiguous_requirement",
    "approach_choice",
    "risk_confirmation",
    "suggestion",
]


@dataclass
class ClarificationResult:
    """Result of a clarification check."""
    decision: str  # "PROCEED" or "CLARIFY"
    type: Optional[str] = None  # one of CLARIFICATION_TYPES
    confidence: float = 1.0
    question: Optional[str] = None
    context: Optional[str] = None

    @property
    def needs_clarification(self) -> bool:
        return self.decision == "CLARIFY"

    def to_dict(self) -> dict:
        return {
            "decision": self.decision,
            "type": self.type,
            "confidence": self.confidence,
            "question": self.question,
            "context": self.context,
        }


# ── Deterministic Detectors ──

# Patterns that indicate the task has enough specificity to proceed
_SPECIFICITY_SIGNALS = [
    re.compile(r'[\w/\\]+\.\w{1,4}'),       # file path (src/foo.py)
    re.compile(r'[A-Z]\w+[.#]\w+'),          # class.method or Class#method
    re.compile(r'[Ll]ine\s*\d+|L\d+'),       # line reference
    re.compile(r'def\s+\w+|class\s+\w+'),    # function/class definition
    re.compile(r'#\d+'),                       # issue/task reference
]

# Vague action words that signal ambiguous_requirement (without specific target)
_VAGUE_ACTIONS = [
    "optimize", "improve", "clean up", "refactor", "fix",
    "优化", "改进", "清理", "重构", "修复",
    "update", "enhance", "better", "更好", "升级",
]

# High-risk signals for risk_confirmation
_RISK_SIGNALS = [
    re.compile(r'migrat(e|ion)', re.I),
    re.compile(r'delet(e|ing)\s+.*(table|schema|database|collection)', re.I),
    re.compile(r'refactor.*(\d{2,})\s*files', re.I),
    re.compile(r'break(ing)?\s+change', re.I),
    re.compile(r'public\s+api', re.I),
    re.compile(r'rm\s+-rf|drop\s+table|truncate', re.I),
    re.compile(r'数据库.*迁移|删除.*表|公开.*接口', re.I),
]

# Keywords that auto-PROCEED (trivial tasks)
_AUTO_PROCEED_PATTERNS = [
    re.compile(r'(read|cat|view|show|list|ls|status|check|log|tail)\b', re.I),
    re.compile(r'(查看|显示|列出|状态|检查|日志)\b'),
]


def _has_specificity(text: str) -> bool:
    """Check if text contains specific targets (file paths, function names, etc.)."""
    return any(p.search(text) for p in _SPECIFICITY_SIGNALS)


def _is_trivial_action(text: str) -> bool:
    """Check if the action is trivially clear (read-only, status checks)."""
    return any(p.search(text) for p in _AUTO_PROCEED_PATTERNS)


def _detect_missing_info(spec: dict, action: str) -> Optional[ClarificationResult]:
    """Detect if required information is missing."""
    problem = spec.get("problem", "")
    expected = spec.get("expected", "")
    combined = f"{action} {problem}"

    # Bug fix without reproduction info
    bug_signals = ["bug", "error", "crash", "fail", "broken", "报错", "崩溃", "出错"]
    is_bug = any(s in combined.lower() for s in bug_signals)
    if is_bug and not _has_specificity(combined):
        return ClarificationResult(
            decision="CLARIFY",
            type="missing_info",
            confidence=0.85,
            question="这个 bug 在哪个文件/函数出现的？有报错信息或复现步骤吗？",
            context="Bug fix without file path or reproduction steps",
        )

    # Action with no target at all — but yield to ambiguous_requirement if vague action word present
    has_vague_word = any(v in action.lower() for v in _VAGUE_ACTIONS)
    if not problem and not expected and len(action.split()) <= 3 and not has_vague_word:
        return ClarificationResult(
            decision="CLARIFY",
            type="missing_info",
            confidence=0.9,
            question="能说得更具体一点吗？目标文件、函数名、或者期望的结果是什么？",
            context="Task spec has no problem description, no expected outcome, and action is too brief",
        )

    return None


def _detect_ambiguous_requirement(spec: dict, action: str) -> Optional[ClarificationResult]:
    """Detect if the requirement has multiple valid interpretations."""
    combined = f"{action} {spec.get('problem', '')}".lower()

    # Vague action without specific target
    has_vague = any(v in combined for v in _VAGUE_ACTIONS)
    has_specific = _has_specificity(combined)

    if has_vague and not has_specific:
        # Find which vague word triggered
        trigger = next((v for v in _VAGUE_ACTIONS if v in combined), "?")
        return ClarificationResult(
            decision="CLARIFY",
            type="ambiguous_requirement",
            confidence=0.75,
            question=f"「{trigger}」具体指什么？目标文件、衡量标准、或者具体要改的地方？",
            context=f"Vague action word '{trigger}' without specific target",
        )

    return None


def _detect_risk_confirmation(spec: dict, action: str) -> Optional[ClarificationResult]:
    """Detect high-risk operations that need owner confirmation."""
    combined = f"{action} {spec.get('problem', '')} {spec.get('summary', '')}"

    for pattern in _RISK_SIGNALS:
        m = pattern.search(combined)
        if m:
            return ClarificationResult(
                decision="CLARIFY",
                type="risk_confirmation",
                confidence=0.9,
                question=f"检测到高风险操作（{m.group()}）。确认要执行吗？影响范围是什么？",
                context=f"High-risk signal: {m.group()}",
            )

    return None


def check_deterministic(spec: dict, action: str) -> ClarificationResult:
    """Tier 1: deterministic clarification check (zero tokens).

    Returns PROCEED if task is clearly actionable, CLARIFY if obvious gaps found.
    Returns PROCEED with low confidence if uncertain (caller should escalate to LLM).
    """
    combined = f"{action} {spec.get('problem', '')} {spec.get('summary', '')}"

    # ── Auto-PROCEED conditions ──

    # Trivial read-only actions
    if _is_trivial_action(action):
        return ClarificationResult(decision="PROCEED", confidence=0.95)

    # Already specific enough
    if _has_specificity(combined) and spec.get("expected"):
        return ClarificationResult(decision="PROCEED", confidence=0.9)

    # Dependency chain tasks (predecessor already clarified scope)
    if spec.get("depends_on"):
        return ClarificationResult(decision="PROCEED", confidence=0.85)

    # Rework tasks (already went through clarification)
    if spec.get("rework_count", 0) > 0:
        return ClarificationResult(decision="PROCEED", confidence=0.9)

    # Direct cognitive mode with file paths
    if spec.get("cognitive_mode") == "direct" and _has_specificity(combined):
        return ClarificationResult(decision="PROCEED", confidence=0.9)

    # ── Clarification detectors (priority order) ──

    # 1. missing_info
    result = _detect_missing_info(spec, action)
    if result:
        return result

    # 2. ambiguous_requirement
    result = _detect_ambiguous_requirement(spec, action)
    if result:
        return result

    # 3. risk_confirmation (skip approach_choice — needs LLM judgment)
    result = _detect_risk_confirmation(spec, action)
    if result:
        return result

    # ── Uncertain: has some info but not clearly sufficient ──
    if _has_specificity(combined):
        return ClarificationResult(decision="PROCEED", confidence=0.7)

    # Low confidence PROCEED — caller may escalate to LLM
    return ClarificationResult(decision="PROCEED", confidence=0.5)


def check_with_llm(spec: dict, action: str, prompt_template: str) -> ClarificationResult:
    """Tier 2: LLM-based clarification check.

    Called when deterministic check returns low confidence (< threshold).
    Uses the clarification.md prompt template.
    """
    from src.core.llm_backends import claude_generate
    from src.core.llm_models import MODEL_HAIKU

    prompt = prompt_template.format(
        department=spec.get("department", "?"),
        action=action,
        problem=spec.get("problem", ""),
        expected=spec.get("expected", ""),
        observation=spec.get("observation", ""),
        cognitive_mode=spec.get("cognitive_mode", "react"),
    )

    try:
        response = claude_generate(prompt, MODEL_HAIKU, timeout=15, max_tokens=300)
    except Exception as e:
        log.warning(f"ClarificationGate: LLM call failed ({e}), defaulting to PROCEED")
        return ClarificationResult(decision="PROCEED", confidence=0.5,
                                   context=f"LLM fallback: {e}")

    # Parse JSON from response
    text = response.strip()
    m = re.search(r'\{[^}]+\}', text, re.DOTALL)
    if not m:
        log.warning(f"ClarificationGate: failed to parse LLM response: {text[:200]}")
        return ClarificationResult(decision="PROCEED", confidence=0.5,
                                   context="LLM response not parseable")

    try:
        data = json.loads(m.group())
    except json.JSONDecodeError:
        return ClarificationResult(decision="PROCEED", confidence=0.5,
                                   context="LLM response JSON invalid")

    decision = data.get("decision", "PROCEED").upper()
    ctype = data.get("type")
    if ctype and ctype not in CLARIFICATION_TYPES:
        ctype = None

    return ClarificationResult(
        decision=decision if decision in ("PROCEED", "CLARIFY") else "PROCEED",
        type=ctype,
        confidence=float(data.get("confidence", 0.7)),
        question=data.get("question"),
        context=data.get("context"),
    )


class ClarificationGate:
    """Pre-dispatch clarification middleware.

    Sits between task creation and preflight in the dispatch pipeline.
    Two-tier: deterministic first, LLM only when uncertain.

    Usage:
        gate = ClarificationGate()
        result = gate.evaluate(spec, action)
        if result.needs_clarification:
            # Return question to user, don't dispatch
    """

    # Confidence threshold: below this, escalate to LLM
    LLM_THRESHOLD = 0.6

    # Source types that skip clarification (already structured/validated)
    SKIP_SOURCES = {"scout", "rework", "group_orchestration", "fact_layer", "expression_layer", "agent_cron"}

    def __init__(self, prompt_template: str = ""):
        self._prompt_template = prompt_template

    @classmethod
    def with_prompt(cls) -> "ClarificationGate":
        """Factory: create gate with prompt loaded from SOUL/."""
        from src.governance.context.prompts import load_prompt
        template = load_prompt("clarification")
        return cls(prompt_template=template)

    def evaluate(self, spec: dict, action: str, source: str = "auto") -> ClarificationResult:
        """Evaluate whether a task needs clarification before dispatch.

        Args:
            spec: Task specification dict
            action: Human-readable action description
            source: Task source ("auto", "user_intent", "scout", etc.)

        Returns:
            ClarificationResult with decision (PROCEED/CLARIFY) and optional question
        """
        # Skip clarification for structured/internal sources
        phase = spec.get("phase", "")
        if source in self.SKIP_SOURCES or phase in self.SKIP_SOURCES:
            return ClarificationResult(decision="PROCEED", confidence=1.0)

        # Tier 1: deterministic
        result = check_deterministic(spec, action)

        if result.needs_clarification:
            log.info(f"ClarificationGate: CLARIFY (deterministic) type={result.type} "
                     f"conf={result.confidence:.2f}")
            return result

        if result.confidence >= self.LLM_THRESHOLD:
            log.debug(f"ClarificationGate: PROCEED (deterministic) conf={result.confidence:.2f}")
            return result

        # Tier 2: LLM escalation (low-confidence deterministic PROCEED)
        if not self._prompt_template:
            log.debug("ClarificationGate: no prompt template, accepting low-confidence PROCEED")
            return result

        log.info(f"ClarificationGate: deterministic uncertain (conf={result.confidence:.2f}), "
                 f"escalating to LLM")
        llm_result = check_with_llm(spec, action, self._prompt_template)

        if llm_result.needs_clarification:
            log.info(f"ClarificationGate: CLARIFY (LLM) type={llm_result.type}")

        return llm_result
