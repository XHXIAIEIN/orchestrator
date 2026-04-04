"""ThrottleGate — 4-layer filter for the proactive push engine.

Layer 0   : Hard off  (_enabled flag)
Layer 0.5 : Critical bypass  (Tier A + severity "critical" always passes)
Layer 1   : Quiet mode  (_quiet_mode blocks non-critical)
Layer 2   : Time window  (CST active hours; blocked signals are queued)
Layer 3   : Rate cap  (MAX_PER_HOUR sends in last 60 min)
Layer 4   : Cooldown  (per-signal-id, from config.COOLDOWNS)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.proactive import config as cfg
from src.proactive.signals import Signal

# ── CST offset (UTC+8) ──────────────────────────────────────────────────────
_CST = timezone(timedelta(hours=8))

_PRUNE_AFTER_HOURS = 48


def _now_local_hour() -> int:
    """Return the current hour in CST (UTC+8). Patchable in tests."""
    return datetime.now(_CST).hour


class ThrottleGate:
    """Multi-layer gate that decides whether a signal should be sent now."""

    def __init__(self) -> None:
        self._enabled: bool = True
        self._quiet_mode: bool = False
        # (signal_id, sent_at_utc) — used for rate cap + cooldown checks
        self._sent_log: list[tuple[str, datetime]] = []
        # Signals blocked by time-window or rate cap, waiting to be drained
        self._queued: list[Signal] = []

    # ── Public properties ────────────────────────────────────────────────────

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    @property
    def is_quiet(self) -> bool:
        return self._quiet_mode

    # ── State mutators ───────────────────────────────────────────────────────

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def set_quiet(self, quiet: bool) -> None:
        self._quiet_mode = quiet

    # ── Core decision ────────────────────────────────────────────────────────

    def should_send(self, signal: Signal) -> bool:
        """Return True if *signal* should be dispatched right now.

        Signals blocked by time window or rate cap are added to the queue
        so they can be retried later via :meth:`drain_queued`.
        """
        is_critical = signal.tier == "A" and signal.severity == "critical"

        # Layer 0: hard off — nothing passes (not even critical)
        if not self._enabled:
            return False

        # Layer 0.5: critical bypass — always send regardless of everything else
        if is_critical:
            return True

        # Layer 1: quiet mode — block everything that isn't critical
        if self._quiet_mode:
            return False

        # Layer 2: time window — only allow during active hours
        hour = _now_local_hour()
        in_window = cfg.ACTIVE_HOUR_START <= hour < cfg.ACTIVE_HOUR_END
        if not in_window:
            self._queued.append(signal)
            return False

        # Layer 3: rate cap — count sends in the last 60 minutes
        now_utc = datetime.now(timezone.utc)
        cutoff_1h = now_utc - timedelta(hours=1)
        recent_count = sum(1 for _, ts in self._sent_log if ts >= cutoff_1h)
        if recent_count >= cfg.MAX_PER_HOUR:
            self._queued.append(signal)
            return False

        # Layer 4: per-signal cooldown
        cooldown_secs = cfg.COOLDOWNS.get(signal.id, 0)
        if cooldown_secs > 0:
            cutoff_cd = now_utc - timedelta(seconds=cooldown_secs)
            # Find the most recent send of this signal_id
            last_sends = [ts for sid, ts in self._sent_log if sid == signal.id]
            if last_sends and max(last_sends) >= cutoff_cd:
                return False

        return True

    # ── Accounting ───────────────────────────────────────────────────────────

    def record_sent(self, signal: Signal) -> None:
        """Record that *signal* was successfully sent.

        Also prunes log entries older than 48 h to keep memory bounded.
        """
        now_utc = datetime.now(timezone.utc)
        self._sent_log.append((signal.id, now_utc))

        # Prune stale entries
        cutoff = now_utc - timedelta(hours=_PRUNE_AFTER_HOURS)
        self._sent_log = [(sid, ts) for sid, ts in self._sent_log if ts >= cutoff]

    # ── Queue management ─────────────────────────────────────────────────────

    def drain_queued(self) -> list[Signal]:
        """Return all queued signals and clear the internal queue."""
        pending = list(self._queued)
        self._queued.clear()
        return pending
