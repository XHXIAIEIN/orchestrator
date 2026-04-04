"""Tests for ThrottleGate — 4-layer filter."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from src.proactive.signals import Signal
from src.proactive.throttle import ThrottleGate
from src.proactive import config as cfg


# ── Helpers ──────────────────────────────────────────────────────────────────

def _signal(
    id: str = "S2",
    tier: str = "B",
    severity: str = "medium",
    title: str = "test signal",
) -> Signal:
    return Signal(id=id, tier=tier, title=title, severity=severity)


def _critical() -> Signal:
    return Signal(id="S1", tier="A", title="critical signal", severity="critical")


ACTIVE_HOUR = cfg.ACTIVE_HOUR_START  # guaranteed to be inside window


# ── Tests ────────────────────────────────────────────────────────────────────

class TestBasicAllow:
    def test_first_signal_always_allowed(self):
        gate = ThrottleGate()
        with patch("src.proactive.throttle._now_local_hour", return_value=ACTIVE_HOUR):
            assert gate.should_send(_signal()) is True

    def test_enabled_by_default(self):
        gate = ThrottleGate()
        assert gate.is_enabled is True

    def test_quiet_off_by_default(self):
        gate = ThrottleGate()
        assert gate.is_quiet is False


class TestCriticalBypass:
    def test_critical_tier_a_bypasses_quiet(self):
        gate = ThrottleGate()
        gate.set_quiet(True)
        # Should pass regardless of hour or quiet mode
        with patch("src.proactive.throttle._now_local_hour", return_value=3):
            assert gate.should_send(_critical()) is True

    def test_critical_bypasses_time_window(self):
        gate = ThrottleGate()
        with patch("src.proactive.throttle._now_local_hour", return_value=3):
            assert gate.should_send(_critical()) is True

    def test_hard_off_blocks_critical(self):
        """Layer 0 (hard off) stops even critical signals."""
        gate = ThrottleGate()
        gate.set_enabled(False)
        with patch("src.proactive.throttle._now_local_hour", return_value=ACTIVE_HOUR):
            assert gate.should_send(_critical()) is False


class TestQuietMode:
    def test_quiet_blocks_non_critical(self):
        gate = ThrottleGate()
        gate.set_quiet(True)
        with patch("src.proactive.throttle._now_local_hour", return_value=ACTIVE_HOUR):
            assert gate.should_send(_signal(tier="B", severity="medium")) is False

    def test_quiet_blocks_tier_a_non_critical(self):
        gate = ThrottleGate()
        gate.set_quiet(True)
        sig = Signal(id="S2", tier="A", title="high but not critical", severity="high")
        with patch("src.proactive.throttle._now_local_hour", return_value=ACTIVE_HOUR):
            assert gate.should_send(sig) is False

    def test_toggle_quiet(self):
        gate = ThrottleGate()
        gate.set_quiet(True)
        assert gate.is_quiet is True
        gate.set_quiet(False)
        assert gate.is_quiet is False
        with patch("src.proactive.throttle._now_local_hour", return_value=ACTIVE_HOUR):
            assert gate.should_send(_signal()) is True


class TestTimeWindow:
    def test_outside_hours_queues_signal(self):
        gate = ThrottleGate()
        sig = _signal()
        with patch("src.proactive.throttle._now_local_hour", return_value=3):
            result = gate.should_send(sig)
        assert result is False
        assert sig in gate._queued

    def test_inside_hours_passes(self):
        gate = ThrottleGate()
        with patch("src.proactive.throttle._now_local_hour", return_value=ACTIVE_HOUR):
            assert gate.should_send(_signal()) is True

    def test_boundary_start_included(self):
        """Hour == ACTIVE_HOUR_START should pass."""
        gate = ThrottleGate()
        with patch("src.proactive.throttle._now_local_hour", return_value=cfg.ACTIVE_HOUR_START):
            assert gate.should_send(_signal()) is True

    def test_boundary_end_excluded(self):
        """Hour == ACTIVE_HOUR_END should be blocked."""
        gate = ThrottleGate()
        sig = _signal()
        with patch("src.proactive.throttle._now_local_hour", return_value=cfg.ACTIVE_HOUR_END):
            result = gate.should_send(sig)
        assert result is False
        assert sig in gate._queued


class TestRateCap:
    def test_rate_limit_blocks_after_max(self):
        gate = ThrottleGate()
        # Fill up the log with MAX_PER_HOUR recent sends
        now = datetime.now(timezone.utc)
        for i in range(cfg.MAX_PER_HOUR):
            gate._sent_log.append((f"S{i+10}", now - timedelta(minutes=1)))

        with patch("src.proactive.throttle._now_local_hour", return_value=ACTIVE_HOUR):
            result = gate.should_send(_signal())
        assert result is False

    def test_rate_limit_allows_after_old_sends(self):
        """Sends older than 1h should not count toward the cap."""
        gate = ThrottleGate()
        now = datetime.now(timezone.utc)
        for i in range(cfg.MAX_PER_HOUR):
            gate._sent_log.append((f"S{i+10}", now - timedelta(hours=2)))

        with patch("src.proactive.throttle._now_local_hour", return_value=ACTIVE_HOUR):
            assert gate.should_send(_signal()) is True

    def test_rate_limited_signal_is_queued(self):
        gate = ThrottleGate()
        now = datetime.now(timezone.utc)
        for i in range(cfg.MAX_PER_HOUR):
            gate._sent_log.append((f"S{i+10}", now - timedelta(minutes=1)))

        sig = _signal()
        with patch("src.proactive.throttle._now_local_hour", return_value=ACTIVE_HOUR):
            gate.should_send(sig)
        assert sig in gate._queued


class TestCooldown:
    def test_cooldown_blocks_same_signal_id(self):
        gate = ThrottleGate()
        sig = _signal(id="S1")
        cooldown = cfg.COOLDOWNS.get("S1", 3600)
        # Fake a recent send of S1
        gate._sent_log.append(("S1", datetime.now(timezone.utc) - timedelta(seconds=cooldown // 2)))

        with patch("src.proactive.throttle._now_local_hour", return_value=ACTIVE_HOUR):
            assert gate.should_send(sig) is False

    def test_cooldown_allows_after_expiry(self):
        gate = ThrottleGate()
        sig = _signal(id="S1")
        cooldown = cfg.COOLDOWNS.get("S1", 3600)
        # Fake an old send — well past cooldown
        gate._sent_log.append(("S1", datetime.now(timezone.utc) - timedelta(seconds=cooldown + 1)))

        with patch("src.proactive.throttle._now_local_hour", return_value=ACTIVE_HOUR):
            assert gate.should_send(sig) is True

    def test_zero_cooldown_always_passes(self):
        """S8 and S9 have 0-second cooldown — should never be blocked by Layer 4."""
        gate = ThrottleGate()
        sig = _signal(id="S8")
        # Add many past sends of S8
        now = datetime.now(timezone.utc)
        for i in range(3):
            gate._sent_log.append(("S8", now - timedelta(minutes=i + 1)))

        with patch("src.proactive.throttle._now_local_hour", return_value=ACTIVE_HOUR):
            assert gate.should_send(sig) is True


class TestToggleEnabled:
    def test_disabled_blocks_everything(self):
        gate = ThrottleGate()
        gate.set_enabled(False)
        with patch("src.proactive.throttle._now_local_hour", return_value=ACTIVE_HOUR):
            assert gate.should_send(_signal()) is False

    def test_re_enable_works(self):
        gate = ThrottleGate()
        gate.set_enabled(False)
        gate.set_enabled(True)
        with patch("src.proactive.throttle._now_local_hour", return_value=ACTIVE_HOUR):
            assert gate.should_send(_signal()) is True


class TestRecordSent:
    def test_record_sent_adds_to_log(self):
        gate = ThrottleGate()
        sig = _signal()
        gate.record_sent(sig)
        assert len(gate._sent_log) == 1
        assert gate._sent_log[0][0] == sig.id

    def test_record_sent_prunes_old_entries(self):
        gate = ThrottleGate()
        # Inject a 49h-old entry
        old_ts = datetime.now(timezone.utc) - timedelta(hours=49)
        gate._sent_log.append(("S_OLD", old_ts))
        gate.record_sent(_signal())
        # The 49h-old entry should be pruned
        ids = [sid for sid, _ in gate._sent_log]
        assert "S_OLD" not in ids


class TestDrainQueued:
    def test_drain_returns_and_clears(self):
        gate = ThrottleGate()
        # Block two signals via time window
        s1, s2 = _signal(id="S2"), _signal(id="S3")
        with patch("src.proactive.throttle._now_local_hour", return_value=3):
            gate.should_send(s1)
            gate.should_send(s2)

        drained = gate.drain_queued()
        assert s1 in drained
        assert s2 in drained
        assert gate._queued == []

    def test_drain_empty_returns_empty_list(self):
        gate = ThrottleGate()
        assert gate.drain_queued() == []
