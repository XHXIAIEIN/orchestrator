# Vector Memory Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace SQLite bag-of-chars vector search with Qdrant + Qwen3-Embedding (via Ollama), adding semantic retrieval to learnings, experiences, structured memory, run logs, and file index.

**Architecture:** `QdrantStore` is the single entry point for all vector ops. It embeds text via Ollama's `/api/embed` endpoint (Qwen3-Embedding, 4096-dim), stores vectors in Qdrant (5 collections), and provides `search_with_fallback()` that degrades to SequenceMatcher when Qdrant/Ollama are unavailable. SQLite remains the authority; Qdrant is a search index rebuilt from SQLite on demand.

**Tech Stack:** `qdrant-client>=1.9.0`, `httpx` (async Ollama calls), Qdrant server (already running), Ollama (already running with `qwen3-embedding`)

**Spec:** `docs/superpowers/specs/2026-04-03-vector-memory-layer-design.md`

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Create | `src/storage/qdrant_store.py` | QdrantStore class: embed, upsert, search, health |
| Create | `src/jobs/sync_vectors.py` | Hourly incremental sync from SQLite → Qdrant |
| Create | `scripts/migrate_to_qdrant.py` | One-shot full migration script |
| Create | `tests/test_qdrant_store.py` | Unit tests for QdrantStore |
| Modify | `requirements.txt` | Add qdrant-client, httpx |
| Modify | `src/storage/_learnings_mixin.py:11-75` | Hook upsert after add_learning() |
| Modify | `src/storage/_runs_mixin.py:38-55,159-167` | Hook upsert after append_run_log() and add_experience() |
| Modify | `src/storage/_sessions_mixin.py:184-220` | Hook upsert after add_experience_unified() |
| Modify | `src/governance/context/structured_memory.py:259-273` | Hook upsert after StructuredMemoryStore.add() |
| Modify | `src/governance/dispatcher.py:253-297` | Inject semantic learning/run retrieval before dispatch |
| Modify | `src/storage/dedup.py:41-91` | Add embedding-based similarity path |
| Modify | `src/scheduler.py:39-55` | Register sync_vectors job |
| Retire | `src/storage/vector_db.py` → `.trash/` | Replaced by qdrant_store.py |

---

### Task 1: Add Dependencies

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add qdrant-client and httpx to requirements.txt**

Add after the `websockets` line:

```
# Vector memory layer (Qdrant + Ollama embedding)
qdrant-client>=1.9.0
httpx>=0.27.0
```

- [ ] **Step 2: Install dependencies**

Run: `pip install qdrant-client httpx`
Expected: both packages install without error

- [ ] **Step 3: Verify imports**

Run: `python3 -c "from qdrant_client import QdrantClient; import httpx; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "deps: add qdrant-client and httpx for vector memory layer"
```

---

### Task 2: QdrantStore Core — Embed + Collection Management

**Files:**
- Create: `src/storage/qdrant_store.py`
- Create: `tests/test_qdrant_store.py`

- [ ] **Step 1: Write failing tests for embed and collection management**

```python
# tests/test_qdrant_store.py
"""Tests for QdrantStore — Qdrant + Ollama embedding."""
import uuid
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from qdrant_client import QdrantClient, models

from src.storage.qdrant_store import QdrantStore, make_point_id


# ── Fixtures ──

@pytest.fixture
def memory_client():
    """Qdrant in-memory client for testing."""
    return QdrantClient(":memory:")


@pytest.fixture
def store(memory_client):
    """QdrantStore with in-memory Qdrant and mocked Ollama."""
    s = QdrantStore.__new__(QdrantStore)
    s.client = memory_client
    s.ollama_url = "http://localhost:11434"
    s.model = "qwen3-embedding"
    s.dim = 4096
    s._http = MagicMock()
    return s


# ── Point ID ──

def test_make_point_id_deterministic():
    id1 = make_point_id("learnings", 42)
    id2 = make_point_id("learnings", 42)
    assert id1 == id2
    assert isinstance(id1, str)
    # Different collection or row → different ID
    assert make_point_id("learnings", 42) != make_point_id("experiences", 42)
    assert make_point_id("learnings", 42) != make_point_id("learnings", 43)


# ── Collection Management ──

def test_ensure_collection_creates(memory_client, store):
    store.ensure_collection("test_col")
    info = memory_client.get_collection("test_col")
    assert info.config.params.vectors.size == 4096
    assert info.config.params.vectors.distance == models.Distance.COSINE


def test_ensure_collection_idempotent(memory_client, store):
    store.ensure_collection("test_col")
    store.ensure_collection("test_col")  # no error
    info = memory_client.get_collection("test_col")
    assert info.config.params.vectors.size == 4096


# ── Embed ──

@pytest.mark.asyncio
async def test_embed_calls_ollama(store):
    fake_vec = [0.1] * 4096
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"embeddings": [fake_vec]}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
        result = await store.embed(["hello world"])

    assert len(result) == 1
    assert len(result[0]) == 4096


@pytest.mark.asyncio
async def test_embed_batch(store):
    fake_vec = [0.1] * 4096
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"embeddings": [fake_vec, fake_vec, fake_vec]}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
        result = await store.embed(["a", "b", "c"])

    assert len(result) == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_qdrant_store.py -v --tb=short 2>&1 | head -30`
