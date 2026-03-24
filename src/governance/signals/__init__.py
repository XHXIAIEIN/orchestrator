# src/governance/signals/__init__.py
from .cross_dept import (
    Signal, SignalBus, SignalType, SignalStatus, SignalPriority,
    signal_vulnerability, signal_pattern_failure, signal_retest,
    check_sibling_rule,
)

__all__ = [
    "Signal", "SignalBus", "SignalType", "SignalStatus", "SignalPriority",
    "signal_vulnerability", "signal_pattern_failure", "signal_retest",
    "check_sibling_rule",
]
