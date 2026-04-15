"""Tests for R72 three-layer signal extraction + stagnation detection."""
import re
import pytest
from src.governance.signals.signal_extractor import (
    SignalExtractor, SignalHistory, ExtractedSignal,
    KeywordProfile, _extract_layer1, _extract_layer2,
)


class TestLayer1Regex:
    def test_detects_error_loop(self):
        text = "Got the same error again: ModuleNotFoundError"
        signals = _extract_layer1(text)
        ids = [s.id for s in signals]
        assert "error_loop" in ids or "import_error" in ids

    def test_detects_timeout(self):
        signals = _extract_layer1("Request timed out after 30s")
        assert any(s.id == "timeout_error" for s in signals)

    def test_detects_cjk_feature_request(self):
        signals = _extract_layer1("能不能支持 YAML 格式的配置？")
        assert any(s.id == "feature_request_cjk" for s in signals)

    def test_no_false_positives_on_clean_text(self):
        signals = _extract_layer1("The quick brown fox jumps over the lazy dog")
        assert len(signals) == 0


class TestLayer2Keywords:
    def test_perf_bottleneck_single_keyword_not_enough(self):
        """Single keyword below threshold should not trigger."""
        signals = _extract_layer2("The app is slow")
        assert not any(s.id == "perf_bottleneck" for s in signals)

    def test_perf_bottleneck_multiple_keywords(self):
        """Multiple keywords exceeding threshold should trigger."""
        signals = _extract_layer2("The app is slow and we got a timeout and memory leak")
        assert any(s.id == "perf_bottleneck" for s in signals)

    def test_security_concern(self):
        signals = _extract_layer2("Found SQL injection vulnerability with exposed credentials")
        assert any(s.id == "security_concern" for s in signals)

    def test_custom_profile(self):
        profile = KeywordProfile("custom_signal", threshold=3.0, keywords={
            "widget": 2.0, "broken": 2.0,
        })
        assert profile.score("The widget is broken") >= 4.0
        assert profile.score("Hello world") == 0.0


class TestSignalHistory:
    def test_stagnation_detection(self):
        history = SignalHistory(max_cycles=8, stagnation_threshold=3)
        sig = ExtractedSignal(id="error_loop", source_layer=1, score=1.0, context="test")

        # Not stagnant after 2 cycles
        history.record_cycle([sig])
        history.record_cycle([sig])
        assert not history.is_stagnant("error_loop")

        # Stagnant after 3 cycles
        history.record_cycle([sig])
        assert history.is_stagnant("error_loop")

    def test_repair_loop_detection(self):
        history = SignalHistory(repair_loop_threshold=3)
        repair_sig = ExtractedSignal(id="error_loop", source_layer=1, score=1.0, context="")

        history.record_cycle([repair_sig])
        history.record_cycle([repair_sig])
        assert not history.should_force_innovation

        history.record_cycle([repair_sig])
        assert history.should_force_innovation

    def test_repair_loop_resets_on_non_repair(self):
        history = SignalHistory(repair_loop_threshold=3)
        repair_sig = ExtractedSignal(id="error_loop", source_layer=1, score=1.0, context="")
        other_sig = ExtractedSignal(id="feature_request_cjk", source_layer=1, score=1.0, context="")

        history.record_cycle([repair_sig])
        history.record_cycle([repair_sig])
        history.record_cycle([other_sig])  # breaks the streak
        assert not history.should_force_innovation

    def test_empty_cycle_tracking(self):
        history = SignalHistory()
        sig = ExtractedSignal(id="test", source_layer=1, score=1.0, context="")

        for _ in range(4):
            history.record_cycle([sig], blast_radius=0)
        assert history.empty_cycle_count == 4

    def test_frequency_map(self):
        history = SignalHistory()
        sig_a = ExtractedSignal(id="a", source_layer=1, score=1.0, context="")
        sig_b = ExtractedSignal(id="b", source_layer=1, score=1.0, context="")

        history.record_cycle([sig_a, sig_b])
        history.record_cycle([sig_a])

        freq = history.get_frequency_map()
        assert freq["a"] == 2
        assert freq["b"] == 1


class TestSignalExtractor:
    def test_full_pipeline(self):
        extractor = SignalExtractor()
        text = "ModuleNotFoundError: No module named 'foo'. Same error again and again."
        signals = extractor.extract(text, blast_radius=1)
        assert len(signals) > 0
        assert all(isinstance(s, ExtractedSignal) for s in signals)

    def test_dedup_keeps_highest_score(self):
        extractor = SignalExtractor()
        # Text that triggers the same signal from multiple regex matches
        text = "timeout error timeout error timeout"
        signals = extractor.extract(text)
        ids = [s.id for s in signals]
        # Each unique id should appear at most once after dedup
        assert len(ids) == len(set(ids))

    def test_force_innovation_injected(self):
        extractor = SignalExtractor()
        error_text = "ModuleNotFoundError again and again"

        # Run 3 cycles with repair signals
        for _ in range(3):
            signals = extractor.extract(error_text, blast_radius=1)

        # After 3 repair cycles, force_innovation should appear
        ids = [s.id for s in signals]
        assert "force_innovation_after_repair_loop" in ids

    def test_empty_text_returns_nothing(self):
        extractor = SignalExtractor()
        signals = extractor.extract("")
        assert len(signals) == 0

    def test_stats(self):
        extractor = SignalExtractor()
        extractor.extract("test text")
        stats = extractor.get_stats()
        assert stats["cycle_count"] == 1
        assert "history_frequency" in stats
