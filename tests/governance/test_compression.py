"""Tests for Ratio-Based Context Compression."""
from src.governance.compression import ContextCompressor, COMPRESSION_PRESETS


def test_basic_flow():
    comp = ContextCompressor(max_context_tokens=1000, threshold=0.8, target_ratio=0.5)
    comp.add_turn("user", "hello", tokens=100)
    assert not comp.should_compress()
    assert comp.usage_ratio == 0.1


def test_should_compress_at_threshold():
    comp = ContextCompressor(max_context_tokens=1000, threshold=0.8)
    for i in range(8):
        comp.add_turn("assistant", f"response {i}", tokens=100)
    assert comp.should_compress()  # 800/1000 = 0.8


def test_compress_reduces_tokens():
    comp = ContextCompressor(max_context_tokens=1000, target_ratio=0.5, protect_last_n=2)
    for i in range(10):
        comp.add_turn("assistant", f"response {i} with some content", tokens=100)
    result = comp.compress()
    assert result["compressed"] is True
    assert result["tokens_after"] < result["tokens_before"]
    assert comp._total_tokens <= 1000 * 0.5 + 200  # target + some overhead


def test_protect_last_n():
    comp = ContextCompressor(max_context_tokens=1000, target_ratio=0.3, protect_last_n=3)
    for i in range(10):
        comp.add_turn("assistant", f"turn {i}", tokens=100)
    comp.compress()
    # Should still have at least 3 turns (protected) + 1 summary
    assert len(comp._turns) >= 4


def test_no_compress_when_below_target():
    comp = ContextCompressor(max_context_tokens=10000, target_ratio=0.6)
    comp.add_turn("user", "hello", tokens=100)
    result = comp.compress()
    assert result["compressed"] is False


def test_from_model_preset():
    comp = ContextCompressor.from_model("claude-haiku-4-5-20251001")
    assert comp.max_context_tokens == 100_000
    assert comp.target_ratio == 0.5

    comp2 = ContextCompressor.from_model("claude-opus-4-6")
    assert comp2.max_context_tokens == 1_000_000


def test_from_model_unknown_defaults_sonnet():
    comp = ContextCompressor.from_model("unknown-model-xyz")
    assert comp.max_context_tokens == COMPRESSION_PRESETS["sonnet"]["max_tokens"]


def test_usage_ratio():
    comp = ContextCompressor(max_context_tokens=1000)
    comp.add_turn("user", "x", tokens=250)
    assert comp.usage_ratio == 0.25


def test_get_stats():
    comp = ContextCompressor(max_context_tokens=1000, threshold=0.8, target_ratio=0.5)
    comp.add_turn("user", "hello", tokens=100)
    stats = comp.get_stats()
    assert stats["total_tokens"] == 100
    assert stats["turns"] == 1
    assert stats["compressions"] == 0


def test_compress_all_protected():
    comp = ContextCompressor(max_context_tokens=1000, protect_last_n=100)
    # Need total > target (1000 * 0.6 = 600) so it doesn't bail with "within target"
    for i in range(8):
        comp.add_turn("user", f"msg {i}", tokens=100)
    result = comp.compress()
    assert result["compressed"] is False
    assert result["reason"] == "all turns protected"
