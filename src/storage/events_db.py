import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from src.storage._schema import get_table_ddl, get_migrations, get_deferred_indexes, TABLE_DDL
from src.storage._tasks_mixin import TasksMixin, _ALLOWED_TASK_COLUMNS  # noqa: F401 — re-export
from src.storage._profile_mixin import ProfileMixin
from src.storage._learnings_mixin import LearningsMixin
from src.storage._runs_mixin import RunsMixin
from src.storage._sessions_mixin import SessionsMixin
from src.storage._wake_mixin import WakeMixin

log = logging.getLogger(__name__)

_DEFAULT_DB = str(Path(__file__).resolve().parent.parent.parent / "data" / "events.db")

# Per-path singleton lock: all EventsDB instances sharing the same file share one lock + connection.
_pool_lock = threading.Lock()
_pools: dict[str, "_ConnPool"] = {}


class _ConnPool:
    """Single-connection pool with a threading lock — serialises all DB access to one file."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    def _raw_connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # DELETE journal — WAL's -shm file breaks on Docker NTFS bind-mounts.
        try:
            conn.execute("PRAGMA journal_mode=DELETE")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("PRAGMA busy_timeout=30000")
        except sqlite3.OperationalError:
            pass
        return conn

    @contextmanager
    def connect(self):
        """Yield the shared connection under the serialisation lock.

        Uses the connection as a context manager so that SQLite auto-commits on
        success and auto-rolls-back on exception — same semantics as the old
        ``with self._connect() as conn`` pattern used by all mixins.
        """
        with self.lock:
            if self._conn is None:
                self._conn = self._raw_connect()
            try:
                with self._conn:  # sqlite3 auto-commit / rollback
                    yield self._conn
            except sqlite3.OperationalError as exc:
                if "database is locked" in str(exc) or "disk I/O error" in str(exc):
                    log.warning(f"events_db: connection error, recycling: {exc}")
                    try:
                        self._conn.close()
                    except Exception:
                        pass
                    self._conn = self._raw_connect()
                raise


def _get_pool(db_path: str) -> _ConnPool:
    with _pool_lock:
        if db_path not in _pools:
            _pools[db_path] = _ConnPool(db_path)
        return _pools[db_path]


class EventsDB(TasksMixin, ProfileMixin, LearningsMixin, RunsMixin, SessionsMixin, WakeMixin):
    def __init__(self, db_path: str = _DEFAULT_DB):
        self.db_path = db_path
        self._pool = _get_pool(db_path)
        self._init_tables()

    def _connect(self):
        """Return a context manager that yields the shared connection under lock.

        All mixins use ``with self._connect() as conn:`` — this now serialises
        through the pool instead of creating a new connection every time.
        """
        return self._pool.connect()

    def _connect_safe(self):
        """Alias kept for backward compat — same as _connect now."""
        return self._pool.connect()

    def _init_tables(self):
        with self._connect() as conn:
            conn.executescript(TABLE_DDL)
            for _table, col, typ in get_migrations():
                try:
                    conn.execute(f"ALTER TABLE {_table} ADD COLUMN {col} {typ}")
                except sqlite3.OperationalError:
                    pass
            for idx_sql in get_deferred_indexes():
                try:
                    conn.execute(idx_sql)
                except sqlite3.OperationalError:
                    pass

    def get_tables(self) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            return [row["name"] for row in rows]

    def get_size_bytes(self) -> int:
        path = Path(self.db_path)
        return path.stat().st_size if path.exists() else 0
