# tests/gateway/test_model_fallback.py
"""Tests for model fallback chain."""
import json
from unittest.mock import MagicMock, patch, call
from src.gateway.model_fallback import ModelFallbackChain


def test_fallback_returns_first_success():
    """Should return result from first model that succeeds."""
    chain = ModelFallbackChain(models=["model-a", "model-b", "model-c"])
    results = {"model-a": RuntimeError("rate limited"), "model-b": '{"action":"test"}'}

    def mock_call(prompt, model):
        r = results.get(model)
        if isinstance(r, Exception):
            raise r
        return r

    result = chain.call(prompt="test", call_fn=mock_call)
    assert result == '{"action":"test"}'
    assert chain.last_model_used == "model-b"


def test_fallback_all_fail_raises():
    """Should raise if all models fail."""
    chain = ModelFallbackChain(models=["model-a", "model-b"])

    def mock_call(prompt, model):
        raise RuntimeError(f"{model} down")

    try:
        chain.call(prompt="test", call_fn=mock_call)
        assert False, "Should have raised"
    except RuntimeError as e:
        assert "All models failed" in str(e)


def test_fallback_tracks_attempts():
    """Should record each attempt."""
    chain = ModelFallbackChain(models=["model-a", "model-b"])

    def mock_call(prompt, model):
        if model == "model-a":
            raise RuntimeError("timeout")
        return '{"ok":true}'

    chain.call(prompt="test", call_fn=mock_call)
    assert len(chain.attempts) == 2
    assert chain.attempts[0]["model"] == "model-a"
    assert "timeout" in chain.attempts[0]["error"]
    assert chain.attempts[1]["model"] == "model-b"
    assert chain.attempts[1]["error"] is None


def test_fallback_empty_response_triggers_next():
    """Empty or too-short responses should trigger fallback."""
    chain = ModelFallbackChain(models=["model-a", "model-b"], min_response_len=5)

    def mock_call(prompt, model):
        if model == "model-a":
            return ""  # empty
        return '{"action":"fixed"}'

    result = chain.call(prompt="test", call_fn=mock_call)
    assert result == '{"action":"fixed"}'
