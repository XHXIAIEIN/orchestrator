"""Sliding window trajectory for desktop automation engine context.

Keeps the last N (screenshot, action, result) steps and provides
helpers for turning them into LLM-ready context.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field

from .types import TrajectoryStep


@dataclass
class Trajectory:
    max_steps: int = 8
    steps: list[TrajectoryStep] = field(default_factory=list)
    _summary: str = field(default="", repr=False)

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def append(self, step: TrajectoryStep) -> None:
        """Add *step*. Auto-summarizes when the window is full."""
        self.steps.append(step)
        if len(self.steps) > self.max_steps:
            self.summarize(keep_recent=self.max_steps - 2)

    def summarize(self, keep_recent: int = 3) -> str:
        """Compress older steps into a text summary, keeping recent *keep_recent* steps.

        Returns the summary text.  Also stores it internally so
        :meth:`to_prompt_context` can prepend it automatically.

        This is a LOCAL summarization (no LLM call) -- action + result text only.
        """
        if len(self.steps) <= keep_recent:
            return self._summary  # nothing to compress

        to_compress = self.steps[:-keep_recent]
        kept = self.steps[-keep_recent:]

        parts: list[str] = []
        if self._summary:
            parts.append(self._summary)

        for step in to_compress:
            action = step.action if isinstance(step.action, str) else str(step.action)
            result = step.result or "no result"
            if len(result) > 100:
                result = result[:100] + "..."
            parts.append(f"Step: {action} -> {result}")

        self._summary = "\n".join(parts)
        self.steps = list(kept)
        return self._summary

    # ------------------------------------------------------------------
    # Sizing
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self.steps)

    @property
    def step_count(self) -> int:
        """Total logical steps including summarized ones."""
        summarized = self._summary.count("\n") + 1 if self._summary else 0
        return len(self.steps) + summarized

    # ------------------------------------------------------------------
    # LLM helpers
    # ------------------------------------------------------------------

    def to_prompt_context(self) -> list[dict]:
        """Return a list of dicts, one per step.

        Each dict contains:
          - ``"text"``: human-readable step description
          - ``"image"`` / ``"screenshot"``: base64-encoded thumbnail
        """
        if not self.steps and not self._summary:
            return []

        ctx: list[dict] = []

        # Prepend compressed history when available
        if self._summary:
            ctx.append({
                "text": f"[Previous actions summary]\n{self._summary}\n[Recent actions follow]",
            })

        for idx, step in enumerate(self.steps, start=1):
            action_json = json.dumps(step.action, ensure_ascii=False)
            prefix = f"[{step.source}] " if step.source != "agent" else ""
            text = f"Step {idx}: {prefix}{action_json} -> {step.result}"
            b64 = base64.b64encode(step.screenshot_thumbnail).decode("ascii")
            ctx.append({"text": text, "image": b64, "screenshot": b64})
        return ctx

    def get_images_b64(self) -> list[str]:
        """Return base64-encoded screenshots for the LLM Router."""
        return [
            base64.b64encode(step.screenshot_thumbnail).decode("ascii")
            for step in self.steps
        ]

    def get_action_summary(self) -> str:
        """Return a multi-line text summary of all steps.

        Format: ``Step 1: {...} -> success\\nStep 2: {...} -> error``
        """
        if not self.steps:
            return ""

        lines: list[str] = []
        for idx, step in enumerate(self.steps, start=1):
            action_json = json.dumps(step.action, ensure_ascii=False)
            prefix = f"[{step.source}] " if step.source != "agent" else ""
            lines.append(f"Step {idx}: {prefix}{action_json} -> {step.result}")
        return "\n".join(lines)
