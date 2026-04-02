"""
Qdrant vector store — Ollama embedding + Qdrant storage/search.

Uses Ollama /api/embed for embeddings and qdrant-client for vector ops.
Auto-detects Docker vs host environment for URL defaults.
"""

import logging
import os
import uuid
from pathlib import Path

import httpx
from qdrant_client import QdrantClient, models

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment detection
# ---------------------------------------------------------------------------

_IN_DOCKER = Path("/.dockerenv").exists()

_DEFAULT_HOST = "host.docker.internal" if _IN_DOCKER else "localhost"

QDRANT_URL = os.environ.get("QDRANT_URL", f"http://{_DEFAULT_HOST}:6333")
OLLAMA_URL = os.environ.get("OLLAMA_URL", f"http://{_DEFAULT_HOST}:11434")
OLLAMA_EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "qwen3-embedding")
QDRANT_EMBED_DIM = int(os.environ.get("QDRANT_EMBED_DIM", "4096"))

COLLECTIONS = [
    "orch_learnings",
    "orch_experiences",
    "orch_memory",
    "orch_runs",
    "orch_files",
]

EMBED_BATCH_SIZE = 32


# ---------------------------------------------------------------------------
# Deterministic point ID
# ---------------------------------------------------------------------------

def make_point_id(collection: str, sqlite_id: int) -> str:
    """Deterministic UUID from collection name + sqlite row ID."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"orch.{collection}.{sqlite_id}"))


# ---------------------------------------------------------------------------
# QdrantStore
# ---------------------------------------------------------------------------

class QdrantStore:
    """High-level wrapper around Qdrant + Ollama embeddings."""

    def __init__(
        self,
        qdrant_url: str = QDRANT_URL,
        ollama_url: str = OLLAMA_URL,
        model: str = OLLAMA_EMBED_MODEL,
        dim: int = QDRANT_EMBED_DIM,
    ):
        self.qdrant_url = qdrant_url
        self.ollama_url = ollama_url
        self.model = model
        self.dim = dim
        self.client = QdrantClient(url=qdrant_url)

    # -- Collection management -----------------------------------------------

    def ensure_collection(self, name: str) -> None:
        """Idempotent: create collection if it doesn't exist."""
        if self.client.collection_exists(name):
            return
        self.client.create_collection(
            collection_name=name,
            vectors_config=models.VectorParams(
                size=self.dim,
                distance=models.Distance.COSINE,
            ),
        )
        logger.info("Created Qdrant collection: %s (dim=%d)", name, self.dim)

    def ensure_all_collections(self) -> None:
        """Create all standard collections."""
        for name in COLLECTIONS:
            self.ensure_collection(name)

    # -- Embedding via Ollama ------------------------------------------------

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Batch embed via Ollama /api/embed."""
        async with httpx.AsyncClient(timeout=60) as http:
            resp = await http.post(
                f"{self.ollama_url}/api/embed",
                json={"model": self.model, "input": texts},
            )
            resp.raise_for_status()
            return resp.json()["embeddings"]

    async def embed_single(self, text: str) -> list[float]:
        """Convenience: embed a single text."""
        vectors = await self.embed([text])
        return vectors[0]

    # -- Write ---------------------------------------------------------------

    async def upsert(
        self,
        collection: str,
        collection_prefix: str,
        sqlite_id: int,
        text: str,
        metadata: dict,
    ) -> None:
        """Embed and upsert a single document."""
        vector = await self.embed_single(text)
        point_id = make_point_id(collection_prefix, sqlite_id)
        payload = {**metadata, "text": text, "sqlite_id": sqlite_id}
        self.client.upsert(
            collection_name=collection,
            points=[models.PointStruct(id=point_id, vector=vector, payload=payload)],
        )

    async def upsert_batch(
        self,
        collection: str,
        items: list[dict],
    ) -> int:
        """Batch upsert. Items: [{sqlite_id, collection_prefix, text, metadata}].

        Processes in EMBED_BATCH_SIZE chunks. Skips failed chunks with warning.
        Returns total count upserted.
        """
        total = 0
        for i in range(0, len(items), EMBED_BATCH_SIZE):
            chunk = items[i : i + EMBED_BATCH_SIZE]
            try:
                texts = [it["text"] for it in chunk]
                vectors = await self.embed(texts)
                points = []
                for item, vector in zip(chunk, vectors):
                    point_id = make_point_id(item["collection_prefix"], item["sqlite_id"])
                    payload = {**item.get("metadata", {}), "text": item["text"], "sqlite_id": item["sqlite_id"]}
                    points.append(models.PointStruct(id=point_id, vector=vector, payload=payload))
                self.client.upsert(collection_name=collection, points=points)
                total += len(points)
            except Exception:
                logger.warning(
                    "Failed to upsert batch chunk %d-%d, skipping",
                    i,
                    i + len(chunk),
                    exc_info=True,
                )
        return total

    # -- Search --------------------------------------------------------------

    async def search(
        self,
        collection: str,
        query: str,
        top_k: int = 5,
        filters: dict | None = None,
    ) -> list[dict]:
        """Embed query and search. Returns [{id, text, score, metadata, sqlite_id}]."""
        query_vector = await self.embed_single(query)

        query_filter = None
        if filters:
            conditions = [
                models.FieldCondition(key=k, match=models.MatchValue(value=v))
                for k, v in filters.items()
            ]
            query_filter = models.Filter(must=conditions)

        results = self.client.query_points(
            collection_name=collection,
            query=query_vector,
            query_filter=query_filter,
            limit=top_k,
        )

        out = []
        for point in results.points:
            payload = dict(point.payload) if point.payload else {}
            text = payload.pop("text", "")
            sqlite_id = payload.pop("sqlite_id", None)
            out.append({
                "id": point.id,
                "text": text,
                "score": point.score,
                "metadata": payload,
                "sqlite_id": sqlite_id,
            })
        return out

    async def search_with_fallback(
        self,
        collection: str,
        query: str,
        top_k: int = 5,
        filters: dict | None = None,
    ) -> list[dict]:
        """Like search(), but returns [] on any error instead of raising."""
        try:
            return await self.search(collection, query, top_k=top_k, filters=filters)
        except Exception:
            logger.warning(
                "search_with_fallback failed for %s, returning []",
                collection,
                exc_info=True,
            )
            return []

    # -- Delete --------------------------------------------------------------

    def delete_point(self, collection: str, collection_prefix: str, sqlite_id: int) -> None:
        """Delete a single point by its deterministic ID."""
        point_id = make_point_id(collection_prefix, sqlite_id)
        self.client.delete(
            collection_name=collection,
            points_selector=models.PointIdsList(points=[point_id]),
        )

    # -- Health --------------------------------------------------------------

    def is_available(self) -> bool:
        """Check Qdrant connectivity."""
        try:
            self.client.get_collections()
            return True
        except Exception:
            return False

    def is_ollama_available(self) -> bool:
        """Sync check Ollama /api/tags."""
        try:
            resp = httpx.get(f"{self.ollama_url}/api/tags", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False
