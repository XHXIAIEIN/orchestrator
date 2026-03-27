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

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def append(self, step: TrajectoryStep) -> None:
        """Add *step*, evicting the oldest entry if the window is full."""
        self.steps.append(step)
        if len(self.steps) > self.max_steps:
            self.steps = self.steps[-self.max_steps:]

    # ------------------------------------------------------------------
    # Sizing
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self.steps)

    # ------------------------------------------------------------------
    # LLM helpers
    # ------------------------------------------------------------------

    def to_prompt_context(self) -> list[dict]:
        """Return a list of dicts, one per step.

        Each dict contains:
          - ``"text"``: human-readable step description
          - ``"image"`` / ``"screenshot"``: base64-encoded thumbnail
        """
        if not self.steps:
            return []

        ctx: list[dict] = []
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
