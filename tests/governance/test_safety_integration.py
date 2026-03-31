# tests/governance/test_safety_integration.py
"""Integration tests — verify safety modules are wired into the production pipeline.

Tests that:
1. Each safety module is importable from its integration point
2. Failures in safety modules don't crash the pipeline (try/except guards work)
3. Each module is called during the appropriate pipeline phase
"""
import pytest
from unittest.mock import MagicMock, patch


# ── Test 1: Scrutiny imports injection_test and prompt_lint ──

class TestScrutinyIntegration:
    """Verify injection_test and prompt_lint are wired into scrutiny.py."""

    def test_injection_test_imported_in_scrutiny(self):
        """injection_test should be importable from scrutiny module."""
        from src.governance import scrutiny
        # The module should have attempted the import
        assert hasattr(scrutiny, 'run_injection_suite')

    def test_prompt_lint_imported_in_scrutiny(self):
        """prompt_lint should be importable from scrutiny module."""
        from src.governance import scrutiny
        assert hasattr(scrutiny, 'lint_prompt')

    def test_scrutinize_runs_prompt_lint(self):
        """Scrutinizer.scrutinize should call lint_prompt on the assembled prompt."""
        from src.governance.scrutiny import Scrutinizer

        mock_db = MagicMock()
        mock_db.write_log = MagicMock()
        scrutinizer = Scrutinizer(db=mock_db)

        task = {
            "action": "test action",
            "spec": {"summary": "test", "department": "engineering"},
            "reason": "test",
        }

        # Mock the LLM call to avoid real API calls
        with patch("src.governance.scrutiny.get_router") as mock_router, \
             patch("src.governance.scrutiny.lint_prompt") as mock_lint:
            mock_router.return_value.generate.return_value = "VERDICT: APPROVE\nREASON: looks good"
            mock_lint.return_value = MagicMock(error_count=0, warning_count=0)

            approved, reason = scrutinizer.scrutinize(1, task)

            # lint_prompt should have been called with the assembled prompt
            mock_lint.assert_called_once()
            call_args = mock_lint.call_args
            assert "source" in call_args.kwargs or len(call_args.args) >= 2

    def test_scrutinize_runs_injection_test(self):
        """Scrutinizer.scrutinize should call run_injection_suite."""
        from src.governance.scrutiny import Scrutinizer

        mock_db = MagicMock()
        mock_db.write_log = MagicMock()
        scrutinizer = Scrutinizer(db=mock_db)

        task = {
            "action": "test action",
            "spec": {"summary": "test", "department": "engineering"},
            "reason": "test",
        }

        with patch("src.governance.scrutiny.get_router") as mock_router, \
             patch("src.governance.scrutiny.run_injection_suite") as mock_inject:
            mock_router.return_value.generate.return_value = "VERDICT: APPROVE\nREASON: ok"
            mock_inject.return_value = MagicMock(failed=0, score=100.0)

            scrutinizer.scrutinize(1, task)

            mock_inject.assert_called_once()
            assert mock_inject.call_args.kwargs.get("department") == "engineering"

    def test_scrutinize_survives_lint_crash(self):
        """If lint_prompt raises, scrutinize should not crash."""
        from src.governance.scrutiny import Scrutinizer

        mock_db = MagicMock()
        mock_db.write_log = MagicMock()
        scrutinizer = Scrutinizer(db=mock_db)

        task = {
            "action": "test action",
            "spec": {"summary": "test", "department": "engineering"},
            "reason": "test",
        }

        with patch("src.governance.scrutiny.get_router") as mock_router, \
             patch("src.governance.scrutiny.lint_prompt", side_effect=RuntimeError("boom")):
            mock_router.return_value.generate.return_value = "VERDICT: APPROVE\nREASON: ok"

            # Should not raise
            approved, reason = scrutinizer.scrutinize(1, task)
            assert isinstance(approved, bool)

    def test_scrutinize_survives_injection_crash(self):
        """If run_injection_suite raises, scrutinize should not crash."""
        from src.governance.scrutiny import Scrutinizer

        mock_db = MagicMock()
        mock_db.write_log = MagicMock()
        scrutinizer = Scrutinizer(db=mock_db)

        task = {
            "action": "test action",
            "spec": {"summary": "test", "department": "engineering"},
            "reason": "test",
        }

        with patch("src.governance.scrutiny.get_router") as mock_router, \
             patch("src.governance.scrutiny.run_injection_suite", side_effect=RuntimeError("boom")):
            mock_router.return_value.generate.return_value = "VERDICT: APPROVE\nREASON: ok"

            approved, reason = scrutinizer.scrutinize(1, task)
            assert isinstance(approved, bool)


# ── Test 2: Executor imports dual_verify and drift_detector ──

