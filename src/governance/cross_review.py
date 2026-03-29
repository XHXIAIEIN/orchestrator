"""Cross-Model Outside Voice — stolen from gstack.

Send the same question to two different models, compare their answers,
and produce a consensus report. Used for critical decisions where a
single model's judgment is insufficient.

Key principle (gstack ETHOS): User Sovereignty — both AIs agreeing
is a recommendation, not a mandate. The human decides.

Usage:
    reviewer = CrossModelReviewer()
    report = reviewer.review(
        question="Should we refactor the auth module?",
        context="Current auth uses session tokens stored in cookies...",
    )
    print(report.consensus)  # "agree" / "disagree" / "partial"
    print(report.recommendation)
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

log = logging.getLogger(__name__)


@dataclass
class ReviewReport:
    """Result of a cross-model review."""
    question: str
    model_a: str              # model name
    model_b: str              # model name
    response_a: str           # full response from model A
    response_b: str           # full response from model B
    consensus: str            # "agree", "disagree", "partial"
    recommendation: str       # synthesized recommendation
    confidence: float         # 0.0-1.0
    latency_ms: int           # total wall-clock time
    details: dict = field(default_factory=dict)


# Agreement detection keywords
_AGREE_SIGNALS = ["agree", "same", "consistent", "aligned", "both recommend", "consensus"]
_DISAGREE_SIGNALS = ["disagree", "conflict", "opposite", "contradicts", "different approach"]


def detect_consensus(response_a: str, response_b: str, synthesis: str) -> tuple[str, float]:
    """Detect consensus level from synthesis text. Returns (level, confidence)."""
    import re
    text = synthesis.lower()

    # Check disagree first — word-boundary aware to avoid "disagree" matching "agree"
    disagree_count = sum(1 for s in _DISAGREE_SIGNALS if re.search(r'\b' + re.escape(s) + r'\b', text))
    agree_count = sum(1 for s in _AGREE_SIGNALS if re.search(r'\b' + re.escape(s) + r'\b', text))

    if disagree_count > agree_count:
        return "disagree", min(0.9, 0.5 + disagree_count * 0.1)
    elif agree_count > 0:
        return "agree", min(0.9, 0.5 + agree_count * 0.1)
    else:
        return "partial", 0.5


class CrossModelReviewer:
    """Send questions to two models and synthesize a consensus.

    Uses the existing LLMRouter infrastructure for model calls.
    Models are called in parallel for speed.
    """

    def __init__(self, model_a: str = None, model_b: str = None):
        """
        Args:
            model_a: Primary model ID (default: claude sonnet)
            model_b: Secondary model ID (default: claude haiku for cost efficiency)
        """
        from src.core.llm_models import MODEL_SONNET, MODEL_HAIKU
        self.model_a = model_a or MODEL_SONNET
        self.model_b = model_b or MODEL_HAIKU

    def review(self, question: str, context: str = "",
               max_tokens: int = 1024) -> ReviewReport:
        """Get two model opinions and synthesize consensus.

        Both models get the same prompt. Their responses are then
        synthesized by model_a into a consensus report.
        """
        t0 = time.time()

        review_prompt = self._build_review_prompt(question, context)

        # Parallel model calls
        response_a, response_b = self._call_parallel(
            review_prompt, max_tokens
        )

        # Synthesize consensus (using model_a as the synthesizer)
        synthesis = self._synthesize(question, response_a, response_b, max_tokens)

        consensus, confidence = detect_consensus(response_a, response_b, synthesis)
        elapsed_ms = int((time.time() - t0) * 1000)

        report = ReviewReport(
            question=question,
            model_a=self.model_a,
            model_b=self.model_b,
            response_a=response_a,
            response_b=response_b,
            consensus=consensus,
            recommendation=synthesis,
            confidence=confidence,
            latency_ms=elapsed_ms,
        )

        log.info(
            f"cross_review: consensus={consensus} confidence={confidence:.0%} "
            f"({elapsed_ms}ms, models={self.model_a}/{self.model_b})"
        )
        return report

    def _build_review_prompt(self, question: str, context: str) -> str:
        parts = ["Review the following and provide your assessment:\n"]
        if context:
            parts.append(f"## Context\n{context}\n")
        parts.append(f"## Question\n{question}\n")
        parts.append(
            "\nProvide a clear YES/NO recommendation with reasoning. "
            "Be specific about risks and benefits."
        )
        return "\n".join(parts)

    def _call_parallel(self, prompt: str, max_tokens: int) -> tuple[str, str]:
        """Call both models in parallel. Returns (response_a, response_b)."""
        from src.core.llm_backends import claude_generate

        results = {}
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="cross-review") as pool:
            future_a = pool.submit(claude_generate, prompt, self.model_a, 30, max_tokens)
            future_b = pool.submit(claude_generate, prompt, self.model_b, 30, max_tokens)

            for future, name in [(future_a, "a"), (future_b, "b")]:
                try:
                    results[name] = future.result(timeout=60)
                except Exception as e:
                    log.warning(f"cross_review: model_{name} failed: {e}")
                    results[name] = f"[Model error: {e}]"

        return results.get("a", ""), results.get("b", "")

    def _synthesize(self, question: str, resp_a: str, resp_b: str,
                    max_tokens: int) -> str:
        """Synthesize two model responses into a consensus."""
        from src.core.llm_backends import claude_generate

        synthesis_prompt = f"""Two AI models reviewed the same question. Synthesize their responses into a consensus recommendation.

## Question
{question}

## Model A ({self.model_a})
{resp_a[:2000]}

## Model B ({self.model_b})
{resp_b[:2000]}

## Instructions
1. Do they agree or disagree? Use words "agree", "disagree", or "partial agreement".
2. What is the consensus recommendation?
3. What are the key risks mentioned by either model?
4. Final recommendation in 2-3 sentences.

Be concise. Start with the agreement level."""

        try:
            return claude_generate(synthesis_prompt, self.model_a, 30, max_tokens)
        except Exception as e:
            log.warning(f"cross_review: synthesis failed: {e}")
            return f"Synthesis failed: {e}. Model A said: {resp_a[:500]}. Model B said: {resp_b[:500]}"
