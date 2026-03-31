"""Memory Bridge — connects memory_extractor output to StructuredMemoryStore.

Extracted memories from the 6-type extractor were previously written to
events.db/agent_events (dead data). This bridge routes them to the
6-dimensional structured_memory.py system where they're actually queryable.

Mapping:
  profile    -> persona     (aspect/description/subject)
  preferences -> preference (directive/priority/condition/suggested_action)
  entities   -> identity    (fact/category/subject)
  events     -> activity    (summary/detail/emotion/event_date)
  cases      -> experience  (situation/reasoning/action/outcome/knowledge_value)
  patterns   -> experience  (situation/reasoning — recurring behavioral patterns)
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from src.governance.context.structured_memory import (
    ActivityMemory,
    Dimension,
    ExperienceMemory,
    IdentityMemory,
    PersonaMemory,
    PreferenceMemory,
    StructuredMemoryStore,
)

log = logging.getLogger(__name__)

# ── Singleton store ────────────────────────────────────────────────────

_store_instance: Optional[StructuredMemoryStore] = None


def get_store(db_path: str = None) -> StructuredMemoryStore:
    """Get or create a singleton StructuredMemoryStore.

    Auto-creates DB and tables on first call.
    """
    global _store_instance
    if _store_instance is None:
        kwargs = {"db_path": db_path} if db_path else {}
        _store_instance = StructuredMemoryStore(**kwargs)
    return _store_instance


# ── Category -> Dimension mapping ──────────────────────────────────────

_CATEGORY_TO_DIMENSION: dict[str, Dimension] = {
    "profile": Dimension.PERSONA,
    "preferences": Dimension.PREFERENCE,
    "entities": Dimension.IDENTITY,
    "events": Dimension.ACTIVITY,
    "cases": Dimension.EXPERIENCE,
    "patterns": Dimension.EXPERIENCE,
}


# ── Dedup helper ───────────────────────────────────────────────────────

def _is_duplicate(store: StructuredMemoryStore, dimension: Dimension, text: str) -> bool:
    """Check if a similar memory already exists using keyword search.

    Uses the first 5 significant words from the text as a search query.
    If any result's primary field contains 80%+ of those words, it's a dup.
    """
    words = [w for w in text.split() if len(w) > 2][:5]
    if not words:
        return False

    query = " ".join(words)
    results = store.search(dimension, query, top_k=3)
    if not results:
        return False

    # Check primary text field for overlap
    primary_fields = {
        Dimension.ACTIVITY: "summary",
        Dimension.IDENTITY: "fact",
        Dimension.PREFERENCE: "directive",
        Dimension.EXPERIENCE: "situation",
        Dimension.PERSONA: "aspect",
    }
    pf = primary_fields.get(dimension, "summary")

    text_lower = text.lower()
    for r in results:
        existing = str(r.get(pf, "")).lower()
        # If existing text contains 80%+ of the query words, it's a dup
        matches = sum(1 for w in words if w.lower() in existing)
        if matches >= len(words) * 0.8:
            return True
        # Also check if the new text is essentially the same string
        if text_lower.strip() == existing.strip():
            return True

    return False


# ── Bridge function ────────────────────────────────────────────────────

def save_extracted_to_structured_memory(
    memories: list[dict],
    store: StructuredMemoryStore = None,
) -> dict[str, int]:
    """Route memory_extractor output into StructuredMemoryStore.

    Args:
        memories: List of dicts from extract_memories(), each with:
                  category, l0, l1, tags
        store: Optional store instance. Uses singleton if not provided.

    Returns:
        Dict of {dimension_name: count_inserted}
    """
    if not memories:
        return {}

    store = store or get_store()
    now = datetime.now(timezone.utc)
    counts: dict[str, int] = {}

    for m in memories:
        category = m.get("category", "")
        dimension = _CATEGORY_TO_DIMENSION.get(category)
        if dimension is None:
            log.debug(f"memory_bridge: unknown category '{category}', skipping")
            continue

        l0 = m.get("l0", "")
        l1 = m.get("l1", "")
        tags = m.get("tags", [])

        if not l0:
            continue

        # Dedup: check if similar memory already exists
        if _is_duplicate(store, dimension, l0):
            log.debug(f"memory_bridge: duplicate found for '{l0[:50]}...', skipping")
            continue

        entry = _build_entry(category, dimension, l0, l1, tags, now)
        store.add(dimension, entry)
        counts[dimension.value] = counts.get(dimension.value, 0) + 1

    if counts:
        log.info(f"memory_bridge: saved {sum(counts.values())} memories -> {counts}")

    return counts


def _build_entry(category: str, dimension: Dimension, l0: str, l1: str,
                 tags: list[str], now: datetime):
    """Build the appropriate dataclass entry for a dimension."""

    if dimension == Dimension.PERSONA:
        # profile -> persona: l0 is the aspect, l1 is description
        return PersonaMemory(
            aspect=l0,
            description=l1,
            subject="owner",
            tags=tags,
            confidence=0.75,
            created_at=now,
            updated_at=now,
        )

    if dimension == Dimension.PREFERENCE:
        # preferences -> preference: l0 is the directive, l1 provides context
        return PreferenceMemory(
            directive=l0,
            suggested_action=l1,
            tags=tags,
            confidence=0.75,
            created_at=now,
            updated_at=now,
        )

    if dimension == Dimension.IDENTITY:
        # entities -> identity: l0 is the fact, category from tags
        entity_category = tags[0] if tags else "entity"
        return IdentityMemory(
            fact=l0,
            category=entity_category,
            subject=l1[:100] if l1 else "",
            tags=tags,
            confidence=0.75,
            created_at=now,
            updated_at=now,
        )

    if dimension == Dimension.ACTIVITY:
        # events -> activity: l0 is summary, l1 is detail
        return ActivityMemory(
            summary=l0,
            detail=l1,
            emotion="",
            event_date=now.strftime("%Y-%m-%d"),
            tags=tags,
            confidence=0.75,
            created_at=now,
            updated_at=now,
        )

    if dimension == Dimension.EXPERIENCE:
        # cases or patterns -> experience
        if category == "cases":
            return ExperienceMemory(
                situation=l0,
                reasoning=l1,
                action="",
                outcome="",
                knowledge_value=0.6,
                tags=tags,
                confidence=0.75,
                created_at=now,
                updated_at=now,
            )
        # patterns -> experience with lower knowledge_value (behavioral, not case-specific)
        return ExperienceMemory(
            situation=l0,
            reasoning=l1,
            action="",
            outcome="",
            knowledge_value=0.4,
            tags=["pattern"] + tags,
            confidence=0.7,
            created_at=now,
            updated_at=now,
        )

    # Should not reach here, but defensive
    return ExperienceMemory(
        situation=l0,
        reasoning=l1,
        tags=tags,
        confidence=0.6,
        created_at=now,
        updated_at=now,
    )
