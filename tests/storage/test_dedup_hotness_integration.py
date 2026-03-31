"""Integration tests for dedup + hotness wiring into production pipelines.

Verifies:
1. Duplicate learnings are detected and skipped via learnings.py
2. Hotness scoring produces valid tier classifications via memory_tier.py
3. Cold archival identifies stale memories via maintenance.py
4. Failures in these modules don't crash the pipeline
"""
import sqlite3
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from src.storage.dedup import check_duplicate, DedupDecision, text_similarity
from src.storage.hotness import score_hotness, classify_tier, HotnessScorer, HotnessResult


# ── Fixtures ──

def _make_mock_db(learnings=None):
    """Create a mock DB with get_learnings and add_learning."""
    db = MagicMock()
    db.get_learnings.return_value = learnings or []
    db.add_learning.return_value = 99
    db.write_log = MagicMock()
    return db


def _make_sqlite_db():
    """Create an in-memory SQLite DB with the learnings table for hotness tests."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE learnings (
            id INTEGER PRIMARY KEY,
            pattern_key TEXT,
            rule TEXT,
            area TEXT DEFAULT 'general',
            detail TEXT DEFAULT '',
            context TEXT DEFAULT '',
            source_type TEXT DEFAULT 'error',
            entry_type TEXT DEFAULT 'learning',
            related_keys TEXT DEFAULT '[]',
            status TEXT DEFAULT 'pending',
            recurrence INTEGER DEFAULT 1,
            department TEXT,
            task_id INTEGER,
            hit_count INTEGER DEFAULT 0,
            last_hit_at TEXT,
            created_at TEXT,
            first_seen TEXT,
            last_seen TEXT,
            promoted_at TEXT,
            retired_at TEXT,
            ttl_days INTEGER DEFAULT 0,
            expires_at TEXT
        )
    """)
    return conn


class FakeDB:
    """Thin wrapper around in-memory SQLite for HotnessScorer tests."""
    def __init__(self, conn):
        self._conn = conn

    def _connect(self):
        return self._conn


# ── 1. Dedup integration into learnings pipeline ──

class TestDedupInLearnings:
    """Verify dedup check gates learning creation."""

    def test_duplicate_learning_returns_none(self):
        """append_learning should return None when dedup says skip."""
        existing = [{"id": 1, "rule": "always use pytest for tests",
                     "area": "general", "pattern_key": "test:pytest", "recurrence": 3}]
        db = _make_mock_db(existing)

        from src.governance.audit.learnings import append_learning
        result = append_learning("test:pytest-dup", "always use pytest for tests",
                                 "detail", "general", db)
        # Should be skipped (near-identical rule text)
        assert result is None
        db.add_learning.assert_not_called()

    def test_unique_learning_passes_through(self):
        """append_learning should store when no duplicate found."""
        existing = [{"id": 1, "rule": "deploy with docker compose",
                     "area": "general", "pattern_key": "deploy:docker", "recurrence": 1}]
        db = _make_mock_db(existing)

        from src.governance.audit.learnings import append_learning
        result = append_learning("test:new-rule", "always validate user input",
                                 "detail", "general", db)
        assert result is not None
        db.add_learning.assert_called_once()

    def test_duplicate_error_returns_none(self):
        """append_error should also respect dedup."""
        existing = [{"id": 5, "rule": "timeout on API calls to external services",
                     "area": "reliability", "pattern_key": "err:timeout", "recurrence": 2}]
        db = _make_mock_db(existing)

        from src.governance.audit.learnings import append_error
        result = append_error("err:timeout-dup", "timeout on API calls to external services",
                              "detail", "reliability", db)
        assert result is None

    def test_duplicate_feature_returns_none(self):
        """append_feature should also respect dedup."""
        existing = [{"id": 10, "rule": "need Redis caching layer for hot learnings",
                     "area": "infra", "pattern_key": "feat:redis-cache", "recurrence": 1}]
        db = _make_mock_db(existing)

        from src.governance.audit.learnings import append_feature
        result = append_feature("feat:redis-dup", "need Redis caching layer for hot learnings",
                                "detail", "infra", db)
        assert result is None

    def test_different_area_not_deduped(self):
        """Learnings in different areas should not be deduped against each other."""
        existing = [{"id": 1, "rule": "always use pytest for tests",
                     "area": "security", "pattern_key": "test:pytest", "recurrence": 3}]
        db = _make_mock_db(existing)

        from src.governance.audit.learnings import append_learning
        result = append_learning("test:pytest-general", "always use pytest for tests",
                                 "detail", "general", db)
        # Different area -> should create
        assert result is not None

    def test_dedup_failure_doesnt_crash(self):
        """If dedup module raises, learning should still be stored."""
        db = _make_mock_db()
        db.get_learnings.side_effect = Exception("DB connection lost")

        from src.governance.audit.learnings import append_learning
        result = append_learning("test:resilience", "some rule",
                                 "detail", "general", db)
        # Should still create despite dedup failure
        assert result is not None
        db.add_learning.assert_called_once()


# ── 2. Hotness scoring + tier classification ──

class TestHotnessTierClassification:
    """Verify hotness scoring produces valid tiers."""

    def test_recent_high_hits_is_hot(self):
        now = datetime.now(timezone.utc).isoformat()
        score = score_hotness(10, now)
        assert classify_tier(score) == "hot"

    def test_old_low_hits_is_cold(self):
        old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        score = score_hotness(1, old)
        assert classify_tier(score) == "cold"

    def test_moderate_is_warm(self):
        recent = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        score = score_hotness(2, recent)
        tier = classify_tier(score)
        assert tier in ("warm", "hot")  # 2 * ~0.83 = ~1.66 -> warm

    def test_zero_hits_is_cold(self):
        score = score_hotness(0, None)
        assert classify_tier(score) == "cold"

    def test_memory_tier_classify_learning_tier(self):
        """classify_learning_tier in memory_tier.py should use hotness."""
        from src.governance.context.memory_tier import classify_learning_tier
        now = datetime.now(timezone.utc).isoformat()

        assert classify_learning_tier(10, now) == "hot"
        assert classify_learning_tier(0, None) == "cold"
        assert classify_learning_tier(2, now) in ("warm", "hot")


