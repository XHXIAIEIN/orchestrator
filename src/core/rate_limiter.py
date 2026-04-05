# src/core/rate_limiter.py
"""
Token Bucket Rate Limiter — 双维度限流器 (R39 PraisonAI steal).

两个桶:
  - requests_per_minute: 请求频率限制
  - tokens_per_minute: token 吞吐限制

支持:
  - burst: 允许短时突发 (桶容量 = 每分钟限额)
  - async acquire: 异步等待桶补充
  - try_acquire: 非阻塞尝试
  - 429 backoff: 收到 429 时暂停指定时间
  - 可注入 time/sleep (测试友好)

灵感: PraisonAI llm/rate_limiter.py
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class TokenBucket:
    """经典令牌桶。

    capacity: 桶容量 (允许的突发量)
    refill_rate: 每秒补充的 token 数
    """
    capacity: float
    refill_rate: float
    _tokens: float = field(init=False)
    _last_refill: float = field(init=False)
    _time_func: object = field(default=time.time, repr=False)

    def __post_init__(self):
        self._tokens = self.capacity
        self._last_refill = self._time_func()

    def _refill(self) -> None:
        """根据流逝时间补充 token。"""
        now = self._time_func()
        elapsed = now - self._last_refill
        if elapsed > 0:
            self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_rate)
            self._last_refill = now

    def try_acquire(self, amount: float = 1.0) -> bool:
        """非阻塞尝试获取。成功返回 True。"""
        self._refill()
        if self._tokens >= amount:
            self._tokens -= amount
            return True
        return False

    def wait_time(self, amount: float = 1.0) -> float:
        """计算获取 amount 个 token 需要等待的秒数。"""
        self._refill()
        if self._tokens >= amount:
            return 0.0
        deficit = amount - self._tokens
        return deficit / self.refill_rate if self.refill_rate > 0 else float("inf")

    def drain(self, amount: float) -> None:
        """强制消耗 (用于 429 backoff 后重置)。"""
        self._refill()
        self._tokens = max(0, self._tokens - amount)

    @property
    def available(self) -> float:
        self._refill()
        return self._tokens


@dataclass
class RateLimiter:
    """双维度限流器: 请求频率 + token 吞吐。

    Usage (sync):
        limiter = RateLimiter(requests_per_minute=60, tokens_per_minute=100_000)
        limiter.acquire(tokens=500)  # 阻塞直到有容量
        # ... call LLM ...

    Usage (async):
        await limiter.acquire_async(tokens=500)

    429 backoff:
        limiter.backoff(seconds=30)  # 收到 429 时调用
    """
    requests_per_minute: float = 60.0
    tokens_per_minute: float = 100_000.0
    _time_func: object = field(default=time.time, repr=False)
    _sleep_func: object = field(default=time.sleep, repr=False)
    _request_bucket: TokenBucket = field(init=False, repr=False)
    _token_bucket: TokenBucket = field(init=False, repr=False)
    _backoff_until: float = field(default=0.0, init=False, repr=False)

    def __post_init__(self):
        self._request_bucket = TokenBucket(
            capacity=self.requests_per_minute,
            refill_rate=self.requests_per_minute / 60.0,
            _time_func=self._time_func,
        )
        self._token_bucket = TokenBucket(
            capacity=self.tokens_per_minute,
            refill_rate=self.tokens_per_minute / 60.0,
            _time_func=self._time_func,
        )

    def try_acquire(self, tokens: float = 1.0) -> bool:
        """非阻塞尝试: 两个桶都有容量才通过。"""
        now = self._time_func()
        if now < self._backoff_until:
            return False
        if not self._request_bucket.try_acquire(1.0):
            return False
        if not self._token_bucket.try_acquire(tokens):
            # 回退 request bucket
            self._request_bucket._tokens += 1.0
            return False
        return True

    def acquire(self, tokens: float = 1.0, max_wait: float = 60.0) -> bool:
        """阻塞获取。超过 max_wait 返回 False。"""
        deadline = self._time_func() + max_wait

        while True:
            if self.try_acquire(tokens):
                return True

            now = self._time_func()
            if now >= deadline:
                log.warning(f"RateLimiter: acquire timed out after {max_wait}s")
                return False

            # 计算需要等待的时间
            backoff_wait = max(0, self._backoff_until - now)
            req_wait = self._request_bucket.wait_time(1.0)
            tok_wait = self._token_bucket.wait_time(tokens)
            wait = max(backoff_wait, req_wait, tok_wait)
            wait = min(wait, deadline - now, 5.0)  # 最多等 5s 一轮

            if wait > 0:
                self._sleep_func(wait)

    async def acquire_async(self, tokens: float = 1.0, max_wait: float = 60.0) -> bool:
        """异步阻塞获取。"""
        deadline = self._time_func() + max_wait

        while True:
            if self.try_acquire(tokens):
                return True

            now = self._time_func()
            if now >= deadline:
                log.warning(f"RateLimiter: async acquire timed out after {max_wait}s")
                return False

            backoff_wait = max(0, self._backoff_until - now)
            req_wait = self._request_bucket.wait_time(1.0)
            tok_wait = self._token_bucket.wait_time(tokens)
            wait = max(backoff_wait, req_wait, tok_wait)
            wait = min(wait, deadline - now, 5.0)

            if wait > 0:
                await asyncio.sleep(wait)

    def backoff(self, seconds: float = 30.0) -> None:
        """收到 429 时调用: 暂停所有获取直到 backoff 结束。"""
        self._backoff_until = self._time_func() + seconds
        log.info(f"RateLimiter: backoff for {seconds}s (429 received)")

    @property
    def status(self) -> dict:
        now = self._time_func()
        return {
            "requests_available": round(self._request_bucket.available, 1),
            "requests_per_minute": self.requests_per_minute,
            "tokens_available": round(self._token_bucket.available, 0),
            "tokens_per_minute": self.tokens_per_minute,
            "in_backoff": now < self._backoff_until,
            "backoff_remaining_s": round(max(0, self._backoff_until - now), 1),
        }
