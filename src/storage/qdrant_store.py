"""
Qdrant vector store — Ollama embedding + Qdrant storage/search.

Uses Ollama /api/embed for embeddings and qdrant-client for vector ops.
Auto-detects Docker vs host environment for URL defaults.

Hybrid search (R44 MemPalace steal): keyword overlap re-ranking on top of
semantic results. fused_dist = dist * (1 - weight * overlap).
"""

import logging
import os
import re
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
# Palace Hierarchy Metadata (R44 MemPalace P0#2)
# ---------------------------------------------------------------------------
# Three-level metadata filter: domain > category > topic
# Equivalent to MemPalace's Wing > Hall > Room.
# Applied during upsert to tag documents, and during search to narrow scope.

# Standard domain taxonomy for Orchestrator
DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "system": ["docker", "container", "gpu", "nvidia", "qdrant", "ollama", "deploy", "infra"],
    "code": ["src/", "function", "class", "import", "module", "refactor", "bug", "fix"],
    "memory": ["memory", "remember", "experience", "learning", "pattern", "feedback"],
    "governance": ["governor", "task", "dispatch", "approval", "scrutiny", "department"],
    "collection": ["collector", "scrape", "fetch", "crawl", "schedule", "cron"],
    "channel": ["telegram", "wechat", "bot", "message", "chat", "notification"],
    "soul": ["identity", "personality", "voice", "calibration", "boot", "relationship"],
}


def classify_metadata(text: str, source: str = "") -> dict[str, str]:
    """Auto-classify text into domain/category/topic hierarchy.

    Returns {"domain": str, "category": str, "topic": str}.
    Uses keyword matching with source path hints.
    """
    text_lower = text.lower()
    source_lower = source.lower()
    combined = f"{source_lower} {text_lower}"

    # Domain: highest keyword match score
    best_domain = "general"
    best_score = 0
    for domain, keywords in DOMAIN_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in combined)
        if score > best_score:
            best_score = score
            best_domain = domain

    # Category: derived from source path or content type
    category = "misc"
    if "/" in source or "\\" in source:
        parts = re.split(r"[/\\]", source)
        # Use the deepest meaningful directory as category
        for part in reversed(parts):
            if part and part not in ("src", ".", "..", "data", "SOUL"):
                category = part.lower()
                break

    # Topic: first significant noun phrase or filename stem
    if source:
        topic = Path(source).stem.lower()
    else:
        # Extract first meaningful phrase from text
        words = re.findall(r"[a-zA-Z0-9_]+", text_lower)[:5]
        topic = "_".join(words) if words else "unknown"

    return {"domain": best_domain, "category": category, "topic": topic}


# ---------------------------------------------------------------------------
# Hybrid search helpers (R44 MemPalace P0#5)
# ---------------------------------------------------------------------------

# Minimal stopwords — covers EN + CN particles. Not exhaustive by design:
# over-filtering hurts more than under-filtering for keyword overlap.
_STOPWORDS = frozenset(
    "a an the is are was were be been being have has had do does did "
    "will would shall should may might can could of in to for on with "
    "at by from as into through during before after above below between "
    "and or but not no nor so yet both either neither each every all "
    "any few more most other some such than too very it its this that "
    "these those i me my we our you your he him his she her they them "
    "their what which who whom whose when where how why "
    "的 了 在 是 我 有 和 就 不 人 都 一 一个 上 也 很 到 说 要 去 你 会 着 "
    "没有 看 好 自己 这".split()
)


def _extract_keywords(text: str) -> set[str]:
    """Extract meaningful keywords from text, lowercased, stopwords removed."""
    tokens = re.findall(r"[a-zA-Z0-9_\-\.]+|[\u4e00-\u9fff]+", text.lower())
    return {t for t in tokens if t not in _STOPWORDS and len(t) > 1}


