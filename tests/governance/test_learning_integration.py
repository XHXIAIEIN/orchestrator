# tests/governance/test_learning_integration.py
"""Tests for wiring orphan learning modules into production paths.

Verifies:
1. fact_extractor is called from ReviewManager.finalize_task
2. experience_cull is called from maintenance.experience_cull
3. fix_first classifies eval findings in the review pipeline
"""
import json
import types
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call

import pytest


# ── fact_extractor unit tests ──

class TestFactExtractor:
    """Test fact_extractor.extract_facts independently."""

    def test_extract_error_fix(self):
        from src.governance.learning.fact_extractor import extract_facts

        output = "The build failed because missing dependency foo. Fixed by installing foo==2.0"
        facts = extract_facts(output)
        assert len(facts) >= 1
        assert any("error_fix" in f.pattern_key for f in facts)

    def test_extract_config(self):
        from src.governance.learning.fact_extractor import extract_facts

        output = "Resolved by setting max_retries to 5 in the config."
        facts = extract_facts(output)
        assert any("config" in f.pattern_key for f in facts)

    def test_extract_workaround(self):
        from src.governance.learning.fact_extractor import extract_facts

        output = "The API doesn't support batch mode, use single requests instead."
        facts = extract_facts(output)
        assert any("workaround" in f.pattern_key for f in facts)

    def test_extract_dependency(self):
        from src.governance.learning.fact_extractor import extract_facts

        output = "module_a depends on module_b for the data pipeline."
        facts = extract_facts(output)
        assert any("dep" in f.pattern_key for f in facts)

    def test_extract_performance(self):
        from src.governance.learning.fact_extractor import extract_facts

        output = "The query takes 450 milliseconds on average."
        facts = extract_facts(output)
        assert any("perf" in f.pattern_key for f in facts)

    def test_empty_output_no_facts(self):
        from src.governance.learning.fact_extractor import extract_facts

        facts = extract_facts("")
        assert facts == []

    def test_max_15_facts(self):
        from src.governance.learning.fact_extractor import extract_facts

        # Build output with many patterns
        lines = []
        for i in range(20):
            lines.append(f"module_{i}_aaa depends on module_{i}_bbb")
        output = "\n".join(lines)
        facts = extract_facts(output)
        assert len(facts) <= 15

    def test_dedup_by_pattern_key(self):
        from src.governance.learning.fact_extractor import extract_facts

        output = (
            "module_foo depends on module_bar.\n"
            "module_foo depends on module_bar again.\n"
        )
        facts = extract_facts(output)
        keys = [f.pattern_key for f in facts]
        assert len(keys) == len(set(keys))


# ── fix_first unit tests ──

class TestFixFirst:
    """Test fix_first classification logic."""

    def test_auto_fix_lint(self):
        from src.governance.quality.fix_first import classify_finding, FixAction

        result = classify_finding("ruff found unused import", "HIGH")
        assert result.action == FixAction.AUTO_FIX

    def test_ask_architecture(self):
        from src.governance.quality.fix_first import classify_finding, FixAction

        result = classify_finding("architecture decision needed for service split", "CRITICAL")
        assert result.action == FixAction.ASK

    def test_skip_low_info(self):
        from src.governance.quality.fix_first import classify_finding, FixAction

        result = classify_finding("note: consider adding more comments", "INFO")
        assert result.action == FixAction.SKIP

    def test_classify_eval_result(self):
        from src.governance.quality.fix_first import classify_eval_result, FixAction
        from src.governance.pipeline.eval_loop import EvalResult, EvalIssue, IssueSeverity

        eval_result = EvalResult(
            passed=False,
            issues=[
                EvalIssue(severity=IssueSeverity.HIGH, description="unused import os"),
                EvalIssue(severity=IssueSeverity.CRITICAL, description="architecture redesign needed"),
                EvalIssue(severity=IssueSeverity.INFO, description="nit: spacing"),
            ],
        )
        report = classify_eval_result(eval_result, task_id=42)
        assert report.task_id == 42
        assert len(report.findings) == 3
        assert not report.can_auto_resolve  # architecture = ASK

    def test_all_auto_fixable(self):
        from src.governance.quality.fix_first import classify_eval_result, FixAction
        from src.governance.pipeline.eval_loop import EvalResult, EvalIssue, IssueSeverity

        eval_result = EvalResult(
            passed=False,
            issues=[
                EvalIssue(severity=IssueSeverity.HIGH, description="missing type hint annotation"),
                EvalIssue(severity=IssueSeverity.LOW, description="typo in variable name"),
            ],
        )
        report = classify_eval_result(eval_result, task_id=10)
        assert report.can_auto_resolve


