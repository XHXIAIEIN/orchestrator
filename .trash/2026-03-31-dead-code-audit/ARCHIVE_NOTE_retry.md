# collectors/retry.py — Archived 2026-03-31

Replaced by: core/resilient_retry.py (ChatDev R13, strict superset)
- resilient_retry has 4-layer exception matching (type blacklist/whitelist, HTTP status, message substring)
- Full __cause__/__context__ chain traversal
- Configurable RetryPolicy dataclass vs hardcoded TransientError/PermanentError

Nothing lost. Safe to delete permanently.