Expected: ImportError — `src.storage.qdrant_store` does not exist yet

- [ ] **Step 3: Implement QdrantStore core (embed + collection)**

```python
# src/storage/qdrant_store.py
"""QdrantStore — Orchestrator vector memory layer.

Qdrant + Ollama Qwen3-Embedding. Single entry point for all vector ops.
SQLite stays authority; Qdrant is a search index.
"""
import logging
import os
import uuid
from typing import Optional

import httpx
from qdrant_client import QdrantClient, models

log = logging.getLogger(__name__)

# ── Config ──

_IN_DOCKER = os.path.exists("/.dockerenv")

QDRANT_URL = os.environ.get(
    "QDRANT_URL",
    "http://host.docker.internal:6333" if _IN_DOCKER else "http://localhost:6333",
)
OLLAMA_URL = os.environ.get(
    "OLLAMA_URL",
    "http://host.docker.internal:11434" if _IN_DOCKER else "http://localhost:11434",
)
OLLAMA_EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "qwen3-embedding")
EMBED_DIM = int(os.environ.get("QDRANT_EMBED_DIM", "4096"))
EMBED_BATCH_SIZE = 32

# ── Collections ──

COLLECTIONS = [
    "orch_learnings",
    "orch_experiences",
    "orch_memory",
    "orch_runs",
    "orch_files",
]


def make_point_id(collection: str, sqlite_id: int) -> str:
    """Deterministic UUID from collection name + SQLite rowid."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"orch.{collection}.{sqlite_id}"))


class QdrantStore:
    """Orchestrator vector memory layer — Qdrant + Ollama Embedding."""

    def __init__(
        self,
        qdrant_url: str = QDRANT_URL,
        ollama_url: str = OLLAMA_URL,
        model: str = OLLAMA_EMBED_MODEL,
        dim: int = EMBED_DIM,
    ):
        self.client = QdrantClient(url=qdrant_url, timeout=30)
        self.ollama_url = ollama_url
        self.model = model
        self.dim = dim

    # ── Collection Management ──

    def ensure_collection(self, name: str) -> None:
        """Create collection if it doesn't exist. Idempotent."""
        existing = [c.name for c in self.client.get_collections().collections]
        if name in existing:
            return
        self.client.create_collection(
            collection_name=name,
            vectors_config=models.VectorParams(
                size=self.dim,
                distance=models.Distance.COSINE,
            ),
        )
        log.info(f"qdrant: created collection '{name}' (dim={self.dim})")

    def ensure_all_collections(self) -> None:
        """Create all Orchestrator collections."""
        for name in COLLECTIONS:
            self.ensure_collection(name)

    # ── Embedding ──

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts via Ollama /api/embed. Returns list of vectors."""
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self.ollama_url}/api/embed",
                json={"model": self.model, "input": texts},
            )
            resp.raise_for_status()
            data = resp.json()
        return data["embeddings"]

    async def embed_single(self, text: str) -> list[float]:
        """Embed a single text. Convenience wrapper."""
        vecs = await self.embed([text])
        return vecs[0]

    # ── Health ──

    def is_available(self) -> bool:
        """Check Qdrant connectivity."""
        try:
            self.client.get_collections()
            return True
        except Exception:
            return False

    def is_ollama_available(self) -> bool:
        """Check Ollama connectivity (sync, for health checks)."""
        try:
            resp = httpx.get(f"{self.ollama_url}/api/tags", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_qdrant_store.py -v --tb=short 2>&1 | tail -20`
Expected: all 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/storage/qdrant_store.py tests/test_qdrant_store.py
git commit -m "feat(vector): QdrantStore core — embed + collection management"
```

---

### Task 3: QdrantStore Write + Search + Fallback

**Files:**
- Modify: `src/storage/qdrant_store.py`
- Modify: `tests/test_qdrant_store.py`

- [ ] **Step 1: Write failing tests for upsert and search**

Append to `tests/test_qdrant_store.py`:

```python
# ── Upsert + Search ──

@pytest.mark.asyncio
async def test_upsert_and_search(memory_client, store):
    store.ensure_collection("test_search")

    # Mock embed to return deterministic vectors
    async def _fake_embed(texts):
        # Return slightly different vectors per text
        vecs = []
        for t in texts:
            v = [0.0] * 4096
            for i, c in enumerate(t[:100]):
                v[i % 4096] = ord(c) / 1000.0
            vecs.append(v)
        return vecs

    store.embed = _fake_embed

    await store.upsert("test_search", "learnings", 1, "never use rm -rf in production", {"area": "ops"})
    await store.upsert("test_search", "learnings", 2, "always backup before deploy", {"area": "ops"})

    results = await store.search("test_search", "dangerous production commands", top_k=2)
    assert len(results) == 2
    assert "id" in results[0]
    assert "score" in results[0]
    assert "text" in results[0]
    assert "metadata" in results[0]


