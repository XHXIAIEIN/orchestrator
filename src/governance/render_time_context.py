"""Render-Time Prompt Injection — dynamic prompt sections refreshed per-dispatch.

Stolen from Claude Code v2.1.88 query.ts buildSystemPrompt pattern.
Instead of building the prompt once at task start, dynamic sections are
re-evaluated before each API call (or each attempt in the rollout loop).

This ensures the prompt reflects:
- Current governor rules (may change mid-session)
- Latest checkpoint timings (for self-awareness of bottlenecks)
- Active scratchpad context (from sibling workers)
- Task dependency state (predecessors may complete while we're running)

Static sections (department identity, tool list, task spec) are still built
once by build_execution_prompt(). This module provides the DYNAMIC overlay.
"""
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)


@dataclass
class DynamicSection:
    """A named section of the prompt that refreshes on each render.

    provider: callable that returns the section content (or empty string to skip)
    priority: lower = rendered first (0-99)
    max_chars: content is truncated to this limit
    """
    name: str
    provider: Callable[[], str]
    priority: int = 50
    max_chars: int = 2000


class RenderTimeContext:
    """Manages dynamic prompt sections that refresh before each dispatch.

    Usage::

        rtc = RenderTimeContext(task_id=42)

        # Register dynamic sections
        rtc.register("checkpoint_summary", lambda: format_checkpoints(task_id), priority=80)
        rtc.register("scratchpad", lambda: pad.build_context(), priority=60)
        rtc.register("sibling_status", lambda: get_sibling_status(task_id), priority=70)

        # Before each dispatch, render the dynamic overlay
        dynamic_prompt = rtc.render()
        full_prompt = static_prompt + "\\n" + dynamic_prompt
    """

    def __init__(self, task_id: int):
        self._task_id = task_id
        self._sections: list[DynamicSection] = []
        self._render_count = 0
        self._last_render_ms = 0

    def register(self, name: str, provider: Callable[[], str],
                 priority: int = 50, max_chars: int = 2000):
        """Register a dynamic section.

        Duplicate names are replaced (last registration wins).
        """
        # Remove existing section with same name
        self._sections = [s for s in self._sections if s.name != name]
        self._sections.append(DynamicSection(
            name=name,
            provider=provider,
            priority=priority,
            max_chars=max_chars,
        ))
        self._sections.sort(key=lambda s: s.priority)

    def unregister(self, name: str):
        """Remove a dynamic section by name."""
        self._sections = [s for s in self._sections if s.name != name]

    def render(self) -> str:
        """Render all dynamic sections into a single string.

        Sections that return empty string are silently skipped.
        Each section is wrapped in a labeled block for debuggability.
        """
        start = time.time()
        self._render_count += 1

        parts = []
        for section in self._sections:
            try:
                content = section.provider()
                if not content or not content.strip():
                    continue

                # Truncate if over limit
                if len(content) > section.max_chars:
                    content = content[:section.max_chars] + f"\n[...truncated to {section.max_chars} chars]"

                parts.append(f"<!-- dynamic:{section.name} -->\n{content}")

            except Exception as e:
                log.warning(f"RenderTimeContext: section '{section.name}' failed: {e}")
                continue

        self._last_render_ms = int((time.time() - start) * 1000)

        if not parts:
            return ""

        header = f"<!-- render-time context (render #{self._render_count}, {self._last_render_ms}ms) -->"
        return f"{header}\n" + "\n\n".join(parts)

    @property
    def section_names(self) -> list[str]:
        """List registered section names in priority order."""
        return [s.name for s in self._sections]

    @property
    def stats(self) -> dict:
        """Render statistics for diagnostics."""
        return {
            "render_count": self._render_count,
            "last_render_ms": self._last_render_ms,
            "section_count": len(self._sections),
            "section_names": self.section_names,
        }


# ── Pre-built dynamic section providers ──

def make_checkpoint_provider(db, task_id: int) -> Callable[[], str]:
    """Provider that formats recent checkpoints as a timing summary.

    Useful for agent self-awareness: 'my last API call took 15s,
    but approval only took 1s'.
    """
    def _provide() -> str:
        try:
            checkpoints = db.get_checkpoints(task_id, limit=20)
            if len(checkpoints) < 2:
                return ""

            lines = ["**Timing profile (last checkpoints):**"]
            prev = checkpoints[0]
            for ckpt in checkpoints[1:]:
                delta_ms = ckpt["timestamp_ms"] - prev["timestamp_ms"]
                lines.append(f"- {prev['name']} → {ckpt['name']}: {delta_ms}ms")
                prev = ckpt

            total_ms = checkpoints[-1]["timestamp_ms"] - checkpoints[0]["timestamp_ms"]
            lines.append(f"- **Total**: {total_ms}ms")
            return "\n".join(lines)
        except Exception:
            return ""

    return _provide


def make_scratchpad_provider(task_id: int, max_chars: int = 2000) -> Callable[[], str]:
    """Provider that reads scratchpad context for this task."""
    def _provide() -> str:
        try:
            from src.governance.scratchpad import ScratchpadManager
            pad = ScratchpadManager(task_id)
            return pad.build_context(max_chars=max_chars)
        except Exception:
            return ""

    return _provide


def make_sibling_status_provider(db, task_id: int) -> Callable[[], str]:
    """Provider that shows status of sibling tasks (same parent).

    Gives the agent awareness of parallel work happening alongside it.
    """
    def _provide() -> str:
        try:
            task = db.get_task(task_id)
            if not task:
                return ""
            parent_id = task.get("spec", {}).get("parent_task_id") or task.get("parent_task_id")
            if not parent_id:
                return ""

            # Get sibling tasks (same parent, different ID)
            siblings = db.get_child_tasks(int(parent_id))
            if not siblings:
                return ""

            lines = ["**Sibling tasks:**"]
            for sib in siblings:
                if sib["id"] == task_id:
                    continue
                status_icon = {"done": "✓", "running": "⟳", "pending": "○", "failed": "✗"}.get(sib.get("status", ""), "?")
                lines.append(f"- {status_icon} #{sib['id']}: {sib.get('action', '')[:60]} [{sib.get('status', 'unknown')}]")

            return "\n".join(lines) if len(lines) > 1 else ""
        except Exception:
            return ""

    return _provide
