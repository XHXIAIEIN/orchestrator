"""LLM Proxy — transparent layer between agents and model backends.

Collects request/response spans for observability.
Allows dynamic model switching without agent code changes.
Supports request/response middleware hooks.
"""

import time
import logging
from dataclasses import dataclass, field
from typing import Callable, Any

logger = logging.getLogger(__name__)


@dataclass
class LLMSpan:
    """A single LLM request-response span."""
    request_id: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    duration_ms: float = 0
    success: bool = True
    error: str | None = None
    metadata: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class LLMProxy:
    """Transparent proxy for LLM calls with span collection.

    Usage:
        proxy = LLMProxy(default_model="sonnet")
        proxy.add_middleware(log_requests)
        proxy.override_model("opus")  # Dynamic switch

        result = await proxy.generate(prompt, **kwargs)
        print(proxy.get_spans())  # Full trace
    """

    def __init__(self, default_model: str = "sonnet", router=None):
        self._default_model = default_model
        self._model_override: str | None = None
        self._router = router  # LLMRouter instance
        self._spans: list[LLMSpan] = []
        self._max_spans = 1000
        self._middlewares: list[Callable] = []

    @property
    def active_model(self) -> str:
        return self._model_override or self._default_model

    def override_model(self, model: str | None):
        """Dynamically switch model. None resets to default."""
        old = self.active_model
        self._model_override = model
        if model:
            logger.info(f"LLM Proxy: model override {old} → {model}")

    def add_middleware(self, fn: Callable):
        """Add request/response middleware. fn(span) -> span or None."""
        self._middlewares.append(fn)

    async def generate(self, prompt: str, **kwargs) -> dict:
        """Proxy a generation request through the router."""
        import uuid

        span = LLMSpan(
            request_id=str(uuid.uuid4())[:8],
            model=self.active_model,
        )

        # Run pre-middlewares
        for mw in self._middlewares:
            try:
                mw(span)
            except Exception:
                pass

        start = time.perf_counter()
        try:
            if self._router:
                result = self._router.generate(
                    prompt=prompt,
                    task_type=kwargs.get("task_type", "default"),
                    **{k: v for k, v in kwargs.items() if k != "task_type"},
                )
            else:
                result = {"text": "", "error": "no router configured"}

            span.duration_ms = round((time.perf_counter() - start) * 1000, 2)
            span.success = bool(result.get("text"))
            span.prompt_tokens = result.get("prompt_tokens", 0)
            span.completion_tokens = result.get("completion_tokens", 0)
        except Exception as e:
            span.duration_ms = round((time.perf_counter() - start) * 1000, 2)
            span.success = False
            span.error = str(e)
            result = {"text": "", "error": str(e)}

        self._record_span(span)
        return result

    def _record_span(self, span: LLMSpan):
        self._spans.append(span)
        if len(self._spans) > self._max_spans:
            self._spans = self._spans[-self._max_spans:]

    def get_spans(self, n: int = 50) -> list[LLMSpan]:
        return self._spans[-n:]

    def get_stats(self) -> dict:
        if not self._spans:
            return {"total": 0}
        total = len(self._spans)
        successes = sum(1 for s in self._spans if s.success)
        avg_ms = sum(s.duration_ms for s in self._spans) / total
        return {
            "total": total,
            "success_rate": round(successes / total, 3),
            "avg_duration_ms": round(avg_ms, 1),
            "active_model": self.active_model,
            "model_override": self._model_override,
        }