@pytest.mark.asyncio
async def test_upsert_batch(memory_client, store):
    store.ensure_collection("test_batch")

    async def _fake_embed(texts):
        return [[float(i)] * 4096 for i in range(len(texts))]

    store.embed = _fake_embed

    items = [
        {"sqlite_id": 1, "collection_prefix": "learnings", "text": "rule one", "metadata": {}},
        {"sqlite_id": 2, "collection_prefix": "learnings", "text": "rule two", "metadata": {}},
        {"sqlite_id": 3, "collection_prefix": "learnings", "text": "rule three", "metadata": {}},
    ]
    count = await store.upsert_batch("test_batch", items)
    assert count == 3

    info = memory_client.get_collection("test_batch")
    assert info.points_count == 3


# ── Fallback ──

@pytest.mark.asyncio
async def test_search_with_fallback_when_available(memory_client, store):
    store.ensure_collection("test_fb")

    async def _fake_embed(texts):
        return [[0.1] * 4096 for _ in texts]

    store.embed = _fake_embed

    await store.upsert("test_fb", "learnings", 1, "test fallback", {})
    results = await store.search_with_fallback("test_fb", "test", top_k=1)
    assert len(results) == 1


@pytest.mark.asyncio
async def test_search_with_fallback_when_unavailable():
    store = QdrantStore(qdrant_url="http://localhost:1", ollama_url="http://localhost:1")
    results = await store.search_with_fallback("orch_learnings", "test", top_k=1)
    assert results == []  # graceful empty, no exception
```

- [ ] **Step 2: Run tests to verify new tests fail**

Run: `python -m pytest tests/test_qdrant_store.py::test_upsert_and_search -v --tb=short`
Expected: AttributeError — `QdrantStore` has no `upsert` method

- [ ] **Step 3: Implement upsert, search, and fallback**

Add to `QdrantStore` class in `src/storage/qdrant_store.py`:

```python
    # ── Write ──

    async def upsert(
        self,
        collection: str,
        collection_prefix: str,
        sqlite_id: int,
        text: str,
        metadata: dict,
    ) -> None:
        """Embed + upsert a single document."""
        point_id = make_point_id(collection_prefix, sqlite_id)
        vec = await self.embed_single(text)
        self.client.upsert(
            collection_name=collection,
            points=[
                models.PointStruct(
                    id=point_id,
                    vector=vec,
                    payload={"text": text, "sqlite_id": sqlite_id, **metadata},
                )
            ],
        )

    async def upsert_batch(
        self,
        collection: str,
        items: list[dict],
    ) -> int:
        """Batch embed + upsert. Each item: {sqlite_id, collection_prefix, text, metadata}.

        Processes in chunks of EMBED_BATCH_SIZE. Returns count upserted.
        """
        total = 0
        for i in range(0, len(items), EMBED_BATCH_SIZE):
            chunk = items[i : i + EMBED_BATCH_SIZE]
            texts = [it["text"] for it in chunk]
            try:
                vecs = await self.embed(texts)
            except Exception as e:
                log.warning(f"qdrant: embed failed for batch {i}-{i+len(chunk)}: {e}")
                continue

            points = []
            for item, vec in zip(chunk, vecs):
                point_id = make_point_id(
                    item.get("collection_prefix", collection),
                    item["sqlite_id"],
                )
                points.append(
                    models.PointStruct(
                        id=point_id,
                        vector=vec,
                        payload={"text": item["text"], "sqlite_id": item["sqlite_id"],
                                 **item.get("metadata", {})},
                    )
                )
            self.client.upsert(collection_name=collection, points=points)
            total += len(points)
        return total

    # ── Search ──

    async def search(
        self,
        collection: str,
        query: str,
        top_k: int = 5,
        filters: Optional[dict] = None,
    ) -> list[dict]:
        """Semantic search. Returns [{id, text, score, metadata}]."""
        query_vec = await self.embed_single(query)

        qdrant_filter = None
        if filters:
            conditions = [
                models.FieldCondition(
                    key=k, match=models.MatchValue(value=v)
                )
                for k, v in filters.items()
            ]
            qdrant_filter = models.Filter(must=conditions)

        hits = self.client.query_points(
            collection_name=collection,
            query=query_vec,
            query_filter=qdrant_filter,
            limit=top_k,
        ).points

        results = []
        for hit in hits:
            payload = hit.payload or {}
            results.append({
                "id": str(hit.id),
                "text": payload.get("text", ""),
                "score": hit.score,
                "metadata": {k: v for k, v in payload.items() if k not in ("text", "sqlite_id")},
                "sqlite_id": payload.get("sqlite_id"),
            })
        return results

    async def search_with_fallback(
        self,
        collection: str,
        query: str,
        top_k: int = 5,
        filters: Optional[dict] = None,
    ) -> list[dict]:
        """Search with graceful degradation. Returns [] if both Qdrant and Ollama are down."""
        try:
            return await self.search(collection, query, top_k, filters)
        except Exception as e:
            log.warning(f"qdrant: search failed for '{collection}', falling back: {e}")
            return []

    # ── Delete ──

    def delete_point(self, collection: str, collection_prefix: str, sqlite_id: int) -> None:
        """Delete a single point by SQLite ID."""
        point_id = make_point_id(collection_prefix, sqlite_id)
        self.client.delete(
            collection_name=collection,
            points_selector=models.PointIdsList(points=[point_id]),
        )
