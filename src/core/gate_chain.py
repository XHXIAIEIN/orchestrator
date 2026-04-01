"""
Cheapest-First Gate Chain — multi-layer activation gates for background tasks.

Stolen from: Claude Code autoDream.ts (5-layer gate chain)
Pattern: Order gates by computational cost. Most calls rejected at cheapest layer.

Gate 1: Config check (memory read)     ~0μs
Gate 2: Time check (stat mtime)        ~1μs
Gate 3: Throttle check (in-memory var) ~0μs
Gate 4: Resource scan (readdir+stat)   ~5ms
Gate 5: Lock acquisition (file write)  ~10ms
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass
class GateResult:
    passed: bool
    gate_name: str
    reason: str = ""

    def __bool__(self) -> bool:
        return self.passed


class Gate:
    """Single gate in a gate chain."""

    def __init__(self, name: str, check: Callable[[], GateResult], cost_rank: int = 0):
        self.name = name
        self.check = check
        self.cost_rank = cost_rank  # Lower = cheaper = checked first

    def evaluate(self) -> GateResult:
        return self.check()


class GateChain:
    """Ordered chain of gates. Cheapest first, short-circuits on first failure."""

    def __init__(self, name: str):
        self.name = name
        self._gates: list[Gate] = []

    def add(self, gate: Gate) -> "GateChain":
        self._gates.append(gate)
        self._gates.sort(key=lambda g: g.cost_rank)
        return self

    def evaluate(self) -> GateResult:
        """Run all gates in cost order. Return first failure or final pass."""
        for gate in self._gates:
            result = gate.evaluate()
            if not result:
                return result
        return GateResult(passed=True, gate_name=self.name, reason="all gates passed")


# --- Pre-built gate factories ---

def config_gate(key: str, config: dict) -> Gate:
    """Gate 1: Check if feature is enabled in config. Cost: ~0μs."""
    def check() -> GateResult:
        enabled = config.get(key, False)
        return GateResult(
            passed=bool(enabled),
            gate_name=f"config:{key}",
            reason="" if enabled else f"{key} is disabled",
        )
    return Gate(name=f"config:{key}", check=check, cost_rank=0)


def time_gate(lock_path: Path, min_hours: float = 24.0) -> Gate:
    """Gate 2: Check if enough time elapsed since last run. Cost: ~1μs (stat)."""
    def check() -> GateResult:
        if not lock_path.exists():
            return GateResult(passed=True, gate_name="time", reason="no prior run")
        mtime = lock_path.stat().st_mtime
        hours_since = (time.time() - mtime) / 3600
        passed = hours_since >= min_hours
        return GateResult(
            passed=passed,
            gate_name="time",
            reason="" if passed else f"only {hours_since:.1f}h since last run (need {min_hours}h)",
        )
    return Gate(name="time", check=check, cost_rank=1)


def throttle_gate(state: dict, key: str = "last_scan", min_seconds: float = 600) -> Gate:
    """Gate 3: In-memory throttle. Cost: ~0μs."""
    def check() -> GateResult:
        last = state.get(key, 0)
        elapsed = time.time() - last
        passed = elapsed >= min_seconds
        return GateResult(
            passed=passed,
            gate_name="throttle",
            reason="" if passed else f"throttled ({elapsed:.0f}s < {min_seconds:.0f}s)",
        )
    return Gate(name="throttle", check=check, cost_rank=2)


def resource_gate(check_fn: Callable[[], bool], description: str) -> Gate:
    """Gate 4: Custom resource check (e.g., enough new sessions). Cost: ~5ms."""
    def check() -> GateResult:
        passed = check_fn()
        return GateResult(
            passed=passed,
            gate_name=f"resource:{description}",
            reason="" if passed else f"resource check failed: {description}",
        )
    return Gate(name=f"resource:{description}", check=check, cost_rank=3)
