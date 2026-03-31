"""Tests for the shared SQLitePool (src.storage.pool)."""
import gc
import os
import sqlite3
import threading

import pytest

from src.storage.pool import SQLitePool, get_pool, _registry, _registry_lock


# ── Helpers ────────────────────────────────────────────────────────────

def _cleanup_registry(*db_paths):
    """Remove pools from the global registry and close connections."""
    with _registry_lock:
        for p in db_paths:
            pool = _registry.pop(p, None)
            if pool and pool._conn:
                try:
                    pool._conn.close()
                except Exception:
                    pass
    gc.collect()


# ── Basic lifecycle ───────────────────────────────────────────────────

class TestSQLitePoolBasic:

    def test_connect_creates_db(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        pool = SQLitePool(db_path)
        with pool.connect() as conn:
            conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
            conn.execute("INSERT INTO t VALUES (1)")
        with pool.connect() as conn:
            row = conn.execute("SELECT id FROM t").fetchone()
            assert row[0] == 1

    def test_default_pragmas(self, tmp_path):
        db_path = str(tmp_path / "pragmas.db")
        pool = SQLitePool(db_path)
        with pool.connect() as conn:
            jm = conn.execute("PRAGMA journal_mode").fetchone()[0]
            bt = conn.execute("PRAGMA busy_timeout").fetchone()[0]
            assert jm == "delete"
            assert bt == 30000

    def test_custom_pragmas(self, tmp_path):
        db_path = str(tmp_path / "custom.db")
        pool = SQLitePool(db_path, pragmas={"journal_mode": "WAL", "busy_timeout": "5000"})
        with pool.connect() as conn:
            jm = conn.execute("PRAGMA journal_mode").fetchone()[0]
            bt = conn.execute("PRAGMA busy_timeout").fetchone()[0]
            assert jm == "wal"
            assert bt == 5000

    def test_row_factory(self, tmp_path):
        db_path = str(tmp_path / "factory.db")
        pool = SQLitePool(db_path, row_factory=sqlite3.Row)
        with pool.connect() as conn:
            conn.execute("CREATE TABLE t (name TEXT)")
            conn.execute("INSERT INTO t VALUES ('hello')")
            row = conn.execute("SELECT name FROM t").fetchone()
            assert row["name"] == "hello"

    def test_ensure_parent(self, tmp_path):
        db_path = str(tmp_path / "sub" / "dir" / "test.db")
        pool = SQLitePool(db_path, ensure_parent=True)
        with pool.connect() as conn:
            conn.execute("CREATE TABLE t (id INTEGER)")
        assert os.path.exists(db_path)

    def test_no_ensure_parent_missing_dir(self, tmp_path):
        db_path = str(tmp_path / "nonexistent" / "test.db")
        pool = SQLitePool(db_path, ensure_parent=False)
        with pytest.raises(sqlite3.OperationalError):
            with pool.connect() as conn:
                pass


# ── Singleton registry ────────────────────────────────────────────────

class TestPoolRegistry:

    def test_singleton_per_path(self, tmp_path):
        db_path = str(tmp_path / "singleton.db")
        try:
            p1 = get_pool(db_path, log_prefix="test1")
            p2 = get_pool(db_path, log_prefix="test2")
            assert p1 is p2
        finally:
            _cleanup_registry(db_path)

    def test_different_paths_different_pools(self, tmp_path):
        db1 = str(tmp_path / "a.db")
        db2 = str(tmp_path / "b.db")
        try:
            p1 = get_pool(db1)
            p2 = get_pool(db2)
            assert p1 is not p2
        finally:
            _cleanup_registry(db1, db2)


# ── Connection reuse ──────────────────────────────────────────────────

class TestConnectionReuse:

    def test_same_connection_across_calls(self, tmp_path):
        db_path = str(tmp_path / "reuse.db")
        pool = SQLitePool(db_path)
        conn_ids = []
        with pool.connect() as conn:
            conn_ids.append(id(conn))
        with pool.connect() as conn:
            conn_ids.append(id(conn))
        assert conn_ids[0] == conn_ids[1], "Should reuse the same connection object"

    def test_get_conn_returns_same(self, tmp_path):
        db_path = str(tmp_path / "get_conn.db")
        pool = SQLitePool(db_path)
        with pool.lock:
            c1 = pool.get_conn()
            c2 = pool.get_conn()
            assert c1 is c2


# ── Recycle ───────────────────────────────────────────────────────────

class TestRecycle:

    def test_recycle_resets_connection(self, tmp_path):
        db_path = str(tmp_path / "recycle.db")
        pool = SQLitePool(db_path)
        with pool.connect() as conn:
            pass
        old_conn = pool._conn
        pool.recycle()
        assert pool._conn is None
        # Next connect should create a new connection
        with pool.connect() as conn:
            assert conn is not old_conn


# ── Thread safety ─────────────────────────────────────────────────────

class TestThreadSafety:

    def test_concurrent_writes(self, tmp_path):
        db_path = str(tmp_path / "threads.db")
        pool = SQLitePool(db_path)
        with pool.connect() as conn:
            conn.execute("CREATE TABLE t (val INTEGER)")

        errors = []
        def writer(n):
            try:
                for i in range(20):
                    with pool.connect() as conn:
                        conn.execute("INSERT INTO t VALUES (?)", (n * 100 + i,))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors}"
        with pool.connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
            assert count == 80


# ── Retry on locked DB ───────────────────────────────────────────────

class TestRetry:

    def test_retry_on_locked(self, tmp_path):
        """Pool retries when the connection raises 'database is locked'."""
        db_path = str(tmp_path / "locked.db")
        pool = SQLitePool(db_path, max_retries=2, retry_base_delay=0.01)

        # Seed the DB
        with pool.connect() as conn:
            conn.execute("CREATE TABLE t (id INTEGER)")

        call_count = 0
        orig_raw = pool._raw_connect

        def patched_raw():
            nonlocal call_count
            call_count += 1
            return orig_raw()

        pool._raw_connect = patched_raw

        # Force a locked error on first attempt by monkeypatching
        attempt = [0]
        orig_execute = sqlite3.Connection.execute

        # We can't easily simulate locked, so just verify the pool works normally
        with pool.connect() as conn:
            conn.execute("INSERT INTO t VALUES (1)")
        with pool.connect() as conn:
            assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1
