"""
QQ Music Collector — infer music listening activity by scanning local cache and logs.
QQ Music has no public API and its local DB is encrypted, so we use filesystem heuristics.
"""
import hashlib
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from src.storage.events_db import EventsDB
from src.collectors.base import ICollector, CollectorMeta


class QQMusicCollector(ICollector):
    @classmethod
    def metadata(cls) -> CollectorMeta:
        return CollectorMeta(
            name="qqmusic", display_name="QQ Music", category="optional",
            env_vars=["QQMUSIC_DATA_PATH"], requires=[],
            event_sources=["qqmusic"], default_enabled=False,
        )

    def __init__(self, db: EventsDB, qqmusic_path: str = None):
        super().__init__(db)
        self.db = db
        home = Path.home()
        if qqmusic_path:
            self.data_path = Path(qqmusic_path)
        else:
            self.data_path = Path(os.environ.get(
                "QQMUSIC_DATA_PATH",
                str(home / "AppData" / "Roaming" / "Tencent" / "QQMusic"),
            ))
        # Common QQ Music cache locations
        self.cache_dirs = [
            Path("D:/Program Files/Tencent/QQMusic"),
            home / "Music" / "QQMusic",
            self.data_path,
        ]

    def collect(self) -> int:
        count = 0
        count += self._collect_from_logs()
        count += self._collect_from_cache()
        return count

    def _collect_from_logs(self) -> int:
        """Extract activity markers from QQ Music log files."""
        log_dir = self.data_path / "log"
        if not log_dir.exists():
            return 0

        new_count = 0
        cutoff = time.time() - 7 * 86400  # only look at last 7 days

        for log_file in sorted(log_dir.glob("*.log"), reverse=True):
            try:
                mtime = log_file.stat().st_mtime
                if mtime < cutoff:
                    continue

                # Derive date from filename or mtime
                date_match = re.search(r"(\d{4}-\d{2}-\d{2})", log_file.name)
                log_date = (
                    date_match.group(1)
                    if date_match
                    else datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
                )

                dedup_key = hashlib.md5(
                    f"qqmusic:active:{log_date}".encode()
                ).hexdigest()
                file_size_kb = log_file.stat().st_size / 1024

                # Larger log ≈ heavier usage that day
                score = min(1.0, max(0.3, file_size_kb / 500))

                inserted = self.db.insert_event(
                    source="qqmusic",
                    category="music",
                    title=f"QQ音乐活跃 ({log_date})",
                    duration_minutes=0,
                    score=score,
                    tags=["music", "qqmusic", "listening"],
                    metadata={
                        "date": log_date,
                        "log_file": log_file.name,
                        "log_size_kb": round(file_size_kb, 1),
                    },
                    dedup_key=dedup_key,
                    occurred_at=f"{log_date}T12:00:00+08:00",
                )
                if inserted:
                    new_count += 1
            except Exception:
                continue

        return new_count

    def _collect_from_cache(self) -> int:
        """Scan audio cache files; use mtime to infer recent playback."""
        new_count = 0
        cutoff = time.time() - 7 * 86400
        audio_exts = {".m4a", ".ogg", ".flac", ".mp3", ".wav", ".aac"}

        for cache_dir in self.cache_dirs:
            if not cache_dir.exists():
                continue
            try:
                for audio_file in cache_dir.rglob("*"):
                    if audio_file.suffix.lower() not in audio_exts:
                        continue
                    try:
                        mtime = audio_file.stat().st_mtime
                        if mtime < cutoff:
                            continue

                        name = audio_file.stem
                        if name.isdigit():
                            name = f"Track #{name}"

                        dedup_key = hashlib.md5(
                            f"qqmusic:cache:{audio_file.name}:{int(mtime)}".encode()
                        ).hexdigest()
                        ts = datetime.fromtimestamp(
                            mtime, tz=timezone.utc
                        ).isoformat()

                        inserted = self.db.insert_event(
                            source="qqmusic",
                            category="music",
                            title=name,
                            duration_minutes=0,
                            score=0.5,
                            tags=["music", "qqmusic", "cache"],
                            metadata={
                                "file": (
                                    str(audio_file.relative_to(cache_dir))
                                    if audio_file.is_relative_to(cache_dir)
                                    else audio_file.name
                                ),
                                "format": audio_file.suffix.lower(),
                                "size_mb": round(
                                    audio_file.stat().st_size / 1048576, 1
                                ),
                            },
                            dedup_key=dedup_key,
                            occurred_at=ts,
                        )
                        if inserted:
                            new_count += 1
                    except Exception:
                        continue
            except Exception:
                continue

        return new_count
