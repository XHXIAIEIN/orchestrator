"""Model-aware pricing registry — stolen from MachinaOS R40 pricing.py.
Matching strategy: exact → prefix → contains → provider default → global fallback.
Tracks input/output/cache_read/reasoning tokens separately.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPricing:
    """Per-model pricing rates in $/million tokens."""
    input_per_mtok: float = 3.0
    output_per_mtok: float = 15.0
    cache_read_per_mtok: float = 0.0
    reasoning_per_mtok: float = 0.0

    def compute_cost(self, tokens: dict[str, int]) -> float:
        return (
            tokens.get("input", 0) * self.input_per_mtok
            + tokens.get("output", 0) * self.output_per_mtok
            + tokens.get("cache_read", 0) * self.cache_read_per_mtok
            + tokens.get("reasoning", 0) * self.reasoning_per_mtok
        ) / 1_000_000


class PricingRegistry:
    """Registry with fallback chain: exact → prefix → contains → default."""
    DEFAULT_PRICING = ModelPricing(input_per_mtok=3.0, output_per_mtok=15.0)

    def __init__(self) -> None:
        self._exact: dict[str, ModelPricing] = {}

    def add(self, model_key: str, pricing: ModelPricing) -> None:
        self._exact[model_key] = pricing

    def lookup(self, model_id: str) -> ModelPricing:
        # 1. Exact match
        if model_id in self._exact:
            return self._exact[model_id]
        # 2. Prefix match (longest wins)
        best_key, best_len = "", 0
        for key in self._exact:
            if model_id.startswith(key) and len(key) > best_len:
                best_key, best_len = key, len(key)
        if best_key:
            return self._exact[best_key]
        # 3. Contains match
        for key, pricing in self._exact.items():
            if key in model_id:
                return pricing
        # 4. Default
        return self.DEFAULT_PRICING


# Built-in pricing table (2026-04 rates)
_BUILTIN = PricingRegistry()
_BUILTIN.add("claude-opus-4", ModelPricing(input_per_mtok=15.0, output_per_mtok=75.0, cache_read_per_mtok=1.5))
_BUILTIN.add("claude-sonnet-4", ModelPricing(input_per_mtok=3.0, output_per_mtok=15.0, cache_read_per_mtok=0.3))
_BUILTIN.add("claude-haiku-4", ModelPricing(input_per_mtok=0.8, output_per_mtok=4.0, cache_read_per_mtok=0.08))
_BUILTIN.add("gpt-4o", ModelPricing(input_per_mtok=2.5, output_per_mtok=10.0))
_BUILTIN.add("gpt-4o-mini", ModelPricing(input_per_mtok=0.15, output_per_mtok=0.6))
_BUILTIN.add("o3", ModelPricing(input_per_mtok=10.0, output_per_mtok=40.0, reasoning_per_mtok=40.0))


def get_builtin_registry() -> PricingRegistry:
    return _BUILTIN
