"""Tests for QdrantStore — uses in-memory Qdrant, mocks Ollama."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from qdrant_client import QdrantClient, models

from src.storage.qdrant_store import COLLECTIONS, QdrantStore, make_point_id

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DIM = 8  # small dimension for fast tests


def _fake_vector(seed: float = 0.1) -> list[float]:
    """Generate a deterministic fake vector."""
    return [seed + i * 0.01 for i in range(DIM)]


def _make_store() -> QdrantStore:
    """Create a QdrantStore with in-memory Qdrant and small dim."""
    store = QdrantStore.__new__(QdrantStore)
    store.client = QdrantClient(":memory:")
    store.qdrant_url = "http://localhost:6333"
    store.ollama_url = "http://localhost:11434"
    store.model = "test-model"
    store.dim = DIM
    return store


async def _fake_embed(texts: list[str]) -> list[list[float]]:
    """Fake embed: return a unique-ish vector per text."""
    return [_fake_vector(seed=hash(t) % 100 / 100.0) for t in texts]


async def _fake_embed_single(text: str) -> list[float]:
    vecs = await _fake_embed([text])
    return vecs[0]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_make_point_id_deterministic():
    """Same inputs produce the same ID; different inputs produce different IDs."""
    id1 = make_point_id("learnings", 42)
    id2 = make_point_id("learnings", 42)
    id3 = make_point_id("learnings", 43)
    id4 = make_point_id("experiences", 42)

    assert id1 == id2
    # valid UUID
    uuid.UUID(id1)
    assert id1 != id3
    assert id1 != id4


def test_ensure_collection_creates():
    """Creates a collection with correct dim and cosine distance."""
    store = _make_store()
    store.ensure_collection("test_col")

    assert store.client.collection_exists("test_col")
    info = store.client.get_collection("test_col")
    assert info.config.params.vectors.size == DIM
    assert info.config.params.vectors.distance == models.Distance.COSINE


def test_ensure_collection_idempotent():
    """Calling ensure_collection twice doesn't raise."""
    store = _make_store()
    store.ensure_collection("test_col")
    store.ensure_collection("test_col")  # should not raise
    assert store.client.collection_exists("test_col")


@pytest.mark.asyncio
async def test_embed_calls_ollama():
    """Mock httpx to verify Ollama request format."""
    store = _make_store()

    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {
        "embeddings": [[0.1] * DIM, [0.2] * DIM]
    }

    mock_client_instance = AsyncMock()
    mock_client_instance.post = AsyncMock(return_value=fake_response)
    mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
    mock_client_instance.__aexit__ = AsyncMock(return_value=False)

    with patch("src.storage.qdrant_store.httpx.AsyncClient", return_value=mock_client_instance):
        result = await store.embed(["hello", "world"])

    assert len(result) == 2
    assert result[0] == [0.1] * DIM

    # Verify the POST request
    call_args = mock_client_instance.post.call_args
    assert "/api/embed" in call_args[0][0]
    body = call_args[1]["json"]
    assert body["model"] == "test-model"
    assert body["input"] == ["hello", "world"]


@pytest.mark.asyncio
async def test_embed_batch():
    """Multiple texts return multiple vectors."""
    store = _make_store()

    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {
        "embeddings": [[0.1] * DIM, [0.2] * DIM, [0.3] * DIM]
    }

    mock_client_instance = AsyncMock()
    mock_client_instance.post = AsyncMock(return_value=fake_response)
    mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
    mock_client_instance.__aexit__ = AsyncMock(return_value=False)

    with patch("src.storage.qdrant_store.httpx.AsyncClient", return_value=mock_client_instance):
        result = await store.embed(["a", "b", "c"])

    assert len(result) == 3
    assert result[2] == [0.3] * DIM


@pytest.mark.asyncio
async def test_upsert_and_search():
    """Upsert 2 docs then search — results come back with scores."""
    store = _make_store()
    store.ensure_collection("test_col")

    # Monkey-patch embed methods to avoid Ollama
    store.embed = _fake_embed
    store.embed_single = _fake_embed_single

    await store.upsert(
        collection="test_col",
        collection_prefix="test_col",
        sqlite_id=1,
        text="Python is great for AI",
        metadata={"source": "test"},
    )
    await store.upsert(
        collection="test_col",
        collection_prefix="test_col",
        sqlite_id=2,
        text="Rust is great for systems",
        metadata={"source": "test"},
    )

    results = await store.search("test_col", query="Python AI", top_k=5)
    assert len(results) == 2
    # Each result should have the expected keys
    for r in results:
        assert "id" in r
        assert "text" in r
        assert "score" in r
        assert "metadata" in r
        assert "sqlite_id" in r
        assert r["score"] > 0


@pytest.mark.asyncio
async def test_upsert_batch():
    """Batch upsert 3 items, verify points_count."""
    store = _make_store()
    store.ensure_collection("test_col")
    store.embed = _fake_embed

    items = [
        {"sqlite_id": 10, "collection_prefix": "test_col", "text": "first doc", "metadata": {"k": "v1"}},
        {"sqlite_id": 11, "collection_prefix": "test_col", "text": "second doc", "metadata": {"k": "v2"}},
        {"sqlite_id": 12, "collection_prefix": "test_col", "text": "third doc", "metadata": {"k": "v3"}},
    ]
    count = await store.upsert_batch("test_col", items)
    assert count == 3

    info = store.client.get_collection("test_col")
    assert info.points_count == 3


@pytest.mark.asyncio
async def test_search_with_fallback_when_available():
    """search_with_fallback works normally when everything's fine."""
    store = _make_store()
    store.ensure_collection("test_col")
    store.embed = _fake_embed
    store.embed_single = _fake_embed_single

    await store.upsert(
        collection="test_col",
        collection_prefix="test_col",
        sqlite_id=1,
        text="test content",
        metadata={},
    )

    results = await store.search_with_fallback("test_col", query="test", top_k=5)
    assert len(results) == 1
    assert results[0]["text"] == "test content"


@pytest.mark.asyncio
async def test_search_with_fallback_when_unavailable():
    """search_with_fallback returns [] on error instead of raising."""
    store = _make_store()
    # Don't create collection — search will fail
    store.embed_single = _fake_embed_single

    results = await store.search_with_fallback("nonexistent_col", query="test", top_k=5)
    assert results == []


@pytest.mark.asyncio
async def test_delete_point():
    """Upsert a point then delete it — verify it's gone."""
    store = _make_store()
    store.ensure_collection("test_col")
    store.embed = _fake_embed
    store.embed_single = _fake_embed_single

    await store.upsert(
        collection="test_col",
        collection_prefix="test_col",
        sqlite_id=99,
        text="deletable content",
        metadata={},
    )

    # Verify it exists
    results = await store.search("test_col", query="deletable", top_k=5)
    assert len(results) == 1

    # Delete
    store.delete_point("test_col", "test_col", 99)

    # Verify it's gone
    results = await store.search("test_col", query="deletable", top_k=5)
    assert len(results) == 0
