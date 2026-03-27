"""Policy Suggester — generate blueprint change suggestions from denial patterns."""
import logging
from datetime import datetime, timezone
from pathlib import Path

from src.governance.policy.observer import aggregate_denials, _suggestions_path

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent
while _REPO_ROOT != _REPO_ROOT.parent and not ((_REPO_ROOT / "departments").is_dir() and (_REPO_ROOT / "src").is_dir()):
    _REPO_ROOT = _REPO_ROOT.parent
_DEPT_ROOT = _REPO_ROOT / "departments"


# ── Suggest: generate blueprint changes ──────────────────────────

def generate_suggestions(department: str) -> str:
    """Generate human-readable policy suggestions based on accumulated denials.

    Returns markdown text. Also writes to departments/{dept}/policy-suggestions.md.
    """
    from src.governance.policy.blueprint import load_blueprint

    agg = aggregate_denials(department)
    if agg["total"] == 0:
        return ""

    bp = load_blueprint(department)
    if not bp:
        return ""

    lines = [
        f"# Policy Suggestions for {bp.name_zh} ({department})",
        f"",
        f"_Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} "
        f"from {agg['total']} denial events_",
        "",
    ]

    suggestions = []

    # Tool suggestions
    if agg["top_tools_blocked"]:
        lines.append("## Tool Access")
        for tool, count in agg["top_tools_blocked"]:
            lines.append(f"- **{tool}** blocked {count}x → Consider adding to `policy.allowed_tools`")
            suggestions.append({
                "field": "policy.allowed_tools",
                "action": "add",
                "value": tool,
                "evidence": f"Blocked {count} times across recent tasks",
            })
        lines.append("")

    # Timeout suggestions
    if agg["timeout_count"] >= 2:
        lines.append("## Timeout")
        lines.append(f"- {agg['timeout_count']} timeouts detected (current: {bp.timeout_s}s)")
        lines.append(f"- → Consider increasing `timeout_s` to {bp.timeout_s + 120}")
        suggestions.append({
            "field": "timeout_s",
            "action": "increase",
            "value": bp.timeout_s + 120,
            "evidence": f"{agg['timeout_count']} timeout events",
        })
        lines.append("")

    # Max turns suggestions
    if agg["max_turns_count"] >= 2:
        lines.append("## Max Turns")
        lines.append(f"- {agg['max_turns_count']} tasks hit turn limit (current: {bp.max_turns})")
        lines.append(f"- → Consider increasing `max_turns` to {bp.max_turns + 10}")
        suggestions.append({
            "field": "max_turns",
            "action": "increase",
            "value": bp.max_turns + 10,
            "evidence": f"{agg['max_turns_count']} max_turns events",
        })
        lines.append("")

    # Write-in-readonly suggestions
    write_count = agg["by_type"].get("write_in_readonly", 0)
    if write_count >= 2:
        lines.append("## Read-Only Friction")
        lines.append(f"- {write_count} write attempts in read-only department")
        lines.append(f"- → Review if `read_only: true` is still appropriate, "
                     f"or ensure tasks requiring writes go to engineering")
        lines.append("")

    # Summary
    if suggestions:
        lines.append("## Blueprint Diff (suggested)")
        lines.append("```yaml")
        for s in suggestions:
            lines.append(f"# {s['evidence']}")
            if s["action"] == "add":
                lines.append(f"{s['field']}: [..., {s['value']}]")
            else:
                lines.append(f"{s['field']}: {s['value']}")
        lines.append("```")
        lines.append("")
        lines.append("_Apply these changes to `blueprint.yaml` after review._")

    md = "\n".join(lines)

    # Write to file
    try:
        _suggestions_path(department).write_text(md, encoding="utf-8")
    except Exception as e:
        log.warning(f"PolicyAdvisor: failed to write suggestions for {department}: {e}")

    return md


def generate_all_suggestions() -> dict[str, str]:
    """Generate suggestions for all departments. Returns {dept: markdown}."""
    results = {}
    if not _DEPT_ROOT.exists():
        return results

    for dept_dir in sorted(_DEPT_ROOT.iterdir()):
        if not dept_dir.is_dir() or dept_dir.name.startswith((".", "_", "shared")):
            continue
        denials_file = dept_dir / "policy-denials.jsonl"
        if denials_file.exists():
            md = generate_suggestions(dept_dir.name)
            if md:
                results[dept_dir.name] = md

    return results
