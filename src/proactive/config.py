"""Proactive engine configuration — all tunable knobs in one place."""
from __future__ import annotations

import os


def _int(key: str, default: int) -> int:
    return int(os.environ.get(key, default))


# Scheduling
SCAN_INTERVAL_MINUTES: int = _int("PROACTIVE_SCAN_INTERVAL", 5)
ACTIVE_HOUR_START: int = _int("PROACTIVE_HOUR_START", 10)
ACTIVE_HOUR_END: int = _int("PROACTIVE_HOUR_END", 23)
MAX_PER_HOUR: int = _int("PROACTIVE_MAX_PER_HOUR", 5)

# Per-signal cooldowns (seconds)
COOLDOWNS: dict[str, int] = {
    "S1":  21600,   # 6h
    "S2":  3600,    # 1h
    "S3":  86400,   # 24h
    "S4":  10800,   # 3h
    "S5":  604800,  # 7d
    "S6":  86400,   # 24h
    "S7":  604800,  # 7d
    "S8":  0,
    "S9":  0,
    "S10": 1209600, # 14d
    "S11": 3600,    # 1h
    "S12": 86400,   # 24h
}

# Detector thresholds
COLLECTOR_FAIL_STREAK: int = _int("PROACTIVE_COLLECTOR_FAIL_STREAK", 3)
GOVERNOR_FAIL_STREAK: int = _int("PROACTIVE_GOVERNOR_FAIL_STREAK", 3)
DB_SIZE_WARN_MB: int = _int("PROACTIVE_DB_SIZE_WARN_MB", 50)
DB_GROWTH_WARN_MB: int = _int("PROACTIVE_DB_GROWTH_WARN_MB", 5)
PROJECT_SILENCE_DAYS: int = _int("PROACTIVE_PROJECT_SILENCE_DAYS", 5)
LATE_NIGHT_HOUR_START: int = _int("PROACTIVE_LATE_NIGHT_START", 1)
LATE_NIGHT_HOUR_END: int = _int("PROACTIVE_LATE_NIGHT_END", 5)
LATE_NIGHT_MIN_COMMITS: int = _int("PROACTIVE_LATE_NIGHT_MIN_COMMITS", 2)
REPEAT_PATTERN_THRESHOLD: int = _int("PROACTIVE_REPEAT_THRESHOLD", 3)
REPEAT_PATTERN_WINDOW_HOURS: int = _int("PROACTIVE_REPEAT_WINDOW_HOURS", 24)
GITHUB_NOTIFICATION_LIMIT: int = _int("PROACTIVE_GH_NOTIF_LIMIT", 5)
MAX_LLM_PER_SCAN: int = _int("PROACTIVE_MAX_LLM_PER_SCAN", 2)
