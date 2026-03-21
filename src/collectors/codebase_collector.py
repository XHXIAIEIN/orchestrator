"""
Codebase Collector — 采集 Orchestrator 自己的代码变更。
自我感知的基础：知道自己什么时候被改了、改了什么。
"""
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from src.storage.events_db import EventsDB
from src.collectors.base import ICollector, CollectorMeta

log = logging.getLogger(__name__)


class CodebaseCollector(ICollector):
    @classmethod
    def metadata(cls) -> CollectorMeta:
        return CollectorMeta(
            name="codebase", display_name="Codebase", category="core",
            env_vars=["ORCHESTRATOR_ROOT"], requires=["git"],
            event_sources=["codebase"], default_enabled=True,
        )

    def __init__(self, db: EventsDB = None, db_path: str = "events.db"):
        self.db = db or EventsDB(db_path)
        super().__init__(self.db)
        self.repo_path = os.environ.get(
            "ORCHESTRATOR_ROOT",
            str(Path(__file__).parent.parent.parent)
        )

    def collect(self) -> int:
        """采集最近 7 天的 Orchestrator 自身 commit。"""
        try:
            result = subprocess.run(
                ["git", "log", "--since=7 days ago", "--format=%H|%an|%s|%aI", "--no-merges"],
                capture_output=True, text=True, timeout=30,
                cwd=self.repo_path,
            )
            if result.returncode != 0:
                log.warning(f"CodebaseCollector: git log failed: {result.stderr[:100]}")
                return 0
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            log.warning(f"CodebaseCollector: {e}")
            return 0

        count = 0
        for line in result.stdout.strip().splitlines():
            parts = line.split("|", 3)
            if len(parts) < 4:
                continue
            sha, author, subject, date = parts

            # 获取变更统计
            stat = ""
            try:
                stat_result = subprocess.run(
                    ["git", "diff", "--shortstat", f"{sha}^..{sha}"],
                    capture_output=True, text=True, timeout=10,
                    cwd=self.repo_path,
                )
                stat = stat_result.stdout.strip()
            except Exception:
                pass

            dedup_key = f"orchestrator:commit:{sha[:12]}"
            inserted = self.db.insert_event(
                source="orchestrator_codebase",
                category="self_commit",
                title=subject,
                duration_minutes=0,
                score=0.5,
                tags=["orchestrator", "self"],
                metadata={"sha": sha[:12], "author": author, "stat": stat},
                dedup_key=dedup_key,
                occurred_at=date,
            )
            if inserted:
                count += 1

        if count:
            log.info(f"CodebaseCollector: {count} new self-commits")
        return count
