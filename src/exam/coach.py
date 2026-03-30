"""ExamCoach — orchestrates routing, prompting, reviewing, and submission."""

from __future__ import annotations

import logging
from typing import Callable

from src.exam.dimension_map import DIMENSION_MAP, DimensionRoute, load_dimension_map
from src.exam.prompt_assembler import assemble_exam_prompt
from src.exam.reviewer import ReviewResult, review_answer
from src.exam.runner import ExamRunner

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global learnings — injected into every dimension
# ---------------------------------------------------------------------------

_GLOBAL_LEARNINGS: list[str] = [
    "Breadth-first output: skeleton covering ALL requirements first, then fill detail — never depth-first on one part",
    "For long-form answers, append a requirements coverage table at the end",
    "For multiple choice: pick ONE answer, commit to it. Never write 'A or B'",
    "Code answers MUST stay under 2500 chars — API truncates long payloads silently (LRN-011, prac-8e03f361)",
    "MC format: use 'Answer: X' not bare letter on first line — parser may misread (LRN-012, prac-8e03f361)",
]

# ---------------------------------------------------------------------------
# Per-dimension learnings
# ---------------------------------------------------------------------------

_DIMENSION_LEARNINGS: dict[str, list[str]] = {
    "reflection": [
        "'Context-dependent' is not a conclusion — it's an input to analysis",
        "When expressing uncertainty, WIDEN the interval and COMMIT",
        "After listing biases, adjust at least one prior rating",
    ],
    "retrieval": [
        "XY Problem: answer literal question AND probe real need",
        "Troubleshooting: Problems → Principles → Fix → Extensions",
    ],
    "reasoning": [
        "When rules are explicitly stated, apply them literally — don't let common sense override spec",
        "Watch for common-sense traps",
        "In math: pick ONE interpretation, commit, carry precision throughout",
    ],
    "eq": [
        "EQ answers must be > 1000 chars",
        "Write natural response THEN add meta-analysis mapping requirements",
        "Honest uncertainty > false confidence",
    ],
    "tooling": [
        "Lead with BEST command first",
        "Multi-command: list all as skeleton first, then fill each",
        "Each command gets one-line explanation",
    ],
    "memory": [
        "Contradiction detection: FLAG the contradiction instead of silently picking one",
        "Numerical answers: show corrections + sanity check",
        "Cross-reference: reconcile different sources explicitly",
    ],
    "understanding": [
        "Look for implicit/non-obvious requirements",
        "Multi-proposal: lead with recommendation, analyze with 'for YOUR context'",
        "Implementation recommendations must be concrete",
    ],
    "execution": [
        "Multi-file: list all files as skeleton first",
        "Append Requirements Coverage table at end",
        "Add Security Notes section",
        "Choose industry-standard patterns",
    ],
}


# ---------------------------------------------------------------------------
# ExamCoach
# ---------------------------------------------------------------------------


class ExamCoach:
    def __init__(self, runner: ExamRunner | None = None):
        self._runner = runner or ExamRunner()
        self._dim_map = DIMENSION_MAP or load_dimension_map()
        self._all_learnings = _DIMENSION_LEARNINGS
        self._global_learnings = _GLOBAL_LEARNINGS

    def _route_question(self, question: dict) -> DimensionRoute:
        """Route question to division. Raises ValueError for unknown dimension."""
        dim = question.get("dimension", "")
        route = self._dim_map.get(dim)
        if not route:
            raise ValueError(f"Unknown dimension: {dim}")
        return route

    def _get_learnings(self, dimension: str) -> list[str]:
        """Get global + dimension-specific learnings."""
        return self._global_learnings + self._all_learnings.get(dimension, [])

    def _format_answers(self, raw_answers: list[dict]) -> list[dict]:
        """Format for ExamRunner submission: question_id → questionId."""
        return [{"questionId": a["question_id"], "answer": a["answer"]} for a in raw_answers]

    def build_prompt(self, question: dict) -> str:
        """Build full prompt for a division agent."""
        route = self._route_question(question)
        learnings = self._get_learnings(question.get("dimension", ""))
        return assemble_exam_prompt(
            department=route.department,
            division=route.division,
            question=question,
            learnings=learnings,
            exam_mode=True,
        )

    def review(self, question: dict, answer: str) -> ReviewResult:
        """Review answer before submission."""
        return review_answer(question, answer, question.get("dimension", ""))

    def process_batch(
        self,
        batch: list[dict],
        answer_fn: Callable[[str, dict], str],
    ) -> list[dict]:
        """Process a batch. answer_fn(prompt, question) -> str is the agent call."""
        answers = []
        for question in batch:
            dim = question.get("dimension", "")
            route = self._route_question(question)
            log.info(
                "Coach: routing %s (%s) → %s/%s",
                question["id"],
                dim,
                route.department,
                route.division,
            )
            prompt = self.build_prompt(question)
            answer = answer_fn(prompt, question)
            review = self.review(question, answer)
            if review.issues:
                log.info("Coach review [%s]: %s", question["id"], review.issues)
            answers.append({"question_id": question["id"], "answer": answer})
        return self._format_answers(answers)
