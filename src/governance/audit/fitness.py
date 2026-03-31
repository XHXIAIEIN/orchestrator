"""
Harness Engineering — fitness rules with Gate/Tier semantics.

Stolen from phodal/entrix (Round 15):
- Gate: HARD (blocks) / SOFT (weighted score) / ADVISORY (report only)
- Tier: FAST (<30s) / NORMAL (<5min) / DEEP (<15min)
- Rules defined in docs/fitness/*.md YAML frontmatter (Markdown-as-Code)

Data flow:
  docs/fitness/*.md → load_fitness_rules() → FitnessRule[]
  FitnessRule + ExamResult → evaluate() → FitnessVerdict
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from src.governance.audit.waiver import WaiverRegistry

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Gate(Enum):
    """Three-level gate semantics (entrix pattern).

    HARD  — blocks pipeline, exit code 2
    SOFT  — contributes to weighted score, can fail overall
    ADVISORY — report only, never blocks or degrades score
    """
    HARD = "hard"
    SOFT = "soft"
    ADVISORY = "advisory"


class Tier(Enum):
    """Progressive execution depth (entrix pattern).

    FAST   — <30s: lint, static checks, quick sanity
    NORMAL — <5min: unit tests, contract checks, exam scoring
    DEEP   — <15min: E2E, security scan, full audit
    """
    FAST = "fast"
    NORMAL = "normal"
    DEEP = "deep"

    @classmethod
    def includes(cls, run_tier: Tier) -> list[Tier]:
        """Return tiers that should execute at a given run_tier.

        e.g. Tier.NORMAL includes [FAST, NORMAL]
        """
        order = [cls.FAST, cls.NORMAL, cls.DEEP]
        idx = order.index(run_tier)
        return order[: idx + 1]


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class FitnessRule:
    """A single fitness check dimension, loaded from YAML frontmatter."""
    dimension: str
    pattern_key: str
    gate: Gate = Gate.SOFT
    tier: Tier = Tier.NORMAL
    weight: int = 50
    threshold_pass: int = 85
    threshold_warn: int = 70
    error_summary: str = ""
    learning_summary: str = ""
    detail: str = ""
    # Waiver support (entrix pattern)
    waiver_reason: str = ""
    waiver_expires: str = ""  # ISO date


@dataclass
class RuleVerdict:
    """Result of evaluating one rule against a score."""
    dimension: str
    score: float
    gate: Gate
    tier: Tier
    status: str  # "pass" | "warn" | "fail" | "waived"
    message: str = ""
    original_gate: Gate | None = None  # set when waiver downgraded the gate
    waived_by: str = ""  # waiver rule_id if a waiver was applied


@dataclass
class FitnessVerdict:
    """Aggregate result of all fitness rules."""
    results: list[RuleVerdict] = field(default_factory=list)
    weighted_score: float = 0.0
    hard_failures: list[str] = field(default_factory=list)
    evidence_gaps: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return len(self.hard_failures) == 0

    @property
    def exit_code(self) -> int:
        """Entrix-compatible exit codes: 0=pass, 1=score low, 2=hard fail."""
        if self.hard_failures:
            return 2
        if self.weighted_score < 70:
            return 1
        return 0


# ---------------------------------------------------------------------------
# YAML frontmatter loader
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)


def _parse_yaml_simple(text: str) -> dict[str, Any]:
    """Minimal YAML parser for flat key-value frontmatter.

    Handles: strings, ints, floats. No nested structures needed.
    Avoids PyYAML dependency for this lightweight use case.
    """
    result = {}
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        # Type coercion
        if val.isdigit():
            result[key] = int(val)
        elif val.replace(".", "", 1).isdigit():
            result[key] = float(val)
        else:
            result[key] = val
    return result


def _load_one_rule(path: Path) -> FitnessRule | None:
    """Load a single fitness rule from a markdown file."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        log.warning("fitness: cannot read %s", path)
        return None

    m = _FRONTMATTER_RE.match(text)
    if not m:
        log.warning("fitness: no frontmatter in %s", path)
        return None

    meta = _parse_yaml_simple(m.group(1))

    dimension = meta.get("dimension", path.stem)
    gate_str = meta.get("gate", "soft")
    tier_str = meta.get("tier", "normal")

    # Body after frontmatter = detail text
    body = text[m.end():].strip()

    return FitnessRule(
        dimension=dimension,
        pattern_key=meta.get("pattern_key", f"agent-{dimension}-fitness"),
        gate=Gate(gate_str) if gate_str in ("hard", "soft", "advisory") else Gate.SOFT,
        tier=Tier(tier_str) if tier_str in ("fast", "normal", "deep") else Tier.NORMAL,
        weight=meta.get("weight", 50),
        threshold_pass=meta.get("threshold_pass", 85),
        threshold_warn=meta.get("threshold_warn", 70),
        error_summary=meta.get("error_summary", ""),
        learning_summary=meta.get("learning_summary", ""),
        detail=body or meta.get("detail", ""),
        waiver_reason=meta.get("waiver_reason", ""),
        waiver_expires=meta.get("waiver_expires", ""),
    )


