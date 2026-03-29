"""FutureGate — Future-based blocking coordination.

Stolen from ChatDev 2.0's server/services/session_execution.py.
Replaces DB-polling for approval/human-input with memory-level notification.
"""
from __future__ import annotations

import logging
import time
import threading
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


class GateTimeout(Exception):
    pass

class GateCancelled(Exception):
    pass


@dataclass
class _GateEntry:
    gate_id: str
    label: str
    future: Future
    cancel_event: threading.Event = field(default_factory=threading.Event)
    cancel_reason: str = ""
    created_at: float = field(default_factory=time.time)


class FutureGate:
    def __init__(self):
        self._gates: dict[str, _GateEntry] = {}
        self._lock = threading.Lock()
        self._counter = 0

    def open(self, label: str = "") -> str:
        with self._lock:
            self._counter += 1
            gate_id = f"gate_{self._counter}"
            self._gates[gate_id] = _GateEntry(gate_id=gate_id, label=label, future=Future())
            log.debug(f"FutureGate: opened {gate_id} ({label})")
            return gate_id

    def wait(self, gate_id: str, timeout: float = 300.0) -> Any:
        with self._lock:
            entry = self._gates.get(gate_id)
            if not entry:
                raise KeyError(f"Gate {gate_id} not found")
        try:
            start = time.time()
            poll_interval = 1.0
            while True:
                if entry.cancel_event.is_set():
                    raise GateCancelled(entry.cancel_reason or "cancelled")
                elapsed = time.time() - start
                remaining = timeout - elapsed
                if remaining <= 0:
                    raise GateTimeout(f"Gate {gate_id} timed out after {timeout}s")
                try:
                    result = entry.future.result(timeout=min(poll_interval, remaining))
                    return result
                except TimeoutError:
                    continue
                except Exception:
                    if entry.cancel_event.is_set():
                        raise GateCancelled(entry.cancel_reason or "cancelled")
                    raise
        finally:
            self._cleanup(gate_id)

    def provide(self, gate_id: str, value: Any):
        with self._lock:
            entry = self._gates.get(gate_id)
            if not entry:
                log.warning(f"FutureGate: provide called on unknown gate {gate_id}")
                return
        if not entry.future.done():
            entry.future.set_result(value)

    def cancel(self, gate_id: str, reason: str = ""):
        with self._lock:
            entry = self._gates.get(gate_id)
            if not entry:
                return
        entry.cancel_reason = reason
        entry.cancel_event.set()
        if not entry.future.done():
            entry.future.cancel()

    def is_waiting(self, gate_id: str) -> bool:
        with self._lock:
            entry = self._gates.get(gate_id)
            if not entry:
                return False
            return not entry.future.done() and not entry.cancel_event.is_set()

    def status(self, gate_id: str) -> dict:
        with self._lock:
            entry = self._gates.get(gate_id)
            if not entry:
                return {"exists": False}
            return {"exists": True, "gate_id": gate_id, "label": entry.label,
                    "done": entry.future.done(), "cancelled": entry.cancel_event.is_set(),
                    "age_s": round(time.time() - entry.created_at, 1)}

    def _cleanup(self, gate_id: str):
        with self._lock:
            self._gates.pop(gate_id, None)
