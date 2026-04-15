"""R72 Evolver: Idle-Aware Scheduler — triggers background work during system idle.

Cross-platform idle time detection:
    - Windows: GetLastInputInfo via ctypes
    - macOS: ioreg HIDIdleTime
    - Linux: xprintidle or /proc/stat

Four intensity tiers based on idle duration:
    signal_only  (1-5 min)  : lightweight signal extraction only
    normal       (5-15 min) : normal analysis + memory consolidation
    aggressive   (15-30 min): distillation + reflection + synthesis
    deep         (30+ min)  : full deep evolution cycle

The scheduler itself doesn't execute work — it emits tier signals that the
governor or proactive engine can consume.

Source: yoyo-evolve IdleScheduler (R72 deep steal)
"""
from __future__ import annotations

import logging
import platform
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

log = logging.getLogger(__name__)


class IdleTier(Enum):
    """Intensity tiers for idle-triggered work."""
    ACTIVE = "active"              # User is active, no background work
    SIGNAL_ONLY = "signal_only"    # 1-5 min idle: lightweight checks
    NORMAL = "normal"              # 5-15 min: analysis + memory
    AGGRESSIVE = "aggressive"      # 15-30 min: distillation + reflection
    DEEP = "deep"                  # 30+ min: full evolution


@dataclass
class IdleSchedulerConfig:
    """Thresholds for idle tier transitions (seconds)."""
    signal_only_s: float = 60.0       # 1 min
    normal_s: float = 300.0           # 5 min
    aggressive_s: float = 900.0       # 15 min
    deep_s: float = 1800.0            # 30 min

    poll_interval_s: float = 30.0     # How often to check idle time
    enabled: bool = True


@dataclass
class IdleState:
    """Current idle state snapshot."""
    idle_seconds: float
    tier: IdleTier
    last_check: float = 0.0           # monotonic timestamp
    platform: str = ""
    detection_method: str = ""
    error: str | None = None


# ── Platform-specific idle detection ──

def _get_idle_time_windows() -> float:
    """Get idle time on Windows via GetLastInputInfo."""
    import ctypes
    import ctypes.wintypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.wintypes.UINT),
            ("dwTime", ctypes.wintypes.DWORD),
        ]

    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)

    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
        raise OSError("GetLastInputInfo failed")

    millis = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
    return millis / 1000.0


def _get_idle_time_darwin() -> float:
    """Get idle time on macOS via ioreg."""
    result = subprocess.run(
        ["ioreg", "-c", "IOHIDSystem", "-d", "4"],
        capture_output=True, text=True, timeout=5,
    )
    for line in result.stdout.splitlines():
        if "HIDIdleTime" in line:
            # Extract nanoseconds value
            parts = line.split("=")
            if len(parts) >= 2:
                ns = int(parts[-1].strip())
                return ns / 1_000_000_000.0
    raise OSError("HIDIdleTime not found in ioreg output")


