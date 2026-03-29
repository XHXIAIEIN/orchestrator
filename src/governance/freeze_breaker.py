"""Auto-Freeze Circuit Breaker — stolen from OpenAkita OrgRuntime.

Detects agent sessions spinning without doing useful work:
- No tool calls for N consecutive turns → idle_spin
- Consistently tiny output → low_output

Complements StuckDetector (repetitive actions) and DoomLoop (broad patterns).
This catches the "thinking but not doing" case.
"""
import logging

log = logging.getLogger(__name__)


class FreezeBreaker:
    """Track agent turn activity and trigger freeze on idle spinning."""

    def __init__(self, idle_threshold: int = 5, min_useful_text: int = 10):
        """
        Args:
            idle_threshold: Consecutive idle turns before freeze.
            min_useful_text: Minimum text length to count as "useful output".
        """
        self.idle_threshold = idle_threshold
        self.min_useful_text = min_useful_text
        self._consecutive_idle = 0
        self._frozen = False
        self._reason = ""
        self._total_turns = 0

    def record_turn(self, tool_calls: int, text_len: int):
        """Record a turn's activity. Call after each AssistantMessage."""
        self._total_turns += 1
        if tool_calls > 0:
            self._consecutive_idle = 0
        elif text_len < self.min_useful_text:
            self._consecutive_idle += 1
        else:
            self._consecutive_idle += 1

    def should_freeze(self) -> bool:
        """Check if agent should be frozen."""
        if self._frozen:
            return True
        if self._consecutive_idle >= self.idle_threshold:
            self._frozen = True
            self._reason = "idle_spin"
            log.warning(
                f"FreezeBreaker: frozen after {self._consecutive_idle} "
                f"consecutive idle turns (total: {self._total_turns})"
            )
            return True
        return False

    @property
    def reason(self) -> str:
        return self._reason

    def get_status(self) -> dict:
        return {
            "consecutive_idle": self._consecutive_idle,
            "total_turns": self._total_turns,
            "frozen": self._frozen,
            "reason": self._reason,
        }
