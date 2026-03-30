"""
Waiver Registry — temporary rule exemptions with expiration.

Stolen from phodal/entrix (Round 15, P1):
  Waivers let you temporarily exempt a fitness rule from enforcement.
  Each waiver declares reason/owner/issue/expires_at. When it expires,
  the rule automatically resumes enforcement — no manual intervention.

  This turns "known tech debt" from invisible rot into a tracked,
  time-bounded commitment.

Usage:
  registry = WaiverRegistry()
  registry.register(Waiver(
      rule_id="test-coverage",
      reason="Migrating test framework, coverage temporarily drops",
      owner="礼部",
      issue_ref="orchestrator#42",
      created_at="2026-03-31T00:00:00+08:00",
      expires_at="2026-04-14T00:00:00+08:00",
  ))

  if registry.is_waived("test-coverage"):
      ...  # skip enforcement

  expired = registry.check_expired()  # auto-detect overdue waivers
  registry.enforce_expired()          # mark them inactive
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# YAML I/O helpers (avoid hard PyYAML dep — use it if available, else minimal)
# ---------------------------------------------------------------------------

try:
    import yaml

    def _yaml_load(path: Path) -> list[dict]:
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        return data if isinstance(data, list) else []

    def _yaml_dump(data: list[dict], path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

except ImportError:
    # Minimal fallback: flat key-value per entry, separated by "---"
    import json

    def _yaml_load(path: Path) -> list[dict]:  # type: ignore[misc]
        text = path.read_text(encoding="utf-8")
        return json.loads(text) if text.strip() else []

    def _yaml_dump(data: list[dict], path: Path) -> None:  # type: ignore[misc]
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Waiver:
    """A temporary exemption for a fitness rule."""

    rule_id: str
    reason: str
    owner: str
    expires_at: str  # ISO 8601
    created_at: str = ""  # ISO 8601, auto-filled if empty
    issue_ref: str = ""  # optional issue/ticket reference
    active: bool = True

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    @property
    def is_expired(self) -> bool:
        """Check if this waiver has passed its expiration time."""
        try:
            expires = datetime.fromisoformat(self.expires_at)
            # Ensure timezone-aware comparison
            now = datetime.now(timezone.utc)
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            return now > expires
        except (ValueError, TypeError):
            # Unparseable date = treat as expired (fail-safe)
            log.warning("waiver: unparseable expires_at '%s' for rule %s, treating as expired",
                        self.expires_at, self.rule_id)
            return True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Waiver:
        return cls(
            rule_id=data.get("rule_id", ""),
            reason=data.get("reason", ""),
            owner=data.get("owner", ""),
            expires_at=data.get("expires_at", ""),
            created_at=data.get("created_at", ""),
            issue_ref=data.get("issue_ref", ""),
            active=data.get("active", True),
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class WaiverRegistry:
    """Manages a collection of rule waivers with YAML persistence."""

    def __init__(self, waiver_file: str = "data/waivers.yaml"):
        self.path = Path(waiver_file)
        self._waivers: dict[str, Waiver] = {}  # keyed by rule_id
        self.load()

    # --- Core operations ---

    def register(self, waiver: Waiver) -> None:
        """Register a new waiver (overwrites existing waiver for same rule_id)."""
        self._waivers[waiver.rule_id] = waiver
        self.save()
        log.info("waiver: registered for rule '%s' (owner=%s, expires=%s)",
                 waiver.rule_id, waiver.owner, waiver.expires_at)

    def revoke(self, rule_id: str) -> bool:
        """Revoke (deactivate) a waiver by rule_id. Returns True if found."""
        waiver = self._waivers.get(rule_id)
        if waiver is None:
            log.warning("waiver: cannot revoke '%s' — not found", rule_id)
            return False
        waiver.active = False
        self.save()
        log.info("waiver: revoked for rule '%s'", rule_id)
        return True

    def is_waived(self, rule_id: str) -> bool:
        """Check if a rule is currently under active, non-expired waiver."""
        waiver = self._waivers.get(rule_id)
        if waiver is None:
            return False
        return waiver.active and not waiver.is_expired

    def get(self, rule_id: str) -> Waiver | None:
        """Get waiver for a rule_id, or None."""
        return self._waivers.get(rule_id)

    # --- Expiration management ---

    def check_expired(self) -> list[Waiver]:
        """Return all waivers that are active but past their expiration."""
        return [w for w in self._waivers.values() if w.active and w.is_expired]

    def enforce_expired(self) -> list[Waiver]:
        """Deactivate all expired waivers. Returns the list of newly deactivated ones."""
        expired = self.check_expired()
        for w in expired:
            w.active = False
            log.info("waiver: expired and deactivated — rule '%s' (was: %s)", w.rule_id, w.reason)
        if expired:
            self.save()
        return expired

    # --- Listing ---

    def list_active(self) -> list[Waiver]:
        """List all active (non-expired) waivers."""
        return [w for w in self._waivers.values() if w.active and not w.is_expired]

    def list_all(self) -> list[Waiver]:
        """List all waivers regardless of status."""
        return list(self._waivers.values())

    # --- Persistence ---

    def load(self) -> None:
        """Load waivers from YAML file."""
        if not self.path.exists():
            self._waivers = {}
            return
        try:
            data = _yaml_load(self.path)
            self._waivers = {
                d["rule_id"]: Waiver.from_dict(d)
                for d in data
                if isinstance(d, dict) and "rule_id" in d
            }
            log.debug("waiver: loaded %d waivers from %s", len(self._waivers), self.path)
        except Exception as e:
            log.error("waiver: failed to load %s: %s", self.path, e)
            self._waivers = {}

    def save(self) -> None:
        """Persist waivers to YAML file."""
        data = [w.to_dict() for w in self._waivers.values()]
        try:
            _yaml_dump(data, self.path)
            log.debug("waiver: saved %d waivers to %s", len(data), self.path)
        except Exception as e:
            log.error("waiver: failed to save %s: %s", self.path, e)
