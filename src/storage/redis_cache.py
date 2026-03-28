"""Redis hot cache — transparent fallback to no-op when unavailable.

Lazy-init: first call tries to connect. If Redis is up, use it.
If not, all methods silently return None/empty — zero impact on callers.

Auto-enable: when data volume exceeds thresholds, Redis becomes
recommended. If unavailable at that point, logs a warning once.
"""
import json
import logging
import time
from typing import Any

log = logging.getLogger(__name__)

# Data volume thresholds — when exceeded, Redis is recommended
THRESHOLDS = {
    "chat_messages": 500,    # messages across all channels
    "learnings": 200,        # learning rules
    "tasks": 1000,           # total tasks
    "agent_events": 5000,    # agent execution events
}

# Redis connection config
REDIS_URL = "redis://localhost:6379"
DEFAULT_TTL = 86400  # 24h


class RedisCache:
    """Transparent Redis cache with lazy init and auto-fallback."""

    def __init__(self, url: str = REDIS_URL):
        self._url = url
        self._client = None
        self._available: bool | None = None  # None = not checked yet
        self._warned_threshold = False

    @property
    def available(self) -> bool:
        """Check if Redis is available. Lazy: only connects on first check."""
        if self._available is None:
            self._try_connect()
        return self._available

    def _try_connect(self):
        """Attempt Redis connection. Non-blocking, fails silently."""
        try:
            import redis
            self._client = redis.from_url(
                self._url,
                socket_connect_timeout=1,
                socket_timeout=1,
                decode_responses=True,
            )
            self._client.ping()
            self._available = True
            log.info("redis_cache: connected to %s", self._url)
        except Exception:
            self._client = None
            self._available = False
            # Don't log on startup — only log when actually needed
            pass

    def _reconnect_if_needed(self) -> bool:
        """Re-check connection (e.g. Redis started after orchestrator)."""
        if self._available:
            try:
                self._client.ping()
                return True
            except Exception:
                self._available = False
                self._client = None
                return False
        # Retry connect at most every 60s
        self._try_connect()
        return self._available

    # ── Key-Value ops ──

    def get(self, key: str) -> str | None:
        if not self.available:
            return None
        try:
            return self._client.get(key)
        except Exception:
            return None

    def set(self, key: str, value: str, ttl: int = DEFAULT_TTL) -> bool:
        if not self.available:
            return False
        try:
            self._client.setex(key, ttl, value)
            return True
        except Exception:
            return False

    def delete(self, key: str) -> bool:
        if not self.available:
            return False
        try:
            self._client.delete(key)
            return True
        except Exception:
            return False

    # ── JSON ops ──

    def get_json(self, key: str) -> Any:
        raw = self.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    def set_json(self, key: str, value: Any, ttl: int = DEFAULT_TTL) -> bool:
        try:
            return self.set(key, json.dumps(value, ensure_ascii=False, default=str), ttl)
        except Exception:
            return False

    # ── List ops (message buffer) ──

    def lpush(self, key: str, value: str, ttl: int = DEFAULT_TTL) -> bool:
        if not self.available:
            return False
        try:
            self._client.lpush(key, value)
            self._client.expire(key, ttl)
            return True
        except Exception:
            return False

    def lrange(self, key: str, start: int = 0, stop: int = -1) -> list[str]:
        if not self.available:
            return []
        try:
            return self._client.lrange(key, start, stop)
        except Exception:
            return []

    # ── Threshold check ──

    def check_thresholds(self, db) -> dict[str, bool]:
        """Check if any data volume exceeds threshold.

        Returns dict of {table: exceeded}. If exceeded and Redis
        unavailable, logs a one-time warning.
        """
        exceeded = {}
        any_exceeded = False

        for table, threshold in THRESHOLDS.items():
            try:
                with db._connect() as conn:
                    count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                exceeded[table] = count > threshold
                if count > threshold:
                    any_exceeded = True
            except Exception:
                exceeded[table] = False

        if any_exceeded and not self.available and not self._warned_threshold:
            self._warned_threshold = True
            tables = [t for t, v in exceeded.items() if v]
            log.warning(
                "redis_cache: data volume threshold exceeded for %s — "
                "Redis recommended but unavailable. "
                "Run: docker compose --profile redis up -d redis",
                ", ".join(tables),
            )

        return exceeded

    # ── Status ──

    def status(self) -> dict:
        return {
            "available": self.available,
            "url": self._url,
            "warned_threshold": self._warned_threshold,
        }


# Singleton
_instance: RedisCache | None = None


def get_redis() -> RedisCache:
    """Get the global RedisCache instance (lazy singleton)."""
    global _instance
    if _instance is None:
        _instance = RedisCache()
    return _instance
