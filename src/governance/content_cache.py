"""R68 LangGraph: Content-Addressed Agent Cache — xxh3 hash keying.

Problem: agent_cache.py uses random task_id as cache key.
Same prompt + same tools called twice → cache miss → wasted LLM call.

Solution: Hash the prompt content + tool call args to produce a deterministic
cache key. Same input → same key → cache hit.

LangGraph uses xxh3_128 (xxhash). We use xxhash if available, falling
back to hashlib.blake2b (fast, standard library, 128-bit).

Integration: Called by executor.py before dispatching an agent task.
The cache key replaces the random task_id for cache lookup.

Source: LangGraph CachePolicy + xxh3_128_hexdigest (R68 deep steal)
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

log = logging.getLogger(__name__)

# Try xxhash for speed (LangGraph's choice); fallback to blake2b
try:
    from xxhash import xxh3_128_hexdigest as _fast_hash

    def _hash_bytes(data: bytes) -> str:
        return _fast_hash(data)

    _HASH_ALGO = "xxh3_128"
except ImportError:
    def _hash_bytes(data: bytes) -> str:
        return hashlib.blake2b(data, digest_size=16).hexdigest()

    _HASH_ALGO = "blake2b_128"
    log.debug("content_cache: xxhash not available, using blake2b fallback")


def content_cache_key(
    prompt: str,
    tools: list[dict] | None = None,
    model: str = "",
    extra: dict[str, Any] | None = None,
) -> str:
    """Generate a deterministic cache key from prompt content.

    The key is a hex digest of the prompt + sorted tool definitions + model.
    Same inputs → same key → cache hit.

    Args:
        prompt: the full prompt text
        tools: list of tool call dicts (name + args)
        model: model identifier (different models = different keys)
        extra: any additional context that affects the output

    Returns:
        Hex string cache key (32 chars for xxh3_128, 32 for blake2b_128)
    """
    parts = [prompt]

    if model:
        parts.append(f"\x00model={model}")

    if tools:
        # Normalize: sort by name, then sort args keys
        normalized_tools = []
        for t in tools:
            name = t.get("name", t.get("tool", ""))
            args = t.get("args", t.get("input", {}))
            if isinstance(args, dict):
                stable_args = json.dumps(
                    {k: str(v)[:500] for k, v in sorted(args.items())},
                    sort_keys=True,
                    ensure_ascii=False,
                )
            else:
                stable_args = str(args)[:500]
            normalized_tools.append(f"{name}:{stable_args}")
        normalized_tools.sort()
        parts.append("\x00tools=" + "\x01".join(normalized_tools))

    if extra:
        parts.append(
            "\x00extra=" + json.dumps(extra, sort_keys=True, ensure_ascii=False)
        )

    payload = "\x02".join(parts).encode("utf-8")
    return _hash_bytes(payload)


def get_hash_algorithm() -> str:
    """Return the name of the hash algorithm in use."""
    return _HASH_ALGO
