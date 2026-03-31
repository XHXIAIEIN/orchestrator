"""Tests for preflight check types in blueprint.py.

Covers the env_var and command check types salvaged from skill_template.py,
plus existing check types for completeness.
"""
import os
from dataclasses import dataclass

from src.governance.policy.blueprint import (
    PreflightCheck, PreflightResult, _run_single_check, run_preflight,
    preflight_passed, Blueprint,
)


def _make_blueprint(department: str = "engineering", preflight: list = None) -> Blueprint:
    """Helper to create a minimal blueprint for testing."""
    return Blueprint(
        department=department,
        name_zh="test",
        model="claude-sonnet-4-6",
        preflight=preflight or [],
    )


def _run(check_type: str, target: str = "", required: bool = True) -> PreflightResult:
    """Shorthand: run a single preflight check."""
    check = PreflightCheck(name=f"test_{check_type}", check=check_type,
                           target=target, required=required)
    bp = _make_blueprint()
    return _run_single_check(check, {}, ".", bp)


# ── env_var (salvaged from skill_template.py) ──

def test_env_var_set():
    os.environ["_TEST_PREFLIGHT_VAR"] = "hello"
    result = _run("env_var", target="_TEST_PREFLIGHT_VAR")
    assert result.passed is True
    del os.environ["_TEST_PREFLIGHT_VAR"]


def test_env_var_empty_string():
    os.environ["_TEST_PREFLIGHT_VAR"] = ""
    result = _run("env_var", target="_TEST_PREFLIGHT_VAR")
    assert result.passed is False
    del os.environ["_TEST_PREFLIGHT_VAR"]


def test_env_var_missing():
    result = _run("env_var", target="_DEFINITELY_NOT_SET_XYZ987")
    assert result.passed is False


def test_env_var_missing_optional():
    result = _run("env_var", target="_DEFINITELY_NOT_SET_XYZ987", required=False)
    # Optional check: passed=True when not required and check fails
    assert result.passed is True


# ── command (salvaged from skill_template.py) ──

def test_command_success():
    # python -c "pass" should always succeed on any platform
    result = _run("command", target='python -c "pass"')
    assert result.passed is True


def test_command_failure():
    result = _run("command", target='python -c "raise SystemExit(1)"')
    assert result.passed is False


def test_command_failure_optional():
    result = _run("command", target='python -c "raise SystemExit(1)"', required=False)
    assert result.passed is True


# ── cwd_exists ──

def test_cwd_exists():
    result = _run("cwd_exists")
    assert result.passed is True


# ── file_exists ──

def test_file_exists_found():
    # src/ directory always exists in repo root
    check = PreflightCheck(name="test_file", check="file_exists", target="src")
    bp = _make_blueprint()
    result = _run_single_check(check, {}, ".", bp)
    assert result.passed is True


def test_file_exists_not_found():
    check = PreflightCheck(name="test_file", check="file_exists",
                           target="nonexistent_xyz_dir")
    bp = _make_blueprint()
    result = _run_single_check(check, {}, ".", bp)
    assert result.passed is False


# ── Integration: run_preflight + preflight_passed ──

def test_run_preflight_all_pass():
    bp = _make_blueprint(preflight=[
        PreflightCheck(name="cwd", check="cwd_exists"),
    ])
    results = run_preflight(bp, {}, ".")
    passed, reason = preflight_passed(results)
    assert passed is True
    assert reason == ""


def test_run_preflight_required_failure():
    bp = _make_blueprint(preflight=[
        PreflightCheck(name="cwd", check="cwd_exists"),
        PreflightCheck(name="missing", check="file_exists",
                       target="nonexistent_xyz", required=True),
    ])
    results = run_preflight(bp, {}, ".")
    passed, reason = preflight_passed(results)
    assert passed is False
    assert "missing" in reason


def test_run_preflight_optional_failure_still_passes():
    bp = _make_blueprint(preflight=[
        PreflightCheck(name="cwd", check="cwd_exists"),
        PreflightCheck(name="optional", check="file_exists",
                       target="nonexistent_xyz", required=False),
    ])
    results = run_preflight(bp, {}, ".")
    passed, reason = preflight_passed(results)
    assert passed is True


# ── Unknown check type ──

def test_unknown_check_type_passes():
    result = _run("totally_made_up_check")
    assert result.passed is True  # unknown checks are skipped
