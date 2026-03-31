"""Tests for TaskHandoff — consolidated from Swarm R11 + Agents SDK HandoffFilter."""
import time
from src.governance.task_handoff import TaskHandoff, _DEPT_SPECIFIC_FIELDS, _UNIVERSAL_FIELDS


# ── Basic dataclass behavior ──

def test_basic_creation():
    h = TaskHandoff(
        from_dept="engineering", to_dept="quality",
        handoff_type="quality_review", task_id=1,
        output="done", reason="review needed",
    )
    assert h.from_dept == "engineering"
    assert h.to_dept == "quality"
    assert h.handoff_type == "quality_review"
    assert h.task_id == 1
    assert h.rework_count == 0
    assert h.timestamp > 0


def test_to_dict_basic():
    h = TaskHandoff(
        from_dept="quality", to_dept="engineering",
        handoff_type="rework", task_id=42,
        reason="failed review", rework_count=2,
        artifact={"commit": "abc123", "files_changed": ["a.py"]},
        context_updates={"department": "engineering"},
    )
    d = h.to_dict()
    assert d["from_dept"] == "quality"
    assert d["to_dept"] == "engineering"
    assert d["handoff_type"] == "rework"
    assert d["task_id"] == 42
    assert d["reason"] == "failed review"
    assert d["rework_count"] == 2
    assert "commit" in d["artifact_keys"]
    assert "department" in d["context_keys"]
    assert "timestamp" in d


def test_to_dict_omits_zero_compression():
    h = TaskHandoff(from_dept="a", to_dept="b", handoff_type="x", task_id=1)
    d = h.to_dict()
    assert "compression_ratio" not in d


def test_to_dict_includes_compression_when_nonzero():
    h = TaskHandoff(from_dept="a", to_dept="b", handoff_type="x", task_id=1,
                    compression_ratio=0.35)
    d = h.to_dict()
    assert d["compression_ratio"] == 0.35


def test_timestamp_auto_populated():
    before = time.time()
    h = TaskHandoff(from_dept="a", to_dept="b", handoff_type="x", task_id=1)
    after = time.time()
    assert before <= h.timestamp <= after


# ── Context filtering (from Agents SDK HandoffFilter) ──

def test_filter_preserves_universal_fields():
    h = TaskHandoff(from_dept="engineering", to_dept="quality",
                    handoff_type="quality_review", task_id=1)
    spec = {"department": "engineering", "intent": "code_fix", "priority": "high",
            "problem": "bug in auth", "summary": "fix auth bug"}
    result = h.filter_context(spec)
    assert result["intent"] == "code_fix"
    assert result["priority"] == "high"
    assert result["department"] == "quality"  # updated to target


def test_filter_removes_source_dept_fields():
    h = TaskHandoff(from_dept="engineering", to_dept="quality",
                    handoff_type="quality_review", task_id=1)
    spec = {"department": "engineering", "intent": "code_fix",
            "problem": "bug", "code_diff": "big diff here",
            "implementation_notes": "lots of notes"}
    result = h.filter_context(spec)
    assert "code_diff" not in result
    assert "implementation_notes" not in result


def test_filter_keeps_target_dept_fields():
    h = TaskHandoff(from_dept="engineering", to_dept="quality",
                    handoff_type="quality_review", task_id=1)
    spec = {"department": "quality", "intent": "quality_review",
            "problem": "review code", "test_results": "all pass"}
    result = h.filter_context(spec)
    assert "test_results" in result


def test_filter_passes_non_dept_specific_fields():
    h = TaskHandoff(from_dept="engineering", to_dept="quality",
                    handoff_type="quality_review", task_id=1)
    spec = {"department": "engineering", "intent": "code_fix",
            "problem": "bug", "custom_field": "should survive",
            "task_id": "42"}
    result = h.filter_context(spec)
    assert result["custom_field"] == "should survive"
    assert result["task_id"] == "42"


def test_filter_updates_source_tag():
    h = TaskHandoff(from_dept="engineering", to_dept="quality",
                    handoff_type="quality_review", task_id=1)
    spec = {"department": "engineering", "intent": "code_fix", "problem": "x"}
    result = h.filter_context(spec)
    assert result["source"] == "handoff:engineering\u2192quality"


def test_filter_populates_compression_metrics():
    h = TaskHandoff(from_dept="engineering", to_dept="quality",
                    handoff_type="quality_review", task_id=1)
    spec = {"department": "engineering", "intent": "test", "problem": "x",
            "code_diff": "a" * 1000, "git_log": "b" * 500}
    h.filter_context(spec)
    assert h.compression_ratio > 0
    assert h.context_before > h.context_after


def test_filter_stores_in_context_updates():
    h = TaskHandoff(from_dept="engineering", to_dept="quality",
                    handoff_type="quality_review", task_id=1)
    spec = {"department": "engineering", "intent": "test", "problem": "x"}
    result = h.filter_context(spec)
    assert h.context_updates == result


# ── History compression (Agents SDK nest_handoff_history) ──

def test_compress_history_short():
    result = TaskHandoff.compress_history("Short conversation", "engineering")
    assert "<HANDOFF_HISTORY from=engineering>" in result
    assert "Short conversation" in result
    assert "truncated" not in result


def test_compress_history_long():
    long_text = "word " * 200  # > 500 chars
    result = TaskHandoff.compress_history(long_text, "engineering")
    assert "truncated=true" in result
    assert f"original_len={len(long_text)}" in result


def test_compress_history_custom_max():
    text = "a " * 100  # 200 chars
    short = TaskHandoff.compress_history(text, "quality", max_len=50)
    assert "truncated=true" in short

    long_enough = TaskHandoff.compress_history(text, "quality", max_len=300)
    assert "truncated" not in long_enough


# ── Edge cases ──

def test_filter_empty_spec():
    h = TaskHandoff(from_dept="engineering", to_dept="quality",
                    handoff_type="quality_review", task_id=1)
    result = h.filter_context({})
    assert result["department"] == "quality"
    assert "source" in result


def test_filter_unknown_department():
    h = TaskHandoff(from_dept="engineering", to_dept="unknown_dept",
                    handoff_type="escalation", task_id=1)
    spec = {"department": "engineering", "intent": "test", "problem": "x",
            "code_diff": "big diff", "custom": "keep me"}
    result = h.filter_context(spec)
    # code_diff is engineering-specific, target is unknown → stripped
    assert "code_diff" not in result
    # custom is not dept-specific → kept
    assert result["custom"] == "keep me"


def test_rework_handoff_fields():
    """Verify rework handoffs carry the rework_count properly."""
    h = TaskHandoff(
        from_dept="quality", to_dept="engineering",
        handoff_type="rework", task_id=10,
        output="FAIL: tests broken",
        reason="quality review failed",
        rework_count=3,
    )
    d = h.to_dict()
    assert d["rework_count"] == 3
    assert d["handoff_type"] == "rework"
