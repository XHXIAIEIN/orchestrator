"""Transformer Pipeline — composable pure function chain with auto-timing.

Inspired by Firecrawl's 18-step document transformation pipeline.
Each step is a pure function: (meta: dict, doc: dict) -> (meta: dict, doc: dict)
Steps are independently timed, logged, and can be conditionally skipped.

Usage:
    pipeline = TransformerPipeline("channel-format")
    pipeline.add("strip_html", strip_html_step)
    pipeline.add("truncate", truncate_step, condition=lambda m, d: len(d.get("text","")) > 5000)
    pipeline.add("add_metadata", add_metadata_step)

    result_meta, result_doc = pipeline.run(meta, doc)
    print(pipeline.get_timing())  # per-step timing breakdown
"""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from typing import Callable, Any

logger = logging.getLogger(__name__)

# Type alias for a transformer step
TransformFn = Callable[[dict, dict], tuple[dict, dict]]
ConditionFn = Callable[[dict, dict], bool]


@dataclass
class StepResult:
    """Result of a single pipeline step."""
    name: str
    duration_ms: float
    skipped: bool = False
    error: str | None = None


@dataclass
class PipelineResult:
    """Result of a full pipeline run."""
    name: str
    meta: dict
    doc: dict
    steps: list[StepResult] = field(default_factory=list)
    total_ms: float = 0.0

    @property
    def success(self) -> bool:
        return all(s.error is None for s in self.steps)

    def get_timing(self) -> dict[str, float]:
        """Return {step_name: duration_ms} for all steps."""
        return {s.name: s.duration_ms for s in self.steps}

    def get_slowest(self, n: int = 3) -> list[tuple[str, float]]:
        """Return N slowest steps."""
        timed = [(s.name, s.duration_ms) for s in self.steps if not s.skipped]
        return sorted(timed, key=lambda x: -x[1])[:n]


class TransformerPipeline:
    """Composable pipeline of pure transformation functions."""

    def __init__(self, name: str = "default"):
        self._name = name
        self._steps: list[tuple[str, TransformFn, ConditionFn | None]] = []

    def add(
        self,
        name: str,
        fn: TransformFn,
        condition: ConditionFn | None = None,
    ) -> "TransformerPipeline":
        """Add a step. Returns self for chaining."""
        self._steps.append((name, fn, condition))
        return self

    def run(self, meta: dict, doc: dict) -> PipelineResult:
        """Run all steps sequentially. Returns PipelineResult."""
        result = PipelineResult(name=self._name, meta=meta, doc=doc)
        start = time.perf_counter()

        for step_name, fn, condition in self._steps:
            # Check condition
            if condition and not condition(result.meta, result.doc):
                result.steps.append(StepResult(name=step_name, duration_ms=0, skipped=True))
                continue

            # Execute step with timing
            step_start = time.perf_counter()
            try:
                result.meta, result.doc = fn(result.meta, result.doc)
                duration = (time.perf_counter() - step_start) * 1000
                result.steps.append(StepResult(name=step_name, duration_ms=round(duration, 2)))
            except Exception as e:
                duration = (time.perf_counter() - step_start) * 1000
                result.steps.append(StepResult(
                    name=step_name, duration_ms=round(duration, 2), error=str(e)
                ))
                logger.warning(f"Pipeline '{self._name}' step '{step_name}' failed: {e}")
                # Continue pipeline — don't abort on single step failure

        result.total_ms = round((time.perf_counter() - start) * 1000, 2)
        return result

    def __len__(self) -> int:
        return len(self._steps)

    def __repr__(self) -> str:
        steps = " → ".join(name for name, _, _ in self._steps)
        return f"TransformerPipeline('{self._name}': {steps})"


# --- Pre-built step functions for common operations ---

def strip_html(meta: dict, doc: dict) -> tuple[dict, dict]:
    """Remove HTML tags from doc['text']."""
    import re
    text = doc.get("text", "")
    doc["text"] = re.sub(r'<[^>]+>', '', text)
    return meta, doc


def truncate_text(max_chars: int = 10000) -> TransformFn:
    """Factory: truncate doc['text'] to max_chars."""
    def _truncate(meta: dict, doc: dict) -> tuple[dict, dict]:
        text = doc.get("text", "")
        if len(text) > max_chars:
            doc["text"] = text[:max_chars] + f"\n... [truncated at {max_chars} chars]"
            meta["truncated"] = True
        return meta, doc
    return _truncate


def add_timestamp(meta: dict, doc: dict) -> tuple[dict, dict]:
    """Add processing timestamp to meta."""
    meta["processed_at"] = time.time()
    return meta, doc


def normalize_whitespace(meta: dict, doc: dict) -> tuple[dict, dict]:
    """Collapse multiple whitespace into single spaces."""
    import re
    text = doc.get("text", "")
    doc["text"] = re.sub(r'\s+', ' ', text).strip()
    return meta, doc
