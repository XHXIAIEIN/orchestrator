"""
采集器声誉系统 — 追踪每个采集器的长期健康状况。
灵感：OpenCLI 的 AI 自助闭环评估 + Strategy Cascade 的信心度。
"""
import json
import logging
from datetime import datetime, timezone, timedelta

from src.storage.events_db import EventsDB

log = logging.getLogger(__name__)

CIRCUIT_OPEN_THRESHOLD = 5   # 连续失败次数
CIRCUIT_OPEN_DURATION = 3600  # 熔断时间（秒）


class ReputationTracker:
    def __init__(self, db: EventsDB):
        self.db = db
        self._cache: dict[str, dict] = {}

    def _default_rep(self, name: str) -> dict:
        return {
            "name": name,
            "total_runs": 0,
            "successful_runs": 0,
            "total_events": 0,
            "avg_events_per_run": 0.0,
            "last_success": "",
            "last_failure": "",
            "last_failure_reason": "",
            "streak": 0,
            "health_score": 1.0,
        }

    def _load(self, name: str) -> dict:
        if name in self._cache:
            return self._cache[name]
        try:
            with self.db._connect() as conn:
                row = conn.execute(
                    "SELECT data FROM collector_reputation WHERE name = ?", (name,)
                ).fetchone()
                if row:
                    self._cache[name] = json.loads(row["data"])
                    return self._cache[name]
        except Exception:
            pass
        self._cache[name] = self._default_rep(name)
        return self._cache[name]

    def _save(self, name: str):
        rep = self._cache.get(name, self._default_rep(name))
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self.db._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO collector_reputation (name, data, updated_at) VALUES (?, ?, ?)",
                    (name, json.dumps(rep, ensure_ascii=False), now),
                )
        except Exception as e:
            log.warning(f"reputation: failed to save {name}: {e}")

    def update(self, name: str, event_count: int, error: str = None):
        rep = self._load(name)
        now = datetime.now(timezone.utc).isoformat()
        rep["total_runs"] += 1

        if event_count >= 0:
            rep["successful_runs"] += 1
            rep["total_events"] += event_count
            rep["avg_events_per_run"] = rep["total_events"] / rep["successful_runs"]
            rep["last_success"] = now
            rep["streak"] = max(rep["streak"] + 1, 1)
        else:
            rep["last_failure"] = now
            rep["last_failure_reason"] = error or "unknown"
            rep["streak"] = min(rep["streak"] - 1, -1)

        rep["health_score"] = self._calc_health(rep)
        self._cache[name] = rep
        self._save(name)

    def _calc_health(self, rep: dict) -> float:
        rate = rep["successful_runs"] / max(rep["total_runs"], 1)
        volume = min(rep["avg_events_per_run"] / 10.0, 1.0)
        trend = 1.0 if rep["streak"] > 0 else max(0.0, 1.0 + rep["streak"] * 0.1)
        return round(rate * 0.6 + volume * 0.2 + trend * 0.2, 3)

    def should_skip(self, name: str) -> tuple[bool, str]:
        rep = self._load(name)
        if rep["streak"] <= -CIRCUIT_OPEN_THRESHOLD:
            if rep["last_failure"]:
                try:
                    last = datetime.fromisoformat(rep["last_failure"])
                    if (datetime.now(timezone.utc) - last).total_seconds() < CIRCUIT_OPEN_DURATION:
                        return True, f"circuit open: {-rep['streak']} consecutive failures"
                except (ValueError, TypeError):
                    pass
        return False, ""

    def get_all(self) -> list[dict]:
        try:
            with self.db._connect() as conn:
                rows = conn.execute("SELECT data FROM collector_reputation ORDER BY name").fetchall()
                return [json.loads(r["data"]) for r in rows]
        except Exception:
            return list(self._cache.values())