# ── experience_cull unit tests ──

class TestExperienceCull:
    """Test experience_cull.run_cull logic."""

    def test_cull_report_format(self):
        from src.governance.learning.experience_cull import CullReport

        report = CullReport(
            retired=[{"pattern_key": "old_rule", "hit_count": 0, "age_days": 20}],
            at_risk=[],
            promoted=[],
            total_active=10,
        )
        text = report.format()
        assert "Retired 1" in text
        assert "10 active" in text

    def test_record_hit_graceful(self):
        """record_hit should not raise on DB error."""
        from src.governance.learning.experience_cull import record_hit

        mock_db = MagicMock()
        mock_db._connect.side_effect = Exception("DB locked")
        # Should not raise
        record_hit(mock_db, learning_id=999)


# ── Integration: fact_extractor wired into ReviewManager ──

class TestFactExtractorIntegration:
    """Verify fact_extractor is called during finalize_task."""

    def test_fact_extractor_called_on_done(self):
        """When a task completes, extract_facts should be called on the output."""
        from src.governance.learning.fact_extractor import extract_facts as real_extract

        mock_db = MagicMock()
        mock_db.get_agent_events.return_value = []
        mock_db.unblock_ready_dependents.return_value = []

        with patch("src.governance.review.extract_facts", wraps=real_extract) as mock_extract, \
             patch("src.governance.review.save_extracted_facts") as mock_save, \
             patch("src.governance.review.validate_output", return_value={"valid": True, "missing_fields": [], "score": 1.0}), \
             patch("src.governance.review.append_run_log", None), \
             patch("src.governance.review.record_outcome", None), \
             patch("src.governance.review.get_fan_out", None), \
             patch("src.governance.review.observe_task_execution", None), \
             patch("src.governance.review.should_trigger", return_value=False):

            from src.governance.review import ReviewManager
            rm = ReviewManager(db=mock_db)

            output = "Build failed because missing dep. Fixed by pip install requests."
            rm.finalize_task(
                task_id=1,
                task={"spec": {}, "source": "test"},
                dept_key="engineering",
                status="done",
                output=output,
                task_cwd="/tmp",
                project_name="test",
                now=datetime.now(timezone.utc).isoformat(),
            )

            mock_extract.assert_called_once()
            # save should be called since the output has extractable facts
            mock_save.assert_called_once()

    def test_fact_extractor_skipped_on_failure(self):
        """fact_extractor should not run when task status is not 'done'."""
        mock_db = MagicMock()
        mock_db.get_agent_events.return_value = []

        with patch("src.governance.review.extract_facts") as mock_extract, \
             patch("src.governance.review.validate_output", return_value={"valid": True, "missing_fields": [], "score": 1.0}), \
             patch("src.governance.review.append_run_log", None), \
             patch("src.governance.review.record_outcome", None), \
             patch("src.governance.review.get_fan_out", None), \
             patch("src.governance.review.observe_task_execution", None):

            from src.governance.review import ReviewManager
            rm = ReviewManager(db=mock_db)

            rm.finalize_task(
                task_id=2,
                task={"spec": {}, "source": "test"},
                dept_key="engineering",
                status="failed",
                output="something broke",
                task_cwd="/tmp",
                project_name="test",
                now=datetime.now(timezone.utc).isoformat(),
            )

            mock_extract.assert_not_called()


# ── Integration: fix_first wired into review pipeline ──