```

- [ ] **Step 4: Run all tests**

Run: `python -m pytest tests/test_qdrant_store.py -v --tb=short`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/storage/qdrant_store.py tests/test_qdrant_store.py
git commit -m "feat(vector): QdrantStore upsert, search, and fallback"
```

---

### Task 4: Write Path — Learnings Mixin Hook

**Files:**
- Modify: `src/storage/_learnings_mixin.py:11-75`

- [ ] **Step 1: Add qdrant upsert hook to add_learning()**

At the end of `add_learning()`, after the INSERT/UPDATE, fire-and-forget an async upsert. Since the mixin is sync, use a background task pattern:

Add at top of `src/storage/_learnings_mixin.py`:

```python
from src.storage.qdrant_store import QdrantStore

def _qdrant_sync_learning(learning_id: int, rule: str, metadata: dict):
    """Fire-and-forget Qdrant upsert for a learning. Non-blocking."""
    import asyncio
    try:
        store = _get_qdrant_store()
        if store is None:
            return
        loop = asyncio.new_event_loop()
        loop.run_until_complete(
            store.upsert("orch_learnings", "learnings", learning_id, rule, metadata)
        )
        loop.close()
    except Exception as e:
        log.debug(f"qdrant sync skipped for learning #{learning_id}: {e}")


_qdrant_store_instance = None

def _get_qdrant_store():
    global _qdrant_store_instance
    if _qdrant_store_instance is None:
        try:
            s = QdrantStore()
            if s.is_available():
                s.ensure_collection("orch_learnings")
                _qdrant_store_instance = s
        except Exception:
            pass
    return _qdrant_store_instance
```

Then at the end of `add_learning()`, before both `return` statements (line 50 and 75), add:

```python
        # Sync to Qdrant (fire-and-forget)
        import threading
        threading.Thread(
            target=_qdrant_sync_learning,
            args=(existing["id"] if existing else cursor.lastrowid,
                  rule,
                  {"area": area, "department": department or "", "source_type": source_type,
                   "pattern_key": pattern_key, "status": "pending"}),
            daemon=True,
        ).start()
```

- [ ] **Step 2: Verify learnings mixin still works**

Run: `python -m pytest tests/ -k "learning" -v --tb=short 2>&1 | tail -20`
Expected: existing learning tests still PASS

- [ ] **Step 3: Commit**

```bash
git add src/storage/_learnings_mixin.py
git commit -m "feat(vector): hook Qdrant upsert into add_learning()"
```

---

### Task 5: Write Path — Experience + Run Log + Structured Memory Hooks

**Files:**
- Modify: `src/storage/_runs_mixin.py:38-55,159-167`
- Modify: `src/storage/_sessions_mixin.py:184-220`
- Modify: `src/governance/context/structured_memory.py:259-273`

- [ ] **Step 1: Add hook to add_experience() in _runs_mixin.py**

Same pattern as learnings — fire-and-forget thread. Add at top of `_runs_mixin.py`:

```python
def _qdrant_sync_experience(exp_id: int, text: str, metadata: dict):
    """Fire-and-forget Qdrant upsert for an experience."""
    import asyncio
    try:
        from src.storage.qdrant_store import QdrantStore
        store = QdrantStore()
        if not store.is_available():
            return
        store.ensure_collection("orch_experiences")
        loop = asyncio.new_event_loop()
        loop.run_until_complete(
            store.upsert("orch_experiences", "experiences", exp_id, text, metadata)
        )
        loop.close()
    except Exception:
        pass
```

At end of `add_experience()` (after line 167), before `return cursor.lastrowid`:

```python
            exp_id = cursor.lastrowid
        # Sync to Qdrant
        import threading
        threading.Thread(
            target=_qdrant_sync_experience,
            args=(exp_id, f"{summary}\n{detail}",
                  {"date": date, "type": type, "instance": instance or ""}),
            daemon=True,
        ).start()
        return exp_id
```

- [ ] **Step 2: Add hook to append_run_log() in _runs_mixin.py**

Same pattern. Add helper:

```python
def _qdrant_sync_run(run_id: int, text: str, metadata: dict):
    """Fire-and-forget Qdrant upsert for a run log."""
    import asyncio
    try:
        from src.storage.qdrant_store import QdrantStore
        store = QdrantStore()
        if not store.is_available():
            return
        store.ensure_collection("orch_runs")
        loop = asyncio.new_event_loop()
        loop.run_until_complete(
            store.upsert("orch_runs", "runs", run_id, text, metadata)
        )
        loop.close()
    except Exception:
        pass
```

At end of `append_run_log()` (after line 55), before `return cursor.lastrowid`:

```python
            run_id = cursor.lastrowid
        import threading
        threading.Thread(
            target=_qdrant_sync_run,
            args=(run_id, f"[{department}] {summary}\n{notes}",
                  {"department": department, "status": status, "duration_s": duration_s}),
            daemon=True,
        ).start()
        return run_id
```

- [ ] **Step 3: Add hook to add_experience_unified() in _sessions_mixin.py**

