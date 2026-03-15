"""一次性脚本：根据 session_id 回填 attention_debts 的 project 字段。"""
import json
import os
import sqlite3
from pathlib import Path

CLAUDE_HOME = os.environ.get("CLAUDE_HOME", str(Path.home() / ".claude"))
DB_PATH = os.path.join(
    os.environ.get("ORCHESTRATOR_ROOT", "."), "events.db"
)


def _claude_dir_to_project(dirname: str) -> str:
    lower = dirname.lower()
    anchor = lower.find("github-")
    if anchor >= 0:
        return dirname[anchor + 7:]
    if "--" in dirname:
        after_drive = dirname.split("--", 1)[1]
        for marker in ("Desktop-", "Documents-"):
            idx = after_drive.find(marker)
            if idx >= 0:
                return after_drive[idx + len(marker):]
        return after_drive
    return dirname


def build_session_project_map() -> dict[str, str]:
    """扫描 Claude projects 目录，建立 session_id/slug → project_name 映射。"""
    projects_dir = Path(CLAUDE_HOME) / "projects"
    if not projects_dir.exists():
        return {}

    mapping = {}
    for proj in projects_dir.iterdir():
        if not proj.is_dir():
            continue
        project_name = _claude_dir_to_project(proj.name)
        for sf in proj.glob("*.jsonl"):
            mapping[sf.stem] = project_name
            # 也提取 slug
            try:
                with open(sf, encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        obj = json.loads(line)
                        slug = obj.get("slug")
                        if slug:
                            mapping[slug] = project_name
                            break
            except Exception:
                pass
    return mapping


def backfill():
    mapping = build_session_project_map()
    print(f"Built mapping: {len(mapping)} session → project entries")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute(
        "SELECT id, session_id FROM attention_debts WHERE project = '' OR project IS NULL"
    )
    rows = cursor.fetchall()
    print(f"Debts to backfill: {len(rows)}")

    updated = 0
    for debt_id, session_id in rows:
        project = mapping.get(session_id, "")
        if project:
            conn.execute(
                "UPDATE attention_debts SET project = ? WHERE id = ?",
                (project, debt_id),
            )
            updated += 1

    conn.commit()
    conn.close()
    print(f"Updated: {updated}/{len(rows)} debts")


if __name__ == "__main__":
    backfill()
