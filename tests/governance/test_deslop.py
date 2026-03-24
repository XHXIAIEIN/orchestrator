"""Tests for deslop (AI smell detection)."""
from src.governance.learning.deslop import scan_for_slop, format_slop_report


def test_detects_over_comment():
    code = "# This function initializes the database connection\ndef init_db(): pass"
    findings = scan_for_slop("test.py", code)
    assert any(f.category == "over_comment" for f in findings)


def test_detects_boilerplate_docstring():
    code = '"""This function does something."""\ndef foo(): pass'
    findings = scan_for_slop("test.py", code)
    assert any(f.category == "boilerplate_docstring" for f in findings)


def test_detects_robot_naming():
    code = "data_dict = {}\ntemp_var = 0"
    findings = scan_for_slop("test.py", code)
    assert any(f.category == "robot_naming" for f in findings)


def test_clean_code_no_findings():
    code = "def calculate_price(items: list[Item]) -> float:\n    return sum(i.price for i in items)"
    findings = scan_for_slop("test.py", code)
    assert len(findings) == 0


def test_format_empty_report():
    assert format_slop_report([]) == ""


def test_format_nonempty_report():
    findings = scan_for_slop("test.py", "# This function returns the value\ndef get(): pass")
    report = format_slop_report(findings)
    assert "AI" in report or "臭味" in report
