"""
Claude Memory Collector — 桥接 Claude Code 的文件记忆到 Orchestrator EventsDB。
扫描 .claude/projects/*/memory/*.md，解析 frontmatter，作为事件写入。
"""
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from src.collectors.base import ICollector, CollectorMeta
from src.storage.events_db import EventsDB

log = logging.getLogger(__name__)

# Claude Code memory root
_CLAUDE_HOME = Path(os.environ.get("CLAUDE_MEMORY_ROOT", str(Path.home() / ".claude")))
_MEMORY_GLOB = "projects/*/memory/*.md"
_INDEX_FILE = "MEMORY.md"


class ClaudeMemoryCollector(ICollector):
    """采集 Claude Code 的 memory 文件变化。"""

    @classmethod
    def metadata(cls) -> CollectorMeta:
        return CollectorMeta(
            name="claude_memory",
            display_name="Claude Code Memory",
            category="optional",
            env_vars=[],
            requires=[],
            event_sources=["claude_memory"],
            default_enabled=True,
        )

    def preflight(self) -> tuple[bool, str]:
        if not _CLAUDE_HOME.exists():
            return False, f"Claude home not found: {_CLAUDE_HOME}"
        memory_dirs = list(_CLAUDE_HOME.glob("projects/*/memory"))
        if not memory_dirs:
            return False, "No Claude Code memory directories found"
        return True, f"Found {len(memory_dirs)} project memory dirs"

    def collect(self) -> int:
        """扫描所有 memory 文件，对比上次采集，写入新增/变更的。"""
        count = 0
        memory_files = list(_CLAUDE_HOME.glob(_MEMORY_GLOB))

        for md_file in memory_files:
            if md_file.name == _INDEX_FILE:
                continue  # Skip index file

            try:
                content = md_file.read_text(encoding="utf-8")
                frontmatter = self._parse_frontmatter(content)
                if not frontmatter:
                    continue

                # Extract project name from path
                # .claude/projects/<project>/memory/<file>.md
                parts = md_file.parts
                project_idx = next(
                    (i + 1 for i, p in enumerate(parts) if p == "projects"),
                    -1,
                )
                project = parts[project_idx] if 0 < project_idx < len(parts) else "unknown"

                # Use file mtime as occurred_at
                mtime = datetime.fromtimestamp(md_file.stat().st_mtime, tz=timezone.utc)

                # Dedup key: file path hash
                dedup_key = f"claude_memory:{project}:{md_file.name}"

                # Body = content after frontmatter
                body = self._strip_frontmatter(content).strip()
                if len(body) > 500:
                    body = body[:500] + "..."

                memory_type = frontmatter.get("type", "unknown")

                inserted = self.db.insert_event(
                    source="claude_memory",
                    category=memory_type,
                    title=frontmatter.get("name", md_file.stem),
                    duration_minutes=0,
                    score=self._type_score(memory_type),
                    tags=["memory", memory_type, project],
                    metadata={
                        "file": str(md_file.name),
                        "project": project,
                        "description": frontmatter.get("description", ""),
                        "memory_type": memory_type,
                        "body_preview": body,
                        "full_path": str(md_file),
                    },
                    dedup_key=dedup_key,
                    occurred_at=mtime.isoformat(),
                )
                if inserted:
                    count += 1

            except Exception as e:
                self.log(f"Failed to process {md_file.name}: {e}", "WARNING")

        self.log(f"Collected {count} memory entries from {len(memory_files)} files")
        return count

    @staticmethod
    def _parse_frontmatter(content: str) -> dict | None:
        """Extract YAML frontmatter from markdown."""
        match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
        if not match:
            return None
        try:
            import yaml
            return yaml.safe_load(match.group(1))
        except Exception:
            return None

    @staticmethod
    def _strip_frontmatter(content: str) -> str:
        """Remove YAML frontmatter, return body."""
        return re.sub(r'^---\s*\n.*?\n---\s*\n?', '', content, count=1, flags=re.DOTALL)

    @staticmethod
    def _type_score(memory_type: str) -> float:
        """Memory type → relevance score."""
        return {
            "feedback": 0.9,   # 行为偏好最重要
            "user": 0.8,       # 用户信息
            "project": 0.7,    # 项目上下文
            "reference": 0.5,  # 参考资料
        }.get(memory_type, 0.3)
