"""
Blueprint — NemoClaw-inspired declarative department configuration.

Each department has a blueprint.yaml that declares:
  - identity & model (machine-readable version of SKILL.md)
  - authority_level (READ/PROPOSE/MUTATE — hard ceiling, APPROVE reserved for human)
  - policy (permission boundaries — what this dept CAN and CANNOT do)
  - preflight (pre-execution verification checklist)
  - lifecycle hooks (resolve → verify → plan → apply → status)

SKILL.md remains the LLM prompt (agent reads it).
blueprint.yaml is the machine config (Governor reads it).
Two layers, two audiences, zero coupling.
"""
import logging
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any

import yaml

from src.core.llm_router import MODEL_SONNET

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent
while _REPO_ROOT != _REPO_ROOT.parent and not ((_REPO_ROOT / "departments").is_dir() and (_REPO_ROOT / "src").is_dir()):
    _REPO_ROOT = _REPO_ROOT.parent
_DEPT_ROOT = _REPO_ROOT / "departments"


# ── Authority Ceiling ────────────────────────────────────────────
# Four-level permission hierarchy. AI agents cap at MUTATE; APPROVE is human-only.

class AuthorityCeiling(IntEnum):
    READ = 1       # 只读：观察、审计、报告
    PROPOSE = 2    # 建议：可写临时/提案文件，不可修改源码
    MUTATE = 3     # 变更：可修改源码、配置、运行命令
    APPROVE = 4    # 批准：可 commit、push、合并 — 仅人类

    @classmethod
    def from_str(cls, s: str) -> "AuthorityCeiling":
        return cls[s.upper()] if s else cls.MUTATE


# Each ceiling level defines maximum allowed tools (hard cap).
# Blueprint allowed_tools can only be a SUBSET of these.
# Note: Bash at READ level is intentional — security/quality need Bash
# for read-only commands (grep, pytest, etc). The read_only flag in Policy
# separately constrains what Bash can do via prompt instructions.
CEILING_TOOL_CAPS: dict[AuthorityCeiling, set[str]] = {
    AuthorityCeiling.READ: {"Read", "Glob", "Grep", "Bash"},
    AuthorityCeiling.PROPOSE: {"Read", "Glob", "Grep", "Bash", "Write"},
    AuthorityCeiling.MUTATE: {"Read", "Glob", "Grep", "Bash", "Write", "Edit"},
    AuthorityCeiling.APPROVE: {"Read", "Glob", "Grep", "Bash", "Write", "Edit"},
}


@dataclass
class Policy:
    """Department permission boundary."""
    allowed_tools: list[str] = field(default_factory=list)
    denied_tools: list[str] = field(default_factory=list)
    writable_paths: list[str] = field(default_factory=lambda: ["**"])
    readable_paths: list[str] = field(default_factory=lambda: ["**"])
    denied_paths: list[str] = field(default_factory=list)
    can_commit: bool = False
    can_network: bool = False
    max_file_changes: int = 0  # 0 = unlimited
    read_only: bool = False


@dataclass
class PreflightCheck:
    """Single pre-execution verification step."""
    name: str
    check: str  # "cwd_exists" | "file_exists" | "disk_space" | "git_clean" | "env_var" | "command" | "custom"
    target: str = ""  # path, pattern, or custom expression
    required: bool = True
    message: str = ""


@dataclass
class Blueprint:
    """Complete department blueprint."""
    department: str
    name_zh: str
    model: str
    version: str = "1"
    description: str = ""

    # Authority ceiling — hard cap, AI max = MUTATE
    authority: AuthorityCeiling = AuthorityCeiling.MUTATE

    # Policy (must stay within authority ceiling)
    policy: Policy = field(default_factory=Policy)

    # Preflight checks
    preflight: list[PreflightCheck] = field(default_factory=list)

    # Lifecycle config
    max_turns: int = 25
    timeout_s: int = 300
    retry_on_failure: bool = False

    # Collaboration
    on_done: str = ""  # "quality_review" | "" | custom
    on_fail: str = ""  # "log_only" | "alert" | "rework"

    # Raw data for extension
    extra: dict = field(default_factory=dict)


def _parse_policy(raw: dict) -> Policy:
    """Parse policy section from blueprint YAML."""
    if not raw:
        return Policy()
    return Policy(
        allowed_tools=raw.get("allowed_tools", []),
        denied_tools=raw.get("denied_tools", []),
        writable_paths=raw.get("writable_paths", ["**"]),
        readable_paths=raw.get("readable_paths", ["**"]),
        denied_paths=raw.get("denied_paths", []),
        can_commit=raw.get("can_commit", False),
        can_network=raw.get("can_network", False),
        max_file_changes=raw.get("max_file_changes", 0),
        read_only=raw.get("read_only", False),
    )


