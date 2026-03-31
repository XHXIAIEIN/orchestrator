"""Tool Concurrency Safety Classifier.

Stolen from Claude Code v2.1.88 StreamingToolExecutor.isConcurrencySafe().
Declares which tools can safely run in parallel and which must run exclusively.

Conservative default: unlisted tools are treated as unsafe.

Usage:
    classifier = ConcurrencyClassifier()
    classifier.is_concurrent_safe("Read")   # True
    classifier.is_concurrent_safe("Edit")   # False
    classifier.can_run_together("Grep", "Glob")   # True
    classifier.can_run_together("Edit", "Write")   # False
"""
import fnmatch
import logging
from pathlib import Path
from typing import Literal

import yaml

log = logging.getLogger(__name__)

ConcurrencyClass = Literal["safe", "unsafe", "guarded"]

_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "tool_concurrency.yaml"


class ConcurrencyClassifier:
    """Classifies tools by concurrency safety.

    Loads from YAML config with hot-reload on file change.
    """

    def __init__(self, config_path: str | Path = _CONFIG_PATH):
        self._config_path = Path(config_path)
        self._safe: set[str] = set()
        self._unsafe_patterns: list[str] = []
        self._guard_groups: dict[str, set[str]] = {}
        self._file_mtime: float = 0
        self._load()

    def _load(self):
        """Load or reload config from YAML."""
        if not self._config_path.exists():
            log.warning(f"ConcurrencyClassifier: config not found at {self._config_path}, using defaults")
            self._safe = {"Read", "Glob", "Grep", "LS", "WebSearch", "WebFetch"}
            return

        try:
            mtime = self._config_path.stat().st_mtime
            if mtime == self._file_mtime:
                return  # No change

            with open(self._config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            self._safe = set(data.get("safe", []))
            self._unsafe_patterns = [p for p in data.get("unsafe", []) if "*" in str(p)]
            self._guard_groups = {}
            for group_name, tools in (data.get("guarded", {}) or {}).items():
                self._guard_groups[group_name] = set(tools or [])

            self._file_mtime = mtime
            log.info(
                f"ConcurrencyClassifier: loaded {len(self._safe)} safe, "
                f"{len(self._unsafe_patterns)} unsafe patterns, "
                f"{len(self._guard_groups)} guard groups"
            )
        except Exception as e:
            log.error(f"ConcurrencyClassifier: failed to load config: {e}")

    def _maybe_reload(self):
        """Check file mtime and reload if changed."""
        try:
            if self._config_path.exists():
                mtime = self._config_path.stat().st_mtime
                if mtime != self._file_mtime:
                    self._load()
        except Exception:
            pass

    def classify(self, tool_name: str) -> ConcurrencyClass:
        """Classify a tool's concurrency safety.

        Returns 'safe', 'unsafe', or 'guarded'.
        """
        self._maybe_reload()

        if tool_name in self._safe:
            return "safe"

        # Check guard groups
        for _group_name, tools in self._guard_groups.items():
            if tool_name in tools:
                return "guarded"

        # Check wildcard unsafe patterns
        for pattern in self._unsafe_patterns:
            if fnmatch.fnmatch(tool_name, pattern):
                return "unsafe"

        # Default: unsafe (conservative)
        return "unsafe"

    def is_concurrent_safe(self, tool_name: str) -> bool:
        """Convenience: True if tool can run in parallel with anything."""
        return self.classify(tool_name) == "safe"

    def get_guard_group(self, tool_name: str) -> str | None:
        """Return the guard group name, or None if tool isn't guarded."""
        self._maybe_reload()
        for group_name, tools in self._guard_groups.items():
            if tool_name in tools:
                return group_name
        return None

    def can_run_together(self, tool_a: str, tool_b: str) -> bool:
        """Check if two tools can run concurrently.

        Rules:
        - safe + anything = True
        - guarded + same group = True
        - guarded + different group = False
        - unsafe + anything non-safe = False
        """
        class_a = self.classify(tool_a)
        class_b = self.classify(tool_b)

        if class_a == "safe" or class_b == "safe":
            return True

        if class_a == "guarded" and class_b == "guarded":
            return self.get_guard_group(tool_a) == self.get_guard_group(tool_b)

        return False


# ── Singleton ──

_instance: ConcurrencyClassifier | None = None


def get_concurrency_classifier() -> ConcurrencyClassifier:
    """Get or create the singleton ConcurrencyClassifier."""
    global _instance
    if _instance is None:
        _instance = ConcurrencyClassifier()
    return _instance
