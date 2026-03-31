"""Tests for waiver integration into fitness rules evaluation.

Covers:
  - WaiverRegistry + evaluate_rules integration
  - HARD→SOFT downgrade with active waiver
  - SOFT→ADVISORY downgrade with active waiver
  - Expired waiver = full enforcement
  - Revoked waiver = full enforcement
  - Missing waiver = no effect
  - WaiverRegistry auto-expiry during evaluation
  - Legacy frontmatter waiver backward compatibility
"""
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.governance.audit.fitness import (
    Gate,
    Tier,
    FitnessRule,
    evaluate_rules,
)
from src.governance.audit.waiver import Waiver, WaiverRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _future_iso(days: int = 30) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _past_iso(days: int = 1) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _make_registry(tmp_path: Path, waivers: list[Waiver] | None = None) -> WaiverRegistry:
    """Create a WaiverRegistry with an ephemeral file."""
    reg = WaiverRegistry(waiver_file=str(tmp_path / "waivers.yaml"))
    for w in (waivers or []):
        reg.register(w)
    return reg


def _hard_rule(dim: str = "execution") -> FitnessRule:
    return FitnessRule(
        dimension=dim, pattern_key=f"{dim}-key",
        gate=Gate.HARD, tier=Tier.NORMAL,
        weight=35, threshold_pass=85, threshold_warn=70,
    )


def _soft_rule(dim: str = "understanding") -> FitnessRule:
    return FitnessRule(
        dimension=dim, pattern_key=f"{dim}-key",
        gate=Gate.SOFT, tier=Tier.NORMAL,
        weight=20, threshold_pass=90, threshold_warn=75,
    )


def _advisory_rule(dim: str = "retrieval") -> FitnessRule:
    return FitnessRule(
        dimension=dim, pattern_key=f"{dim}-key",
        gate=Gate.ADVISORY, tier=Tier.FAST,
        weight=10, threshold_pass=90, threshold_warn=80,
    )


# ---------------------------------------------------------------------------
# Waiver grant + HARD→SOFT downgrade
# ---------------------------------------------------------------------------

def test_hard_rule_with_active_waiver_downgrades_to_soft(tmp_path):
    """HARD rule + active waiver → downgraded to SOFT, no hard_failure."""
    rules = {"execution": _hard_rule()}
    reg = _make_registry(tmp_path, [
        Waiver(rule_id="execution", reason="Migration in progress",
               owner="礼部", expires_at=_future_iso()),
    ])
    scores = {"execution": 50}  # well below threshold

    v = evaluate_rules(rules, scores, waiver_registry=reg)

    assert v.passed, "Should pass — HARD downgraded to SOFT"
    assert "execution" not in v.hard_failures
    r = v.results[0]
    assert r.gate == Gate.SOFT
    assert r.original_gate == Gate.HARD
    assert r.waived_by == "execution"
    assert r.status == "fail"


def test_hard_rule_with_active_waiver_still_contributes_to_score(tmp_path):
    """Downgraded HARD→SOFT still contributes to weighted score."""
    rules = {"execution": _hard_rule()}
    reg = _make_registry(tmp_path, [
        Waiver(rule_id="execution", reason="test",
               owner="test", expires_at=_future_iso()),
    ])
    scores = {"execution": 50}

    v = evaluate_rules(rules, scores, waiver_registry=reg)

    # SOFT contributes to weighted score
    assert v.weighted_score == 50.0


# ---------------------------------------------------------------------------
# SOFT→ADVISORY downgrade
# ---------------------------------------------------------------------------

def test_soft_rule_with_active_waiver_downgrades_to_advisory(tmp_path):
    """SOFT rule + active waiver → ADVISORY, no score impact."""
    rules = {"understanding": _soft_rule()}
    reg = _make_registry(tmp_path, [
        Waiver(rule_id="understanding", reason="Refactoring",
               owner="工部", expires_at=_future_iso()),
    ])
    scores = {"understanding": 40}  # failing hard

    v = evaluate_rules(rules, scores, waiver_registry=reg)

    assert v.passed
    r = v.results[0]
    assert r.gate == Gate.ADVISORY
    assert r.original_gate == Gate.SOFT
    # ADVISORY doesn't contribute to weighted score
    assert v.weighted_score == 0.0  # no scoreable rules


# ---------------------------------------------------------------------------
# ADVISORY + waiver = stays ADVISORY
# ---------------------------------------------------------------------------

def test_advisory_rule_with_waiver_stays_advisory(tmp_path):
    """ADVISORY + waiver → still ADVISORY (can't downgrade further)."""
    rules = {"retrieval": _advisory_rule()}
    reg = _make_registry(tmp_path, [
        Waiver(rule_id="retrieval", reason="Expected",
               owner="test", expires_at=_future_iso()),
    ])
    scores = {"retrieval": 30}

    v = evaluate_rules(rules, scores, waiver_registry=reg)

    assert v.passed
    r = v.results[0]
    assert r.gate == Gate.ADVISORY


# ---------------------------------------------------------------------------
# Expired waiver = full enforcement
# ---------------------------------------------------------------------------

def test_expired_waiver_means_full_enforcement(tmp_path):
    """Expired waiver → rule enforced at original gate level."""
    rules = {"execution": _hard_rule()}
    reg = _make_registry(tmp_path, [
        Waiver(rule_id="execution", reason="Was migrating",
               owner="礼部", expires_at=_past_iso(days=5)),
    ])
    scores = {"execution": 50}

    v = evaluate_rules(rules, scores, waiver_registry=reg)

    assert not v.passed, "Expired waiver should not protect"
    assert "execution" in v.hard_failures
    r = v.results[0]
    assert r.gate == Gate.HARD
    assert r.waived_by == ""


