import hashlib
import json
import re
from pathlib import Path
from src.storage.events_db import EventsDB

KEYWORD_PATTERNS = [
    r'\b(python|javascript|typescript|rust|go|java|bash|shell)\b',
    r'\b(agent|orchestrator|llm|ai|claude|gpt|prompt)\b',
    r'\b(bug|fix|error|debug|test|refactor)\b',
    r'\b(设计|架构|系统|功能|实现|优化|构建)\b',
    r'\b(数据|分析|模型|训练|推理|向量)\b',
]


def extract_tags(text: str) -> list:
    found = set()
    for pattern in KEYWORD_PATTERNS:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            found.add(m.group(0).lower())
    return list(found)[:10]


class ClaudeCollector:
    def __init__(self, db: EventsDB, claude_home: str = None):
        self.db = db
        self.claude_home = Path(claude_home) if claude_home else Path.home() / ".claude"

    def collect(self) -> int:
        projects_dir = self.claude_home / "projects"
        if not projects_dir.exists():
            return 0
        new_count = 0
        for project_dir in projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            for session_file in project_dir.glob("*.jsonl"):
                new_count += self._process_session(session_file, project_dir.name)
        return new_count

    def _process_session(self, session_file: Path, project_name: str) -> int:
        try:
            mtime = session_file.stat().st_mtime
        except OSError:
            return 0

        dedup_hash = hashlib.md5(f"claude:{mtime}:{session_file.name}".encode()).hexdigest()

        messages = []
        try:
            with open(session_file, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        messages.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            return 0

        if not messages:
            return 0

        all_text = " ".join(
            m.get("content", "") if isinstance(m.get("content"), str)
            else str(m.get("content", ""))
            for m in messages
        )
        tags = extract_tags(all_text)
        approx_tokens = len(all_text) // 4
        score = min(1.0, approx_tokens / 2000)
        duration = len(messages) * 1.5

        inserted = self.db.insert_event(
            source="claude",
            category="conversation",
            title=f"[{project_name}] {session_file.stem[:40]}",
            duration_minutes=duration,
            score=score,
            tags=tags,
            metadata={"project": project_name, "messages": len(messages), "approx_tokens": approx_tokens},
            dedup_key=dedup_hash,
        )
        return 1 if inserted else 0
