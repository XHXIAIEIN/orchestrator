"""Channel 5-Level Routing + Least-Load Balancing.

Priority (highest first):
1. Binding: explicit task→channel binding (e.g., "send result to Telegram")
2. Direct: message arrived on a specific channel, reply on same
3. User Default: user's preferred channel (from profile)
4. Channel Default: the channel marked as default in config
5. Global Default: hardcoded fallback (usually Telegram)

When multiple channels are available at the same priority level,
the one with the lowest load score is selected. (R60 MinerU P1-1)
"""

import random
import threading
from dataclasses import dataclass, field


@dataclass
class ChannelRoute:
    channel: str       # "telegram" | "wechat" | "wecom" | "chat"
    level: int         # 1-5 priority level
    reason: str        # why this channel was chosen


@dataclass
class ChannelLoadState:
    """Per-channel load tracking for least-load routing.

    R60 MinerU steal — WorkerState.score() pattern:
    score = (queued + processing + pending) / max_concurrent
    pending_assignments is an optimistic counter: incremented BEFORE the
    send fires, so two concurrent callers see pre-inflated scores and split.
    """
    queued: int = 0
    processing: int = 0
    pending_assignments: int = 0
    max_concurrent: int = 10  # per-channel throughput cap

    def score(self) -> float:
        denom = max(1, self.max_concurrent)
        return (self.queued + self.processing + self.pending_assignments) / denom

    def acquire(self) -> None:
        """Optimistic pre-increment before sending."""
        self.pending_assignments += 1

    def release(self, *, started: bool = True) -> None:
        """Call after send completes (or fails)."""
        self.pending_assignments = max(0, self.pending_assignments - 1)

    def mark_processing(self) -> None:
        self.processing += 1

    def mark_done(self) -> None:
        self.processing = max(0, self.processing - 1)

    def enqueue(self) -> None:
        self.queued += 1

    def dequeue(self) -> None:
        self.queued = max(0, self.queued - 1)


class ChannelRouter:
    """Resolve which channel to use for outbound messages.

    R60 MinerU P1-1: when multiple channels are candidates at the same
    priority, select the one with the lowest load score. Same-score ties
    are broken by random shuffle (prevents hot-spot on alphabetically first).
    """

    def __init__(self, default_channel: str = "telegram"):
        self._bindings: dict[str, str] = {}  # task_id → channel
        self._user_defaults: dict[str, str] = {}  # user_id → channel
        self._channel_default: str = default_channel
        self._global_default: str = "telegram"
        self._load: dict[str, ChannelLoadState] = {}  # channel_name → load
        self._lock = threading.Lock()

    # ── Load tracking ──

    def register_channel(self, name: str, max_concurrent: int = 10) -> None:
        """Register a channel's throughput cap for load balancing."""
        with self._lock:
            self._load[name] = ChannelLoadState(max_concurrent=max_concurrent)

    def get_load(self, name: str) -> ChannelLoadState:
        """Get load state for a channel (auto-creates if unknown)."""
        with self._lock:
            if name not in self._load:
                self._load[name] = ChannelLoadState()
            return self._load[name]

    def acquire(self, name: str) -> None:
        """Optimistic pre-increment before sending to a channel."""
        self.get_load(name).acquire()

    def release(self, name: str) -> None:
        """Release after send completes."""
        self.get_load(name).release()

    def select_least_loaded(self, candidates: list[str]) -> str:
        """Pick the least-loaded channel from candidates.

        MinerU pattern: shuffle for tie-breaking, then sort by score.
        """
        if len(candidates) <= 1:
            return candidates[0] if candidates else self._global_default

        shuffled = list(candidates)
        random.shuffle(shuffled)
        shuffled.sort(key=lambda c: self.get_load(c).score())
        return shuffled[0]

    # ── Bindings ──

    def bind(self, task_id: str, channel: str):
        """Level 1: Explicitly bind a task to a channel."""
        self._bindings[task_id] = channel

    def set_user_default(self, user_id: str, channel: str):
        """Level 3: Set a user's preferred channel."""
        self._user_defaults[user_id] = channel

    def set_channel_default(self, channel: str):
        """Level 4: Set the channel-level default."""
        self._channel_default = channel

    def resolve(
        self,
        task_id: str | None = None,
        source_channel: str | None = None,
        user_id: str | None = None,
        candidates: list[str] | None = None,
    ) -> ChannelRoute:
        """Resolve the best channel using 5-level priority.

        If `candidates` is provided and the resolved level has multiple
        options, the least-loaded candidate is selected.
        """
        # Level 1: Binding
        if task_id and task_id in self._bindings:
            return ChannelRoute(self._bindings[task_id], 1, f"bound to task {task_id}")

        # Level 2: Direct (reply on same channel)
        if source_channel:
            return ChannelRoute(source_channel, 2, f"reply to source {source_channel}")

        # Level 3: User default
        if user_id and user_id in self._user_defaults:
            return ChannelRoute(self._user_defaults[user_id], 3, f"user {user_id} preference")

        # Level 4/5: Channel or global default — apply load balancing
        if candidates and len(candidates) > 1:
            best = self.select_least_loaded(candidates)
            return ChannelRoute(best, 4, f"least-loaded from {len(candidates)} candidates")

        # Level 4: Channel default
        if self._channel_default:
            return ChannelRoute(self._channel_default, 4, "channel default")

        # Level 5: Global default
        return ChannelRoute(self._global_default, 5, "global fallback")

    def unbind(self, task_id: str):
        """Remove a task binding."""
        self._bindings.pop(task_id, None)

    def load_summary(self) -> dict[str, dict]:
        """Snapshot of all channel loads for diagnostics."""
        with self._lock:
            return {
                name: {"score": round(s.score(), 3), "q": s.queued,
                       "p": s.processing, "pa": s.pending_assignments,
                       "max": s.max_concurrent}
                for name, s in self._load.items()
            }
