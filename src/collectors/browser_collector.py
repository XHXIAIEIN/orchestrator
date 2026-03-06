import hashlib
import shutil
import sqlite3
import tempfile
from pathlib import Path
from src.storage.events_db import EventsDB

CHROME_EPOCH_OFFSET = 11644473600 * 1_000_000

URL_CATEGORIES = {
    "dev": ["github.com", "gitlab.com", "stackoverflow.com", "docs.", "developer.", "localhost", "127.0.0.1"],
    "reading": ["medium.com", "news.ycombinator.com", "reddit.com", "substack.com", "wikipedia.org", "arxiv.org"],
    "media": ["youtube.com", "bilibili.com", "twitch.tv", "netflix.com", "spotify.com"],
    "ai": ["claude.ai", "chatgpt.com", "openai.com", "anthropic.com", "huggingface.co"],
    "social": ["twitter.com", "x.com", "weibo.com", "linkedin.com", "discord.com"],
}


def categorize_url(url: str) -> str:
    url_lower = url.lower()
    for category, patterns in URL_CATEGORIES.items():
        if any(p in url_lower for p in patterns):
            return category
    return "other"


class BrowserCollector:
    def __init__(self, db: EventsDB, history_paths: dict = None):
        self.db = db
        self.history_paths = history_paths if history_paths is not None else self._auto_detect()

    def _auto_detect(self) -> dict:
        home = Path.home()
        candidates = {
            "chrome": home / "AppData/Local/Google/Chrome/User Data/Default/History",
            "edge": home / "AppData/Local/Microsoft/Edge/User Data/Default/History",
        }
        return {k: str(v) for k, v in candidates.items() if v.exists()}

    def collect(self) -> int:
        total = 0
        for browser, path in self.history_paths.items():
            total += self._collect_from(browser, path)
        return total

    def _collect_from(self, browser: str, history_path: str) -> int:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            shutil.copy2(history_path, tmp_path)
        except (OSError, PermissionError):
            return 0

        new_count = 0
        try:
            conn = sqlite3.connect(tmp_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT u.url, u.title, v.visit_time, v.visit_duration
                FROM visits v JOIN urls u ON v.url = u.id
                WHERE v.visit_time > 0
                ORDER BY v.visit_time DESC LIMIT 500
            """).fetchall()
            conn.close()
        except Exception:
            return 0
        finally:
            try:
                Path(tmp_path).unlink()
            except OSError:
                pass

        for row in rows:
            url = row["url"] or ""
            title = row["title"] or url[:80]
            visit_time = row["visit_time"] or 0
            duration_us = row["visit_duration"] or 0
            duration_min = duration_us / 60_000_000

            dedup_key = hashlib.md5(f"{browser}:{url}:{visit_time}".encode()).hexdigest()
            category = categorize_url(url)
            score = min(1.0, duration_min / 10) if duration_min > 0 else 0.1

            inserted = self.db.insert_event(
                source=f"browser_{browser}",
                category=category,
                title=title[:200],
                duration_minutes=duration_min,
                score=score,
                tags=[category, browser],
                metadata={"url": url[:500]},
                dedup_key=dedup_key,
            )
            if inserted:
                new_count += 1
        return new_count
