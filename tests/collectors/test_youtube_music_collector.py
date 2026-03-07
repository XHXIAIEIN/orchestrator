import sqlite3
import pytest
from src.collectors.youtube_music_collector import YouTubeMusicCollector, _parse_title
from src.storage.events_db import EventsDB

CHROME_EPOCH_OFFSET = 11644473600 * 1_000_000


def make_fake_history(path) -> str:
    import time
    db_path = str(path / "History")
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE urls (
            id INTEGER PRIMARY KEY,
            url TEXT,
            title TEXT,
            last_visit_time INTEGER
        );
        CREATE TABLE visits (
            id INTEGER PRIMARY KEY,
            url INTEGER,
            visit_time INTEGER,
            visit_duration INTEGER
        );
    """)
    # Use a timestamp close to now so get_recent_events doesn't filter it out
    base_ts = CHROME_EPOCH_OFFSET + int(time.time() * 1_000_000)
    conn.execute("INSERT INTO urls VALUES (1, 'https://music.youtube.com/watch?v=abc123&list=PL1', '歌曲名称 - 艺人 - YouTube Music', ?)", (base_ts,))
    conn.execute("INSERT INTO urls VALUES (2, 'https://music.youtube.com/watch?v=xyz789', 'YouTube Music', ?)", (base_ts,))
    conn.execute("INSERT INTO visits VALUES (1, 1, ?, 180000000)", (base_ts,))   # 180s
    conn.execute("INSERT INTO visits VALUES (2, 1, ?, 200000000)", (base_ts + 1000,))  # 200s, same day
    conn.execute("INSERT INTO visits VALUES (3, 2, ?, 5000000)", (base_ts,))    # 5s (< 10s, filtered)
    conn.commit()
    conn.close()
    return db_path


def test_parse_title():
    assert _parse_title("My Song - Artist - YouTube Music") == "My Song - Artist"
    assert _parse_title("YouTube Music") == "Unknown"
    assert _parse_title("歌曲名称") == "歌曲名称"


def test_collector_aggregates_same_video(tmp_path):
    hist = make_fake_history(tmp_path)
    db = EventsDB(str(tmp_path / "events.db"))
    collector = YouTubeMusicCollector(db=db, history_paths=[hist])
    count = collector.collect()
    # abc123 played twice on same day → 1 event; xyz789 too short → 0
    assert count == 1
    events = db.get_recent_events(days=365, source="youtube_music")
    assert len(events) == 1
    assert "歌曲名称" in events[0]["title"]
    assert round(events[0]["duration_minutes"], 1) == round((180 + 200) / 60, 1)


def test_collector_deduplicates(tmp_path):
    hist = make_fake_history(tmp_path)
    db = EventsDB(str(tmp_path / "events.db"))
    collector = YouTubeMusicCollector(db=db, history_paths=[hist])
    collector.collect()
    count2 = collector.collect()
    assert count2 == 0
