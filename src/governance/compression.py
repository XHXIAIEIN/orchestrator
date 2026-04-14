"""Ratio-Based Context Compression — stolen from Hermes.

Replaces fixed token targets with dynamic ratio-based compression.
Adapts to different model context windows automatically.

Config:
    target_ratio: 0.6    # Compress to 60% of current size
    protect_last_n: 5    # Never compress the last 5 turns
    threshold: 0.8       # Only compress when context fills 80% of window

Usage:
    compressor = ContextCompressor(
        max_context_tokens=100000,
        target_ratio=0.6,
        protect_last_n=5,
        threshold=0.8,
    )
    # After each turn:
    compressor.add_turn(role="assistant", content="...", tokens=500)
    if compressor.should_compress():
        summary = compressor.compress()
"""
import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# Default configs per model tier
COMPRESSION_PRESETS = {
    "haiku": {"max_tokens": 100_000, "target_ratio": 0.5, "protect_last_n": 3, "threshold": 0.7},
    "sonnet": {"max_tokens": 200_000, "target_ratio": 0.6, "protect_last_n": 5, "threshold": 0.8},
    "opus":  {"max_tokens": 1_000_000, "target_ratio": 0.7, "protect_last_n": 8, "threshold": 0.85},
}


@dataclass
class Turn:
    """A single conversation turn."""
    role: str          # "user", "assistant", "tool"
    content: str
    tokens: int
    protected: bool = False  # if True, never compressed


