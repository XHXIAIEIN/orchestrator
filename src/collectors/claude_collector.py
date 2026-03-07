import hashlib
import json
import re
from datetime import datetime, timezone
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


def _get_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text":
                parts.append(c.get("text", ""))
        return " ".join(parts)
    return ""


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
        # Dedup by session UUID — one event per conversation
        dedup_key = f"claude:session:{session_file.stem}"

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

        # Extract slug and first user message for readable title
        slug = None
        first_user_text = ""
        occurred_at = None
        all_text_parts = []

        for m in messages:
            if not slug and isinstance(m.get("slug"), str):
                slug = m["slug"]
            if not occurred_at and isinstance(m.get("timestamp"), str):
                occurred_at = m["timestamp"]

            if m.get("type") == "user" and isinstance(m.get("message"), dict):
                text = _get_text(m["message"].get("content", ""))
                if text and not first_user_text:
                    first_user_text = text[:120]
                all_text_parts.append(text)
            elif m.get("type") == "assistant" and isinstance(m.get("message"), dict):
                text = _get_text(m["message"].get("content", ""))
                all_text_parts.append(text[:500])

        all_text = " ".join(all_text_parts)
        tags = extract_tags(all_text)
        approx_tokens = len(all_text) // 4
        score = min(1.0, approx_tokens / 2000)
        user_msgs = [m for m in messages if m.get("type") == "user"]
        duration = len(user_msgs) * 2.0  # ~2 min per exchange

        # Title: prefer slug, fallback to first user message
        if slug:
            title = f"[{project_name[:30]}] {slug}"
        elif first_user_text:
            title = f"[{project_name[:30]}] {first_user_text[:60]}"
        else:
            title = f"[{project_name[:30]}] {session_file.stem[:20]}"

        inserted = self.db.insert_event(
            source="claude",
            category="conversation",
            title=title[:200],
            duration_minutes=duration,
            score=score,
            tags=tags,
            metadata={
                "project": project_name,
                "session_id": session_file.stem,
                "messages": len(user_msgs),
                "approx_tokens": approx_tokens,
                "slug": slug or "",
            },
            dedup_key=dedup_key,
            occurred_at=occurred_at,
        )
        return 1 if inserted else 0