# ---------------------------------------------------------------------------
# Revoked waiver = full enforcement
# ---------------------------------------------------------------------------

def test_revoked_waiver_means_full_enforcement(tmp_path):
    """Revoked (deactivated) waiver → rule enforced normally."""
    rules = {"execution": _hard_rule()}
    reg = _make_registry(tmp_path, [
        Waiver(rule_id="execution", reason="Was needed",
               owner="test", expires_at=_future_iso()),
    ])
    reg.revoke("execution")
    scores = {"execution": 50}

    v = evaluate_rules(rules, scores, waiver_registry=reg)

    assert not v.passed
    assert "execution" in v.hard_failures


# ---------------------------------------------------------------------------
# No waiver = normal behavior
# ---------------------------------------------------------------------------

def test_no_waiver_normal_enforcement(tmp_path):
    """Without any waiver, rules behave exactly as before."""
    rules = {"execution": _hard_rule(), "understanding": _soft_rule()}
    reg = _make_registry(tmp_path)  # empty registry
    scores = {"execution": 50, "understanding": 50}

    v = evaluate_rules(rules, scores, waiver_registry=reg)

    assert not v.passed
    assert "execution" in v.hard_failures


def test_none_registry_normal_enforcement():
    """waiver_registry=None → identical to pre-integration behavior."""
    rules = {"execution": _hard_rule()}
    scores = {"execution": 50}

    v = evaluate_rules(rules, scores, waiver_registry=None)

    assert not v.passed
    assert "execution" in v.hard_failures


# ---------------------------------------------------------------------------
# Auto-expiry during evaluation
# ---------------------------------------------------------------------------

def test_enforce_expired_during_evaluation(tmp_path):
    """evaluate_rules auto-deactivates expired waivers before checking."""
    reg = _make_registry(tmp_path, [
        Waiver(rule_id="execution", reason="Old waiver",
               owner="test", expires_at=_past_iso(days=10)),
    ])
    # The waiver is active=True but expired — enforce_expired should deactivate it
    assert reg.get("execution").active is True

    rules = {"execution": _hard_rule()}
    scores = {"execution": 50}
    v = evaluate_rules(rules, scores, waiver_registry=reg)

    # After evaluation, waiver should be deactivated
    assert reg.get("execution").active is False
    assert not v.passed


# ---------------------------------------------------------------------------
# Mixed: some rules waived, some not
# ---------------------------------------------------------------------------

def test_mixed_waiver_scenario(tmp_path):
    """Multiple rules, only some have waivers."""
    rules = {
        "execution": _hard_rule("execution"),
        "understanding": _soft_rule("understanding"),
        "retrieval": _advisory_rule("retrieval"),
    }
    reg = _make_registry(tmp_path, [
        Waiver(rule_id="execution", reason="Known gap",
               owner="兵部", expires_at=_future_iso()),
        # understanding has no waiver
    ])
    scores = {"execution": 50, "understanding": 50, "retrieval": 50}

    v = evaluate_rules(rules, scores, waiver_registry=reg)

    # execution: HARD→SOFT (waived), fail but no hard_failure
    assert "execution" not in v.hard_failures
    # understanding: SOFT, fail, contributes to score
    # retrieval: ADVISORY, fail, no score impact
    assert v.passed  # no hard failures

    exec_r = [r for r in v.results if r.dimension == "execution"][0]
    assert exec_r.waived_by == "execution"
    assert exec_r.gate == Gate.SOFT

    und_r = [r for r in v.results if r.dimension == "understanding"][0]
    assert und_r.waived_by == ""
    assert und_r.gate == Gate.SOFT


# ---------------------------------------------------------------------------
# Waiver with no score (rule dimension not in scores)
# ---------------------------------------------------------------------------

def test_waiver_with_no_score_records_waived_status(tmp_path):
    """If dimension has waiver but no score, record waived status."""
    rules = {"execution": _hard_rule()}
    reg = _make_registry(tmp_path, [
        Waiver(rule_id="execution", reason="No data yet",
               owner="test", expires_at=_future_iso()),
    ])
    scores = {}  # no score for execution

    v = evaluate_rules(rules, scores, waiver_registry=reg)

    assert v.passed
    waived = [r for r in v.results if r.status == "waived"]
    assert len(waived) == 1
    assert waived[0].dimension == "execution"
    assert waived[0].original_gate == Gate.HARD


# ---------------------------------------------------------------------------
# WaiverRegistry persistence round-trip
# ---------------------------------------------------------------------------

def test_waiver_registry_persistence(tmp_path):
    """Waivers survive save/load cycle."""
    path = str(tmp_path / "waivers.yaml")
    reg1 = WaiverRegistry(waiver_file=path)
    reg1.register(Waiver(
        rule_id="test-rule", reason="Testing persistence",
        owner="test", expires_at=_future_iso(),
    ))

    # Load fresh from same file
    reg2 = WaiverRegistry(waiver_file=path)
    assert reg2.is_waived("test-rule")
    w = reg2.get("test-rule")
    assert w.reason == "Testing persistence"
    assert w.owner == "test"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import inspect
    import tempfile

    tests = [
        (name, obj) for name, obj in inspect.getmembers(sys.modules[__name__])
        if name.startswith("test_") and callable(obj)
    ]
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
            import traceback
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed out of {len(tests)} tests")
