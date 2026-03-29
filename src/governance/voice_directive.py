"""Voice Directive System — stolen from gstack.

Injects consistent voice/tone directives into agent prompts.
Each department can have custom voice parameters while sharing
a common base personality.

Also provides evaluation functions to score output quality:
- Directness (no filler, no hedging)
- Specificity (concrete actions, not vague suggestions)
- Anti-corporate (no buzzwords, no jargon soup)
- AI vocabulary avoidance (no "delve", "tapestry", "leverage")

Usage:
    directive = VoiceDirective.for_department("engineering")
    prompt = directive.inject(base_prompt)

    # Evaluate output:
    score = evaluate_voice(output_text)
"""
import re
import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)

# AI-typical words to avoid (gstack's "AI vocabulary" list)
_AI_WORDS = {
    "delve", "tapestry", "leverage", "synergy", "paradigm",
    "holistic", "robust", "scalable", "ecosystem", "empower",
    "streamline", "optimize", "utilize", "facilitate", "innovative",
    "cutting-edge", "game-changer", "best-in-class", "world-class",
    "revolutionary", "transformative", "seamlessly", "comprehensively",
}

# Hedging phrases that reduce directness
_HEDGE_PATTERNS = [
    re.compile(r'\b(?:I think|I believe|perhaps|maybe|possibly|it seems|'
               r'it appears|in my opinion|it could be|it might be|'
               r'you might want to|you could consider|'
               r'it\'s worth noting|it should be noted)\b', re.I),
]

# Corporate buzzword patterns
_CORPORATE_PATTERNS = [
    re.compile(r'\b(?:circle back|touch base|move the needle|'
               r'low-hanging fruit|deep dive|pivot|bandwidth|'
               r'action item|stakeholder alignment|value proposition|'
               r'thought leadership|core competency)\b', re.I),
]


@dataclass
class VoiceConfig:
    """Voice configuration for a department."""
    tone: str = "direct"           # direct, friendly, formal
    max_hedges: int = 0            # max allowed hedge phrases per response
    allow_ai_words: bool = False   # allow AI-typical vocabulary
    specificity: str = "high"      # low, medium, high
    language: str = "zh"           # primary output language
    custom_rules: list[str] = field(default_factory=list)


# Department voice presets
_DEPT_VOICES: dict[str, VoiceConfig] = {
    "engineering": VoiceConfig(tone="direct", specificity="high"),
    "operations": VoiceConfig(tone="direct", specificity="high"),
    "quality": VoiceConfig(tone="formal", specificity="high"),
    "security": VoiceConfig(tone="formal", specificity="high", custom_rules=[
        "Never disclose specific vulnerability details in non-secure channels",
    ]),
    "personnel": VoiceConfig(tone="friendly", specificity="medium"),
    "protocol": VoiceConfig(tone="formal", specificity="medium"),
}


class VoiceDirective:
    """Injectable voice directive for agent prompts."""

    def __init__(self, config: VoiceConfig = None):
        self.config = config or VoiceConfig()

    @classmethod
    def for_department(cls, department: str) -> "VoiceDirective":
        """Get voice directive for a specific department."""
        config = _DEPT_VOICES.get(department, VoiceConfig())
        return cls(config)

    def to_prompt_block(self) -> str:
        """Generate the voice directive text for prompt injection."""
        lines = ["## Voice Directive"]
        lines.append(f"- Tone: {self.config.tone}")
        lines.append(f"- Specificity: {self.config.specificity}")
        lines.append(f"- Language: {self.config.language}")

        if self.config.tone == "direct":
            lines.append("- Be concise. Lead with the answer, not the reasoning.")
            lines.append("- No hedging (avoid: 'I think', 'perhaps', 'maybe').")
        elif self.config.tone == "formal":
            lines.append("- Use precise, professional language.")
            lines.append("- Structured output preferred (lists, tables).")
        elif self.config.tone == "friendly":
            lines.append("- Conversational but informative.")

        if not self.config.allow_ai_words:
            lines.append("- Avoid AI-typical words: delve, tapestry, leverage, synergy, etc.")

        if self.config.specificity == "high":
            lines.append("- Always provide concrete actions, file paths, code snippets — never vague suggestions.")

        for rule in self.config.custom_rules:
            lines.append(f"- {rule}")

        return "\n".join(lines)

    def inject(self, prompt: str) -> str:
        """Inject voice directive into an existing prompt."""
        block = self.to_prompt_block()
        return f"{prompt}\n\n{block}"


@dataclass
class VoiceScore:
    """Evaluation result for voice quality."""
    directness: float      # 0.0-1.0 (1.0 = very direct)
    specificity: float     # 0.0-1.0 (1.0 = very specific)
    ai_word_count: int     # count of AI-typical words
    hedge_count: int       # count of hedging phrases
    corporate_count: int   # count of corporate buzzwords
    overall: float         # 0.0-1.0 weighted average
    issues: list[str] = field(default_factory=list)


def evaluate_voice(text: str) -> VoiceScore:
    """Evaluate output text for voice quality.

    Scores directness, specificity, and vocabulary quality.
    """
    if not text:
        return VoiceScore(0, 0, 0, 0, 0, 0)

    text_lower = text.lower()
    words = text_lower.split()

    # AI words
    ai_count = sum(1 for w in _AI_WORDS if w in text_lower)

    # Hedges
    hedge_count = sum(len(p.findall(text)) for p in _HEDGE_PATTERNS)

    # Corporate
    corporate_count = sum(len(p.findall(text)) for p in _CORPORATE_PATTERNS)

    # Directness: penalize hedges (per 100 words)
    words_count = max(len(words), 1)
    hedge_ratio = hedge_count / (words_count / 100)
    directness = max(0, 1.0 - hedge_ratio * 0.2)

    # Specificity: check for concrete indicators (paths, code, numbers)
    concrete_indicators = (
        len(re.findall(r'[/\\][\w./]+', text)) +   # file paths
        len(re.findall(r'`[^`]+`', text)) +          # code snippets
        len(re.findall(r'\b\d+\b', text))             # numbers
    )
    specificity = min(1.0, concrete_indicators / max(words_count / 50, 1))

    # Overall
    ai_penalty = min(0.3, ai_count * 0.05)
    corp_penalty = min(0.2, corporate_count * 0.05)
    overall = max(0, (directness * 0.4 + specificity * 0.4 + 0.2) - ai_penalty - corp_penalty)

    issues = []
    if hedge_count > 0:
        issues.append(f"{hedge_count} hedge phrases")
    if ai_count > 0:
        issues.append(f"{ai_count} AI-typical words")
    if corporate_count > 0:
        issues.append(f"{corporate_count} corporate buzzwords")

    return VoiceScore(
        directness=round(directness, 2),
        specificity=round(specificity, 2),
        ai_word_count=ai_count,
        hedge_count=hedge_count,
        corporate_count=corporate_count,
        overall=round(overall, 2),
        issues=issues,
    )