class ContextCompressor:
    """Dynamic context compression with ratio-based targeting."""

    def __init__(
        self,
        max_context_tokens: int = 200_000,
        target_ratio: float = 0.6,
        protect_last_n: int = 5,
        threshold: float = 0.8,
    ):
        self.max_context_tokens = max_context_tokens
        self.target_ratio = target_ratio
        self.protect_last_n = protect_last_n
        self.threshold = threshold
        self._turns: list[Turn] = []
        self._total_tokens = 0
        self._compressions = 0

    @classmethod
    def from_model(cls, model_name: str) -> "ContextCompressor":
        """Create compressor with preset for a model tier."""
        model_lower = model_name.lower()
        for tier, preset in COMPRESSION_PRESETS.items():
            if tier in model_lower:
                return cls(
                    max_context_tokens=preset["max_tokens"],
                    target_ratio=preset["target_ratio"],
                    protect_last_n=preset["protect_last_n"],
                    threshold=preset["threshold"],
                )
        # Default to sonnet preset
        p = COMPRESSION_PRESETS["sonnet"]
        return cls(
            max_context_tokens=p["max_tokens"],
            target_ratio=p["target_ratio"],
            protect_last_n=p["protect_last_n"],
            threshold=p["threshold"],
        )

    def add_turn(self, role: str, content: str, tokens: int = 0):
        """Record a new turn."""
        if tokens == 0:
            tokens = max(len(content) // 3, 1)  # rough estimate
        self._turns.append(Turn(role=role, content=content, tokens=tokens))
        self._total_tokens += tokens

    @property
    def usage_ratio(self) -> float:
        """Current context usage as ratio of max."""
        return self._total_tokens / self.max_context_tokens if self.max_context_tokens > 0 else 0

    def should_compress(self) -> bool:
        """Check if compression is needed based on threshold."""
        return self.usage_ratio >= self.threshold

    def compress(self) -> dict:
        """Compress older turns to fit within target ratio.

        Returns dict with compression details.
        """
        if not self._turns:
            return {"compressed": False, "reason": "no turns"}

        target_tokens = int(self.max_context_tokens * self.target_ratio)
        if self._total_tokens <= target_tokens:
            return {"compressed": False, "reason": "within target"}

        # Protect last N turns
        protect_count = min(self.protect_last_n, len(self._turns))
        protected = self._turns[-protect_count:]
        compressible = self._turns[:-protect_count] if protect_count < len(self._turns) else []

        if not compressible:
            return {"compressed": False, "reason": "all turns protected"}

        # Calculate how much to cut
        protected_tokens = sum(t.tokens for t in protected)
        available = target_tokens - protected_tokens
        compressible_tokens = sum(t.tokens for t in compressible)

        if available <= 0:
            # Even protected turns exceed target — just summarize everything compressible
            summary_content = self._summarize_turns(compressible)
            summary_tokens = max(len(summary_content) // 3, 1)
        else:
            # Compress to fit available budget
            ratio = available / compressible_tokens if compressible_tokens > 0 else 1.0
            if ratio >= 1.0:
                return {"compressed": False, "reason": "compression not needed after protecting"}

            summary_content = self._summarize_turns(compressible)
            summary_tokens = max(len(summary_content) // 3, 1)

        # Replace compressible turns with summary
        summary_turn = Turn(
            role="system",
            content=summary_content,
            tokens=summary_tokens,
            protected=True,
        )
        self._turns = [summary_turn] + protected
        old_total = self._total_tokens
        self._total_tokens = summary_tokens + protected_tokens
        self._compressions += 1

        saved = old_total - self._total_tokens
        log.info(
            f"compression: {old_total} → {self._total_tokens} tokens "
            f"({saved} saved, {len(compressible)} turns compressed)"
        )

        return {
            "compressed": True,
            "tokens_before": old_total,
            "tokens_after": self._total_tokens,
            "tokens_saved": saved,
            "turns_compressed": len(compressible),
            "turns_remaining": len(self._turns),
        }

    def _summarize_turns(self, turns: list[Turn], focus_topic: str = "") -> str:
        """Create a concise summary of compressed turns.

        Parameters
        ----------
        turns:
            待压缩的 turn 列表。
        focus_topic:
            焦点话题。非空时，与该话题相关的内容保留完整细节，
            其余内容激进压缩。焦点指令置于 prompt 末尾（利用 recency bias）。
            该话题的摘要 token 预算约占 60-70%。
        """
        parts = [f"<COMPRESSED_HISTORY turns={len(turns)}>"]
        for t in turns:
            preview = t.content[:100].replace("\n", " ")
            parts.append(f"  [{t.role}] {preview}...")
        parts.append("</COMPRESSED_HISTORY>")
        summary = "\n".join(parts)

        if focus_topic:
            # 焦点指令追加在末尾，利用模型的 recency bias 确保优先权
            summary += (
                f"\n\n<!-- FOCUS: {focus_topic!r} — "
                f"上述内容中与 {focus_topic!r} 相关的部分请保留完整细节 "
                f"（精确数值、文件路径、命令输出、错误信息、决策）；"
                f"无关内容一行概括或省略。"
                f"焦点内容应占摘要 token 预算的 60-70%。 -->"
            )

        return summary

    def compress_with_focus(self, focus_topic: str) -> dict:
        """按焦点话题压缩，相关内容保留更多细节。

        等同于 compress()，但将 focus_topic 传入 _summarize_turns()。
        当用户执行 /compress <topic> 时调用此方法。

        Parameters
        ----------
        focus_topic:
            需要重点保留的话题关键词，如 "数据库迁移" 或 "登录 bug"。
        """
        if not self._turns:
            return {"compressed": False, "reason": "no turns"}

        target_tokens = int(self.max_context_tokens * self.target_ratio)
        if self._total_tokens <= target_tokens:
            return {"compressed": False, "reason": "within target"}

        protect_count = min(self.protect_last_n, len(self._turns))
        protected = self._turns[-protect_count:]
        compressible = self._turns[:-protect_count] if protect_count < len(self._turns) else []

        if not compressible:
            return {"compressed": False, "reason": "all turns protected"}

        protected_tokens = sum(t.tokens for t in protected)

        # 传入 focus_topic，让摘要侧重该话题
        summary_content = self._summarize_turns(compressible, focus_topic=focus_topic)
        summary_tokens = max(len(summary_content) // 3, 1)

        summary_turn = Turn(
            role="system",
            content=summary_content,
            tokens=summary_tokens,
            protected=True,
        )
        self._turns = [summary_turn] + protected
        old_total = self._total_tokens
        self._total_tokens = summary_tokens + protected_tokens
        self._compressions += 1

        saved = old_total - self._total_tokens
        log.info(
            "compression(focus=%r): %d → %d tokens (%d saved, %d turns compressed)",
            focus_topic, old_total, self._total_tokens, saved, len(compressible),
        )

        return {
            "compressed": True,
            "focus_topic": focus_topic,
            "tokens_before": old_total,
            "tokens_after": self._total_tokens,
            "tokens_saved": saved,
            "turns_compressed": len(compressible),
            "turns_remaining": len(self._turns),
        }

    def get_stats(self) -> dict:
        return {
            "total_tokens": self._total_tokens,
            "max_tokens": self.max_context_tokens,
            "usage_ratio": round(self.usage_ratio, 3),
            "threshold": self.threshold,
            "target_ratio": self.target_ratio,
            "turns": len(self._turns),
            "compressions": self._compressions,
        }
