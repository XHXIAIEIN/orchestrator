"""APO — Automatic Prompt Optimization.

Iteratively improve system prompts using textual gradient feedback.
Given evaluation samples, generates prompt variants, scores them,
and selects the best via beam search.

Inspired by Agent Lightning's APO module + DSPy's prompt optimization.
"""

import logging
import hashlib
from dataclasses import dataclass, field
from typing import Callable, Any

logger = logging.getLogger(__name__)


@dataclass
class EvalSample:
    """A sample for evaluating prompt quality."""
    input_text: str
    expected_output: str | None = None  # None = no reference, use quality scorer
    tags: list[str] = field(default_factory=list)


@dataclass
class PromptVariant:
    """A prompt variant being evaluated."""
    prompt_text: str
    score: float = 0.0
    eval_results: list[dict] = field(default_factory=list)
    generation: int = 0
    parent_hash: str = ""

    @property
    def hash(self) -> str:
        return hashlib.md5(self.prompt_text.encode()).hexdigest()[:8]


@dataclass
class APOConfig:
    """Configuration for an APO run."""
    beam_width: int = 3          # Number of variants to keep per generation
    max_generations: int = 5     # Maximum optimization rounds
    samples_per_eval: int = 5    # Samples to evaluate per variant
    improvement_threshold: float = 0.05  # Minimum improvement to continue
    temperature: float = 0.7     # LLM temperature for variant generation


