"""R62 DeerFlow: Dual-Layer Loop Detection — Hash + Frequency.

Layer 1 (Hash): Order-independent md5 hash of tool call sets.
  Catches exact repetition of the same tool+args combination.

Layer 2 (Frequency): Per-tool-type call counters with configurable limits.
  Catches "read 40 different files" scenarios where hash detection fails
  (same tool, different args each time).

Integration: Governor._run_agent_session checks after each agent turn.
Complements the existing doom_loop.py (which checks event DB post-hoc)
and loop-detector.sh (which checks individual tool calls in hooks).

Source: DeerFlow 2.0 LoopDetectionMiddleware (R62 deep steal)
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections import OrderedDict
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class LoopDetectionConfig:
    """Thresholds for dual-layer loop detection."""
    # Layer 1: Hash detection
    hash_window_size: int = 8        # how many recent turn-hashes to keep
    hash_repeat_warn: int = 2        # warn at N identical hashes
    hash_repeat_stop: int = 3        # hard stop at N identical hashes

    # Layer 2: Frequency detection — per-tool limits
    freq_window_turns: int = 15      # sliding window of turns
    default_tool_limit: int = 20     # default max calls per tool type
    tool_limits: dict[str, int] = field(default_factory=lambda: {
        "Read": 30,       # read is common, higher limit
        "Grep": 25,
        "Glob": 20,
        "Edit": 10,       # editing same file repeatedly = bad sign
        "Write": 8,
        "Bash": 15,
    })

    # Special handling: read_file tools grouped by directory
    bucket_by_dir: set[str] = field(default_factory=lambda: {"Read", "Grep"})
    dir_bucket_limit: int = 8  # max reads from same directory


@dataclass
class LoopWarning:
    """Result from loop detection."""
    level: str  # "ok" | "warn" | "stop"
    layer: str  # "hash" | "freq" | "dir_bucket"
    message: str
    details: dict = field(default_factory=dict)

    @property
    def should_warn(self) -> bool:
        return self.level == "warn"

    @property
    def should_stop(self) -> bool:
        return self.level == "stop"


def _normalize_tool_call(tool_call: dict) -> str:
    """Normalize a tool call for stable hashing.

    Sort keys, truncate values, produce deterministic string.
    """
    name = tool_call.get("name", tool_call.get("tool", ""))
    args = tool_call.get("args", tool_call.get("input", {}))

    if isinstance(args, dict):
        # Sort keys, truncate values for stability
        normalized = {k: str(v)[:200] for k, v in sorted(args.items())}
    else:
        normalized = str(args)[:200]

    return f"{name}:{json.dumps(normalized, sort_keys=True, ensure_ascii=False)}"


def _hash_tool_calls(tool_calls: list[dict]) -> str:
    """Order-independent hash of a set of tool calls.

    DeerFlow insight: hash the sorted set, not individual calls.
    This catches "same 3 tools in different order" as a single pattern.
    """
    normalized = sorted(_normalize_tool_call(tc) for tc in tool_calls)
    payload = "\n".join(normalized)
    return hashlib.md5(payload.encode()).hexdigest()[:16]


def _extract_dir(tool_call: dict) -> str | None:
    """Extract directory from a file-oriented tool call."""
    args = tool_call.get("args", tool_call.get("input", {}))
    if isinstance(args, dict):
        for key in ("file_path", "path", "file"):
            val = args.get(key, "")
            if val and "/" in str(val):
                parts = str(val).replace("\\", "/").rsplit("/", 1)
                return parts[0] if len(parts) > 1 else ""
    return None


class LoopDetector:
    """Dual-layer loop detection for agent turns.

    Usage:
        detector = LoopDetector()
        # After each agent turn:
        result = detector.check_turn(tool_calls)
        if result.should_stop:
            # inject warning, force stop
        elif result.should_warn:
            # inject warning message
    """

    def __init__(self, config: LoopDetectionConfig | None = None):
        self.config = config or LoopDetectionConfig()

        # Layer 1 state: recent turn hashes
        self._hash_window: list[str] = []

        # Layer 2 state: per-tool call counts in sliding window
        self._turn_history: list[list[dict]] = []  # list of tool_calls per turn

        # Per-thread tracking (OrderedDict as LRU)
        self._thread_states: OrderedDict[str, "LoopDetector"] = OrderedDict()

    def check_turn(self, tool_calls: list[dict]) -> LoopWarning:
        """Check a single agent turn for loop patterns.

        Args:
            tool_calls: list of tool call dicts from this turn,
                each with 'name'/'tool' and 'args'/'input' keys.

        Returns:
            LoopWarning with level and details.
        """
        if not tool_calls:
            return LoopWarning(level="ok", layer="hash", message="")

        # ── Layer 1: Hash detection ──
        turn_hash = _hash_tool_calls(tool_calls)
        self._hash_window.append(turn_hash)
        if len(self._hash_window) > self.config.hash_window_size:
            self._hash_window = self._hash_window[-self.config.hash_window_size:]

        hash_count = self._hash_window.count(turn_hash)

        if hash_count >= self.config.hash_repeat_stop:
            msg = (
                f"LOOP DETECTED: Identical tool call pattern repeated "
                f"{hash_count}× in last {self.config.hash_window_size} turns. "
                f"You are stuck. Change your approach fundamentally."
            )
            log.warning("loop_detection: hash-stop — %s", msg)
            return LoopWarning(
                level="stop", layer="hash", message=msg,
                details={"hash": turn_hash, "count": hash_count},
            )

        if hash_count >= self.config.hash_repeat_warn:
            msg = (
                f"Repetition warning: Same tool pattern {hash_count}× "
                f"in last {self.config.hash_window_size} turns."
            )
            log.info("loop_detection: hash-warn — %s", msg)
            return LoopWarning(
                level="warn", layer="hash", message=msg,
                details={"hash": turn_hash, "count": hash_count},
            )

        # ── Layer 2: Frequency detection ──
        self._turn_history.append(tool_calls)
        if len(self._turn_history) > self.config.freq_window_turns:
            self._turn_history = self._turn_history[-self.config.freq_window_turns:]

        # Count per-tool usage across the window
        tool_counts: dict[str, int] = {}
        dir_counts: dict[str, int] = {}

        for turn in self._turn_history:
            for tc in turn:
                name = tc.get("name", tc.get("tool", "unknown"))
                tool_counts[name] = tool_counts.get(name, 0) + 1

                # Directory bucketing for read-heavy tools
                if name in self.config.bucket_by_dir:
                    d = _extract_dir(tc)
                    if d:
                        bucket_key = f"{name}:{d}"
                        dir_counts[bucket_key] = dir_counts.get(bucket_key, 0) + 1

        # Check per-tool limits
        for tool_name, count in tool_counts.items():
            limit = self.config.tool_limits.get(
                tool_name, self.config.default_tool_limit
            )
            if count >= limit:
                msg = (
                    f"Tool frequency limit: {tool_name} called {count}× "
                    f"in last {self.config.freq_window_turns} turns "
                    f"(limit: {limit}). Consider a different approach."
                )
                log.warning("loop_detection: freq-stop — %s", msg)
                return LoopWarning(
                    level="stop", layer="freq", message=msg,
                    details={"tool": tool_name, "count": count, "limit": limit},
                )

        # Check directory bucket limits
        for bucket_key, count in dir_counts.items():
            if count >= self.config.dir_bucket_limit:
                msg = (
                    f"Directory saturation: {bucket_key} accessed {count}× "
                    f"in last {self.config.freq_window_turns} turns "
                    f"(limit: {self.config.dir_bucket_limit}). "
                    f"Read the whole directory at once instead of file by file."
                )
                log.info("loop_detection: dir-bucket-warn — %s", msg)
                return LoopWarning(
                    level="warn", layer="dir_bucket", message=msg,
                    details={"bucket": bucket_key, "count": count},
                )

        return LoopWarning(level="ok", layer="hash", message="")

    def reset(self):
        """Clear all state (new conversation)."""
        self._hash_window.clear()
        self._turn_history.clear()

    def get_stats(self) -> dict:
        """Return current detection state for diagnostics."""
        tool_counts: dict[str, int] = {}
        for turn in self._turn_history:
            for tc in turn:
                name = tc.get("name", tc.get("tool", "unknown"))
                tool_counts[name] = tool_counts.get(name, 0) + 1

        return {
            "hash_window_size": len(self._hash_window),
            "turn_history_size": len(self._turn_history),
            "tool_counts": tool_counts,
            "unique_hashes": len(set(self._hash_window)),
        }
