"""Tests for fitness rules: Gate/Tier/loader/evaluator/evidence gap."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.governance.audit.fitness import (
    Gate,
    Tier,
    FitnessRule,
    FitnessVerdict,
    RuleVerdict,
    load_fitness_rules,
    evaluate_rules,
    detect_evidence_gaps,
    _parse_yaml_simple,
)


# ---------------------------------------------------------------------------
# Tier.includes
# ---------------------------------------------------------------------------

def test_tier_includes_fast():
    assert Tier.includes(Tier.FAST) == [Tier.FAST]


def test_tier_includes_normal():
    assert Tier.includes(Tier.NORMAL) == [Tier.FAST, Tier.NORMAL]


def test_tier_includes_deep():
    assert Tier.includes(Tier.DEEP) == [Tier.FAST, Tier.NORMAL, Tier.DEEP]


# ---------------------------------------------------------------------------
# YAML parser
# ---------------------------------------------------------------------------

def test_parse_yaml_simple():
    text = """
dimension: execution
weight: 35
threshold_pass: 85
gate: hard
"""
    result = _parse_yaml_simple(text)
    assert result["dimension"] == "execution"
    assert result["weight"] == 35
    assert result["threshold_pass"] == 85
    assert result["gate"] == "hard"


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def test_load_fitness_rules_from_project():
    """Load real rules from docs/fitness/ if available."""
    project_root = Path(__file__).parent.parent
    fitness_dir = project_root / "docs" / "fitness"
    if not fitness_dir.is_dir():
        return  # skip if not in project
    rules = load_fitness_rules(fitness_dir)
    assert len(rules) >= 4, f"Expected at least 4 rules, got {len(rules)}"
    assert "execution" in rules
    assert rules["execution"].gate == Gate.HARD
    assert rules["execution"].weight == 35


def test_load_fitness_rules_missing_dir(tmp_path):
    rules = load_fitness_rules(tmp_path / "nonexistent")
    assert rules == {}


def test_load_fitness_rules_custom(tmp_path):
    md = tmp_path / "test_dim.md"
    md.write_text(
        "---\n"
        "dimension: test_dim\n"
        "pattern_key: test-key\n"
        "gate: soft\n"
        "tier: fast\n"
        "weight: 20\n"
        "threshold_pass: 80\n"
        "threshold_warn: 60\n"
        "error_summary: Test failed\n"
        "learning_summary: Fix test\n"
        "---\n\nBody detail here.\n",
        encoding="utf-8",
    )
    rules = load_fitness_rules(tmp_path)
    assert "test_dim" in rules
    r = rules["test_dim"]
    assert r.gate == Gate.SOFT
    assert r.tier == Tier.FAST
    assert r.weight == 20
    assert "Body detail" in r.detail


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

def _make_rules():
    return {
        "execution": FitnessRule(
            dimension="execution", pattern_key="exec",
            gate=Gate.HARD, tier=Tier.NORMAL,
            weight=35, threshold_pass=85, threshold_warn=70,
        ),
        "reflection": FitnessRule(
            dimension="reflection", pattern_key="reflect",
            gate=Gate.HARD, tier=Tier.NORMAL,
            weight=30, threshold_pass=85, threshold_warn=65,
        ),
        "understanding": FitnessRule(
            dimension="understanding", pattern_key="understand",
            gate=Gate.SOFT, tier=Tier.NORMAL,
            weight=20, threshold_pass=90, threshold_warn=75,
        ),
        "retrieval": FitnessRule(
            dimension="retrieval", pattern_key="retrieval",
            gate=Gate.ADVISORY, tier=Tier.FAST,
            weight=10, threshold_pass=90, threshold_warn=80,
        ),
    }


def test_evaluate_all_pass():
    rules = _make_rules()
    scores = {"execution": 90, "reflection": 90, "understanding": 95, "retrieval": 95}
    v = evaluate_rules(rules, scores)
    assert v.passed
    assert v.exit_code == 0
    assert len(v.hard_failures) == 0


def test_evaluate_hard_failure():
    rules = _make_rules()
    scores = {"execution": 60, "reflection": 90, "understanding": 95}
    v = evaluate_rules(rules, scores)
    assert not v.passed
    assert v.exit_code == 2
    assert "execution" in v.hard_failures


def test_evaluate_soft_warn():
    rules = _make_rules()
    scores = {"execution": 90, "reflection": 90, "understanding": 78}
    v = evaluate_rules(rules, scores)
    assert v.passed  # SOFT warn doesn't block
    warns = [r for r in v.results if r.status == "warn"]
    assert len(warns) == 1
    assert warns[0].dimension == "understanding"


def test_evaluate_advisory_no_impact():
    rules = _make_rules()
    scores = {"execution": 90, "reflection": 90, "retrieval": 50}
    v = evaluate_rules(rules, scores)
    assert v.passed
    # Advisory failures don't appear in hard_failures
    assert "retrieval" not in v.hard_failures
    # But they do appear in results
    retrieval_result = [r for r in v.results if r.dimension == "retrieval"]
    assert len(retrieval_result) == 1
    assert retrieval_result[0].status == "fail"


def test_evaluate_tier_filtering():
    """FAST run should skip NORMAL tier rules."""
    rules = _make_rules()
    scores = {"execution": 60, "reflection": 60, "retrieval": 50}
    v = evaluate_rules(rules, scores, run_tier=Tier.FAST)
    # execution and reflection are NORMAL tier → skipped
    assert v.passed
    dims_evaluated = [r.dimension for r in v.results]
    assert "execution" not in dims_evaluated
    assert "retrieval" in dims_evaluated


def test_weighted_score():
    rules = _make_rules()
    # execution(35w)=100, reflection(30w)=100, understanding(20w)=50
    # advisory(retrieval) doesn't count
    # weighted = (35*100 + 30*100 + 20*50) / (35+30+20) = 7500/85 ≈ 88.24
    scores = {"execution": 100, "reflection": 100, "understanding": 50, "retrieval": 95}
    v = evaluate_rules(rules, scores)
    assert 88 < v.weighted_score < 89


def test_waiver_skips_rule(tmp_path):
    """Waiver with future expiry date should skip evaluation."""
    rules = {
        "execution": FitnessRule(
            dimension="execution", pattern_key="exec",
            gate=Gate.HARD, tier=Tier.NORMAL,
            weight=35, threshold_pass=85, threshold_warn=70,
            waiver_reason="Known issue, tracking in #42",
            waiver_expires="2099-12-31",
        ),
    }
    scores = {"execution": 30}
    v = evaluate_rules(rules, scores)
    assert v.passed
    waived = [r for r in v.results if r.status == "waived"]
    assert len(waived) == 1


# ---------------------------------------------------------------------------
# Evidence Gap
# ---------------------------------------------------------------------------

def test_evidence_gap_detected():
    changed = ["src/governance/audit/self_eval.py", "src/exam/coach.py"]
    tests = []  # no tests changed
    gaps = detect_evidence_gaps(changed, tests)
    assert len(gaps) == 2


def test_evidence_gap_with_matching_tests():
    changed = ["src/governance/audit/self_eval.py"]
    tests = ["tests/test_self_eval.py"]
    gaps = detect_evidence_gaps(changed, tests)
    assert len(gaps) == 0


def test_evidence_gap_ignores_init():
    changed = ["src/governance/__init__.py"]
    tests = []
    gaps = detect_evidence_gaps(changed, tests)
    assert len(gaps) == 0


def test_evidence_gap_ignores_schema():
    changed = ["src/storage/_schema.py"]
    tests = []
    gaps = detect_evidence_gaps(changed, tests)
    assert len(gaps) == 0


if __name__ == "__main__":
    import inspect
    tests = [
        (name, obj) for name, obj in inspect.getmembers(sys.modules[__name__])
        if name.startswith("test_") and callable(obj)
    ]
    import tempfile
    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            sig = inspect.signature(fn)
            if "tmp_path" in sig.parameters:
                with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
                    fn(Path(td))
            else:
                fn()
            passed += 1
        except Exception as e:
            print(f"FAIL {name}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed out of {len(tests)} tests")