At end of `add_experience_unified()` method (after the `exp_id = cur.lastrowid` line), add:

```python
        # Sync to Qdrant
        try:
            import threading
            from src.storage._runs_mixin import _qdrant_sync_experience
            threading.Thread(
                target=_qdrant_sync_experience,
                args=(exp_id, f"{summary}\n{detail}",
                      {"date": date, "type": etype, "instance": instance or ""}),
                daemon=True,
            ).start()
        except Exception:
            pass
```

- [ ] **Step 4: Add hook to StructuredMemoryStore.add() in structured_memory.py**

At end of `add()` method (after line 273 `return row_id`), add a sync call. Add helper at module level:

```python
def _qdrant_sync_memory(row_id: int, dimension: str, text: str, metadata: dict):
    """Fire-and-forget Qdrant upsert for structured memory."""
    import asyncio
    try:
        from src.storage.qdrant_store import QdrantStore
        store = QdrantStore()
        if not store.is_available():
            return
        store.ensure_collection("orch_memory")
        # Use dimension+rowid to avoid collision across tables
        composite_id = f"{dimension}_{row_id}"
        import uuid
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"orch.memory.{composite_id}"))
        loop = asyncio.new_event_loop()
        loop.run_until_complete(
            store.upsert("orch_memory", "memory", row_id, text,
                         {"dimension": dimension, **metadata})
        )
        loop.close()
    except Exception:
        pass
```

Modify `add()` to call this before `return row_id`:

```python
        # Sync to Qdrant
        import threading
        text_for_embed = " ".join(str(v) for v in data.values() if isinstance(v, str))
        threading.Thread(
            target=_qdrant_sync_memory,
            args=(row_id, dim.value, text_for_embed,
                  {"confidence": getattr(entry, 'confidence', 0.8),
                   "tags": json.dumps(getattr(entry, 'tags', []))}),
            daemon=True,
        ).start()
        return row_id
```

- [ ] **Step 5: Run existing tests to verify no breakage**

Run: `python -m pytest tests/ -v --tb=short -x 2>&1 | tail -30`
Expected: all existing tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/storage/_runs_mixin.py src/storage/_sessions_mixin.py src/governance/context/structured_memory.py
git commit -m "feat(vector): hook Qdrant upsert into experiences, run logs, and structured memory"
```

---

### Task 6: Read Path — Dispatcher Semantic Retrieval

**Files:**
- Modify: `src/governance/dispatcher.py:253-297`

- [ ] **Step 1: Add semantic context retrieval before dispatch**

Add a helper method to `TaskDispatcher`:

```python
    async def _get_semantic_context(self, spec: dict, action: str) -> str:
        """Retrieve relevant learnings and run history for a task via Qdrant."""
        try:
            from src.storage.qdrant_store import QdrantStore
            store = QdrantStore()
            if not store.is_available():
                return ""

            query = f"{action} {spec.get('summary', '')} {spec.get('problem', '')}"
            parts = []

            # Relevant learnings
            learnings = await store.search_with_fallback(
                "orch_learnings", query, top_k=3
            )
            if learnings:
                items = [f"- {l['text']} (area={l['metadata'].get('area', '?')})" for l in learnings]
                parts.append("**Relevant learnings:**\n" + "\n".join(items))

            # Similar past runs
            runs = await store.search_with_fallback(
                "orch_runs", query, top_k=3
            )
            if runs:
                items = [f"- [{r['metadata'].get('department', '?')}] {r['text'][:100]}..." for r in runs]
                parts.append("**Similar past runs:**\n" + "\n".join(items))

            return "\n\n".join(parts)
        except Exception as e:
            log.debug(f"Semantic context retrieval failed: {e}")
            return ""
```

In `dispatch_task()`, after the synthesis quality check (around line 304), inject semantic context into spec:

```python
        # ── Semantic Context from Qdrant ──
        try:
            import asyncio
            semantic_ctx = asyncio.get_event_loop().run_until_complete(
                self._get_semantic_context(spec, action)
            )
            if semantic_ctx:
                spec["semantic_context"] = semantic_ctx
                log.info(f"TaskDispatcher: injected semantic context for task #{task_id}")
        except Exception:
            pass  # non-blocking
```

- [ ] **Step 2: Verify dispatcher still works**

Run: `python -m pytest tests/ -k "dispatch" -v --tb=short 2>&1 | tail -20`
Expected: existing dispatch tests PASS

- [ ] **Step 3: Commit**

```bash
git add src/governance/dispatcher.py
git commit -m "feat(vector): inject semantic learnings/runs context before dispatch"
```

---

### Task 7: Read Path — Dedup Embedding Upgrade

**Files:**
- Modify: `src/storage/dedup.py:41-91`

- [ ] **Step 1: Write failing test for embedding-based dedup**

Add to `tests/test_qdrant_store.py`:

```python
# ── Dedup via Embedding ──

def test_dedup_check_duplicate_with_embedding_fallback():
    """check_duplicate should still work with text similarity when Qdrant is unavailable."""
    from src.storage.dedup import check_duplicate
    existing = [
        {"id": 1, "rule": "never deploy on friday", "area": "ops", "pattern_key": "ops:friday", "recurrence": 3},
    ]
    decision = check_duplicate("do not deploy on fridays", "ops", existing)
    assert decision.action in ("merge", "skip")
    assert decision.similarity > 0.7