def _parse_preflight(raw: list) -> list[PreflightCheck]:
    """Parse preflight checks from blueprint YAML."""
    if not raw:
        return []
    checks = []
    for item in raw:
        if isinstance(item, str):
            # Shorthand: "cwd_exists" -> PreflightCheck(name="cwd_exists", check="cwd_exists")
            checks.append(PreflightCheck(name=item, check=item))
        elif isinstance(item, dict):
            checks.append(PreflightCheck(
                name=item.get("name", item.get("check", "unknown")),
                check=item.get("check", "custom"),
                target=item.get("target", ""),
                required=item.get("required", True),
                message=item.get("message", ""),
            ))
    return checks


def load_blueprint(department: str) -> Blueprint | None:
    """Load a department's blueprint.yaml (or manifest.yaml fallback). Returns None if not found."""
    bp_path = _DEPT_ROOT / department / "blueprint.yaml"
    if not bp_path.exists():
        # Manifest v2: manifest.yaml is the single source of truth
        bp_path = _DEPT_ROOT / department / "manifest.yaml"
        if not bp_path.exists():
            return None

    try:
        raw = yaml.safe_load(bp_path.read_text(encoding="utf-8"))
    except Exception as e:
        log.error(f"blueprint: failed to parse {bp_path}: {e}")
        return None

    if not raw or not isinstance(raw, dict):
        return None

    authority = AuthorityCeiling.from_str(raw.get("authority", "MUTATE"))

    return Blueprint(
        department=department,
        name_zh=raw.get("name_zh", ""),
        model=raw.get("model", MODEL_SONNET),
        version=str(raw.get("version", "1")),
        description=raw.get("description", ""),
        authority=authority,
        policy=_parse_policy(raw.get("policy")),
        preflight=_parse_preflight(raw.get("preflight")),
        max_turns=raw.get("max_turns", 25),
        timeout_s=raw.get("timeout_s", 300),
        retry_on_failure=raw.get("retry_on_failure", False),
        on_done=raw.get("on_done", ""),
        on_fail=raw.get("on_fail", "log_only"),
        extra=raw.get("extra", {}),
    )


def load_all_blueprints() -> dict[str, Blueprint]:
    """Load all department blueprints. Skips departments without blueprint.yaml."""
    blueprints = {}
    if not _DEPT_ROOT.exists():
        return blueprints

    for dept_dir in sorted(_DEPT_ROOT.iterdir()):
        if not dept_dir.is_dir() or dept_dir.name.startswith((".", "_", "shared")):
            continue
        bp = load_blueprint(dept_dir.name)
        if bp:
            blueprints[dept_dir.name] = bp

    return blueprints


# ── Preflight verification ────────────────────────────────────────

@dataclass
class PreflightResult:
    """Result of a single preflight check."""
    check_name: str
    passed: bool
    message: str = ""


def run_preflight(blueprint: Blueprint, task: dict, task_cwd: str) -> list[PreflightResult]:
    """Run all preflight checks for a department blueprint.

    Returns a list of results. If any required check fails, the task should not proceed.
    """
    results = []

    for check in blueprint.preflight:
        result = _run_single_check(check, task, task_cwd, blueprint)
        results.append(result)

    return results


def preflight_passed(results: list[PreflightResult]) -> tuple[bool, str]:
    """Check if all required preflight checks passed.

    Returns (passed, failure_reason).
    """
    failures = [r for r in results if not r.passed]
    if not failures:
        return True, ""

    reasons = "; ".join(f"{r.check_name}: {r.message}" for r in failures)
    return False, reasons


