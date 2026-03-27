"""Channel 5-Level Routing — determines which channel handles a message.

Priority (highest first):
1. Binding: explicit task→channel binding (e.g., "send result to Telegram")
2. Direct: message arrived on a specific channel, reply on same
3. User Default: user's preferred channel (from profile)
4. Channel Default: the channel marked as default in config
5. Global Default: hardcoded fallback (usually Telegram)
"""

from dataclasses import dataclass


@dataclass
class ChannelRoute:
    channel: str       # "telegram" | "wechat" | "wecom" | "chat"
    level: int         # 1-5 priority level
    reason: str        # why this channel was chosen


class ChannelRouter:
    """Resolve which channel to use for outbound messages."""

    def __init__(self, default_channel: str = "telegram"):
        self._bindings: dict[str, str] = {}  # task_id → channel
        self._user_defaults: dict[str, str] = {}  # user_id → channel
        self._channel_default: str = default_channel
        self._global_default: str = "telegram"

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
    ) -> ChannelRoute:
        """Resolve the best channel using 5-level priority."""
        # Level 1: Binding
        if task_id and task_id in self._bindings:
            return ChannelRoute(self._bindings[task_id], 1, f"bound to task {task_id}")

        # Level 2: Direct (reply on same channel)
        if source_channel:
            return ChannelRoute(source_channel, 2, f"reply to source {source_channel}")

        # Level 3: User default
        if user_id and user_id in self._user_defaults:
            return ChannelRoute(self._user_defaults[user_id], 3, f"user {user_id} preference")

        # Level 4: Channel default
        if self._channel_default:
            return ChannelRoute(self._channel_default, 4, "channel default")

        # Level 5: Global default
        return ChannelRoute(self._global_default, 5, "global fallback")

    def unbind(self, task_id: str):
        """Remove a task binding."""
        self._bindings.pop(task_id, None)
