"""Tests for memory consolidation: extractor output -> structured_memory -> retrievable.

Verifies the full pipeline:
  1. memory_extractor output format -> memory_bridge mapping
  2. Dedup prevents identical memories from being inserted twice
  3. All 6 extraction categories map to correct structured_memory dimensions
  4. StructuredMemoryProvider can retrieve bridged memories
"""
import tempfile
from pathlib import Path

import pytest

from src.governance.context.structured_memory import (
    Dimension,
    StructuredMemoryStore,
)
from src.governance.context.memory_bridge import (
    _CATEGORY_TO_DIMENSION,
    _is_duplicate,
    get_store,
    save_extracted_to_structured_memory,
)


# ── Fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary SQLite DB for testing."""
    return str(tmp_path / "test_memory.db")


@pytest.fixture
def store(tmp_db):
    """Fresh StructuredMemoryStore with temp DB."""
    return StructuredMemoryStore(db_path=tmp_db)


def _make_memory(category: str, l0: str, l1: str = "", tags: list[str] = None) -> dict:
    """Helper to create a memory dict matching extractor output format."""
    return {
        "category": category,
        "l0": l0,
        "l1": l1 or f"Detail about {l0}",
        "tags": tags or [category],
    }


# ── Test: Category -> Dimension mapping covers all 6 types ────────────

class TestCategoryMapping:
    def test_all_extractor_categories_mapped(self):
        """All 6 extractor categories have a dimension mapping."""
        expected = {"profile", "preferences", "entities", "events", "cases", "patterns"}
        assert set(_CATEGORY_TO_DIMENSION.keys()) == expected

    def test_profile_maps_to_persona(self):
        assert _CATEGORY_TO_DIMENSION["profile"] == Dimension.PERSONA

    def test_preferences_maps_to_preference(self):
        assert _CATEGORY_TO_DIMENSION["preferences"] == Dimension.PREFERENCE

    def test_entities_maps_to_identity(self):
        assert _CATEGORY_TO_DIMENSION["entities"] == Dimension.IDENTITY

    def test_events_maps_to_activity(self):
        assert _CATEGORY_TO_DIMENSION["events"] == Dimension.ACTIVITY

    def test_cases_maps_to_experience(self):
        assert _CATEGORY_TO_DIMENSION["cases"] == Dimension.EXPERIENCE

    def test_patterns_maps_to_experience(self):
        assert _CATEGORY_TO_DIMENSION["patterns"] == Dimension.EXPERIENCE


# ── Test: Bridge saves to correct dimensions ──────────────────────────

class TestBridgeSave:
    def test_profile_saved_as_persona(self, store):
        memories = [_make_memory("profile", "Expert in Construct 3 game development")]
        counts = save_extracted_to_structured_memory(memories, store=store)
        assert counts.get("persona") == 1

        results = store.search(Dimension.PERSONA, "Construct", top_k=5)
        assert len(results) == 1
        assert "Construct 3" in results[0]["aspect"]

    def test_preferences_saved_as_preference(self, store):
        memories = [_make_memory("preferences", "Always commit per feature point")]
        counts = save_extracted_to_structured_memory(memories, store=store)
        assert counts.get("preference") == 1

        results = store.search(Dimension.PREFERENCE, "commit feature", top_k=5)
        assert len(results) == 1
        assert "commit" in results[0]["directive"].lower()

    def test_entities_saved_as_identity(self, store):
        memories = [_make_memory("entities", "Orchestrator is an AI butler system", tags=["project"])]
        counts = save_extracted_to_structured_memory(memories, store=store)
        assert counts.get("identity") == 1

        results = store.search(Dimension.IDENTITY, "Orchestrator AI", top_k=5)
        assert len(results) == 1
        assert "Orchestrator" in results[0]["fact"]

    def test_events_saved_as_activity(self, store):
        memories = [_make_memory("events", "Successfully migrated memory system to SQLite")]
        counts = save_extracted_to_structured_memory(memories, store=store)
        assert counts.get("activity") == 1

        results = store.search(Dimension.ACTIVITY, "migrated memory", top_k=5)
        assert len(results) == 1
        assert "migrated" in results[0]["summary"].lower()

    def test_cases_saved_as_experience(self, store):
        memories = [_make_memory("cases", "Docker rebuild caused port conflict", "Checked docker ps first")]
        counts = save_extracted_to_structured_memory(memories, store=store)
        assert counts.get("experience") == 1

        results = store.search(Dimension.EXPERIENCE, "Docker rebuild", top_k=5)
        assert len(results) == 1
        assert results[0]["knowledge_value"] == 0.6  # cases get 0.6

    def test_patterns_saved_as_experience_lower_kv(self, store):
        memories = [_make_memory("patterns", "User always prefers direct execution")]
        counts = save_extracted_to_structured_memory(memories, store=store)
        assert counts.get("experience") == 1

        results = store.search(Dimension.EXPERIENCE, "direct execution", top_k=5)
        assert len(results) == 1
        assert results[0]["knowledge_value"] == 0.4  # patterns get 0.4
        # patterns tag added
        import json
        tags = json.loads(results[0]["tags"])
        assert "pattern" in tags


# ── Test: Multiple memories in one batch ──────────────────────────────

