"""
YouTube Music collector — reads Chrome/Edge history for music.youtube.com.
Groups by video_id + calendar day to avoid duplicate entries for repeat listens.
Resolves unknown titles via YouTube oEmbed (no API key required).
"""
import json
import shutil
import sqlite3
import tempfile
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from src.storage.events_db import EventsDB

CHROME_EPOCH_OFFSET = 11644473600 * 1_000_000
MIN_LISTEN_SECONDS = 10

# Generic app-level titles that aren't real song names
_GENERIC_TITLES = {"YouTube Music", "畅听喜爱的歌曲和专辑 | YouTube Music", ""}

# Cache resolved titles in memory to avoid duplicate network requests per run
_title_cache: dict[str, str] = {}


def _chrome_ts_to_iso(chrome_ts: int) -> str:
    try:
        epoch_us = chrome_ts - CHROME_EPOCH_OFFSET
        dt = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=epoch_us)
        return dt.isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()


def _parse_title(title: str) -> str:
    """Strip YouTube Music branding from title (handles both - and | separators)."""
    for suffix in [" | YouTube Music", "| YouTube Music", " - YouTube Music", "- YouTube Music", "YouTube Music"]:
        if title.endswith(suffix):
            title = title[: -len(suffix)].strip(" -|")
    return title.strip()


def _is_generic(title: str) -> bool:
    return not title or title in _GENERIC_TITLES or title == "YouTube Music"


def _oembed_title(video_id: str) -> str:
    """Look up song title via YouTube oEmbed (no API key needed). Returns '' on failure."""
    if video_id in _title_cache:
        return _title_cache[video_id]
    try:
        url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.load(resp)
        title = data.get("title", "")
        artist = data.get("author_name", "")
        # Strip " - Topic" suffix common for auto-generated artist channels
        artist = artist.removesuffix(" - Topic").strip()
        result = f"{title} — {artist}" if artist else title
        _title_cache[video_id] = result
        return result
    except Exception:
        _title_cache[video_id] = ""
        return ""


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


def update_unknown_titles(db: EventsDB) -> int:
    """Retroactively resolve 'Unknown' and '[vid_id]' titles in existing DB records."""
    import sqlite3 as _sqlite3
    conn = _sqlite3.connect(db.db_path)
    conn.row_factory = _sqlite3.Row
    rows = conn.execute("""
        SELECT id, title, metadata FROM events
        WHERE source='youtube_music' AND (title LIKE 'Unknown%' OR title LIKE '[%]%')
    """).fetchall()
    conn.close()

    updated = 0
    for row in rows:
        try:
            meta = json.loads(row["metadata"])
            vid = meta.get("video_id", "")
        except Exception:
            continue
        if not vid:
            continue
        resolved = _oembed_title(vid)
        if not resolved:
            continue
        plays = meta.get("plays", 1)
        new_title = f"{resolved} (×{plays})" if plays > 1 else resolved
        with _sqlite3.connect(db.db_path) as conn:
            conn.execute("UPDATE events SET title=? WHERE id=?", (new_title[:200], row["id"]))
        updated += 1
    return updated


class YouTubeMusicCollector:
    def __init__(self, db: EventsDB, history_paths: list = None, resolve_titles: bool = True):
        self.db = db
        self.history_paths = history_paths if history_paths is not None else _find_chrome_profiles()
        self.resolve_titles = resolve_titles

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

        # Aggregate by (video_id, day)
        sessions: dict[str, dict] = {}
        for row in rows:
            url = row["url"] or ""
            title = row["title"] or ""
            visit_time = row["visit_time"] or 0
            duration_us = row["visit_duration"] or 0

            vid = ""
            if "watch?v=" in url:
                vid = url.split("watch?v=")[1].split("&")[0][:20]
            if not vid:
                continue

            iso = _chrome_ts_to_iso(visit_time)
            day = iso[:10]
            key = f"ytmusic:{vid}:{day}"

            parsed = _parse_title(title)

            if key not in sessions:
                sessions[key] = {
                    "vid": vid,
                    "title": parsed,
                    "day": day,
                    "occurred_at": iso,
                    "duration_us": 0,
                    "plays": 0,
                }
            # Prefer actual song title over generic ones
            if parsed and not _is_generic(parsed) and _is_generic(sessions[key]["title"]):
                sessions[key]["title"] = parsed
            sessions[key]["duration_us"] += duration_us
            sessions[key]["plays"] += 1

        # Resolve unknown titles via oEmbed
        if self.resolve_titles:
            for s in sessions.values():
                if _is_generic(s["title"]):
                    resolved = _oembed_title(s["vid"])
                    if resolved:
                        s["title"] = resolved

        new_count = 0
        for key, s in sessions.items():
            duration_min = s["duration_us"] / 60_000_000
            title = s["title"] or f"[{s['vid']}]"
            if s["plays"] > 1:
                title = f"{title} (×{s['plays']})"
            inserted = self.db.insert_event(
                source="youtube_music",
                category="music",
                title=title[:200],
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
