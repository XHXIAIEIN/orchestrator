import hashlib
import os
import re
import subprocess
from pathlib import Path
from src.storage.events_db import EventsDB
from src.collectors.base import ICollector, CollectorMeta


def find_git_repos(search_paths: list) -> list:
    repos = []
    for base in search_paths:
        base = Path(base)
        if not base.exists():
            continue
        if (base / ".git").exists():
            repos.append(base)
            continue
        try:
            for item in base.iterdir():
                if item.is_dir() and (item / ".git").exists():
                    repos.append(item)
        except PermissionError:
            continue
    return repos


class GitCollector(ICollector):
    @classmethod
    def metadata(cls) -> CollectorMeta:
        return CollectorMeta(
            name="git", display_name="Git", category="core",
            env_vars=["GIT_REPOS_ROOT", "GIT_PATHS"], requires=["git"],
            event_sources=["git"], default_enabled=True,
        )

    def __init__(self, db: EventsDB, search_paths: list = None, days_back: int = 30):
        super().__init__(db)
        self.db = db
        self.days_back = days_back
        if search_paths is None:
            env_root = os.environ.get("GIT_REPOS_ROOT")
            if env_root:
                search_paths = [env_root]
            else:
                home = Path.home()
                search_paths = [
                    str(home / "Desktop"),
                    str(home / "Documents"),
                    str(home / "Documents" / "GitHub"),
                    str(home / "Projects"),
                ]
        self.search_paths = search_paths

    def collect(self) -> int:
        repos = find_git_repos(self.search_paths)
        total = 0
        for repo in repos:
            total += self._collect_repo(repo)
        return total

    def _collect_repo(self, repo_path: Path) -> int:
        try:
            result = subprocess.run(
                ["git", "log", f"--since={self.days_back} days ago",
                 "--format=%H|%s|%ai", "--shortstat"],
                cwd=repo_path, capture_output=True, text=True, timeout=10
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return 0

        new_count = 0
        lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
        i = 0
        while i < len(lines):
            line = lines[i]
            if "|" not in line:
                i += 1
                continue
            parts = line.split("|", 2)
            if len(parts) < 2:
                i += 1
                continue
            commit_hash, message = parts[0].strip(), parts[1].strip()

            insertions = 0
            if i + 1 < len(lines) and "changed" in lines[i + 1]:
                m = re.search(r"(\d+) insertion", lines[i + 1])
                if m:
                    insertions = int(m.group(1))
                i += 1

            dedup_key = f"git:{commit_hash}"
            score = min(1.0, insertions / 200) if insertions > 0 else 0.3

            inserted = self.db.insert_event(
                source="git",
                category="coding",
                title=f"[{repo_path.name}] {message[:100]}",
                duration_minutes=0,
                score=score,
                tags=["git", repo_path.name],
                metadata={"repo": str(repo_path), "hash": commit_hash[:8], "insertions": insertions},
                dedup_key=dedup_key,
            )
            if inserted:
                new_count += 1
            i += 1
        return new_count