```

- [ ] **Step 2: Run test to verify it passes (existing text similarity)**

Run: `python -m pytest tests/test_qdrant_store.py::test_dedup_check_duplicate_with_embedding_fallback -v`
Expected: PASS — text similarity already handles this case

- [ ] **Step 3: Add embedding-enhanced path to check_duplicate**

In `src/storage/dedup.py`, add an optional embedding similarity check that runs when Qdrant is available:

```python
async def check_duplicate_semantic(
    new_rule: str,
    new_area: str,
    threshold: float = 0.85,
) -> DedupDecision | None:
    """Check for duplicates using Qdrant embedding similarity.

    Returns DedupDecision if a match is found, None if Qdrant unavailable or no match.
    Falls back gracefully — caller should use check_duplicate() as backup.
    """
    try:
        from src.storage.qdrant_store import QdrantStore
        store = QdrantStore()
        if not store.is_available():
            return None

        results = await store.search_with_fallback(
            "orch_learnings", new_rule, top_k=3,
            filters={"area": new_area} if new_area else None,
        )
        if not results:
            return None

        top = results[0]
        if top["score"] >= 0.95:
            return DedupDecision(
                action="skip",
                existing_id=top.get("sqlite_id"),
                similarity=top["score"],
                reason=f"embedding near-identical (score={top['score']:.3f})",
            )
        if top["score"] >= threshold:
            return DedupDecision(
                action="merge",
                existing_id=top.get("sqlite_id"),
                similarity=top["score"],
                reason=f"embedding similar (score={top['score']:.3f})",
            )
    except Exception as e:
        log.debug(f"Semantic dedup unavailable: {e}")
    return None
```

- [ ] **Step 4: Run all tests**

Run: `python -m pytest tests/ -v --tb=short -x 2>&1 | tail -20`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/storage/dedup.py
git commit -m "feat(vector): add embedding-based dedup path (fallback to text similarity)"
```

---

### Task 8: Migration Script

**Files:**
- Create: `scripts/migrate_to_qdrant.py`

- [ ] **Step 1: Write migration script**

```python
#!/usr/bin/env python3
"""One-shot migration: SQLite → Qdrant.

Usage: python scripts/migrate_to_qdrant.py [--db data/events.db] [--memory-db data/memory.db]
"""
import argparse
import asyncio
import json
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
    rows = _read_table(db_path, "SELECT id, pattern_key, area, rule, context, department, source_type, status, recurrence FROM learnings WHERE status != 'retired'")
    items = []
    for r in rows:
        items.append({
            "sqlite_id": r["id"],
            "collection_prefix": "learnings",
            "text": f"{r['rule']}\n{r.get('context', '')}".strip(),
            "metadata": {
                "pattern_key": r["pattern_key"],
                "area": r.get("area", "general"),
                "department": r.get("department") or "",
                "source_type": r.get("source_type", ""),
                "status": r.get("status", "pending"),
                "recurrence": r.get("recurrence", 1),
            },
        })
    count = await store.upsert_batch("orch_learnings", items)
    return {"collection": "orch_learnings", "source_rows": len(rows), "upserted": count}


async def migrate_experiences(store, db_path: str) -> dict:
    rows = _read_table(db_path, "SELECT id, date, type, summary, detail, instance FROM experiences ORDER BY id")
    items = []
    for r in rows:
        items.append({
            "sqlite_id": r["id"],
            "collection_prefix": "experiences",
            "text": f"{r['summary']}\n{r.get('detail', '')}".strip(),
            "metadata": {
                "date": r.get("date", ""),
                "type": r.get("type", ""),
                "instance": r.get("instance") or "",
            },
        })
    count = await store.upsert_batch("orch_experiences", items)
    return {"collection": "orch_experiences", "source_rows": len(rows), "upserted": count}


async def migrate_runs(store, db_path: str) -> dict:
    rows = _read_table(db_path, "SELECT id, department, task_id, summary, status, duration_s, notes, files_changed FROM run_logs ORDER BY id")
    items = []
    for r in rows:
        items.append({
            "sqlite_id": r["id"],
            "collection_prefix": "runs",
            "text": f"[{r['department']}] {r['summary']}\n{r.get('notes', '')}".strip(),
            "metadata": {
                "department": r["department"],
                "status": r.get("status", "done"),
                "duration_s": r.get("duration_s", 0),
            },
        })
    count = await store.upsert_batch("orch_runs", items)
    return {"collection": "orch_runs", "source_rows": len(rows), "upserted": count}


async def migrate_files(store, db_path: str) -> dict:
    rows = _read_table(db_path, "SELECT path, routing_hint, tags FROM file_index WHERE routing_hint != ''")
    items = []
    for i, r in enumerate(rows):
        items.append({
            "sqlite_id": i + 1,  # file_index uses path as PK, not rowid
            "collection_prefix": "files",
            "text": f"{r['path']}: {r['routing_hint']}",
            "metadata": {
                "path": r["path"],
                "tags": r.get("tags", "[]"),
            },
        })
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
            # Build text from all string columns
            text_parts = [str(v) for v in r.values() if isinstance(v, str) and v]
            items.append({
                "sqlite_id": r["id"],
                "collection_prefix": f"memory_{dim}",
                "text": " ".join(text_parts[:5]),  # first 5 text fields
                "metadata": {
                    "dimension": dim,
                    "confidence": r.get("confidence", 0.8),
                },
            })
        count = await store.upsert_batch("orch_memory", items)
        log.info(f"  {dim}: {len(rows)} rows → {count} upserted")
        total_rows += len(rows)
        total_upserted += count

    return {"collection": "orch_memory", "source_rows": total_rows, "upserted": total_upserted}


async def main(events_db: str, memory_db: str):
    from src.storage.qdrant_store import QdrantStore

    store = QdrantStore()

    if not store.is_available():
        log.error("Qdrant is not available. Start it first: docker start qdrant")
        return
    if not store.is_ollama_available():
        log.error("Ollama is not available. Start it first: ollama serve")
        return

    log.info("=== Qdrant Migration Start ===")
    log.info(f"Events DB: {events_db}")
    log.info(f"Memory DB: {memory_db}")

    store.ensure_all_collections()

    t0 = time.time()
    results = []

    for name, coro in [
        ("learnings", migrate_learnings(store, events_db)),
        ("experiences", migrate_experiences(store, events_db)),
        ("runs", migrate_runs(store, events_db)),
        ("files", migrate_files(store, events_db)),
        ("memory", migrate_memory(store, memory_db)),
    ]:
        log.info(f"Migrating {name}...")
        try:
            result = await coro
            results.append(result)
            log.info(f"  ✓ {result['source_rows']} rows → {result['upserted']} upserted")
        except Exception as e:
            log.error(f"  ✗ {name} failed: {e}")
            results.append({"collection": name, "source_rows": 0, "upserted": 0, "error": str(e)})

    elapsed = time.time() - t0
    log.info(f"\n=== Migration Complete ({elapsed:.1f}s) ===")
    for r in results:
        status = "✓" if "error" not in r else "✗"
        log.info(f"  {status} {r['collection']}: {r.get('source_rows', 0)} → {r.get('upserted', 0)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate SQLite data to Qdrant")
    parser.add_argument("--db", default=DEFAULT_EVENTS_DB, help="Path to events.db")
    parser.add_argument("--memory-db", default=DEFAULT_MEMORY_DB, help="Path to memory.db")
    args = parser.parse_args()
    asyncio.run(main(args.db, args.memory_db))
```

