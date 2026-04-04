"""Tests for ProactiveEngine — scan_cycle orchestrator."""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call

import pytest

from src.proactive.engine import ProactiveEngine
from src.proactive.signals import Signal
from src.proactive import config as cfg


# ── Helpers ───────────────────────────────────────────────────────────────────

def _signal(id: str = "S2", tier: str = "A", severity: str = "high", title: str = "test") -> Signal:
    return Signal(id=id, tier=tier, title=title, severity=severity)


def _make_engine(signals=None, quiet=False, enabled=True):
    """Build a ProactiveEngine with all collaborators mocked."""
    db = MagicMock()
    registry = MagicMock()
    llm_router = MagicMock()
    llm_router.generate.return_value = "generated message"

    engine = ProactiveEngine(db=db, registry=registry, llm_router=llm_router)

    # Patch detector
    engine.detector = MagicMock()
    engine.detector.detect_all.return_value = signals or []

    # Patch generator to return deterministic strings
    engine.generator = MagicMock()
    engine.generator.generate.return_value = "test notification"

    # Configure throttle state
    if not enabled:
        engine.throttle.set_enabled(False)
    if quiet:
        engine.throttle.set_quiet(True)

    return engine


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestScanCycleNoSignals:
    def test_empty_db_no_broadcasts(self):
        """No signals detected → no broadcasts, no DB logs."""
        engine = _make_engine(signals=[])
        engine.scan_cycle()

        engine.registry.broadcast.assert_not_called()
        engine.db.log_proactive.assert_not_called()


class TestScanCycleSendsAllowedSignal:
    def test_single_signal_broadcast_and_logged(self):
        """Detector returns 1 Tier-A signal → broadcast called + db.log_proactive called."""
        sig = _signal(id="S2", tier="A", severity="critical")
        engine = _make_engine(signals=[sig])

        # Patch ChannelMessage import inside engine module
        mock_cm = MagicMock()
        with patch("src.proactive.engine.ChannelMessage", mock_cm, create=True):
            # Throttle: patch should_send to always return True
            with patch.object(engine.throttle, "should_send", return_value=True):
                with patch.object(engine.throttle, "record_sent") as mock_record:
                    engine.scan_cycle()

        engine.registry.broadcast.assert_called_once()
        engine.db.log_proactive.assert_called_once()
        call_kwargs = engine.db.log_proactive.call_args.kwargs
        assert call_kwargs["action"] == "sent"
        assert call_kwargs["signal_id"] == "S2"

    def test_message_from_generator_is_used(self):
        """The message passed to broadcast comes from generator.generate."""
        sig = _signal(id="S1", tier="A", severity="high")
        engine = _make_engine(signals=[sig])
        engine.generator.generate.return_value = "custom message text"

        with patch.object(engine.throttle, "should_send", return_value=True):
            engine.scan_cycle()

        # ChannelMessage is a plain dataclass — registry.broadcast received it
        engine.registry.broadcast.assert_called_once()
        broadcast_arg = engine.registry.broadcast.call_args.args[0]
        assert broadcast_arg.text == "custom message text"


class TestScanCycleThrottledSignalNotSent:
    def test_quiet_mode_blocks_non_critical(self):
        """Quiet mode active → non-critical signal throttled, broadcast NOT called."""
        sig = _signal(id="S3", tier="B", severity="medium")
        engine = _make_engine(signals=[sig], quiet=True)

        # Active hours so only quiet mode blocks
        with patch("src.proactive.throttle._now_local_hour", return_value=cfg.ACTIVE_HOUR_START):
            engine.scan_cycle()

        engine.registry.broadcast.assert_not_called()
        # DB should still log throttled action
        engine.db.log_proactive.assert_called_once()
        call_kwargs = engine.db.log_proactive.call_args.kwargs
        assert call_kwargs["action"] == "throttled"
        assert call_kwargs["reason"] == "throttle_gate"

    def test_disabled_engine_blocks_all(self):
        """Engine disabled → all signals throttled."""
        sig = _signal(id="S2", tier="A", severity="critical")
        engine = _make_engine(signals=[sig], enabled=False)

        with patch("src.proactive.throttle._now_local_hour", return_value=cfg.ACTIVE_HOUR_START):
            engine.scan_cycle()

        engine.registry.broadcast.assert_not_called()


class TestScanCycleRespectsLLMCap:
    def test_llm_cap_limits_tier_b_c_calls(self):
        """5 Tier-B signals → generator.generate called <= MAX_LLM_PER_SCAN times."""
        signals = [_signal(id=f"S{i+3}", tier="B", severity="medium") for i in range(5)]
        engine = _make_engine(signals=signals)

        # All pass throttle check — ChannelMessage is a plain dataclass, no patch needed
        with patch("src.proactive.throttle._now_local_hour", return_value=cfg.ACTIVE_HOUR_START):
            engine.scan_cycle()

        # Generator called at most MAX_LLM_PER_SCAN times
        assert engine.generator.generate.call_count <= cfg.MAX_LLM_PER_SCAN

    def test_llm_cap_logs_excess_as_throttled(self):
        """Signals beyond the LLM cap should be logged as throttled with reason=llm_cap."""
        n = cfg.MAX_LLM_PER_SCAN + 2
        signals = [_signal(id=f"S{i+3}", tier="B", severity="medium") for i in range(n)]
        engine = _make_engine(signals=signals)

        with patch("src.proactive.throttle._now_local_hour", return_value=cfg.ACTIVE_HOUR_START):
            engine.scan_cycle()

        # At least 2 signals should be logged as llm_cap throttled
        throttled_llm_cap = [
            c for c in engine.db.log_proactive.call_args_list
            if c.kwargs.get("reason") == "llm_cap"
        ]
        assert len(throttled_llm_cap) >= 2

    def test_tier_a_not_counted_toward_llm_cap(self):
        """Tier-A signals use templates (no LLM), so they don't consume LLM budget."""
        # 1 Tier-A (template) + MAX_LLM_PER_SCAN Tier-B signals
        tier_a = _signal(id="S1", tier="A", severity="high")
        tier_b_signals = [_signal(id=f"S{i+3}", tier="B", severity="medium") for i in range(cfg.MAX_LLM_PER_SCAN)]
        signals = [tier_a] + tier_b_signals

        engine = _make_engine(signals=signals)

        with patch("src.proactive.throttle._now_local_hour", return_value=cfg.ACTIVE_HOUR_START):
            engine.scan_cycle()

        # All signals (A + B) should call generator; only B ones count against llm_calls
        # Tier-A (1) + Tier-B (MAX_LLM_PER_SCAN) = all generated, none throttled by llm_cap
        assert engine.generator.generate.call_count == len(signals)
