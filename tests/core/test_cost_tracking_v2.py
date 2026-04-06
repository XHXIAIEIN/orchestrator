import pytest
from src.core.model_pricing import ModelPricing, PricingRegistry


def test_exact_match():
    reg = PricingRegistry()
    reg.add("claude-sonnet-4-6", ModelPricing(input_per_mtok=3.0, output_per_mtok=15.0))
    p = reg.lookup("claude-sonnet-4-6")
    assert p.input_per_mtok == 3.0
    assert p.output_per_mtok == 15.0


def test_prefix_match():
    reg = PricingRegistry()
    reg.add("claude-sonnet", ModelPricing(input_per_mtok=3.0, output_per_mtok=15.0))
    p = reg.lookup("claude-sonnet-4-6-20260301")
    assert p.input_per_mtok == 3.0


def test_fallback_to_default():
    reg = PricingRegistry()
    p = reg.lookup("unknown-model")
    assert p.input_per_mtok == PricingRegistry.DEFAULT_PRICING.input_per_mtok


def test_compute_cost():
    pricing = ModelPricing(input_per_mtok=3.0, output_per_mtok=15.0, cache_read_per_mtok=0.3, reasoning_per_mtok=15.0)
    tokens = {"input": 1000, "output": 500, "cache_read": 2000, "reasoning": 300}
    cost = pricing.compute_cost(tokens)
    expected = (1000 * 3.0 + 500 * 15.0 + 2000 * 0.3 + 300 * 15.0) / 1_000_000
    assert abs(cost - expected) < 1e-9


from src.core.cost_tracking import CostTracker


def test_cost_tracker_detailed_tokens():
    tracker = CostTracker(limit=1.0)
    tracker.add_call("generate", model="claude-sonnet-4-6", cost=0.01,
                     tokens={"input": 1000, "output": 500, "cache_read": 200})
    d = tracker.to_dict()
    assert d["calls"][0]["tokens"]["cache_read"] == 200


def test_session_cost_summary():
    tracker = CostTracker(limit=5.0, source="session-abc")
    tracker.add_call("generate", model="claude-sonnet-4-6", cost=0.03, tokens={"input": 2000, "output": 800})
    tracker.add_call("generate", model="claude-haiku-4-5", cost=0.002, tokens={"input": 1500, "output": 300})
    s = tracker.session_summary()
    assert s["total_cost"] == pytest.approx(0.032, abs=1e-6)
    assert s["total_tokens"]["input"] == 3500
    assert s["total_tokens"]["output"] == 1100
    assert "claude-sonnet-4-6" in s["by_model"]