class APOOptimizer:
    """Automatic Prompt Optimizer using beam search.

    Usage:
        optimizer = APOOptimizer(
            generate_fn=my_llm_call,
            score_fn=my_quality_scorer,
        )

        result = optimizer.optimize(
            initial_prompt="You are a helpful assistant...",
            eval_samples=[EvalSample("What is X?", "X is...")],
            config=APOConfig(beam_width=3, max_generations=5),
        )

        print(result.best_prompt)
        print(result.improvement)
    """

    def __init__(
        self,
        generate_fn: Callable[[str, str], str] | None = None,
        score_fn: Callable[[str, str, str | None], float] | None = None,
    ):
        """
        Args:
            generate_fn: (system_prompt, user_input) -> output_text
            score_fn: (output, input, expected) -> score (0-1)
        """
        self._generate = generate_fn
        self._score = score_fn

    def optimize(
        self,
        initial_prompt: str,
        eval_samples: list[EvalSample],
        config: APOConfig | None = None,
    ) -> "APOResult":
        """Run beam search optimization on a prompt.

        Returns APOResult with the best prompt and optimization history.
        """
        cfg = config or APOConfig()

        # Initialize beam with the original prompt
        beam = [PromptVariant(prompt_text=initial_prompt, generation=0)]
        beam[0].score = self._evaluate_variant(beam[0], eval_samples[:cfg.samples_per_eval])

        initial_score = beam[0].score
        history = [{"generation": 0, "best_score": initial_score, "variants": 1}]

        logger.info(f"APO start: initial score={initial_score:.3f}, beam={cfg.beam_width}, max_gen={cfg.max_generations}")

        for gen in range(1, cfg.max_generations + 1):
            # Generate variants from current beam
            candidates = []
            for parent in beam:
                variants = self._generate_variants(parent, cfg)
                candidates.extend(variants)

            # Evaluate all candidates
            for variant in candidates:
                variant.generation = gen
                variant.score = self._evaluate_variant(variant, eval_samples[:cfg.samples_per_eval])

            # Select top-k (beam search)
            all_variants = beam + candidates
            all_variants.sort(key=lambda v: -v.score)
            beam = all_variants[:cfg.beam_width]

            best_score = beam[0].score
            history.append({
                "generation": gen,
                "best_score": best_score,
                "variants": len(candidates),
                "best_hash": beam[0].hash,
            })

            logger.info(f"APO gen {gen}: best={best_score:.3f}, candidates={len(candidates)}")

            # Early stopping: no significant improvement
            if gen > 1 and (best_score - history[-2]["best_score"]) < cfg.improvement_threshold:
                logger.info(f"APO converged at generation {gen}")
                break

        return APOResult(
            best_prompt=beam[0].prompt_text,
            best_score=beam[0].score,
            initial_score=initial_score,
            improvement=beam[0].score - initial_score,
            generations=len(history) - 1,
            history=history,
            all_variants=[v for v in beam],
        )

    def _evaluate_variant(self, variant: PromptVariant, samples: list[EvalSample]) -> float:
        """Evaluate a prompt variant against samples."""
        if not self._generate or not self._score:
            return 0.0

        scores = []
        for sample in samples:
            try:
                output = self._generate(variant.prompt_text, sample.input_text)
                score = self._score(output, sample.input_text, sample.expected_output)
                scores.append(score)
                variant.eval_results.append({
                    "input": sample.input_text[:100],
                    "score": score,
                })
            except Exception as e:
                logger.warning(f"Eval failed: {e}")
                scores.append(0.0)

        return sum(scores) / len(scores) if scores else 0.0

    def _generate_variants(self, parent: PromptVariant, config: APOConfig) -> list[PromptVariant]:
        """Generate prompt variants from a parent using textual gradient.

        Without LLM: return simple rule-based mutations.
        With LLM: ask it to improve the prompt based on evaluation feedback.
        """
        variants = []

        if self._generate:
            # Use LLM to generate improved variants
            feedback = self._build_feedback(parent)
            meta_prompt = (
                "You are a prompt engineer. Improve the following system prompt based on the feedback.\n"
                "Return ONLY the improved prompt, nothing else.\n\n"
                f"Current prompt:\n{parent.prompt_text}\n\n"
                f"Feedback:\n{feedback}\n\n"
                "Improved prompt:"
            )
            try:
                improved = self._generate("You improve prompts.", meta_prompt)
                if improved and improved.strip() != parent.prompt_text.strip():
                    variants.append(PromptVariant(
                        prompt_text=improved.strip(),
                        parent_hash=parent.hash,
                    ))
            except Exception as e:
                logger.warning(f"Variant generation failed: {e}")

        # Rule-based mutations as fallback
        variants.extend(self._rule_mutations(parent))

        return variants

    def _build_feedback(self, variant: PromptVariant) -> str:
        """Build textual feedback from evaluation results."""
        if not variant.eval_results:
            return "No evaluation data yet."

        lines = []
        for r in variant.eval_results:
            quality = "good" if r["score"] >= 0.7 else "needs improvement" if r["score"] >= 0.4 else "poor"
            lines.append(f"- Input: {r['input']}... → Score: {r['score']:.2f} ({quality})")

        avg = sum(r["score"] for r in variant.eval_results) / len(variant.eval_results)
        lines.append(f"\nAverage score: {avg:.2f}")
        return "\n".join(lines)

    def _rule_mutations(self, parent: PromptVariant) -> list[PromptVariant]:
        """Simple rule-based prompt mutations."""
        mutations = []
        text = parent.prompt_text

        # Add "step by step" if not present
        if "step by step" not in text.lower():
            mutations.append(PromptVariant(
                prompt_text=text + "\nThink step by step before answering.",
                parent_hash=parent.hash,
            ))

        # Add confidence requirement if not present
        if "confidence" not in text.lower() and "uncertain" not in text.lower():
            mutations.append(PromptVariant(
                prompt_text=text + "\nWhen uncertain, say so explicitly rather than guessing.",
                parent_hash=parent.hash,
            ))

        return mutations


@dataclass
class APOResult:
    """Result of an APO optimization run."""
    best_prompt: str
    best_score: float
    initial_score: float
    improvement: float
    generations: int
    history: list[dict]
    all_variants: list[PromptVariant]

    def summary(self) -> str:
        return (
            f"APO Result: {self.initial_score:.3f} → {self.best_score:.3f} "
            f"(+{self.improvement:.3f}) over {self.generations} generations"
        )
