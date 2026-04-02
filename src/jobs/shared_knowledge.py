# src/jobs/shared_knowledge.py
"""Shared Knowledge Auto-Maintenance — keep departments/shared/ fresh.

evolution-v2 §5.3: auto-update codebase-map, known-issues, recent-changes.
Runs as a periodic job alongside skill_evolution and performance_report.

Updates:
  - recent-changes.md: from git log + run-log (last 7 days)
  - known-issues.md: from quality department FAIL verdicts + learnings
  - codebase-map.md: from file index (CAFI) or directory scan
"""
import json
import logging
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent
while _REPO_ROOT != _REPO_ROOT.parent and not ((_REPO_ROOT / "departments").is_dir() and (_REPO_ROOT / "src").is_dir()):
    _REPO_ROOT = _REPO_ROOT.parent

SHARED_DIR = _REPO_ROOT / "departments" / "shared"


def update_recent_changes(db=None, days: int = 7) -> str:
    """Generate recent-changes.md from git log + run-log data."""
    lines = [
        "# Recent Changes",
        f"_Auto-generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_",
        f"_Covers last {days} days_",
        "",
    ]

    # Git log (last N days)
    try:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        result = subprocess.run(
            ["git", "log", f"--since={since}", "--oneline", "--no-merges", "-30"],
            cwd=str(_REPO_ROOT), capture_output=True, text=True, timeout=10,
        )
        if result.stdout.strip():
            lines.append("## Git Commits")
            lines.append("")
            for commit_line in result.stdout.strip().splitlines()[:20]:
                lines.append(f"- `{commit_line}`")
            lines.append("")
    except Exception as e:
        log.debug(f"shared_knowledge: git log failed: {e}")

    # Run-log summaries (from all departments)
    dept_runs = _collect_recent_runs(days)
    if dept_runs:
        lines.append("## Department Activity")
        lines.append("")
        for dept, runs in dept_runs.items():
            success = sum(1 for r in runs if r.get("status") == "done")
            lines.append(f"### {dept} ({len(runs)} runs, {success} success)")
            for r in runs[-5:]:  # last 5 per department
                status_icon = "✅" if r.get("status") == "done" else "❌"
                lines.append(f"- {status_icon} {r.get('summary', '?')[:80]}")
            lines.append("")

    # Files changed summary
    try:
        result = subprocess.run(
            ["git", "diff", "--stat", f"HEAD~20", "HEAD"],
            cwd=str(_REPO_ROOT), capture_output=True, text=True, timeout=10,
        )
        if result.stdout.strip():
            stat_lines = result.stdout.strip().splitlines()
            if stat_lines:
                lines.append("## Files Changed (last 20 commits)")
                lines.append("")
                lines.append(f"```")
                lines.append(stat_lines[-1])  # summary line
                lines.append(f"```")
                lines.append("")
    except Exception:
        pass

    content = "\n".join(lines)
    _write_shared("recent-changes.md", content)
    return content


def update_known_issues(db) -> str:
    """Generate known-issues.md from quality review failures + active learnings."""
    lines = [
        "# Known Issues",
        f"_Auto-generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_",
        "",
    ]

    # Active learnings with high recurrence (likely recurring issues)
    try:
        learnings = db.get_learnings(status="pending", limit=20)
        recurring = [l for l in learnings if l.get("recurrence", 0) >= 2]
        if recurring:
            lines.append("## Recurring Patterns")
            lines.append("")
            for l in recurring[:10]:
                lines.append(f"- **{l['pattern_key']}** (×{l['recurrence']}): {l['rule'][:100]}")
            lines.append("")
    except Exception as e:
        log.debug(f"shared_knowledge: learnings query failed: {e}")

    # Recent failed tasks
    try:
        recent_logs = db.get_logs(limit=50)
        failures = [l for l in recent_logs if l.get("level") == "ERROR"]
        if failures:
            lines.append("## Recent Errors")
            lines.append("")
            seen = set()
            for f in failures[:10]:
                msg = f.get("message", "")[:120]
                key = msg[:50]
                if key not in seen:
                    seen.add(key)
                    lines.append(f"- {msg}")
            lines.append("")
    except Exception as e:
        log.debug(f"shared_knowledge: logs query failed: {e}")

    content = "\n".join(lines)
    _write_shared("known-issues.md", content)
    return content


