"""Tests for Handoff Filter."""
from src.governance.handoff import HandoffFilter, HandoffRecord


def test_filter_preserves_universal_fields():
    hf = HandoffFilter()
    spec = {"department": "engineering", "intent": "code_fix", "priority": "high",
            "problem": "bug in auth", "summary": "fix auth bug"}
    result = hf.filter(spec, "engineering", "quality")
    assert result["intent"] == "code_fix"
    assert result["priority"] == "high"
    assert result["department"] == "quality"  # updated


def test_filter_removes_source_dept_fields():
    hf = HandoffFilter()
    spec = {"department": "engineering", "intent": "code_fix",
            "problem": "bug", "code_diff": "big diff here",
            "implementation_notes": "lots of notes"}
    result = hf.filter(spec, "engineering", "quality")
    assert "code_diff" not in result
    assert "implementation_notes" not in result


def test_filter_keeps_target_dept_fields():
    hf = HandoffFilter()
    spec = {"department": "quality", "intent": "quality_review",
            "problem": "review code", "test_results": "all pass"}
    result = hf.filter(spec, "engineering", "quality")
    assert "test_results" in result


def test_filter_passes_non_dept_specific_fields():
    hf = HandoffFilter()
    spec = {"department": "engineering", "intent": "code_fix",
            "problem": "bug", "custom_field": "should survive",
            "task_id": "42"}
    result = hf.filter(spec, "engineering", "quality")
    assert result["custom_field"] == "should survive"
    assert result["task_id"] == "42"


def test_filter_updates_source():
    hf = HandoffFilter()
    spec = {"department": "engineering", "intent": "code_fix", "problem": "x"}
    result = hf.filter(spec, "engineering", "quality")
    assert result["source"] == "handoff:engineering→quality"


def test_compress_history():
    hf = HandoffFilter()
    spec = {"department": "engineering", "intent": "code_fix", "problem": "x"}
    result = hf.filter(spec, "engineering", "quality", history_text="Long conversation here")
    assert "handoff_history" in result
    assert "HANDOFF_HISTORY" in result["handoff_history"]
    assert "engineering" in result["handoff_history"]


def test_compress_long_history():
    hf = HandoffFilter()
    spec = {"department": "engineering", "intent": "test", "problem": "x"}
    long_history = "word " * 200  # > 500 chars
    result = hf.filter(spec, "engineering", "quality", history_text=long_history)
    assert "truncated=true" in result["handoff_history"]


def test_disabled_route():
    hf = HandoffFilter()
    hf.disable_route("engineering", "security")
    assert not hf.is_enabled("engineering", "security")
    assert hf.is_enabled("engineering", "quality")
    # Disabled route returns spec unchanged
    spec = {"department": "engineering", "problem": "x"}
    result = hf.filter(spec, "engineering", "security")
    assert result["department"] == "engineering"  # unchanged


def test_enable_route():
    hf = HandoffFilter()
    hf.disable_route("a", "b")
    hf.enable_route("a", "b")
    assert hf.is_enabled("a", "b")


def test_on_handoff_callback():
    hf = HandoffFilter()
    records = []
    hf.on_handoff(lambda r: records.append(r), name="test_cb")
    spec = {"department": "engineering", "intent": "test", "problem": "x"}
    hf.filter(spec, "engineering", "quality")
    assert len(records) == 1
    assert isinstance(records[0], HandoffRecord)
    assert records[0].from_dept == "engineering"
    assert records[0].to_dept == "quality"


def test_callback_failure_does_not_break_filter():
    hf = HandoffFilter()
    hf.on_handoff(lambda r: 1 / 0, name="bad_cb")  # will raise
    spec = {"department": "engineering", "intent": "test", "problem": "x"}
    result = hf.filter(spec, "engineering", "quality")
    assert result["department"] == "quality"  # still works


def test_get_stats():
    hf = HandoffFilter()
    spec = {"department": "eng", "intent": "t", "problem": "x"}
    hf.filter(spec, "engineering", "quality")
    hf.filter(spec, "quality", "operations")
    stats = hf.get_stats()
    assert stats["total_handoffs"] == 2


def test_get_stats_empty():
    hf = HandoffFilter()
    stats = hf.get_stats()
    assert stats["total_handoffs"] == 0
    assert stats["avg_compression"] == 0.0


def test_get_history():
    hf = HandoffFilter()
    spec = {"department": "eng", "intent": "t", "problem": "x"}
    hf.filter(spec, "engineering", "quality")
    hf.filter(spec, "quality", "operations")
    history = hf.get_history(limit=1)
    assert len(history) == 1
    assert history[0].to_dept == "operations"


def test_compression_ratio_recorded():
    hf = HandoffFilter()
    spec = {"department": "engineering", "intent": "test", "problem": "x",
            "code_diff": "a" * 1000, "git_log": "b" * 500}
    hf.filter(spec, "engineering", "quality")
    record = hf.get_history()[0]
    assert record.compression_ratio > 0  # should have trimmed something
    assert record.context_before > record.context_after
