# src/gateway/model_fallback.py
"""Model Fallback Chain — stolen from OpenFang.

When the primary model fails (rate limit, timeout, garbage response),
automatically try the next model in the chain. Tracks all attempts
for observability.
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

log = logging.getLogger(__name__)


class ModelFallbackChain:
    """Try models in order until one succeeds.

    Usage:
        chain = ModelFallbackChain(models=["claude-sonnet", "claude-haiku", "ollama/qwen"])
        result = chain.call(prompt, call_fn=my_llm_call)
    """

    def __init__(self, models: list[str], min_response_len: int = 10):
        self.models = models
        self.min_response_len = min_response_len
        self.attempts: list[dict] = []
        self.last_model_used: Optional[str] = None

    def call(self, prompt: str, call_fn: Callable[[str, str], str]) -> str:
        """Try each model in order. Returns first valid response.

        Args:
            prompt: The prompt to send.
            call_fn: Callable(prompt, model) -> str. Raises on failure.

        Returns:
            Response text from first successful model.

        Raises:
            RuntimeError: If all models fail.
        """
        self.attempts = []

        for model in self.models:
            t0 = time.time()
            try:
                result = call_fn(prompt, model)
                elapsed_ms = int((time.time() - t0) * 1000)

                if not result or len(result.strip()) < self.min_response_len:
                    self.attempts.append({
                        "model": model, "elapsed_ms": elapsed_ms,
                        "error": f"low_quality ({len((result or '').strip())} chars)",
                    })
                    log.warning(f"fallback_chain: {model} low quality, trying next")
                    continue

                self.attempts.append({
                    "model": model, "elapsed_ms": elapsed_ms, "error": None,
                })
                self.last_model_used = model
                log.info(f"fallback_chain: {model} succeeded ({elapsed_ms}ms)")
                return result

            except Exception as e:
                elapsed_ms = int((time.time() - t0) * 1000)
                self.attempts.append({
                    "model": model, "elapsed_ms": elapsed_ms, "error": str(e),
                })
                log.warning(f"fallback_chain: {model} failed ({e}), trying next")

        raise RuntimeError(f"All models failed: {self.attempts}")
