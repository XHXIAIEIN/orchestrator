import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from src.storage.events_db import EventsDB
from src.collectors.base import ICollector, CollectorMeta

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


class ClaudeCollector(ICollector):
    @classmethod
    def metadata(cls) -> CollectorMeta:
        return CollectorMeta(
            name="claude", display_name="Claude", category="core",
            env_vars=["CLAUDE_HOME"], requires=[],
            event_sources=["claude"], default_enabled=True,
        )

    def __init__(self, db: EventsDB, claude_home: str = None):
        super().__init__(db)
        self.db = db
        if claude_home:
            self.claude_home = Path(claude_home)
        else:
            env_home = os.environ.get("CLAUDE_HOME")
            self.claude_home = Path(env_home) if env_home else Path.home() / ".claude"

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
        dedup_key = f"claude:session:{session_file.stem}"

        # Stream file — never load entire file into memory (some files are 2GB+)
        slug = None
        first_user_text = ""
        occurred_at = None
        sample_text_parts = []  # only first 200 lines for tag extraction
        user_msg_count = 0
        lines_read = 0
        MAX_SAMPLE_LINES = 200

        try:
            with open(session_file, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if not slug and isinstance(obj.get("slug"), str):
                        slug = obj["slug"]
                    if not occurred_at and isinstance(obj.get("timestamp"), str):
                        occurred_at = obj["timestamp"]

                    if obj.get("type") == "user" and isinstance(obj.get("message"), dict):
                        user_msg_count += 1
                        text = _get_text(obj["message"].get("content", ""))
                        if text and not first_user_text:
                            first_user_text = text[:120]
                        if lines_read < MAX_SAMPLE_LINES:
                            sample_text_parts.append(text[:300])
                    elif obj.get("type") == "assistant" and lines_read < MAX_SAMPLE_LINES:
                        if isinstance(obj.get("message"), dict):
                            text = _get_text(obj["message"].get("content", ""))
                            sample_text_parts.append(text[:300])

                    lines_read += 1
                    # Once we have all metadata and enough sample text, stop reading
                    if lines_read >= MAX_SAMPLE_LINES and slug and first_user_text and occurred_at:
                        break
        except OSError:
            return 0

        if not occurred_at and not first_user_text:
            return 0

        sample_text = " ".join(sample_text_parts)
        tags = extract_tags(sample_text)
        # Estimate total tokens from file size rather than reading everything
        try:
            file_size = session_file.stat().st_size
            approx_tokens = file_size // 8  # rough: ~8 bytes per token in JSONL
        except OSError:
            approx_tokens = len(sample_text) // 4
        score = min(1.0, user_msg_count / 20)
        duration = user_msg_count * 2.0

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
                "messages": user_msg_count,
                "approx_tokens": approx_tokens,
                "slug": slug or "",
            },
            dedup_key=dedup_key,
            occurred_at=occurred_at,
        )
        return 1 if inserted else 0