def _run_single_check(check: PreflightCheck, task: dict, task_cwd: str,
                      blueprint: Blueprint) -> PreflightResult:
    """Execute a single preflight check."""
    try:
        if check.check == "cwd_exists":
            cwd_path = Path(task_cwd)
            if cwd_path.exists() and cwd_path.is_dir():
                return PreflightResult(check.name, True)
            return PreflightResult(check.name, not check.required,
                                   f"Working directory does not exist: {task_cwd}")

        elif check.check == "file_exists":
            target = Path(task_cwd) / check.target if check.target else None
            if target and target.exists():
                return PreflightResult(check.name, True)
            return PreflightResult(check.name, not check.required,
                                   f"Required file not found: {check.target}")

        elif check.check == "skill_exists":
            skill_path = _DEPT_ROOT / blueprint.department / "SKILL.md"
            if skill_path.exists():
                return PreflightResult(check.name, True)
            return PreflightResult(check.name, not check.required,
                                   f"SKILL.md not found for {blueprint.department}")

        elif check.check == "disk_space":
            import shutil
            total, used, free = shutil.disk_usage(task_cwd)
            free_mb = free // (1024 * 1024)
            min_mb = int(check.target) if check.target else 100
            if free_mb >= min_mb:
                return PreflightResult(check.name, True, f"{free_mb}MB free")
            return PreflightResult(check.name, not check.required,
                                   f"Low disk space: {free_mb}MB < {min_mb}MB required")

        elif check.check == "git_clean":
            import subprocess
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=task_cwd, capture_output=True, text=True, timeout=10,
            )
            if not result.stdout.strip():
                return PreflightResult(check.name, True, "Working tree clean")
            return PreflightResult(check.name, not check.required,
                                   f"Uncommitted changes in {task_cwd}")

        elif check.check == "env_var":
            # Salvaged from skill_template.py (Hermes) — check env var is set
            import os
            var_name = check.target or ""
            value = os.environ.get(var_name)
            if value is not None and value != "":
                return PreflightResult(check.name, True, f"env {var_name} is set")
            return PreflightResult(check.name, not check.required,
                                   f"Environment variable not set: {var_name}")

        elif check.check == "command":
            # Salvaged from skill_template.py (Hermes) — run arbitrary command
            import subprocess
            cmd = check.target or ""
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                cwd=task_cwd, timeout=10, stdin=subprocess.DEVNULL,
            )
            if result.returncode == 0:
                return PreflightResult(check.name, True, f"command '{cmd}' passed")
            return PreflightResult(check.name, not check.required,
                                   f"command '{cmd}' failed (exit {result.returncode})")

        elif check.check == "policy_tools_match":
            # Verify blueprint tools match DEPARTMENTS dict
            return PreflightResult(check.name, True, "Skipped (runtime check)")

        else:
            return PreflightResult(check.name, True, f"Unknown check '{check.check}', skipped")

    except Exception as e:
        return PreflightResult(check.name, not check.required, f"Check error: {e}")


# ── Policy enforcement helpers ────────────────────────────────────

def enforce_policy(blueprint: Blueprint, tool_name: str, file_path: str = "",
                   depth: int = 0) -> tuple[bool, str]:
    """Check if a tool/file access is allowed by the department's policy.

    Returns (allowed, reason).
    This is advisory — the actual enforcement happens at Agent SDK level via allowed_tools.
    Blueprint policy adds a second layer of intent documentation.

    Uses ToolPolicy engine: deny-wins semantics, glob matching, depth limits.
    """
    from .tool_policy import ToolPolicy

    policy = blueprint.policy
    tp = ToolPolicy.from_policy(policy, max_depth=blueprint.extra.get("max_agent_depth", 3))

    # Tool check via deny-wins engine
    allowed, reason = tp.is_allowed(tool_name, depth=depth)
    if not allowed:
        return False, f"{blueprint.department}: {reason}"

    # Read-only enforcement (separate from tool policy — semantic layer)
    if policy.read_only and tool_name in ("Edit", "Write", "Bash"):
        return False, f"{blueprint.department} is read-only, '{tool_name}' denied"

    # Path check (simplified — real enforcement uses Agent SDK)
    if file_path and policy.denied_paths:
        from fnmatch import fnmatch
        for pattern in policy.denied_paths:
            if fnmatch(file_path, pattern):
                return False, f"Path '{file_path}' denied by {blueprint.department} policy"

    return True, ""


def get_allowed_tools(blueprint: Blueprint) -> list[str]:
    """Get the effective tool list, capped by authority ceiling.

    Even if blueprint.yaml declares extra tools, ceiling is the hard cap.
    """
    cap = CEILING_TOOL_CAPS.get(blueprint.authority, set())
    requested = set(blueprint.policy.allowed_tools) if blueprint.policy.allowed_tools else cap.copy()

    # Intersection: only tools within BOTH the cap and the request survive
    effective = requested & cap

    capped = requested - cap
    if capped:
        log.warning(
            f"blueprint({blueprint.department}): tools {capped} exceed "
            f"authority ceiling {blueprint.authority.name}, stripped"
        )

    return sorted(effective)
