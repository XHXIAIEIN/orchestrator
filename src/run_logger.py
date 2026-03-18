"""
部门执行记忆：每次任务执行后记录到 departments/{dept}/run-log.jsonl
"""
import json
from datetime import datetime, timezone
from pathlib import Path


def append_run_log(department: str, task_id: int, mode: str, summary: str,
                   files_changed: list = None, commit: str = "",
                   status: str = "done", duration_s: int = 0,
                   notes: str = ""):
    log_path = Path("departments") / department / "run-log.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "task_id": task_id,
        "mode": mode,
        "summary": summary,
        "files_changed": files_changed or [],
        "commit": commit,
        "status": status,
        "duration_s": duration_s,
        "notes": notes,
    }

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load_recent_runs(department: str, n: int = 5) -> list[dict]:
    log_path = Path("departments") / department / "run-log.jsonl"
    if not log_path.exists():
        return []

    lines = log_path.read_text(encoding="utf-8").strip().split("\n")
    recent = lines[-n:] if len(lines) > n else lines

    runs = []
    for line in recent:
        if line.strip():
            try:
                runs.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return runs


def format_runs_for_context(runs: list[dict]) -> str:
    if not runs:
        return ""

    lines = ["## 最近执行记录"]
    for r in runs:
        lines.append(f"- [{r.get('ts','')}] {r.get('summary','')} → {r.get('status','')}"
                     + (f" (note: {r.get('notes','')})" if r.get('notes') else ""))
    return "\n".join(lines)
