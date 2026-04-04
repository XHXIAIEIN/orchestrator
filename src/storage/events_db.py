import logging
import sqlite3
from pathlib import Path

from src.storage._schema import get_table_ddl, get_migrations, get_deferred_indexes, TABLE_DDL
from src.storage._tasks_mixin import TasksMixin, _ALLOWED_TASK_COLUMNS  # noqa: F401 — re-export
from src.storage._profile_mixin import ProfileMixin
from src.storage._learnings_mixin import LearningsMixin
from src.storage._runs_mixin import RunsMixin
from src.storage._sessions_mixin import SessionsMixin
from src.storage._wake_mixin import WakeMixin
from src.storage._context_mixin import ContextMixin
from src.storage._growth_mixin import GrowthMixin
from src.storage._proactive_mixin import ProactiveMixin
from src.storage.pool import get_pool

log = logging.getLogger(__name__)

_DEFAULT_DB = str(Path(__file__).resolve().parent.parent.parent / "data" / "events.db")


class EventsDB(TasksMixin, ProfileMixin, LearningsMixin, RunsMixin, SessionsMixin, WakeMixin, ContextMixin, GrowthMixin, ProactiveMixin):
    def __init__(self, db_path: str = _DEFAULT_DB):
        self.db_path = db_path
        self._pool = get_pool(
            db_path,
            row_factory=sqlite3.Row,
            log_prefix="events_db",
        )
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