class TestBatchSave:
    def test_mixed_categories(self, store):
        memories = [
            _make_memory("profile", "Skilled in pixel art"),
            _make_memory("events", "Deployed v2.0 to production"),
            _make_memory("cases", "Bug in session-stop hook fixed by adding path"),
        ]
        counts = save_extracted_to_structured_memory(memories, store=store)
        assert counts.get("persona") == 1
        assert counts.get("activity") == 1
        assert counts.get("experience") == 1
        assert sum(counts.values()) == 3

    def test_empty_list_returns_empty(self, store):
        counts = save_extracted_to_structured_memory([], store=store)
        assert counts == {}

    def test_unknown_category_skipped(self, store):
        memories = [_make_memory("bogus_category", "This should be skipped")]
        # Override category to something not in the mapping
        memories[0]["category"] = "bogus_category"
        counts = save_extracted_to_structured_memory(memories, store=store)
        assert counts == {}

    def test_empty_l0_skipped(self, store):
        memories = [{"category": "profile", "l0": "", "l1": "detail", "tags": []}]
        counts = save_extracted_to_structured_memory(memories, store=store)
        assert counts == {}


# ── Test: Dedup prevents duplicate insertion ──────────────────────────

class TestDedup:
    def test_exact_duplicate_blocked(self, store):
        memories = [_make_memory("profile", "Expert in Construct 3")]
        save_extracted_to_structured_memory(memories, store=store)

        # Same memory again
        counts = save_extracted_to_structured_memory(memories, store=store)
        assert counts == {}  # nothing new inserted

        # Only 1 entry in persona
        assert store.count(Dimension.PERSONA)["persona"] == 1

    def test_similar_duplicate_blocked(self, store):
        memories = [_make_memory("events", "Migrated memory system to SQLite backend")]
        save_extracted_to_structured_memory(memories, store=store)

        # Same key words, only last word differs — dedup catches this
        similar = [_make_memory("events", "Migrated memory system to SQLite backend today")]
        counts = save_extracted_to_structured_memory(similar, store=store)
        assert counts == {}

    def test_different_content_not_blocked(self, store):
        m1 = [_make_memory("profile", "Expert in Construct 3")]
        m2 = [_make_memory("profile", "Plays guitar on weekends")]
        save_extracted_to_structured_memory(m1, store=store)
        counts = save_extracted_to_structured_memory(m2, store=store)
        assert counts.get("persona") == 1
        assert store.count(Dimension.PERSONA)["persona"] == 2


# ── Test: DB auto-creation ────────────────────────────────────────────

class TestAutoCreate:
    def test_store_creates_db_and_tables(self, tmp_path):
        db_path = str(tmp_path / "nonexistent_dir" / "memory.db")
        store = StructuredMemoryStore(db_path=db_path)
        # Should be able to add and query
        from src.governance.context.structured_memory import PersonaMemory
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        store.add(Dimension.PERSONA, PersonaMemory(
            aspect="test", description="test entry",
            created_at=now, updated_at=now,
        ))
        assert store.count(Dimension.PERSONA)["persona"] == 1


# ── Test: get_store singleton ─────────────────────────────────────────

class TestGetStore:
    def test_singleton_returns_same_instance(self, tmp_db):
        import src.governance.context.memory_bridge as bridge
        # Reset singleton
        bridge._store_instance = None

        s1 = bridge.get_store(db_path=tmp_db)
        s2 = bridge.get_store()
        assert s1 is s2

        # Cleanup
        bridge._store_instance = None


# ── Test: Full pipeline (extract format -> store -> provider retrieval) ─

class TestFullPipeline:
    def test_extract_save_retrieve(self, store):
        """Simulate extractor output -> bridge -> provider query."""
        # Simulated extractor output (same format as extract_memories returns)
        extracted = [
            {"category": "profile", "l0": "Builds indie games with Construct 3",
             "l1": "Active in the Chinese C3 community, creates tools and plugins",
             "tags": ["gamedev", "construct3"]},
            {"category": "events", "l0": "Completed 16 rounds of steal-patterns analysis",
             "l1": "Systematically studied 78+ projects extracting 226+ patterns",
             "tags": ["steal", "governance"]},
            {"category": "preferences", "l0": "Execute directly without asking permission",
             "l1": "User strongly prefers autonomous execution over step-by-step confirmation",
             "tags": ["workflow", "autonomy"]},
        ]

        counts = save_extracted_to_structured_memory(extracted, store=store)
        assert sum(counts.values()) == 3

        # Verify retrievable via search (same path StructuredMemoryProvider uses)
        persona_results = store.search(Dimension.PERSONA, "Construct indie", top_k=5)
        assert len(persona_results) >= 1
        assert "Construct 3" in persona_results[0]["aspect"]

        activity_results = store.search(Dimension.ACTIVITY, "steal patterns", top_k=5)
        assert len(activity_results) >= 1

        pref_results = store.search(Dimension.PREFERENCE, "execute permission", top_k=5)
        assert len(pref_results) >= 1
        assert "permission" in pref_results[0]["directive"].lower()

    def test_get_hot_includes_bridged_memories(self, store):
        """Bridged memories with confidence >= 0.6 appear in get_hot()."""
        extracted = [
            {"category": "profile", "l0": "Senior developer with 10 years experience",
             "l1": "Full stack background", "tags": ["dev"]},
        ]
        save_extracted_to_structured_memory(extracted, store=store)

        hot = store.get_hot(budget_chars=5000)
        assert len(hot) >= 1
        # Our bridge sets confidence=0.75 which is >= 0.6 threshold
        found = any("Senior developer" in str(e.get("aspect", "")) for e in hot)
        assert found
