import sqlite3
import time
import pytest
from pathlib import Path
from src.collectors.browser.collector import BrowserCollector, categorize_url
from src.storage.events_db import EventsDB

CHROME_EPOCH_OFFSET = 11644473600 * 1_000_000


def make_fake_history_db(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("""CREATE TABLE urls (
        id INTEGER PRIMARY KEY, url TEXT NOT NULL,
        title TEXT, visit_count INTEGER DEFAULT 0, last_visit_time INTEGER DEFAULT 0
    )""")
    conn.execute("""CREATE TABLE visits (
        id INTEGER PRIMARY KEY, url INTEGER NOT NULL,
        visit_time INTEGER NOT NULL, visit_duration INTEGER DEFAULT 0
    )""")
    now_chrome = int(time.time() * 1_000_000) + CHROME_EPOCH_OFFSET
    conn.execute("INSERT INTO urls VALUES (1, 'https://github.com/test', 'GitHub Test', 5, ?)", (now_chrome,))
    conn.execute("INSERT INTO visits VALUES (1, 1, ?, 120000000)", (now_chrome,))
    conn.commit()
    conn.close()


def test_categorize_url():
    assert categorize_url("https://github.com/test") == "dev"
    assert categorize_url("https://www.youtube.com/watch") == "media"
    assert categorize_url("https://news.ycombinator.com") == "reading"


def test_collector_reads_history(tmp_path):
    history_path = tmp_path / "Chrome" / "History"
    make_fake_history_db(history_path)
    db = EventsDB(str(tmp_path / "events.db"))
    collector = BrowserCollector(db=db, history_paths={"chrome": str(history_path)})
    count = collector.collect()
    assert count >= 1


def test_collector_deduplicates(tmp_path):
    history_path = tmp_path / "Chrome" / "History"
    make_fake_history_db(history_path)
    db = EventsDB(str(tmp_path / "events.db"))
    collector = BrowserCollector(db=db, history_paths={"chrome": str(history_path)})
    collector.collect()
    count2 = collector.collect()
    assert count2 == 0