# ── 3. Cold archival via maintenance job ──

class TestColdArchival:
    """Verify HotnessScorer.archive_cold identifies stale memories."""

    def _seed_learnings(self, conn):
        """Insert test learnings with varying hotness profiles."""
        now = datetime.now(timezone.utc)
        old = (now - timedelta(days=30)).isoformat()
        recent = now.isoformat()

        # Hot: high hits, recent
        conn.execute(
            "INSERT INTO learnings (id, pattern_key, rule, hit_count, last_hit_at, created_at, status) "
            "VALUES (1, 'hot:rule', 'frequently used', 10, ?, ?, 'promoted')",
            (recent, old),
        )
        # Warm: moderate hits
        conn.execute(
            "INSERT INTO learnings (id, pattern_key, rule, hit_count, last_hit_at, created_at, status) "
            "VALUES (2, 'warm:rule', 'sometimes used', 3, ?, ?, 'pending')",
            (recent, old),
        )
        # Cold: zero hits, old
        conn.execute(
            "INSERT INTO learnings (id, pattern_key, rule, hit_count, last_hit_at, created_at, status) "
            "VALUES (3, 'cold:rule', 'never used', 0, NULL, ?, 'pending')",
            (old,),
        )
        # Cold but too new (created today)
        conn.execute(
            "INSERT INTO learnings (id, pattern_key, rule, hit_count, last_hit_at, created_at, status) "
            "VALUES (4, 'cold:new', 'just created', 0, NULL, ?, 'pending')",
            (recent,),
        )
        conn.commit()

    def test_archive_cold_only_archives_old_cold(self):
        conn = _make_sqlite_db()
        self._seed_learnings(conn)
        db = FakeDB(conn)

        scorer = HotnessScorer(db)
        archived = scorer.archive_cold(min_age_days=7)

        # Only learning #3 (cold + old) should be archived
        assert archived == 1

        row = conn.execute("SELECT status FROM learnings WHERE id = 3").fetchone()
        assert row["status"] == "archived"

        # Hot/warm should remain
        row = conn.execute("SELECT status FROM learnings WHERE id = 1").fetchone()
        assert row["status"] == "promoted"

        # Cold but new should NOT be archived
        row = conn.execute("SELECT status FROM learnings WHERE id = 4").fetchone()
        assert row["status"] == "pending"

    def test_scorer_tier_stats(self):
        conn = _make_sqlite_db()
        self._seed_learnings(conn)
        db = FakeDB(conn)

        scorer = HotnessScorer(db)
        stats = scorer.get_tier_stats()

        assert stats["total"] == 4
        assert stats["hot"] >= 1  # learning #1
        assert stats["cold"] >= 1  # learning #3 and #4


# ── 4. Maintenance job integration ──

class TestMaintenanceHotnessJob:
    """Verify hotness_sweep runs without crashing."""

    def test_hotness_sweep_with_mock_db(self):
        """hotness_sweep should handle DB gracefully."""
        from src.jobs.maintenance import hotness_sweep

        conn = _make_sqlite_db()
        now = datetime.now(timezone.utc)
        old = (now - timedelta(days=30)).isoformat()
        conn.execute(
            "INSERT INTO learnings (id, pattern_key, rule, hit_count, last_hit_at, created_at, status) "
            "VALUES (1, 'test:rule', 'test', 0, NULL, ?, 'pending')",
            (old,),
        )
        conn.commit()

        db = FakeDB(conn)
        db.write_log = MagicMock()

        # Should not raise
        hotness_sweep(db)

    def test_hotness_sweep_empty_db(self):
        """hotness_sweep should handle empty DB."""
        from src.jobs.maintenance import hotness_sweep

        conn = _make_sqlite_db()
        db = FakeDB(conn)
        db.write_log = MagicMock()

        # Should not raise
        hotness_sweep(db)


# ── 5. Resilience: module failures don't crash pipeline ──

class TestResilience:
    """Verify graceful degradation when modules fail."""

    def test_dedup_import_failure_doesnt_block_learning(self):
        """Even if dedup import fails, learnings should still work."""
        db = _make_mock_db()
        # Patch _DEDUP_AVAILABLE to False to simulate import failure
        with patch("src.governance.audit.learnings._DEDUP_AVAILABLE", False):
            from src.governance.audit.learnings import append_learning
            result = append_learning("test:no-dedup", "rule text",
                                     "detail", "general", db)
            assert result is not None
            db.add_learning.assert_called_once()

    def test_hotness_import_failure_doesnt_block_maintenance(self):
        """Even if hotness import fails, maintenance should skip gracefully."""
        with patch("src.jobs.maintenance._HOTNESS_AVAILABLE", False):
            from src.jobs.maintenance import hotness_sweep
            db = MagicMock()
            # Should not raise, just skip
            hotness_sweep(db)

    def test_memory_tier_classify_without_hotness(self):
        """classify_learning_tier should fall back to heuristic."""
        with patch("src.governance.context.memory_tier._HOTNESS_AVAILABLE", False):
            from src.governance.context.memory_tier import classify_learning_tier
            assert classify_learning_tier(10, None) == "hot"
            assert classify_learning_tier(0, None) == "cold"
            assert classify_learning_tier(2, None) == "warm"
