"""Profile/events-related methods for EventsDB."""
import json
from datetime import datetime, timezone, timedelta


class ProfileMixin:

    def insert_event(self, source: str, category: str, title: str,
                     duration_minutes: float, score: float, tags: list,
                     metadata: dict, dedup_key: str = None,
                     occurred_at: str = None) -> bool:
        import sqlite3
        ts = occurred_at or datetime.now(timezone.utc).isoformat()
        try:
            with self._connect() as conn:
                conn.execute(
                    """INSERT INTO events
                       (source, category, title, duration_minutes, score, tags, metadata, dedup_key, occurred_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (source, category, title, duration_minutes, score,
                     json.dumps(tags, ensure_ascii=False),
                     json.dumps(metadata, ensure_ascii=False, default=str),
                     dedup_key, ts)
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def get_recent_events(self, days: int = 7, source: str = None, since: str = None) -> list:
        if since is None:
            since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._connect() as conn:
            if source:
                rows = conn.execute(
                    "SELECT * FROM events WHERE occurred_at >= ? AND source = ? ORDER BY occurred_at DESC",
                    (since, source)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM events WHERE occurred_at >= ? ORDER BY occurred_at DESC",
                    (since,)
                ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["tags"] = json.loads(d["tags"])
            d["metadata"] = json.loads(d["metadata"])
            result.append(d)
        return result

    def get_events_by_day(self, days: int = 60) -> list:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DATE(occurred_at) as day, COUNT(*) as count "
                "FROM events WHERE occurred_at >= ? GROUP BY DATE(occurred_at) ORDER BY day ASC",
                (since,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_events_by_category(self, days: int = 7) -> list:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT category, SUM(duration_minutes) as total_min, COUNT(*) as count "
                "FROM events WHERE occurred_at >= ? GROUP BY category ORDER BY total_min DESC",
                (since,)
            ).fetchall()
        return [dict(r) for r in rows]

    def save_daily_summary(self, date: str, summary: str):
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO daily_summaries (date, summary, created_at) VALUES (?, ?, ?)",
                (date, summary, now)
            )

    def get_daily_summaries(self, days: int = 7) -> list:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT date, summary FROM daily_summaries WHERE date >= ? ORDER BY date DESC",
                (since,)
            ).fetchall()
        result = []
        for r in rows:
            try:
                result.append({"date": r["date"], **json.loads(r["summary"])})
            except Exception:
                pass
        return result

    def save_user_profile(self, profile: dict):
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO user_profile (profile_json, updated_at) VALUES (?, ?)",
                (json.dumps(profile, ensure_ascii=False), now)
            )

    def get_latest_profile(self) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT profile_json FROM user_profile ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
        return json.loads(row["profile_json"]) if row else {}

    def save_insights(self, data: dict):
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO insights (data_json, generated_at) VALUES (?, ?)",
                (json.dumps(data, ensure_ascii=False), now)
            )

    def get_latest_insights(self) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data_json FROM insights ORDER BY generated_at DESC LIMIT 1"
            ).fetchone()
        return json.loads(row["data_json"]) if row else {}

    def save_profile_analysis(self, data: dict, analysis_type: str = 'periodic'):
        now = datetime.now(timezone.utc).isoformat()
        data_copy = dict(data)
        data_copy['generated_at'] = now
        data_copy['type'] = analysis_type
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO profile_analysis (data_json, type, generated_at) VALUES (?, ?, ?)",
                (json.dumps(data_copy, ensure_ascii=False), analysis_type, now)
            )
            conn.execute(
                "DELETE FROM profile_analysis WHERE id NOT IN "
                "(SELECT id FROM profile_analysis ORDER BY id DESC LIMIT 50)"
            )

    def get_profile_analysis(self, analysis_type: str = None) -> dict:
        with self._connect() as conn:
            if analysis_type:
                row = conn.execute(
                    "SELECT data_json FROM profile_analysis WHERE type = ? ORDER BY id DESC LIMIT 1",
                    (analysis_type,)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT data_json FROM profile_analysis ORDER BY id DESC LIMIT 1"
                ).fetchone()
        return json.loads(row["data_json"]) if row else {}