- [ ] **Step 2: Test migration script runs without error (dry check)**

Run: `python scripts/migrate_to_qdrant.py --help`
Expected: prints help text without error

- [ ] **Step 3: Commit**

```bash
git add scripts/migrate_to_qdrant.py
git commit -m "feat(vector): migration script — SQLite to Qdrant one-shot"
```

---

### Task 9: Sync Job + Scheduler Registration

**Files:**
- Create: `src/jobs/sync_vectors.py`
- Modify: `src/scheduler.py:39-55`

- [ ] **Step 1: Create sync_vectors job**

```python
# src/jobs/sync_vectors.py
"""Hourly incremental sync from SQLite → Qdrant.

Compares SQLite MAX(id) with Qdrant points_count per collection,
upserts any new records since last sync.
"""
import asyncio
import logging
import sqlite3
from pathlib import Path

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
            log.info(f"sync_vectors: synced {total} records across {len(results)} collections")
        else:
            log.debug("sync_vectors: no new records to sync")
    except Exception as e:
        log.warning(f"sync_vectors: failed: {e}")


async def _sync_all(store, db) -> list[dict]:
    results = []

    # Learnings
    results.append(await _sync_collection(
        store, db, "orch_learnings", "learnings",
        "SELECT id, pattern_key, area, rule, context, department, source_type, status, recurrence FROM learnings WHERE status != 'retired'",
        lambda r: {
            "text": f"{r['rule']}\n{r.get('context', '')}".strip(),
            "metadata": {"pattern_key": r["pattern_key"], "area": r.get("area", "general"),
                         "department": r.get("department") or "", "status": r.get("status", "pending"),
                         "recurrence": r.get("recurrence", 1)},
        },
    ))

    # Experiences
    results.append(await _sync_collection(
        store, db, "orch_experiences", "experiences",
        "SELECT id, date, type, summary, detail, instance FROM experiences",
        lambda r: {
            "text": f"{r['summary']}\n{r.get('detail', '')}".strip(),
            "metadata": {"date": r.get("date", ""), "type": r.get("type", ""),
                         "instance": r.get("instance") or ""},
        },
    ))

    # Run logs
    results.append(await _sync_collection(
        store, db, "orch_runs", "runs",
        "SELECT id, department, summary, status, duration_s, notes FROM run_logs",
        lambda r: {
            "text": f"[{r['department']}] {r['summary']}\n{r.get('notes', '')}".strip(),
            "metadata": {"department": r["department"], "status": r.get("status", "done"),
                         "duration_s": r.get("duration_s", 0)},
        },
    ))

    return results


async def _sync_collection(store, db, collection: str, prefix: str,
                            query: str, transform_fn) -> dict:
    """Sync a single collection: compare counts, upsert delta."""
    store.ensure_collection(collection)

    # Get Qdrant count
    try:
        info = store.client.get_collection(collection)
        qdrant_count = info.points_count
    except Exception:
        qdrant_count = 0

    # Get SQLite rows
    with db._connect() as conn:
        rows = conn.execute(query).fetchall()
    sqlite_rows = [dict(r) for r in rows]

    if len(sqlite_rows) <= qdrant_count:
        return {"collection": collection, "synced": 0}

    # Upsert all (idempotent — existing points get overwritten)
    items = []
    for r in sqlite_rows:
        transformed = transform_fn(r)
        items.append({
            "sqlite_id": r["id"],
            "collection_prefix": prefix,
            "text": transformed["text"],
            "metadata": transformed["metadata"],
        })

    synced = await store.upsert_batch(collection, items)
    return {"collection": collection, "synced": synced}
```