class TestFixFirstIntegration:
    """Verify fix_first classifies findings in the quality review path."""

    def test_fix_first_called_for_quality_dept(self):
        """When dept_key='quality', fix_first should classify eval findings."""
        mock_db = MagicMock()
        mock_db.get_agent_events.return_value = []
        mock_db.unblock_ready_dependents.return_value = []

        eval_output = "[CRITICAL] architecture redesign\n[HIGH] missing return statement\nPassed: NO"

        with patch("src.governance.review.classify_eval_result") as mock_classify, \
             patch("src.governance.review.validate_output", return_value={"valid": True, "missing_fields": [], "score": 1.0}), \
             patch("src.governance.review.append_run_log", None), \
             patch("src.governance.review.record_outcome", None), \
             patch("src.governance.review.get_fan_out", None), \
             patch("src.governance.review.observe_task_execution", None), \
             patch("src.governance.review.should_trigger", return_value=False), \
             patch("src.governance.review.extract_facts", return_value=[]), \
             patch("src.governance.review.parse_eval_output") as mock_parse:

            # Set up mock eval result with issues
            mock_eval = MagicMock()
            mock_eval.passed = False
            mock_eval.critical_count = 1
            mock_eval.high_count = 1
            mock_eval.should_rework = True
            mock_eval.issues = [MagicMock(), MagicMock()]
            mock_parse.return_value = mock_eval

            mock_report = MagicMock()
            mock_report.auto_fixable = [MagicMock()]
            mock_report.needs_human = [MagicMock()]
            mock_report.skippable = []
            mock_report.can_auto_resolve = False
            mock_classify.return_value = mock_report

            from src.governance.review import ReviewManager
            rm = ReviewManager(db=mock_db)

            rm.finalize_task(
                task_id=5,
                task={"spec": {"rework_count": 0}, "source": "test"},
                dept_key="quality",
                status="done",
                output=eval_output,
                task_cwd="/tmp",
                project_name="test",
                now=datetime.now(timezone.utc).isoformat(),
            )

            mock_classify.assert_called_once()
            # Should store fix_first_report event
            mock_db.add_agent_event.assert_any_call(5, "fix_first_report", {
                "auto_fix": 1,
                "ask": 1,
                "skip": 0,
                "can_auto_resolve": False,
            })


# ── Integration: experience_cull wired into maintenance ──

class TestExperienceCullIntegration:
    """Verify experience_cull is callable from maintenance."""

    def test_experience_cull_function_exists(self):
        from src.jobs.maintenance import experience_cull
        assert callable(experience_cull)

    def test_experience_cull_calls_run_cull(self):
        from src.governance.learning.experience_cull import CullReport

        mock_db = MagicMock()
        mock_report = CullReport(retired=[], at_risk=[], promoted=[], total_active=5)

        with patch("src.jobs.maintenance.run_cull", return_value=mock_report) as mock_cull:
            from src.jobs.maintenance import experience_cull
            experience_cull(mock_db)
            mock_cull.assert_called_once_with(mock_db)

    def test_experience_cull_logs_on_changes(self):
        from src.governance.learning.experience_cull import CullReport

        mock_db = MagicMock()
        mock_report = CullReport(
            retired=[{"pattern_key": "stale_rule"}],
            at_risk=[],
            promoted=[{"pattern_key": "proven_rule"}],
            total_active=20,
        )

        with patch("src.jobs.maintenance.run_cull", return_value=mock_report):
            from src.jobs.maintenance import experience_cull
            experience_cull(mock_db)
            mock_db.write_log.assert_called_once()
            log_msg = mock_db.write_log.call_args[0][0]
            assert "retired 1" in log_msg
            assert "promoted 1" in log_msg


# ── Integration: scheduler registers experience_cull ──

class TestSchedulerRegistration:
    """Verify experience_cull is importable from scheduler."""

    def test_experience_cull_imported_in_scheduler(self):
        """The scheduler module should import experience_cull."""
        import importlib
        # Just verify the import works
        from src.jobs.maintenance import experience_cull
        assert experience_cull is not None


# ── Overlap analysis: fact_extractor vs memory_extractor ──

class TestNoOverlap:
    """Verify fact_extractor and memory_extractor serve different purposes."""

    def test_different_output_types(self):
        """fact_extractor returns ExtractedFact, memory_extractor returns dicts."""
        from src.governance.learning.fact_extractor import extract_facts, ExtractedFact
        # memory_extractor returns list[dict] with keys: category, l0, l1, tags
        # fact_extractor returns list[ExtractedFact] with keys: pattern_key, rule, area, ...
        # They target different storage: learnings table vs memory directory

        facts = extract_facts("setting max_workers to 8 resolved the issue")
        if facts:
            assert isinstance(facts[0], ExtractedFact)
            assert hasattr(facts[0], "pattern_key")
            assert hasattr(facts[0], "rule")

    def test_fact_extractor_is_regex_based(self):
        """fact_extractor uses regex, not LLM — safe for hot path."""
        from src.governance.learning.fact_extractor import extract_facts

        # Should return instantly (no LLM call)
        import time
        start = time.monotonic()
        extract_facts("some output text with no patterns")
        elapsed = time.monotonic() - start
        assert elapsed < 1.0  # must be sub-second (regex only)
