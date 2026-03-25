"""
Output Validator — 校验部门输出是否符合 output_schema。
Constraint Paradox: 约束越紧，输出质量越高。
"""
import logging
import re
import yaml
from pathlib import Path

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def load_output_schema(department: str) -> dict:
    """从 blueprint.yaml 加载部门的 output_schema。"""
    bp_path = _REPO_ROOT / "departments" / department / "blueprint.yaml"
    if not bp_path.exists():
        return {}
    with open(bp_path) as f:
        bp = yaml.safe_load(f)
    return bp.get("output_schema", {})


def validate_output(department: str, output: str) -> dict:
    """
    校验输出是否满足 output_schema。
    返回: {"valid": bool, "missing_fields": [...], "found_fields": [...], "score": float}
    """
    schema = load_output_schema(department)
    if not schema or not schema.get("required_fields"):
        return {"valid": True, "missing_fields": [], "found_fields": [], "score": 1.0}

    required = schema.get("required_fields", [])
    optional = schema.get("optional_fields", [])

    output_lower = output.lower() if output else ""

    found = []
    missing = []

    for field in required:
        patterns = _field_patterns(field)
        if any(p in output_lower for p in patterns):
            found.append(field)
        else:
            missing.append(field)

    # Check optional fields too (for scoring)
    optional_found = []
    for field in optional:
        patterns = _field_patterns(field)
        if any(p in output_lower for p in patterns):
            optional_found.append(field)

    total_possible = len(required) + len(optional)
    total_found = len(found) + len(optional_found)
    score = round(total_found / max(1, total_possible), 2)

    return {
        "valid": len(missing) == 0,
        "missing_fields": missing,
        "found_fields": found + optional_found,
        "score": score,
    }


def _field_patterns(field: str) -> list:
    """Generate search patterns for a field name."""
    # done_summary → ["done_summary", "done summary", "done:", "summary:"]
    patterns = [field.lower()]
    parts = field.lower().replace("_", " ").split()
    patterns.append(" ".join(parts))
    for part in parts:
        if len(part) > 3:  # skip short words
            patterns.append(f"{part}:")
            patterns.append(f"**{part}**")
    # Common output markers
    if field == "done_summary":
        patterns.extend(["done:", "completed:", "summary:", "accomplished:"])
    elif field == "files_changed":
        patterns.extend(["files changed:", "modified:", "changed files:"])
    elif field == "verdict":
        patterns.extend(["verdict:", "pass", "fail", "needs_work", "needs_review"])
    elif field == "findings":
        patterns.extend(["findings:", "issues:", "found:", "- "])
    elif field == "action_taken":
        patterns.extend(["action:", "performed:", "executed:"])
    elif field == "commit_hash":
        patterns.extend(["commit:", "committed:"])
    return patterns