def load_fitness_rules(
    fitness_dir: str | Path = "docs/fitness",
) -> dict[str, FitnessRule]:
    """Load all fitness rules from a directory of markdown files.

    Returns: {dimension_name: FitnessRule}
    """
    fitness_path = Path(fitness_dir)
    if not fitness_path.is_dir():
        log.info("fitness: directory %s not found, using empty rules", fitness_dir)
        return {}

    rules = {}
    for md_file in sorted(fitness_path.glob("*.md")):
        rule = _load_one_rule(md_file)
        if rule:
            rules[rule.dimension] = rule
            log.debug("fitness: loaded %s (gate=%s, tier=%s)", rule.dimension, rule.gate.value, rule.tier.value)

    log.info("fitness: loaded %d rules from %s", len(rules), fitness_dir)
    return rules


# ---------------------------------------------------------------------------
# Evaluation engine
# ---------------------------------------------------------------------------


def _check_waiver(
    rule: FitnessRule,
    waiver_registry: WaiverRegistry | None,
) -> tuple[Gate, str, str]:
    """Check if a rule has an active waiver and compute the effective gate.

    Returns (effective_gate, waiver_id, waiver_message).
    If no waiver applies, returns (rule.gate, "", "").

    Waiver logic:
      - HARD + waiver → downgrade to SOFT (still scored, but won't block)
      - SOFT + waiver → downgrade to ADVISORY (reported, but no score impact)
      - ADVISORY + waiver → stays ADVISORY (already non-blocking)
    """
    waiver_id = ""
    waiver_msg = ""

    # --- Priority 1: WaiverRegistry (the proper system) ---
    if waiver_registry is not None and waiver_registry.is_waived(rule.dimension):
        waiver = waiver_registry.get(rule.dimension)
        if waiver is not None:
            waiver_id = waiver.rule_id
            waiver_msg = f"Waived until {waiver.expires_at}: {waiver.reason} (owner={waiver.owner})"
    else:
        # --- Priority 2: Legacy frontmatter waiver (backward compat) ---
        if rule.waiver_reason and rule.waiver_expires:
            from datetime import date
            try:
                expires = date.fromisoformat(rule.waiver_expires)
                if date.today() <= expires:
                    waiver_id = f"frontmatter:{rule.dimension}"
                    waiver_msg = f"Waived until {rule.waiver_expires}: {rule.waiver_reason}"
            except ValueError:
                pass

    if not waiver_id:
        return rule.gate, "", ""

    # Downgrade gate
    _downgrade = {Gate.HARD: Gate.SOFT, Gate.SOFT: Gate.ADVISORY, Gate.ADVISORY: Gate.ADVISORY}
    effective_gate = _downgrade[rule.gate]
    log.info("fitness: waiver active for '%s' — gate %s→%s (%s)",
             rule.dimension, rule.gate.value, effective_gate.value, waiver_id)
    return effective_gate, waiver_id, waiver_msg


