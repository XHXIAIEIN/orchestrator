"""Resilient Retry — exception chain traversal + multi-layer matching.

Stolen from ChatDev 2.0's entity/configs/node/agent.py (AgentRetryConfig).

Walks __cause__ + __context__ chain to find retryable errors buried
inside wrapper exceptions. Three-layer matching:
  1. Blacklist type names → never retry
  2. Whitelist type names → retry
  3. HTTP status codes → retry
  4. Error message substrings → retry
"""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

log = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass
class RetryPolicy:
    enabled: bool = True
    max_attempts: int = 3
    min_wait_s: float = 1.0
    max_wait_s: float = 10.0
    retry_on_types: list[str] = field(default_factory=list)
    no_retry_types: list[str] = field(default_factory=list)
    retry_on_status_codes: list[int] = field(default_factory=list)
    retry_on_substrings: list[str] = field(default_factory=list)


def _iter_exception_chain(exc: BaseException):
    seen = set()
    current = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _exception_type_names(exc: BaseException) -> set[str]:
    names = set()
    for cls in type(exc).__mro__:
        names.add(cls.__name__)
        if hasattr(cls, "__module__"):
            names.add(f"{cls.__module__}.{cls.__name__}")
    return names


def _extract_status_code(exc: BaseException) -> int | None:
    for attr in ("status_code", "http_status", "code", "status"):
        val = getattr(exc, attr, None)
        if isinstance(val, int):
            return val
    return None


def should_retry(exc: BaseException, policy: RetryPolicy) -> bool:
    if not policy.enabled:
        return False
    chain_info = []
    for error in _iter_exception_chain(exc):
        chain_info.append((error, _exception_type_names(error),
                           _extract_status_code(error), str(error).lower()))
    if policy.no_retry_types:
        no_retry_lower = {t.lower() for t in policy.no_retry_types}
        for _, names, _, _ in chain_info:
            if any(n.lower() in no_retry_lower for n in names):
                return False
    if policy.retry_on_types:
        types_lower = {t.lower() for t in policy.retry_on_types}
        for _, names, _, _ in chain_info:
            if any(n.lower() in types_lower for n in names):
                return True
    if policy.retry_on_status_codes:
        for _, _, status, _ in chain_info:
            if status is not None and status in policy.retry_on_status_codes:
                return True
    if policy.retry_on_substrings:
        subs_lower = [s.lower() for s in policy.retry_on_substrings]
        for _, _, _, message in chain_info:
            if any(sub in message for sub in subs_lower):
                return True
    return False


def resilient_call(fn: Callable[[], T], policy: RetryPolicy) -> T:
    if not policy.enabled:
        return fn()
    last_exc = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return fn()
        except BaseException as exc:
            last_exc = exc
            if attempt >= policy.max_attempts:
                raise
            if not should_retry(exc, policy):
                raise
            base = policy.min_wait_s * (2 ** (attempt - 1))
            wait = min(base, policy.max_wait_s)
            wait *= 0.5 + random.random()
            log.info(f"resilient_retry: attempt {attempt}/{policy.max_attempts} "
                     f"failed ({type(exc).__name__}), retrying in {wait:.1f}s")
            time.sleep(wait)
    raise last_exc