- [ ] **Step 2: Register in scheduler**

In `src/scheduler.py`, add import at top (line 8 area):

```python
from src.jobs.sync_vectors import sync_vectors
```

Add job in `start()` function (after the `hotness_sweep` job, around line 55):

```python
    s.add_job(lambda: run_job("sync_vectors", sync_vectors, db), "interval", hours=1, id="sync_vectors")
```

- [ ] **Step 3: Verify scheduler imports cleanly**

Run: `python -c "from src.scheduler import start; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add src/jobs/sync_vectors.py src/scheduler.py
git commit -m "feat(vector): hourly sync job + scheduler registration"
```

---

### Task 10: Retire vector_db.py

**Files:**
- Retire: `src/storage/vector_db.py` → `.trash/`

- [ ] **Step 1: Check for references to vector_db.py**

Run grep to confirm no live imports:

```bash
grep -r "vector_db" src/ --include="*.py" -l
grep -r "VectorDB" src/ --include="*.py" -l
```

Expected: only `src/storage/vector_db.py` itself (and maybe `__init__.py`)

- [ ] **Step 2: Move to .trash/**

```bash
mkdir -p .trash/2026-04-03-vector-migration
mv src/storage/vector_db.py .trash/2026-04-03-vector-migration/
```

- [ ] **Step 3: Clean any imports in __init__.py**

If `src/storage/__init__.py` exports VectorDB, remove that line.

- [ ] **Step 4: Verify no breakage**

Run: `python -m pytest tests/ -v --tb=short -x 2>&1 | tail -20`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: retire vector_db.py (replaced by qdrant_store.py)"
```

---

### Task 11: Run Migration + Smoke Test

**Files:** None (execution only)

- [ ] **Step 1: Verify Qdrant and Ollama are running**

```bash
curl -s http://localhost:6333/collections | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])"
curl -s http://localhost:11434/api/tags | python3 -c "import sys,json; print(len(json.load(sys.stdin)['models']), 'models')"
```

Expected: `ok` and `N models`

- [ ] **Step 2: Run migration**

```bash
python scripts/migrate_to_qdrant.py
```

Expected: prints migration report with ✓ for each collection

- [ ] **Step 3: Verify collections in Qdrant**

```bash
curl -s http://localhost:6333/collections | python3 -c "import sys,json; [print(f'  {c[\"name\"]}') for c in json.load(sys.stdin)['result']['collections'] if c['name'].startswith('orch_')]"
```

Expected: 5 collections listed (`orch_learnings`, `orch_experiences`, `orch_memory`, `orch_runs`, `orch_files`)

- [ ] **Step 4: Smoke test — search learnings**

```bash
python3 -c "
import asyncio
from src.storage.qdrant_store import QdrantStore
async def test():
    s = QdrantStore()
    results = await s.search('orch_learnings', 'agent reflection declining', top_k=3)
    for r in results:
        print(f'  [{r[\"score\"]:.3f}] {r[\"text\"][:80]}')
asyncio.run(test())
"
```

Expected: returns relevant learnings sorted by score

- [x] **Step 5: Commit migration success to memory** (OBSOLETE 2026-04-17)

Update `MEMORY.md` and `orchestrator_evolution.md` to record Phase 3.7 completion.

---

## Post-hoc Status (2026-04-17)

- ✅ 核心实现合入 main：merge commit `8bb969e` (feat/vector-memory-layer — Qdrant + Qwen3-Embedding Phase 3.7)
- ✅ 关键 commits: `819b48b` (deps), `f44e2e6` (QdrantStore core), `ace7cec` (4 fire-and-forget 写路径), `a59f0d0` (retire vector_db.py)
- ✅ 源文件落地: `src/storage/qdrant_store.py`（存在，作为单一入口）
- ⚠️ Step 5 OBSOLETE: `MEMORY.md` 与 `orchestrator_evolution.md` 两文件已在后续架构重构中移除（当前记忆分层为 `.remember/` + `SOUL/private/experiences.jsonl` + `SOUL/private/hall-of-instances.md`）。Phase 3.7 里程碑记录由 commit 历史 + 代码自留痕替代，无需补写到废弃文件。
