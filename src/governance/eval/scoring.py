"""
LLM-as-Judge + Rubric-Based Scoring (R38 — Anthropic Bloom + AdaRubric + RULERS).

Extends the existing EvalResult (eval_loop.py) with:
  1. ModelGradedScore — structured LLM judge scoring with confidence + reasoning
  2. RubricCriterion  — three-level rubric (Satisfied/Partial/Not Satisfied)
  3. RubricScore      — evidence-anchored scoring per criterion (RULERS pattern)
  4. DimensionAwareFilter — prevents high-scoring dims from masking failures

Separates deterministic checks (tool selection, argument format) from
LLM-judge checks (response quality, goal alignment) per Anthropic guidance.

Usage:
    # Define task-specific rubric
    rubric = [
        RubricCriterion(
            name="correctness",
            weight=0.4,
            description="Output correctly addresses the task",
            satisfied="All requirements met, code runs without errors",
            partial="Most requirements met, minor issues",
            not_satisfied="Fundamental errors, wrong approach",
        ),
        ...
    ]

    # Score with LLM judge
    result = await score_with_rubric(
        task_description="Fix the null pointer in data_processor.py",
        agent_output=output,
        rubric=rubric,
    )
    # ScoringResult with per-criterion scores + composite + confidence
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

log = logging.getLogger(__name__)


# ── Rubric Structures ────────────────────────────────────────


class Verdict(str, Enum):
    """Three-level evaluation verdict (more stable than 5-point for LLM judges)."""
    SATISFIED = "satisfied"             # full credit: 1.0
    PARTIAL = "partial"                 # partial credit: 0.5
    NOT_SATISFIED = "not_satisfied"     # no credit: 0.0

    @property
    def score(self) -> float:
        return {
            Verdict.SATISFIED: 1.0,
            Verdict.PARTIAL: 0.5,
            Verdict.NOT_SATISFIED: 0.0,
        }[self]


@dataclass
class RubricCriterion:
    """One criterion in a scoring rubric.

    weight: relative importance (all weights should sum to 1.0 across criteria).
    The three description fields provide anchoring examples for the LLM judge.
    """
    name: str
    weight: float
    description: str
    satisfied: str            # example of full credit
    partial: str              # example of partial credit
    not_satisfied: str        # example of zero credit


@dataclass
class RubricScore:
    """Score for one criterion with evidence anchoring (RULERS pattern)."""
    criterion: str
    verdict: Verdict
    evidence: str             # specific text from agent output justifying score
    reasoning: str = ""       # judge's chain-of-thought

    @property
    def score(self) -> float:
        return self.verdict.score

    def to_dict(self) -> dict:
        return {
            "criterion": self.criterion,
            "verdict": self.verdict.value,
            "score": self.score,
            "evidence": self.evidence,
            "reasoning": self.reasoning,
        }


# ── Model-Graded Score ───────────────────────────────────────


@dataclass
class ModelGradedScore:
    """One dimension of LLM-as-judge scoring.

    Inspired by Inspect AI's Score structure + Bloom's judge pipeline.
    """
    dimension: str            # e.g. "correctness", "safety", "completeness"
    score: float              # 0-1 normalized
    confidence: float         # judge's self-assessed confidence (0-1)
    reasoning: str            # chain-of-thought from judge
    evidence: str = ""        # specific text cited as justification
    judge_model: str = ""     # which model served as judge

    def to_dict(self) -> dict:
        return {
            "dimension": self.dimension,
            "score": round(self.score, 3),
            "confidence": round(self.confidence, 3),
            "reasoning": self.reasoning,
            "evidence": self.evidence[:300],
            "judge_model": self.judge_model,
        }


# ── Scoring Result ───────────────────────────────────────────


@dataclass
class ScoringResult:
    """Complete scoring result combining rubric scores + model grades."""
    rubric_scores: list[RubricScore] = field(default_factory=list)
    model_grades: list[ModelGradedScore] = field(default_factory=list)
    deterministic_checks: dict = field(default_factory=dict)  # tool_used, format_valid, etc.

    @property
    def rubric_composite(self) -> float:
        """Weighted average of rubric scores."""
        if not self.rubric_scores:
            return 0.0
        total_weight = sum(1.0 for _ in self.rubric_scores)  # equal weight if not specified
        return sum(s.score for s in self.rubric_scores) / total_weight

    @property
    def model_grade_composite(self) -> float:
        """Confidence-weighted average of model grades."""
        if not self.model_grades:
            return 0.0
        total_w = sum(g.confidence for g in self.model_grades)
        if total_w == 0:
            return 0.0
        return sum(g.score * g.confidence for g in self.model_grades) / total_w

    @property
    def weak_dimensions(self) -> list[str]:
        """Dimensions scoring below 0.5 (DimensionAwareFilter from AdaRubric).

        Prevents high-scoring dimensions from masking failures.
        """
        weak = []
        for s in self.rubric_scores:
            if s.score < 0.5:
                weak.append(s.criterion)
        for g in self.model_grades:
            if g.score < 0.5:
                weak.append(g.dimension)
        return weak

    @property
    def has_critical_weakness(self) -> bool:
        """True if any dimension scores 0.0 (not_satisfied)."""
        for s in self.rubric_scores:
            if s.verdict == Verdict.NOT_SATISFIED:
                return True
        for g in self.model_grades:
            if g.score == 0.0:
                return True
        return False

    def to_dict(self) -> dict:
        return {
            "rubric_scores": [s.to_dict() for s in self.rubric_scores],
            "model_grades": [g.to_dict() for g in self.model_grades],
            "deterministic_checks": self.deterministic_checks,
            "rubric_composite": round(self.rubric_composite, 3),
            "model_grade_composite": round(self.model_grade_composite, 3),
            "weak_dimensions": self.weak_dimensions,
            "has_critical_weakness": self.has_critical_weakness,
        }


# ── Rubric Templates ─────────────────────────────────────────


# Pre-built rubrics for common task types (AdaRubric-inspired)
RUBRIC_TEMPLATES: dict[str, list[RubricCriterion]] = {
    "code": [
        RubricCriterion(
            name="correctness", weight=0.4,
            description="Code correctly implements the requirements",
            satisfied="All requirements met, code runs without errors, edge cases handled",
            partial="Core functionality works but missing edge cases or minor bugs",
            not_satisfied="Fundamental errors, wrong approach, code doesn't run",
        ),
        RubricCriterion(
            name="completeness", weight=0.25,
            description="All aspects of the task are addressed",
            satisfied="Every requirement addressed, tests included if applicable",
            partial="Most requirements addressed, some gaps",
            not_satisfied="Major requirements missing",
        ),
        RubricCriterion(
            name="style", weight=0.15,
            description="Code follows project conventions and is readable",
            satisfied="Consistent with existing style, well-organized, clear variable names",
            partial="Mostly consistent, minor style deviations",
            not_satisfied="Significantly deviates from project style, hard to read",
        ),
        RubricCriterion(
            name="safety", weight=0.2,
            description="No security vulnerabilities or data safety issues",
            satisfied="No injection risks, proper input validation, no hardcoded secrets",
            partial="Minor safety concerns that don't affect production",
            not_satisfied="Clear security vulnerabilities, injection risks, leaked secrets",
        ),
    ],
    "research": [
        RubricCriterion(
            name="coverage", weight=0.3,
            description="Breadth and depth of research",
            satisfied="Comprehensive coverage of relevant sources, multiple perspectives",
            partial="Adequate coverage but missing some important sources",
            not_satisfied="Superficial research, few sources, biased perspective",
        ),
        RubricCriterion(
            name="accuracy", weight=0.3,
            description="Factual accuracy of findings",
            satisfied="All facts verifiable, properly attributed, no hallucinations",
            partial="Mostly accurate with minor inaccuracies",
            not_satisfied="Contains significant factual errors or hallucinations",
        ),
        RubricCriterion(
            name="synthesis", weight=0.25,
            description="Quality of analysis and insight extraction",
            satisfied="Clear insights, actionable recommendations, patterns identified",
            partial="Some analysis but mostly descriptive",
            not_satisfied="No meaningful synthesis, just a list of facts",
        ),
        RubricCriterion(
            name="actionability", weight=0.15,
            description="Practical applicability of findings",
            satisfied="Clear next steps with specific implementation guidance",
            partial="Some actionable items but vague on specifics",
            not_satisfied="No practical guidance, purely theoretical",
        ),
    ],
    "conversation": [
        RubricCriterion(
            name="goal_alignment", weight=0.35,
            description="Response addresses the user's actual need",
            satisfied="Directly addresses the core question, anticipates follow-ups",
            partial="Addresses the question but misses underlying need",
            not_satisfied="Off-topic or misunderstands the request",
        ),
        RubricCriterion(
            name="tone", weight=0.2,
            description="Appropriate communication style",
            satisfied="Matches expected tone (friendly/professional/concise as needed)",
            partial="Acceptable tone with minor mismatches",
            not_satisfied="Inappropriate tone, too formal/casual, robotic",
        ),
        RubricCriterion(
            name="completeness", weight=0.25,
            description="Response is thorough without being verbose",
            satisfied="All points addressed, right level of detail",
            partial="Mostly complete, missing some relevant points",
            not_satisfied="Incomplete or excessively verbose",
        ),
        RubricCriterion(
            name="pushback_quality", weight=0.2,
            description="Appropriately challenges flawed requests",
            satisfied="Identifies issues, explains why, offers alternatives",
            partial="Notes concerns but doesn't offer alternatives",
            not_satisfied="Blindly agrees or pushes back without justification",
        ),
    ],
}


def get_rubric_for_task(task_type: str) -> list[RubricCriterion]:
    """Get the appropriate rubric template for a task type.

    Falls back to 'code' rubric if task_type not found.
    """
    return RUBRIC_TEMPLATES.get(task_type, RUBRIC_TEMPLATES["code"])


def infer_task_type(task_description: str) -> str:
    """Infer task type from description keywords."""
    desc_lower = task_description.lower()
    if any(kw in desc_lower for kw in ["研究", "偷师", "调研", "research", "analyze", "survey", "investigate"]):
        return "research"
    if any(kw in desc_lower for kw in ["对话", "回复", "conversation", "reply", "respond", "chat"]):
        return "conversation"
    return "code"  # default


# ── Judge Prompt Builder ──────────────────────────────────────


def build_judge_prompt(
    task_description: str,
    agent_output: str,
    rubric: list[RubricCriterion],
    ground_truth: str = "",
) -> str:
    """Build a structured prompt for the LLM judge.

    Template variables: {task}, {output}, {ground_truth}, {rubric}.
    Judge must output structured JSON with per-criterion verdicts.
    """
    rubric_text = ""
    for i, c in enumerate(rubric, 1):
        rubric_text += f"""
