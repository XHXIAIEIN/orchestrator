"""
YouTube Music collector — reads Chrome/Edge history for music.youtube.com.
Groups by video_id + calendar day to avoid duplicate entries for repeat listens.
"""
import hashlib
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from src.storage.events_db import EventsDB

CHROME_EPOCH_OFFSET = 11644473600 * 1_000_000  # microseconds between 1601-01-01 and 1970-01-01
MIN_LISTEN_SECONDS = 10  # ignore accidental clicks under 10s


def _chrome_ts_to_iso(chrome_ts: int) -> str:
    try:
        epoch_us = chrome_ts - CHROME_EPOCH_OFFSET
        dt = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=epoch_us)
        return dt.isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()


def _parse_title(title: str) -> str:
    """Strip ' - YouTube Music' suffix and return cleaned title."""
    for suffix in [" - YouTube Music", "- YouTube Music", "YouTube Music"]:
        if title.endswith(suffix):
            title = title[: -len(suffix)].strip(" -")
    return title.strip() or "Unknown"


def _find_chrome_profiles() -> list[str]:
    home = Path.home()
    roots = [
        home / "AppData/Local/Google/Chrome/User Data",
        home / "AppData/Local/Microsoft/Edge/User Data",
    ]
    paths = []
    for root in roots:
        if not root.exists():
            continue
        for profile_dir in sorted(root.iterdir()):
            hist = profile_dir / "History"
            if hist.exists() and profile_dir.name in ("Default",) or (
                hist.exists() and profile_dir.name.startswith("Profile")
            ):
                paths.append(str(hist))
    return paths


class YouTubeMusicCollector:
    def __init__(self, db: EventsDB, history_paths: list = None):
        self.db = db
        self.history_paths = history_paths if history_paths is not None else _find_chrome_profiles()

    def collect(self) -> int:
        total = 0
        for path in self.history_paths:
            total += self._collect_from(path)
        return total

    def _collect_from(self, history_path: str) -> int:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            shutil.copy2(history_path, tmp_path)
        except (OSError, PermissionError):
            return 0

        rows = []
        try:
            conn = sqlite3.connect(tmp_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT u.url, u.title, v.visit_time, v.visit_duration
                FROM visits v JOIN urls u ON v.url = u.id
                WHERE u.url LIKE '%music.youtube.com/watch%'
                  AND v.visit_duration >= ?
                ORDER BY v.visit_time ASC
            """, (MIN_LISTEN_SECONDS * 1_000_000,)).fetchall()
            conn.close()
        except Exception:
            return 0
        finally:
            try:
                Path(tmp_path).unlink()
            except OSError:
                pass

        # Aggregate: group by (video_id, day)
        sessions: dict[str, dict] = {}
        for row in rows:
            url = row["url"] or ""
            title = row["title"] or ""
            visit_time = row["visit_time"] or 0
            duration_us = row["visit_duration"] or 0

            # Extract video ID
            vid = ""
            if "watch?v=" in url:
                vid = url.split("watch?v=")[1].split("&")[0][:20]
            if not vid:
                continue

            iso = _chrome_ts_to_iso(visit_time)
            day = iso[:10]  # YYYY-MM-DD
            key = f"ytmusic:{vid}:{day}"

            if key not in sessions:
                sessions[key] = {
                    "vid": vid,
                    "title": _parse_title(title),
                    "day": day,
                    "occurred_at": iso,
                    "duration_us": 0,
                    "plays": 0,
                }
            # Prefer non-generic titles
            if title and "YouTube Music" not in title or sessions[key]["title"] == "Unknown":
                sessions[key]["title"] = _parse_title(title)
            sessions[key]["duration_us"] += duration_us
            sessions[key]["plays"] += 1

        new_count = 0
        for key, s in sessions.items():
            duration_min = s["duration_us"] / 60_000_000
            inserted = self.db.insert_event(
                source="youtube_music",
                category="music",
                title=f"{s['title']} (×{s['plays']})" if s["plays"] > 1 else s["title"],
                duration_minutes=duration_min,
                score=min(1.0, duration_min / 5),
                tags=["music", "youtube"],
                metadata={"video_id": s["vid"], "plays": s["plays"], "day": s["day"]},
                dedup_key=key,
                occurred_at=s["occurred_at"],
            )
            if inserted:
                new_count += 1
        return new_count
