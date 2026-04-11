"""R48 (Hermes v0.8): Pluggable Context Engine ABC.

Higher-level abstraction over Condenser — adds lifecycle (init/update/end),
tool provisioning, and config-driven selection.

A Context Engine can:
1. Compress context (delegates to Condenser pipeline)
2. Provide its own tools (e.g., LCM provides lcm_grep)
3. Report truthful compressible space
4. Respect protected context boundaries
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from .base import View, Event
from .pipeline import CondenserPipeline


@dataclass
class CompressResult:
    """Result of a context compression pass."""
    content: str
    original_tokens: int
    compressed_tokens: int
    protected_tokens: int
    strategy_used: str
    metadata: dict = field(default_factory=dict)

    @property
    def compression_ratio(self) -> float:
        if self.original_tokens == 0:
            return 1.0
        return self.compressed_tokens / self.original_tokens


class ContextEngine(ABC):
    """Pluggable Context Engine ABC (inspired by Hermes Agent v0.8).

    Higher-level than Condenser: adds lifecycle, tool slots, and
    protected-boundary declarations. Concrete engines swap strategies
    without changing the caller.
    """

    # ── Lifecycle ──────────────────────────────────────────────────────────

    @abstractmethod
    def initialize(self, session_id: str, config: dict[str, Any]) -> None:
        """Set up engine state for a new session."""
        ...

    @abstractmethod
    def finalize(self) -> None:
        """Tear down engine state at session end."""
        ...

    # ── Compression ────────────────────────────────────────────────────────

    @abstractmethod
    def should_compress(self, token_count: int, max_tokens: int) -> bool:
        """Return True if compression should run now."""
        ...

    @abstractmethod
    def compress(self, context: str | View, max_tokens: int) -> CompressResult:
        """Compress context to fit within max_tokens.

        Accepts either a raw string or a View (event list).
        Returns CompressResult with content + diagnostic stats.
        """
        ...

    # ── Tool / boundary registration ───────────────────────────────────────

    def get_tool_schemas(self) -> list[dict]:
        """Return JSON-Schema tool definitions provided by this engine.

        Override in engines that expose their own tools (e.g., lcm_grep).
        Default: no tools.
        """
        return []

    def get_protected_boundaries(self) -> list[str]:
        """Return content patterns / identifiers that must survive compression.

        Strings are treated as substring patterns against event content.
        Default: nothing protected.
        """
        return []


# ── Default implementation ─────────────────────────────────────────────────

class DefaultContextEngine(ContextEngine):
    """Wraps an existing CondenserPipeline as a ContextEngine.

    Config keys (all optional):
        compress_threshold: float  — fraction of max_tokens at which to trigger (default 0.85)
        protected_patterns: list[str]  — content substrings that must survive
    """

    _DEFAULT_THRESHOLD = 0.85

    def __init__(self, pipeline: CondenserPipeline | None = None):
        self._pipeline = pipeline
        self._session_id: str = ""
        self._config: dict[str, Any] = {}
        self._threshold: float = self._DEFAULT_THRESHOLD
        self._protected: list[str] = []

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def initialize(self, session_id: str, config: dict[str, Any]) -> None:
        self._session_id = session_id
        self._config = config
        self._threshold = float(config.get("compress_threshold", self._DEFAULT_THRESHOLD))
        self._protected = list(config.get("protected_patterns", []))

    def finalize(self) -> None:
        self._session_id = ""
        self._config = {}

    # ── Compression ────────────────────────────────────────────────────────

    def should_compress(self, token_count: int, max_tokens: int) -> bool:
        if max_tokens <= 0:
            return False
        return (token_count / max_tokens) >= self._threshold

    def compress(self, context: str | View, max_tokens: int) -> CompressResult:
        # Normalise input to View
        if isinstance(context, str):
            view = View([Event(id=0, event_type="system", source="agent",
                               content=context)])
        else:
            view = context

        original_tokens = view.token_estimate()

        # Separate out protected events so the pipeline won't drop them
        protected_events: list[Event] = []
        compressible_events: list[Event] = []
        for ev in view.events:
            if any(pat in ev.content for pat in self._protected):
                protected_events.append(ev)
            else:
                compressible_events.append(ev)

        protected_tokens = View(protected_events).token_estimate()

        # Run pipeline on compressible portion (if pipeline configured)
        if self._pipeline and compressible_events:
            compressed_view = self._pipeline.condense(View(compressible_events))
        else:
            compressed_view = View(compressible_events)

        # Reconstruct: protected events first, then compressed remainder
        final_events = protected_events + compressed_view.events
        final_view = View(final_events)
        compressed_tokens = final_view.token_estimate()

        content = "\n".join(ev.content for ev in final_view.events)

        return CompressResult(
            content=content,
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            protected_tokens=protected_tokens,
            strategy_used=(
                "condenser_pipeline" if self._pipeline else "passthrough"
            ),
            metadata={
                "session_id": self._session_id,
                "pipeline_stages": len(self._pipeline.condensers) if self._pipeline else 0,
            },
        )

    # ── Boundaries ─────────────────────────────────────────────────────────

    def get_protected_boundaries(self) -> list[str]:
        return list(self._protected)