### Criterion {i}: {c.name} (weight: {c.weight})
{c.description}

- SATISFIED: {c.satisfied}
- PARTIAL: {c.partial}
- NOT_SATISFIED: {c.not_satisfied}
"""

    gt_section = ""
    if ground_truth:
        gt_section = f"""
## Ground Truth / Reference
{ground_truth[:1000]}
"""

    return f"""You are evaluating an AI agent's output on a specific task.

## Task Description
{task_description}

## Agent Output
{agent_output[:3000]}
{gt_section}
## Scoring Rubric
{rubric_text}

## Instructions

For EACH criterion:
1. Quote specific evidence from the agent output (≤100 chars)
2. Assign a verdict: "satisfied", "partial", or "not_satisfied"
3. Explain your reasoning in 1-2 sentences
4. Rate your confidence in this judgment (0.0-1.0)

Output valid JSON array:
```json
[
  {{
    "criterion": "<name>",
    "verdict": "satisfied|partial|not_satisfied",
    "evidence": "<quoted text from output>",
    "reasoning": "<1-2 sentence explanation>",
    "confidence": 0.85
  }},
  ...
]
```

IMPORTANT:
- Judge the FINAL STATE (what the agent actually produced), not what it claimed to do
- Each verdict MUST cite evidence from the output
- Be calibrated: "partial" is the default when unsure, not "satisfied"
- Do NOT let one strong dimension mask weaknesses in others
"""


def parse_judge_response(response: str, rubric: list[RubricCriterion]) -> ScoringResult:
    """Parse the LLM judge's JSON response into a ScoringResult.

    Handles common JSON extraction issues (markdown code blocks, etc.).
    """
    # Extract JSON from response (may be wrapped in ```json ... ```)
    json_match = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', response, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)
    else:
        # Try to find raw JSON array
        json_match = re.search(r'\[.*\]', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
        else:
            log.warning("judge response contains no parseable JSON")
            return ScoringResult()

    try:
        scores_data = json.loads(json_str)
    except json.JSONDecodeError as e:
        log.warning(f"judge response JSON parse error: {e}")
        return ScoringResult()

    rubric_scores = []
    model_grades = []

    for entry in scores_data:
        criterion_name = entry.get("criterion", "")
        verdict_str = entry.get("verdict", "partial").lower().strip()
        evidence = entry.get("evidence", "")
        reasoning = entry.get("reasoning", "")
        confidence = float(entry.get("confidence", 0.7))

        # Map to Verdict enum
        verdict_map = {
            "satisfied": Verdict.SATISFIED,
            "partial": Verdict.PARTIAL,
            "not_satisfied": Verdict.NOT_SATISFIED,
            # Common alternatives
            "pass": Verdict.SATISFIED,
            "fail": Verdict.NOT_SATISFIED,
        }
        verdict = verdict_map.get(verdict_str, Verdict.PARTIAL)

        rubric_scores.append(RubricScore(
            criterion=criterion_name,
            verdict=verdict,
            evidence=evidence[:300],
            reasoning=reasoning[:300],
        ))

        # Also store as ModelGradedScore for composite calculation
        model_grades.append(ModelGradedScore(
            dimension=criterion_name,
            score=verdict.score,
            confidence=confidence,
            reasoning=reasoning[:300],
            evidence=evidence[:300],
        ))

    return ScoringResult(
        rubric_scores=rubric_scores,
        model_grades=model_grades,
    )


# ── High-level API ────────────────────────────────────────────


async def score_with_rubric(
    task_description: str,
    agent_output: str,
    rubric: list[RubricCriterion] | None = None,
    ground_truth: str = "",
    judge_model: str = "",
) -> ScoringResult:
    """Score agent output using LLM-as-Judge with a rubric.

    If no rubric provided, auto-selects based on task type.
    Returns ScoringResult with per-criterion verdicts + composite.
    """
    if rubric is None:
        task_type = infer_task_type(task_description)
        rubric = get_rubric_for_task(task_type)

    prompt = build_judge_prompt(task_description, agent_output, rubric, ground_truth)

    # Call LLM judge
    try:
        from src.core.llm_router import get_router
        router = get_router()
        response = router.generate(
            prompt,
            task_type="eval_judge",
            model=judge_model or None,
        )
    except Exception as e:
        log.warning(f"LLM judge call failed: {e}")
        return ScoringResult()

    result = parse_judge_response(response, rubric)

    # Tag model grades with judge model info
    for g in result.model_grades:
        g.judge_model = judge_model or "default"

    return result


def score_deterministic(
    agent_output: str,
    expected_tools: list[str] | None = None,
    expected_format: str | None = None,
    max_length: int | None = None,
) -> dict:
    """Run deterministic (non-LLM) checks on agent output.

    These are fast, cheap, and reliable — use before LLM judge.
    Returns dict of check_name → bool.
    """
    checks = {}

    if expected_format:
        if expected_format == "json":
            try:
                json.loads(agent_output)
                checks["format_valid"] = True
            except (json.JSONDecodeError, TypeError):
                checks["format_valid"] = False
        elif expected_format == "markdown":
            checks["format_valid"] = "#" in agent_output or "```" in agent_output

    if max_length is not None:
        checks["length_ok"] = len(agent_output) <= max_length

    checks["non_empty"] = bool(agent_output and agent_output.strip())

    return checks