class TestExecutorIntegration:
    """Verify dual_verify and drift_detector are wired into executor.py."""

    def test_dual_verify_imported_in_executor(self):
        """dual_verify should be importable from executor module."""
        from src.governance import executor
        assert hasattr(executor, 'dual_cross_verify')

    def test_drift_detector_imported_in_executor(self):
        """DriftDetector should be importable from executor module."""
        from src.governance import executor
        assert hasattr(executor, 'DriftDetector')

    def test_blast_radius_imported_in_executor(self):
        """estimate_blast_radius should be imported for dual_verify gating."""
        from src.governance.executor import estimate_blast_radius
        assert callable(estimate_blast_radius)


# ── Test 3: Supervisor imports convergence and drift_detector ──

class TestSupervisorIntegration:
    """Verify convergence and drift_detector are wired into supervisor.py."""

    def test_convergence_imported_in_supervisor(self):
        """Convergence module should be importable from supervisor."""
        from src.governance import supervisor
        assert hasattr(supervisor, 'ConvergenceState')
        assert hasattr(supervisor, 'check_convergence')

    def test_drift_detector_imported_in_supervisor(self):
        """DriftDetector should be importable from supervisor."""
        from src.governance import supervisor
        assert hasattr(supervisor, 'DriftDetector')

    def test_supervisor_has_convergence_state(self):
        """RuntimeSupervisor should initialize convergence state."""
        from src.governance.supervisor import RuntimeSupervisor
        sv = RuntimeSupervisor()
        assert hasattr(sv, '_convergence_state')

    def test_supervisor_has_drift_detector_slot(self):
        """RuntimeSupervisor should have drift detector slot."""
        from src.governance.supervisor import RuntimeSupervisor
        sv = RuntimeSupervisor()
        assert hasattr(sv, '_drift_detector')

    def test_supervisor_record_convergence_score(self):
        """RuntimeSupervisor should accept convergence scores."""
        from src.governance.supervisor import RuntimeSupervisor
        sv = RuntimeSupervisor()
        sv.record_convergence_score(7.0, "iteration 1 output")
        sv.record_convergence_score(7.2, "iteration 2 output")
        if sv._convergence_state:
            assert len(sv._convergence_state.scores) == 2

    def test_supervisor_evaluate_includes_convergence(self):
        """When convergence scores plateau, evaluate should return a decision."""
        from src.governance.supervisor import RuntimeSupervisor
        sv = RuntimeSupervisor()

        # Record plateauing scores
        sv.record_convergence_score(6.0)
        sv.record_convergence_score(6.1)
        sv.record_convergence_score(6.1)

        decisions = sv.evaluate()
        # Should include convergence-related decision
        convergence_decisions = [d for d in decisions if "convergence" in d.detector_name]
        if sv._convergence_state:
            assert len(convergence_decisions) >= 1

    def test_supervisor_evaluate_includes_drift(self):
        """When drift detector is integrated and reports drift, evaluate should include it."""
        from src.governance.supervisor import RuntimeSupervisor

        sv = RuntimeSupervisor()

        # Create and integrate a mock drift detector
        if DriftReport is not None:
            mock_detector = MagicMock()
            mock_report = MagicMock()
            mock_report.is_drifting = True
            mock_report.should_intervene = False
            mock_report.drift_score = 0.6
            mock_report.to_dict.return_value = {"drift_score": 0.6}
            mock_detector.check.return_value = mock_report

            sv.integrate_drift_detector(mock_detector)
            decisions = sv.evaluate()

            drift_decisions = [d for d in decisions if "drift" in d.detector_name]
            assert len(drift_decisions) >= 1

    def test_supervisor_evaluate_survives_convergence_crash(self):
        """If convergence check raises, evaluate should not crash."""
        from src.governance.supervisor import RuntimeSupervisor
        sv = RuntimeSupervisor()
        sv.record_convergence_score(6.0)
        sv.record_convergence_score(6.0)

        with patch("src.governance.supervisor.check_convergence", side_effect=RuntimeError("boom")):
            # Should not raise
            decisions = sv.evaluate()
            assert isinstance(decisions, list)

    def test_supervisor_evaluate_survives_drift_crash(self):
        """If drift detector crashes, evaluate should not crash."""
        from src.governance.supervisor import RuntimeSupervisor
        sv = RuntimeSupervisor()

        mock_detector = MagicMock()
        mock_detector.check.side_effect = RuntimeError("boom")
        sv.integrate_drift_detector(mock_detector)

        decisions = sv.evaluate()
        assert isinstance(decisions, list)

    def test_integrate_drift_detector_method(self):
        """integrate_drift_detector should set the internal detector."""
        from src.governance.supervisor import RuntimeSupervisor
        sv = RuntimeSupervisor()
        mock = MagicMock()
        sv.integrate_drift_detector(mock)
        assert sv._drift_detector is mock


# Try to import DriftReport for conditional test
try:
    from src.governance.safety.drift_detector import DriftReport
except ImportError:
    DriftReport = None
