#!/usr/bin/env python3
"""One-shot migration: SQLite → Qdrant.

Usage: python scripts/migrate_to_qdrant.py [--db data/events.db] [--memory-db data/memory.db]
"""
import argparse
import asyncio
import logging
import sqlite3
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_EVENTS_DB = str(BASE_DIR / "data" / "events.db")
DEFAULT_MEMORY_DB = str(BASE_DIR / "data" / "memory.db")


def _read_table(db_path: str, query: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(query).fetchall()
    conn.close()
    return [dict(r) for r in rows]


async def migrate_learnings(store, db_path: str) -> dict:
    rows = _read_table(db_path,
        "SELECT id, pattern_key, area, rule, context, department, source_type, status, recurrence "
        "FROM learnings WHERE status != 'retired'")
    items = [{"sqlite_id": r["id"], "collection_prefix": "learnings",
              "text": f"{r['rule']}\n{r.get('context', '')}".strip(),
              "metadata": {"pattern_key": r["pattern_key"], "area": r.get("area", "general"),
                           "department": r.get("department") or "", "status": r.get("status", "pending"),
                           "recurrence": r.get("recurrence", 1)}} for r in rows]
    count = await store.upsert_batch("orch_learnings", items)
    return {"collection": "orch_learnings", "source_rows": len(rows), "upserted": count}


async def migrate_experiences(store, db_path: str) -> dict:
    rows = _read_table(db_path, "SELECT id, date, type, summary, detail, instance FROM experiences ORDER BY id")
    items = [{"sqlite_id": r["id"], "collection_prefix": "experiences",
              "text": f"{r['summary']}\n{r.get('detail', '')}".strip(),
              "metadata": {"date": r.get("date", ""), "type": r.get("type", ""),
                           "instance": r.get("instance") or ""}} for r in rows]
    count = await store.upsert_batch("orch_experiences", items)
    return {"collection": "orch_experiences", "source_rows": len(rows), "upserted": count}


async def migrate_runs(store, db_path: str) -> dict:
    rows = _read_table(db_path,
        "SELECT id, department, summary, status, duration_s, notes FROM run_logs ORDER BY id")
    items = [{"sqlite_id": r["id"], "collection_prefix": "runs",
              "text": f"[{r['department']}] {r['summary']}\n{r.get('notes', '')}".strip(),
              "metadata": {"department": r["department"], "status": r.get("status", "done"),
                           "duration_s": r.get("duration_s", 0)}} for r in rows]
    count = await store.upsert_batch("orch_runs", items)
    return {"collection": "orch_runs", "source_rows": len(rows), "upserted": count}


async def migrate_files(store, db_path: str) -> dict:
    rows = _read_table(db_path, "SELECT path, routing_hint, tags FROM file_index WHERE routing_hint != ''")
    items = [{"sqlite_id": i + 1, "collection_prefix": "files",
              "text": f"{r['path']}: {r['routing_hint']}",
              "metadata": {"path": r["path"], "tags": r.get("tags", "[]")}} for i, r in enumerate(rows)]
    count = await store.upsert_batch("orch_files", items)
    return {"collection": "orch_files", "source_rows": len(rows), "upserted": count}


async def migrate_memory(store, memory_db_path: str) -> dict:
    dimensions = ["activity", "identity", "context", "preference", "experience", "persona"]
    total_rows = 0
    total_upserted = 0
    for dim in dimensions:
        try:
            rows = _read_table(memory_db_path, f"SELECT * FROM {dim} ORDER BY id")
        except Exception:
            log.info(f"  {dim}: table not found or empty, skipping")
            continue
        items = []
        for r in rows:
            text_parts = [str(v) for v in r.values() if isinstance(v, str) and v]
            items.append({"sqlite_id": r["id"], "collection_prefix": f"memory_{dim}",
                          "text": " ".join(text_parts[:5]),
                          "metadata": {"dimension": dim, "confidence": r.get("confidence", 0.8)}})
        count = await store.upsert_batch("orch_memory", items)
        log.info(f"  {dim}: {len(rows)} rows -> {count} upserted")
        total_rows += len(rows)
        total_upserted += count
    return {"collection": "orch_memory", "source_rows": total_rows, "upserted": total_upserted}


async def main(events_db: str, memory_db: str):
    from src.storage.qdrant_store import QdrantStore
    store = QdrantStore()
    if not store.is_available():
        log.error("Qdrant is not available. Start it first.")
        return
    if not store.is_ollama_available():
        log.error("Ollama is not available. Start it first.")
        return

    log.info("=== Qdrant Migration Start ===")
    log.info(f"Events DB: {events_db}")
    log.info(f"Memory DB: {memory_db}")
    store.ensure_all_collections()

    t0 = time.time()
    results = []
    for name, coro in [("learnings", migrate_learnings(store, events_db)),
                        ("experiences", migrate_experiences(store, events_db)),
                        ("runs", migrate_runs(store, events_db)),
                        ("files", migrate_files(store, events_db)),
                        ("memory", migrate_memory(store, memory_db))]:
        log.info(f"Migrating {name}...")
        try:
            result = await coro
            results.append(result)
            log.info(f"  done: {result['source_rows']} rows -> {result['upserted']} upserted")
        except Exception as e:
            log.error(f"  FAILED: {name}: {e}")
            results.append({"collection": name, "error": str(e)})

    elapsed = time.time() - t0
    log.info(f"\n=== Migration Complete ({elapsed:.1f}s) ===")
    for r in results:
        status = "OK" if "error" not in r else "FAIL"
        log.info(f"  [{status}] {r.get('collection', '?')}: {r.get('source_rows', 0)} -> {r.get('upserted', 0)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate SQLite data to Qdrant")
    parser.add_argument("--db", default=DEFAULT_EVENTS_DB)
    parser.add_argument("--memory-db", default=DEFAULT_MEMORY_DB)
    args = parser.parse_args()
    asyncio.run(main(args.db, args.memory_db))