def evaluate_rules(
    rules: dict[str, FitnessRule],
    scores: dict[str, float],
    *,
    run_tier: Tier = Tier.NORMAL,
    changed_files: list[str] | None = None,
    test_files_changed: list[str] | None = None,
    waiver_registry: WaiverRegistry | None = None,
) -> FitnessVerdict:
    """Evaluate fitness rules against dimension scores.

    Args:
        rules: loaded fitness rules
        scores: {dimension: score} from exam or self-eval
        run_tier: only evaluate rules at this tier or below
        changed_files: git-changed source files (for evidence gap)
        test_files_changed: git-changed test files (for evidence gap)
        waiver_registry: optional WaiverRegistry for rule exemptions
    """
    # Auto-expire stale waivers before evaluation
    if waiver_registry is not None:
        expired = waiver_registry.enforce_expired()
        for w in expired:
            log.info("fitness: waiver expired pre-eval — rule '%s' now enforced", w.rule_id)

    active_tiers = Tier.includes(run_tier)
    verdict = FitnessVerdict()

    total_weight = 0
    weighted_sum = 0.0

    for dim, rule in rules.items():
        if rule.tier not in active_tiers:
            continue

        # --- Waiver check (integrated) ---
        effective_gate, waiver_id, waiver_msg = _check_waiver(rule, waiver_registry)

        score = scores.get(dim)
        if score is None:
            # Even with no score, record waived status if waiver is active
            if waiver_id:
                verdict.results.append(RuleVerdict(
                    dimension=dim, score=-1, gate=effective_gate, tier=rule.tier,
                    status="waived", message=waiver_msg,
                    original_gate=rule.gate, waived_by=waiver_id,
                ))
            continue

        # Determine status
        if score >= rule.threshold_pass:
            status = "pass"
            msg = ""
        elif score >= rule.threshold_warn:
            status = "warn"
            msg = rule.error_summary or f"{dim} score {score} below pass threshold {rule.threshold_pass}"
        else:
            status = "fail"
            msg = rule.error_summary or f"{dim} score {score} below warn threshold {rule.threshold_warn}"

        rv = RuleVerdict(
            dimension=dim, score=score, gate=effective_gate, tier=rule.tier,
            status=status, message=msg,
            original_gate=rule.gate if waiver_id else None,
            waived_by=waiver_id,
        )
        verdict.results.append(rv)

        # Gate semantics — uses effective_gate (already downgraded by waiver)
        if status == "fail" and effective_gate == Gate.HARD:
            verdict.hard_failures.append(dim)

        # Weighted scoring (SOFT + HARD contribute, ADVISORY does not)
        if effective_gate != Gate.ADVISORY:
            total_weight += rule.weight
            weighted_sum += rule.weight * score

    # Final weighted score
    if total_weight > 0:
        verdict.weighted_score = weighted_sum / total_weight

    # Evidence gap detection (entrix pattern)
    if changed_files is not None and test_files_changed is not None:
        verdict.evidence_gaps = detect_evidence_gaps(changed_files, test_files_changed)

    return verdict


# ---------------------------------------------------------------------------
# Evidence Gap detection (entrix Review Trigger pattern)
# ---------------------------------------------------------------------------

# Source patterns → expected test companion patterns
_SOURCE_TO_TEST = [
    (re.compile(r"^src/(.+)\.py$"), r"tests/test_\1.py"),
    (re.compile(r"^src/(.+)/([^/]+)\.py$"), r"tests/test_\2.py"),
]


def detect_evidence_gaps(
    changed_sources: list[str],
    changed_tests: list[str],
) -> list[str]:
    """Detect source files changed without corresponding test changes.

    Returns list of source files missing test evidence.
    """
    gaps = []
    test_set = set(changed_tests)

    for src in changed_sources:
        # Skip non-Python, __init__, and test files themselves
        if not src.endswith(".py"):
            continue
        if "__init__" in src or src.startswith("tests/"):
            continue
        if "/migrations/" in src or "/_schema" in src:
            continue

        has_evidence = False
        for pattern, replacement in _SOURCE_TO_TEST:
            m = pattern.match(src.replace("\\", "/"))
            if m:
                expected_test = m.expand(replacement)
                # Check if any changed test file matches
                for test in test_set:
                    normalized = test.replace("\\", "/")
                    if expected_test in normalized or Path(expected_test).stem in normalized:
                        has_evidence = True
                        break
            if has_evidence:
                break

        # Also check if ANY test file changed (relaxed mode)
        if not has_evidence and test_set:
            # If at least some tests changed, only flag files with zero test coverage
            has_evidence = False

        if not has_evidence and not test_set:
            # No tests changed at all — flag everything
            gaps.append(src)
        elif not has_evidence:
            gaps.append(src)

    return gaps