def update_codebase_map() -> str:
    """Generate codebase-map.md from directory structure."""
    lines = [
        "# Codebase Map",
        f"_Auto-generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_",
        "",
        "## Directory Structure",
        "",
    ]

    # Scan key directories
    key_dirs = ["src", "departments", "SOUL", "dashboard"]
    for dir_name in key_dirs:
        dir_path = _REPO_ROOT / dir_name
        if not dir_path.exists():
            continue

        lines.append(f"### {dir_name}/")
        _scan_dir(dir_path, lines, depth=0, max_depth=2)
        lines.append("")

    # Module summary
    lines.append("## Key Modules")
    lines.append("")
    module_descriptions = {
        "src/core/": "核心基础设施 (event_bus, llm_router, config)",
        "src/governance/": "治理管线 (executor, scrutiny, pipeline, safety, learning)",
        "src/gateway/": "前门路由 (intent, dispatcher, classifier)",
        "src/storage/": "数据存储 (events_db, qdrant_store)",
        "src/channels/": "通信通道 (telegram, wechat)",
        "src/collectors/": "数据采集器",
        "src/analysis/": "分析引擎 (daily_analyst, profile, performance)",
        "src/jobs/": "定时任务 (scheduler, periodic)",
        "departments/": "六部配置 (SKILL.md, manifest.yaml, guidelines/)",
        "SOUL/": "灵魂系统 (identity, voice, management, compiler)",
    }
    for path, desc in module_descriptions.items():
        if (_REPO_ROOT / path).exists():
            lines.append(f"- **{path}** — {desc}")

    content = "\n".join(lines)
    _write_shared("codebase-map.md", content)
    return content


def update_all(db) -> dict:
    """Run all shared knowledge updates. Returns {filename: char_count}."""
    results = {}
    try:
        content = update_recent_changes(db)
        results["recent-changes.md"] = len(content)
    except Exception as e:
        log.error(f"shared_knowledge: recent-changes failed: {e}")

    try:
        content = update_known_issues(db)
        results["known-issues.md"] = len(content)
    except Exception as e:
        log.error(f"shared_knowledge: known-issues failed: {e}")

    try:
        content = update_codebase_map()
        results["codebase-map.md"] = len(content)
    except Exception as e:
        log.error(f"shared_knowledge: codebase-map failed: {e}")

    if results:
        log.info(f"shared_knowledge: updated {len(results)} files — {results}")

    return results


# ── Helpers ──

def _collect_recent_runs(days: int) -> dict[str, list]:
    """Collect run-log entries from all departments for the last N days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    dept_runs = {}

    dept_dir = _REPO_ROOT / "departments"
    for d in sorted(dept_dir.iterdir()):
        if not d.is_dir() or d.name.startswith((".", "_", "shared")):
            continue
        run_log = d / "run-log.jsonl"
        if not run_log.exists():
            continue
        try:
            runs = []
            for line in run_log.read_text(encoding="utf-8").strip().split("\n"):
                if not line.strip():
                    continue
                r = json.loads(line)
                if r.get("ts", "") >= cutoff:
                    runs.append(r)
            if runs:
                dept_runs[d.name] = runs
        except Exception:
            continue

    return dept_runs


def _scan_dir(path: Path, lines: list, depth: int, max_depth: int):
    """Recursively scan directory for map output."""
    indent = "  " * (depth + 1)
    try:
        entries = sorted(path.iterdir())
    except PermissionError:
        return

    dirs = [e for e in entries if e.is_dir() and not e.name.startswith((".", "__", "node_modules"))]
    files = [e for e in entries if e.is_file() and e.suffix in (".py", ".md", ".yaml", ".yml", ".json")]

    for d in dirs[:15]:
        py_count = len(list(d.glob("*.py")))
        suffix = f" ({py_count} py)" if py_count else ""
        lines.append(f"{indent}- **{d.name}/**{suffix}")
        if depth < max_depth:
            _scan_dir(d, lines, depth + 1, max_depth)

    if files and depth >= max_depth:
        lines.append(f"{indent}  ({len(files)} files)")


def _write_shared(filename: str, content: str):
    """Write to departments/shared/ directory."""
    SHARED_DIR.mkdir(parents=True, exist_ok=True)
    path = SHARED_DIR / filename
    path.write_text(content, encoding="utf-8")
    log.info(f"shared_knowledge: wrote {path} ({len(content)} chars)")
