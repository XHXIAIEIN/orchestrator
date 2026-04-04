"""Proactive engine configuration — all tunable knobs in one place."""
import os


def _int(key: str, default: int) -> int:
    return int(os.environ.get(key, default))


# ── Scan cycle ──
SCAN_INTERVAL_MINUTES = _int("PROACTIVE_SCAN_INTERVAL", 5)

# ── Time window (hour range, 24h format, CST) ──
ACTIVE_HOUR_START = _int("PROACTIVE_HOUR_START", 10)
ACTIVE_HOUR_END = _int("PROACTIVE_HOUR_END", 23)

# ── Rate cap ──
MAX_PER_HOUR = _int("PROACTIVE_MAX_PER_HOUR", 5)

# ── Per-signal cooldown (seconds) ──
COOLDOWNS: dict[str, int] = {
    "S1": 21600,    # 6h  — collector failures
    "S2": 3600,     # 1h  — container health
    "S3": 86400,    # 24h — DB size
    "S4": 10800,    # 3h  — governor failures
    "S5": 604800,   # 7d  — project silence
    "S6": 86400,    # 24h — late night activity
    "S7": 604800,   # 7d  — repeated patterns
    "S8": 0,        # per batch — batch completion
    "S9": 0,        # per round — steal progress
    "S10": 1209600, # 14d — DEFER overdue
    "S11": 3600,    # 1h  — GitHub activity
    "S12": 86400,   # 24h — dependency vulns
}

# ── Signal thresholds ──
COLLECTOR_FAIL_STREAK = _int("PROACTIVE_COLLECTOR_FAIL_STREAK", 3)
GOVERNOR_FAIL_STREAK = _int("PROACTIVE_GOVERNOR_FAIL_STREAK", 3)
DB_SIZE_WARN_MB = _int("PROACTIVE_DB_SIZE_WARN_MB", 50)
DB_GROWTH_WARN_MB = _int("PROACTIVE_DB_GROWTH_WARN_MB", 5)
PROJECT_SILENCE_DAYS = _int("PROACTIVE_PROJECT_SILENCE_DAYS", 5)
LATE_NIGHT_HOUR_START = _int("PROACTIVE_LATE_NIGHT_START", 1)
LATE_NIGHT_HOUR_END = _int("PROACTIVE_LATE_NIGHT_END", 5)
LATE_NIGHT_MIN_COMMITS = _int("PROACTIVE_LATE_NIGHT_MIN_COMMITS", 2)
REPEAT_PATTERN_THRESHOLD = _int("PROACTIVE_REPEAT_THRESHOLD", 3)

# ── LLM generation cap per scan ──
MAX_LLM_PER_SCAN = _int("PROACTIVE_MAX_LLM_PER_SCAN", 2)
