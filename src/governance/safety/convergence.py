# src/governance/safety/convergence.py
"""Ralph Loop Convergence Detection — know when to stop iterating.

Stolen from claude-cognitive's convergence detection. When a self-reflection
or improvement loop is running (e.g., eval→rework→eval→rework), detect
when further iterations are unlikely to produce better results.

Convergence signals:
  1. Score plateau — quality score stops improving
  2. Oscillation — score bounces between values without trending
  3. Diminishing returns — improvement rate drops below threshold
  4. Content stability — output text similarity exceeds threshold
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# Minimum iterations before convergence detection
MIN_ITERATIONS = 2
# Minimum improvement per iteration to justify continuing
MIN_IMPROVEMENT_RATE = 0.05  # 5% improvement
# Score difference below which we consider "same"
PLATEAU_EPSILON = 0.5
# Maximum oscillations before declaring non-convergent
MAX_OSCILLATIONS = 3


@dataclass
class ConvergenceState:
    """Tracks iteration history for convergence analysis."""
    scores: list[float] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    iteration: int = 0

    def record(self, score: float, text: str = "") -> None:
        """Record an iteration's result."""
        self.scores.append(score)
        if text:
            self.texts.append(text[:500])  # cap stored text
        self.iteration += 1


@dataclass
class ConvergenceVerdict:
    """Result of convergence analysis."""
    converged: bool
    reason: str
    recommendation: str    # "continue" | "stop" | "escalate"
    iterations: int = 0
    current_score: float = 0.0
    improvement_rate: float = 0.0

    def to_dict(self) -> dict:
        return {
            "converged": self.converged,
            "reason": self.reason,
            "recommendation": self.recommendation,
            "iterations": self.iterations,
            "current_score": round(self.current_score, 2),
            "improvement_rate": round(self.improvement_rate, 3),
        }


def check_convergence(state: ConvergenceState, max_iterations: int = 5) -> ConvergenceVerdict:
    """Analyze iteration history and decide whether to continue.

    Returns a verdict with recommendation:
      - "continue": still improving, keep going
      - "stop": converged or diminishing returns, good enough
      - "escalate": stuck/oscillating, needs human intervention
    """
    n = len(state.scores)

    # Not enough data
    if n < MIN_ITERATIONS:
        return ConvergenceVerdict(
            converged=False,
            reason="Insufficient iterations",
            recommendation="continue",
            iterations=n,
            current_score=state.scores[-1] if state.scores else 0,
        )

    current = state.scores[-1]
    previous = state.scores[-2]

    # Check 1: Perfect score — done
    if current >= 9.5:  # For 0-10 scale
        return ConvergenceVerdict(
            converged=True,
            reason="Near-perfect score achieved",
            recommendation="stop",
            iterations=n,
            current_score=current,
        )

    # Check 2: Score plateau
    if abs(current - previous) < PLATEAU_EPSILON:
        plateau_len = 1
        for i in range(n - 2, -1, -1):
            if abs(state.scores[i] - current) < PLATEAU_EPSILON:
                plateau_len += 1
            else:
                break

        if plateau_len >= 2:
            return ConvergenceVerdict(
                converged=True,
                reason=f"Score plateaued at {current:.1f} for {plateau_len} iterations",
                recommendation="stop",
                iterations=n,
                current_score=current,
            )

    # Check 3: Oscillation detection
    if n >= 3:
        directions = []
        for i in range(1, n):
            diff = state.scores[i] - state.scores[i - 1]
            if abs(diff) > PLATEAU_EPSILON:
                directions.append(1 if diff > 0 else -1)

        if len(directions) >= 3:
            sign_changes = sum(
                1 for i in range(1, len(directions))
                if directions[i] != directions[i - 1]
            )
            if sign_changes >= MAX_OSCILLATIONS:
                return ConvergenceVerdict(
                    converged=False,
                    reason=f"Score oscillating ({sign_changes} direction changes)",
                    recommendation="escalate",
                    iterations=n,
                    current_score=current,
                )

    # Check 4: Diminishing returns
    if n >= 3:
        recent_improvement = current - state.scores[-3]
        rate = recent_improvement / max(state.scores[-3], 1.0)
        if rate < MIN_IMPROVEMENT_RATE and current < 8.0:
            return ConvergenceVerdict(
                converged=True,
                reason=f"Diminishing returns: {rate:.1%} improvement over last 2 iterations",
                recommendation="stop" if current >= 6.0 else "escalate",
                iterations=n,
                current_score=current,
                improvement_rate=rate,
            )

    # Check 5: Max iterations reached
    if n >= max_iterations:
        return ConvergenceVerdict(
            converged=False,
            reason=f"Max iterations ({max_iterations}) reached",
            recommendation="stop" if current >= 6.0 else "escalate",
            iterations=n,
            current_score=current,
        )

    # Check 6: Text similarity (if texts available)
    if len(state.texts) >= 2:
        similarity = _text_similarity(state.texts[-1], state.texts[-2])
        if similarity > 0.95:
            return ConvergenceVerdict(
                converged=True,
                reason=f"Output text {similarity:.0%} similar to previous — no meaningful change",
                recommendation="stop",
                iterations=n,
                current_score=current,
            )

    # Still improving — continue
    improvement = current - previous
    return ConvergenceVerdict(
        converged=False,
        reason=f"Still improving: {previous:.1f} → {current:.1f} (+{improvement:.1f})",
        recommendation="continue",
        iterations=n,
        current_score=current,
        improvement_rate=improvement / max(previous, 1.0),
    )


def _text_similarity(a: str, b: str) -> float:
    """Quick text similarity check using character trigram overlap."""
    if not a or not b:
        return 0.0

    def trigrams(s: str) -> set:
        s = s.lower()
        return {s[i:i+3] for i in range(len(s) - 2)}

    ta = trigrams(a)
    tb = trigrams(b)
    if not ta or not tb:
        return 0.0

    intersection = len(ta & tb)
    union = len(ta | tb)
    return intersection / union if union > 0 else 0.0
