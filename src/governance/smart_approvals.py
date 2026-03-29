"""Smart Approvals — stolen from Hermes.

Learns from approval decisions to auto-approve safe commands.
Tracks command patterns and their approval history. Commands
approved N times without denial are promoted to auto-approve.

Complements TrustLadder (operation-level trust) with command-level trust.

Usage:
    approvals = SmartApprovals()
    # Record decisions
    approvals.record("git push origin feature-branch", "approve")
    approvals.record("git push origin feature-branch", "approve")
    # After threshold, auto-approve
    assert approvals.should_auto_approve("git push origin feature-branch")
    # Deny resets trust
    approvals.record("rm -rf /tmp/data", "deny")
    assert not approvals.should_auto_approve("rm -rf /tmp/data")
"""
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)

DEFAULT_APPROVE_THRESHOLD = 2  # approved N times -> auto-approve
DEFAULT_DECAY_DAYS = 7         # trust decays after N days without use


@dataclass
class CommandRecord:
    """Tracks approval history for a command pattern."""
    pattern: str
    approvals: int = 0
    denials: int = 0
    last_approved: float = 0.0
    last_denied: float = 0.0
    auto_approved_count: int = 0

    @property
    def net_trust(self) -> int:
        """Net trust score: approvals minus denials."""
        return self.approvals - (self.denials * 3)  # denials weigh more


def normalize_command(command: str) -> str:
    """Normalize a command for pattern matching.

    Strips variable parts (paths, IDs, timestamps) to group similar commands.
    """
    normalized = command.strip()
    # Replace UUIDs
    normalized = re.sub(
        r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
        '<UUID>', normalized,
    )
    # Replace numbers (but keep small ones like port numbers)
    normalized = re.sub(r'\b\d{5,}\b', '<NUM>', normalized)
    # Replace quoted strings
    normalized = re.sub(r'"[^"]*"', '"<STR>"', normalized)
    normalized = re.sub(r"'[^']*'", "'<STR>'", normalized)
    return normalized


class SmartApprovals:
    """Learn from approval decisions and auto-approve trusted commands."""

    def __init__(self, threshold: int = DEFAULT_APPROVE_THRESHOLD,
                 decay_days: int = DEFAULT_DECAY_DAYS):
        self._threshold = threshold
        self._decay_days = decay_days
        self._records: dict[str, CommandRecord] = {}
        self._stats = {"auto_approved": 0, "recorded": 0}

    def record(self, command: str, decision: str):
        """Record an approval decision for a command.

        Args:
            command: The command string
            decision: "approve" or "deny"
        """
        pattern = normalize_command(command)
        if pattern not in self._records:
            self._records[pattern] = CommandRecord(pattern=pattern)

        record = self._records[pattern]
        now = time.time()

        if decision == "approve":
            record.approvals += 1
            record.last_approved = now
        elif decision == "deny":
            record.denials += 1
            record.last_denied = now
            # Denial resets approval count (safety first)
            record.approvals = 0

        self._stats["recorded"] += 1
        log.debug(f"smart_approvals: recorded {decision} for '{pattern}' "
                  f"(approvals={record.approvals}, denials={record.denials})")

    def should_auto_approve(self, command: str) -> bool:
        """Check if a command should be auto-approved based on history."""
        pattern = normalize_command(command)
        record = self._records.get(pattern)

        if not record:
            return False

        # Must meet threshold
        if record.approvals < self._threshold:
            return False

        # Must not have recent denial
        if record.denials > 0 and record.last_denied > record.last_approved:
            return False

        # Check decay
        if self._decay_days >= 0 and record.last_approved > 0:
            days_since = (time.time() - record.last_approved) / 86400
            if days_since > self._decay_days:
                return False

        record.auto_approved_count += 1
        self._stats["auto_approved"] += 1
        log.info(f"smart_approvals: auto-approved '{pattern}'")
        return True

    def get_trusted_commands(self) -> list[dict]:
        """List all commands that would be auto-approved."""
        trusted = []
        for pattern, record in self._records.items():
            if record.approvals >= self._threshold and record.denials == 0:
                trusted.append({
                    "pattern": pattern,
                    "approvals": record.approvals,
                    "auto_approved": record.auto_approved_count,
                })
        return trusted

    def revoke_trust(self, command: str):
        """Manually revoke trust for a command pattern."""
        pattern = normalize_command(command)
        if pattern in self._records:
            self._records[pattern].approvals = 0
            self._records[pattern].denials += 1
            log.info(f"smart_approvals: revoked trust for '{pattern}'")

    def get_stats(self) -> dict:
        return {
            **self._stats,
            "tracked_commands": len(self._records),
            "trusted_commands": len(self.get_trusted_commands()),
        }