def _keyword_overlap(query_kw: set[str], doc_text: str) -> float:
    """Fraction of query keywords found in document text (0.0 - 1.0)."""
    if not query_kw:
        return 0.0
    doc_lower = doc_text.lower()
    hits = sum(1 for kw in query_kw if kw in doc_lower)
    return hits / len(query_kw)


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
        auto_classify: bool = True,
        use_content_hash: bool = True,
    ) -> str:
        """Embed and upsert a single document.

        When auto_classify=True (default), adds domain/category/topic metadata
        from Palace Hierarchy classification (R44 P0#2) if not already present.

        When use_content_hash=True (default, R45c), checks content hash first:
            - "unchanged": skip entirely (saves embedding + Qdrant write)
            - "metadata_only": update Qdrant payload without re-embedding
            - "changed"/"new": full embed + upsert

        Returns: "unchanged", "metadata_only", "upserted"
        """
        if auto_classify:
            source = metadata.get("source", metadata.get("source_file", ""))
            hierarchy = classify_metadata(text, source)
            for key in ("domain", "category", "topic"):
                if key not in metadata:
                    metadata[key] = hierarchy[key]

        point_id = make_point_id(collection_prefix, sqlite_id)
        point_key = f"{collection_prefix}.{sqlite_id}"

        # R45c: Content hash check
        if use_content_hash:
            try:
                from src.storage.content_hash import ContentHashCache
                cache = ContentHashCache()
                source_hint = metadata.get("source", metadata.get("source_file", ""))
                status = cache.check(collection, point_key, text, source_hint, metadata)

                if status == "unchanged":
                    return "unchanged"

                if status == "metadata_only":
                    # Update payload without re-embedding
                    payload = {**metadata, "text": text, "sqlite_id": sqlite_id}
                    self.client.set_payload(
                        collection_name=collection,
                        payload=payload,
                        points=[point_id],
                    )
                    cache.update(collection, point_key, text, source_hint, metadata)
                    return "metadata_only"
            except Exception:
                logger.debug("Content hash cache unavailable, proceeding with full upsert")

        vector = await self.embed_single(text)
        payload = {**metadata, "text": text, "sqlite_id": sqlite_id}
        self.client.upsert(
            collection_name=collection,
            points=[models.PointStruct(id=point_id, vector=vector, payload=payload)],
        )

        # R45c: Record hash after successful upsert
        if use_content_hash:
            try:
                from src.storage.content_hash import ContentHashCache
                cache = ContentHashCache()
                source_hint = metadata.get("source", metadata.get("source_file", ""))
                cache.update(collection, point_key, text, source_hint, metadata)
            except Exception:
                pass  # Non-critical

        return "upserted"

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
        hybrid: bool = True,
        hybrid_weight: float = 0.30,
    ) -> list[dict]:
        """Embed query and search with optional hybrid keyword re-ranking.

        When hybrid=True (default), over-fetches semantic results then re-ranks
        using keyword overlap: fused_dist = dist * (1 - weight * overlap).
        Stolen from MemPalace R44 P0#5 (hybrid v1 formula).

        Returns [{id, text, score, metadata, sqlite_id}].
        """
        # R67 MemPalace: sanitize query to prevent system prompt pollution
        from src.storage.query_sanitizer import sanitize_query
        result = sanitize_query(query)
        if result["was_sanitized"]:
            logger.debug("query sanitized: method=%s len=%d→%d",
                         result["method"], len(query), len(result["clean_query"]))
        query = result["clean_query"] or query

        query_vector = await self.embed_single(query)

        query_filter = None
        if filters:
            conditions = [
                models.FieldCondition(key=k, match=models.MatchValue(value=v))
                for k, v in filters.items()
            ]
            query_filter = models.Filter(must=conditions)

        # Over-fetch for hybrid re-ranking (min 50, or 10x top_k)
        fetch_k = max(50, top_k * 10) if hybrid else top_k

        results = self.client.query_points(
            collection_name=collection,
            query=query_vector,
            query_filter=query_filter,
            limit=fetch_k,
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

        # Hybrid keyword re-ranking
        if hybrid and out:
            query_kw = _extract_keywords(query)
            if query_kw:
                for item in out:
                    overlap = _keyword_overlap(query_kw, item["text"])
                    # score from Qdrant is similarity (higher=better for cosine).
                    # Boost score by keyword overlap: fused = score * (1 + weight * overlap)
                    item["score"] = item["score"] * (1.0 + hybrid_weight * overlap)
                out.sort(key=lambda x: x["score"], reverse=True)

        return out[:top_k]

    async def search_scoped(
        self,
        collection: str,
        query: str,
        top_k: int = 5,
        domain: str | None = None,
        category: str | None = None,
        topic: str | None = None,
        **kwargs,
    ) -> list[dict]:
        """Search with Palace Hierarchy metadata pre-filter (R44 P0#2).

        Narrows search scope before semantic matching: domain > category > topic.
        This gives ~34% R@10 improvement over unfiltered search (MemPalace benchmark).
        """
        filters = {}
        if domain:
            filters["domain"] = domain
        if category:
            filters["category"] = category
        if topic:
            filters["topic"] = topic
        return await self.search(
            collection, query, top_k=top_k, filters=filters or None, **kwargs,
        )

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
