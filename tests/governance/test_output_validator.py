import pytest
from src.governance.output_validator import validate_output, load_output_schema, _field_patterns


def test_engineering_output_valid():
    output = """DONE: Refactored the parser module
    Files changed: src/parser.py, tests/test_parser.py
    Commit: abc123"""
    result = validate_output("engineering", output)
    assert result["valid"] is True
    assert "done_summary" in result["found_fields"]
    assert "files_changed" in result["found_fields"]


def test_engineering_output_missing_fields():
    output = "I looked at the code but didn't change anything."
    result = validate_output("engineering", output)
    # May or may not be valid depending on how lenient the patterns are
    # At minimum, test that it returns a score < 1.0
    assert result["score"] < 1.0


def test_quality_verdict_found():
    output = """Verdict: PASS
    Findings:
    - Code is clean
    - Tests pass"""
    result = validate_output("quality", output)
    assert result["valid"] is True


def test_unknown_department():
    result = validate_output("nonexistent", "some output")
    assert result["valid"] is True  # no schema = always valid


def test_field_patterns():
    patterns = _field_patterns("done_summary")
    assert "done:" in patterns
    assert "summary:" in patterns


def test_empty_output():
    result = validate_output("engineering", "")
    assert result["valid"] is False


def test_load_output_schema_engineering():
    schema = load_output_schema("engineering")
    assert "required_fields" in schema
    assert "done_summary" in schema["required_fields"]
    assert "files_changed" in schema["required_fields"]


def test_load_output_schema_nonexistent():
    schema = load_output_schema("nonexistent_dept")
    assert schema == {}


def test_operations_output_valid():
    output = """Summary: Ran DB vacuum and cleaned up stale records.
    Action taken: executed VACUUM on events.db
    Metrics before: 1.2GB, after: 800MB"""
    result = validate_output("operations", output)
    assert result["valid"] is True


def test_operations_output_missing_action():
    output = """Done: cleaned up the database."""
    result = validate_output("operations", output)
    # Missing action_taken
    assert "action_taken" in result["missing_fields"]


def test_security_output_valid():
    output = """Verdict: PASS
    Findings:
    - No hardcoded secrets found
    - Dependencies are up to date"""
    result = validate_output("security", output)
    assert result["valid"] is True


def test_score_range():
    output = "Done: finished the task. Files changed: src/foo.py"
    result = validate_output("engineering", output)
    assert 0.0 <= result["score"] <= 1.0


def test_protocol_minimal_schema():
    schema = load_output_schema("protocol")
    assert schema["required_fields"] == ["done_summary"]
    assert schema["optional_fields"] == []


def test_personnel_minimal_schema():
    schema = load_output_schema("personnel")
    assert schema["required_fields"] == ["done_summary"]