def _get_idle_time_linux() -> float:
    """Get idle time on Linux via xprintidle (X11) or /proc/uptime."""
    # Try xprintidle first (X11)
    try:
        result = subprocess.run(
            ["xprintidle"], capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return int(result.stdout.strip()) / 1000.0
    except FileNotFoundError:
        pass

    # Fallback: /proc/uptime (not true user idle, but usable)
    try:
        with open("/proc/uptime") as f:
            parts = f.read().split()
            # Second value is cumulative idle time (not what we want ideally,
            # but best available without X11)
            return float(parts[1])
    except (OSError, IndexError, ValueError):
        pass

    raise OSError("No idle time detection method available on Linux")


def get_system_idle_time() -> tuple[float, str]:
    """Get system idle time in seconds.

    Returns:
        (idle_seconds, detection_method)
    """
    system = platform.system()

    if system == "Windows":
        return _get_idle_time_windows(), "GetLastInputInfo"
    elif system == "Darwin":
        return _get_idle_time_darwin(), "ioreg_HIDIdleTime"
    elif system == "Linux":
        return _get_idle_time_linux(), "xprintidle_or_proc"
    else:
        raise OSError(f"Unsupported platform: {system}")


# ── Scheduler ──

def classify_idle_tier(idle_s: float, config: IdleSchedulerConfig) -> IdleTier:
    """Classify idle time into intensity tier."""
    if idle_s >= config.deep_s:
        return IdleTier.DEEP
    elif idle_s >= config.aggressive_s:
        return IdleTier.AGGRESSIVE
    elif idle_s >= config.normal_s:
        return IdleTier.NORMAL
    elif idle_s >= config.signal_only_s:
        return IdleTier.SIGNAL_ONLY
    else:
        return IdleTier.ACTIVE


class IdleScheduler:
    """Monitors system idle time and emits tier-based work signals.

    Usage:
        scheduler = IdleScheduler()

        # Check current state (call periodically from main loop):
        state = scheduler.check()
        if state.tier == IdleTier.AGGRESSIVE:
            run_distillation()
            run_reflection()

        # Or register callbacks per tier:
        scheduler.on_tier(IdleTier.AGGRESSIVE, run_distillation)
        scheduler.on_tier(IdleTier.DEEP, run_deep_evolution)
        scheduler.dispatch()  # fires callbacks if tier matches
    """

    def __init__(self, config: IdleSchedulerConfig | None = None):
        self.config = config or IdleSchedulerConfig()
        self._last_tier = IdleTier.ACTIVE
        self._callbacks: dict[IdleTier, list[Callable]] = {t: [] for t in IdleTier}
        self._last_dispatch: dict[IdleTier, float] = {}  # monotonic timestamps
        self._cooldown_s = 300.0  # min seconds between same-tier dispatches

    def check(self) -> IdleState:
        """Check current system idle state."""
        if not self.config.enabled:
            return IdleState(
                idle_seconds=0, tier=IdleTier.ACTIVE,
                last_check=time.monotonic(),
                platform=platform.system(),
                detection_method="disabled",
            )

        try:
            idle_s, method = get_system_idle_time()
            tier = classify_idle_tier(idle_s, self.config)
            state = IdleState(
                idle_seconds=idle_s,
                tier=tier,
                last_check=time.monotonic(),
                platform=platform.system(),
                detection_method=method,
            )
        except OSError as exc:
            state = IdleState(
                idle_seconds=0,
                tier=IdleTier.ACTIVE,
                last_check=time.monotonic(),
                platform=platform.system(),
                detection_method="error",
                error=str(exc),
            )

        # Log tier transitions
        if state.tier != self._last_tier:
            log.info(
                "idle_scheduler: %s → %s (idle %.0fs)",
                self._last_tier.value, state.tier.value, state.idle_seconds,
            )
            self._last_tier = state.tier

        return state

    def on_tier(self, tier: IdleTier, callback: Callable) -> None:
        """Register a callback for when a specific idle tier is reached."""
        self._callbacks[tier].append(callback)

    def dispatch(self) -> list[str]:
        """Check idle state and fire callbacks for current tier.

        Returns list of callback names that were dispatched.
        Respects cooldown to prevent re-firing.
        """
        state = self.check()
        dispatched = []

        if state.tier == IdleTier.ACTIVE:
            return dispatched

        now = time.monotonic()

        # Fire callbacks for current tier and all lower tiers
        tier_order = [IdleTier.SIGNAL_ONLY, IdleTier.NORMAL,
                      IdleTier.AGGRESSIVE, IdleTier.DEEP]
        tier_idx = tier_order.index(state.tier) if state.tier in tier_order else -1

        for i, tier in enumerate(tier_order):
            if i > tier_idx:
                break

            last = self._last_dispatch.get(tier, 0)
            if now - last < self._cooldown_s:
                continue

            for cb in self._callbacks[tier]:
                try:
                    cb()
                    dispatched.append(f"{tier.value}:{cb.__name__}")
                except Exception as exc:
                    log.error(
                        "idle_scheduler: callback %s failed: %s",
                        cb.__name__, exc,
                    )
            if self._callbacks[tier]:
                self._last_dispatch[tier] = now

        return dispatched

    def get_stats(self) -> dict:
        """Return scheduler state for diagnostics."""
        return {
            "enabled": self.config.enabled,
            "current_tier": self._last_tier.value,
            "thresholds": {
                "signal_only_s": self.config.signal_only_s,
                "normal_s": self.config.normal_s,
                "aggressive_s": self.config.aggressive_s,
                "deep_s": self.config.deep_s,
            },
            "registered_callbacks": {
                t.value: len(cbs) for t, cbs in self._callbacks.items()
            },
        }
