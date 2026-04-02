"""Hourly incremental sync from SQLite -> Qdrant.

Compares SQLite row counts with Qdrant point counts,
upserts any new records since last sync.
"""
import asyncio
import logging

log = logging.getLogger(__name__)


def sync_vectors(db):
    """Sync new records from SQLite to Qdrant. Called by scheduler."""
    try:
        from src.storage.qdrant_store import QdrantStore
        store = QdrantStore()
        if not store.is_available() or not store.is_ollama_available():
            log.info("sync_vectors: Qdrant or Ollama unavailable, skipping")
            return

        loop = asyncio.new_event_loop()
        results = loop.run_until_complete(_sync_all(store, db))
        loop.close()

        total = sum(r.get("synced", 0) for r in results)
        if total > 0:
            log.info(f"sync_vectors: synced {total} records")
        else:
            log.debug("sync_vectors: no new records")
    except Exception as e:
        log.warning(f"sync_vectors: failed: {e}")


async def _sync_all(store, db) -> list[dict]:
    results = []
    results.append(await _sync_collection(
        store, db, "orch_learnings", "learnings",
        "SELECT id, pattern_key, area, rule, context, department, source_type, status, recurrence FROM learnings WHERE status != 'retired'",
        lambda r: {"text": f"{r['rule']}\n{r.get('context', '')}".strip(),
                    "metadata": {"pattern_key": r["pattern_key"], "area": r.get("area", "general"),
                                 "department": r.get("department") or "", "status": r.get("status", "pending"),
                                 "recurrence": r.get("recurrence", 1)}},
    ))
    results.append(await _sync_collection(
        store, db, "orch_experiences", "experiences",
        "SELECT id, date, type, summary, detail, instance FROM experiences",
        lambda r: {"text": f"{r['summary']}\n{r.get('detail', '')}".strip(),
                    "metadata": {"date": r.get("date", ""), "type": r.get("type", ""),
                                 "instance": r.get("instance") or ""}},
    ))
    results.append(await _sync_collection(
        store, db, "orch_runs", "runs",
        "SELECT id, department, summary, status, duration_s, notes FROM run_logs",
        lambda r: {"text": f"[{r['department']}] {r['summary']}\n{r.get('notes', '')}".strip(),
                    "metadata": {"department": r["department"], "status": r.get("status", "done"),
                                 "duration_s": r.get("duration_s", 0)}},
    ))
    return results


async def _sync_collection(store, db, collection, prefix, query, transform_fn) -> dict:
    store.ensure_collection(collection)
    try:
        info = store.client.get_collection(collection)
        qdrant_count = info.points_count
    except Exception:
        qdrant_count = 0

    with db._connect() as conn:
        rows = conn.execute(query).fetchall()
    sqlite_rows = [dict(r) for r in rows]

    if len(sqlite_rows) <= qdrant_count:
        return {"collection": collection, "synced": 0}

    items = []
    for r in sqlite_rows:
        t = transform_fn(r)
        items.append({"sqlite_id": r["id"], "collection_prefix": prefix,
                       "text": t["text"], "metadata": t["metadata"]})

    synced = await store.upsert_batch(collection, items)
    return {"collection": collection, "synced": synced}
