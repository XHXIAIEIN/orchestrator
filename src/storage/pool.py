"""Generic SQLite single-connection pool with thread-safe singleton per db_path.

Extracted from three near-identical implementations:
  - src/storage/events_db.py (_ConnPool)
  - src/channels/chat/db.py (_ChatConnPool)
  - src/governance/context/structured_memory.py (_MemoryPool)
"""
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

log = logging.getLogger(__name__)

# Global singleton registry — one pool per db_path.
_registry_lock = threading.Lock()
_registry: dict[str, "SQLitePool"] = {}


def _unicode_lower(s: str | None) -> str | None:
    """Unicode-aware casefold for SQLite (R69 Memos steal).

    Python's str.casefold() handles CJK, accented characters, and all Unicode —
    equivalent to Go's cases.Fold() from golang.org/x/text/cases.
    Registered as orch_lower() on every SQLite connection via SQLitePool.
    """
    if s is None:
        return None
    return s.casefold()


class SQLitePool:
    """Single-connection pool with a threading lock — serialises all DB access to one file.

    Args:
        db_path:        Path to the SQLite database file.
        pragmas:        Dict of PRAGMA key→value to execute on each new connection.
                        Defaults to journal_mode=DELETE, busy_timeout=30000.
        row_factory:    Optional row_factory to set on the connection (e.g. sqlite3.Row).
        timeout:        sqlite3.connect timeout in seconds.
        max_retries:    Number of retries on 'database is locked' / 'disk I/O error'.
        retry_base_delay: Base delay (seconds) for exponential backoff between retries.
        ensure_parent:  If True, create parent directories of db_path on connect.
        log_prefix:     Prefix for log messages (helps identify which subsystem).
    """

    def __init__(
        self,
        db_path: str,
        *,
        pragmas: dict[str, str | int] | None = None,
        row_factory=None,
        timeout: int = 30,
        max_retries: int = 3,
        retry_base_delay: float = 0.5,
        ensure_parent: bool = False,
        log_prefix: str = "sqlite_pool",
    ):
        self.db_path = db_path
        self.pragmas = pragmas if pragmas is not None else {
            "journal_mode": "DELETE",
            "busy_timeout": "30000",
        }
        self.row_factory = row_factory
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        self.ensure_parent = ensure_parent
        self.log_prefix = log_prefix

        self.lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    def _raw_connect(self) -> sqlite3.Connection:
        if self.ensure_parent:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=self.timeout, check_same_thread=False)
        if self.row_factory is not None:
            conn.row_factory = self.row_factory
        for key, val in self.pragmas.items():
            try:
                conn.execute(f"PRAGMA {key}={val}")
            except sqlite3.OperationalError:
                pass
        # R69 Memos: register Unicode casefold for CJK-safe case-insensitive search.
        # SQLite's built-in LOWER() only handles ASCII; this enables:
        #   WHERE orch_lower(col) LIKE orch_lower(?)
        conn.create_function("orch_lower", 1, _unicode_lower, deterministic=True)
        return conn

    @contextmanager
    def connect(self):
        """Yield the shared connection under the serialisation lock.

        Uses the connection as a context manager so that SQLite auto-commits on
        success and auto-rolls-back on exception.

        Retries up to max_retries times with exponential backoff on
        ``database is locked`` / ``disk I/O error``.  The lock is released
        during sleep so other threads can make progress.
        """
        last_exc: sqlite3.OperationalError | None = None
        for attempt in range(self.max_retries + 1):
            with self.lock:
                if self._conn is None:
                    self._conn = self._raw_connect()
                try:
                    with self._conn:  # sqlite3 auto-commit / rollback
                        yield self._conn
                    return  # success
                except sqlite3.OperationalError as exc:
                    if "database is locked" in str(exc) or "disk I/O error" in str(exc):
                        log.warning(f"{self.log_prefix}: connection error, recycling: {exc}")
                        try:
                            self._conn.close()
                        except Exception:
                            pass
                        self._conn = self._raw_connect()
                        last_exc = exc
                    else:
                        raise
            # lock released — sleep before next attempt
            if attempt < self.max_retries:
                delay = self.retry_base_delay * (2 ** attempt)
                log.info(f"{self.log_prefix}: retrying in {delay}s (attempt {attempt + 1}/{self.max_retries})")
                time.sleep(delay)
        raise last_exc  # type: ignore[misc]

    def get_conn(self) -> sqlite3.Connection:
        """Get or create the shared connection.  Caller must hold self.lock."""
        if self._conn is None:
            self._conn = self._raw_connect()
        return self._conn

    def recycle(self):
        """Close and reset the connection (call on unrecoverable error)."""
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None


def get_pool(
    db_path: str,
    *,
    pragmas: dict[str, str | int] | None = None,
    row_factory=None,
    timeout: int = 30,
    max_retries: int = 3,
    retry_base_delay: float = 0.5,
    ensure_parent: bool = False,
    log_prefix: str = "sqlite_pool",
) -> SQLitePool:
    """Return the singleton pool for *db_path*, creating it on first call.

    All keyword arguments are only used when the pool is first created;
    subsequent calls for the same db_path return the existing pool.
    """
    with _registry_lock:
        if db_path not in _registry:
            _registry[db_path] = SQLitePool(
                db_path,
                pragmas=pragmas,
                row_factory=row_factory,
                timeout=timeout,
                max_retries=max_retries,
                retry_base_delay=retry_base_delay,
                ensure_parent=ensure_parent,
                log_prefix=log_prefix,
            )
        return _registry[db_path]
