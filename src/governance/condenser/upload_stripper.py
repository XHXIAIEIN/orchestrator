# src/governance/condenser/upload_stripper.py
"""Upload Mention Stripping (R29 — stolen from bytedance/deer-flow).

Actively strip file upload/temporary file references from context before
memory persistence. Future sessions can't find absent files, so references
to ephemeral paths create confusion.

Patterns stripped:
  - /mnt/user-data/uploads/...
  - /tmp/... (but NOT /tmp/orchestrator-* — those are ours)
  - C:\\Users\\...\\AppData\\Local\\Temp\\...
  - <uploaded_files>...</uploaded_files> XML blocks
  - Docker container paths: /app/tmp/...
"""
from __future__ import annotations

import logging
import re

from .base import Condenser, Event, View

log = logging.getLogger(__name__)

REPLACEMENT = "[ephemeral-file-removed]"

# Pre-compiled patterns — order matters (more specific before general)
STRIP_PATTERNS: list[re.Pattern[str]] = [
    # XML upload blocks (dotall for multiline content)
    re.compile(r"<uploaded_files>.*?</uploaded_files>", re.DOTALL),
    # Cloud sandbox upload paths
    re.compile(r"/mnt/user-data/uploads/[^\s]+"),
    # Docker container temp paths (must precede generic /tmp/ to avoid partial match)
    re.compile(r"/app/tmp/[^\s]+"),
    # /tmp paths — but NOT /tmp/orchestrator-* (those are ours)
    re.compile(r"/tmp/(?!orchestrator-)[^\s]+"),
    # Windows temp paths (double-escaped backslashes for literal match)
    re.compile(r"C:\\\\Users\\\\[^\\\\]+\\\\AppData\\\\Local\\\\Temp\\\\[^\s]+"),
    # Also match single-backslash Windows paths (common in user messages)
    re.compile(r"C:\\Users\\[^\\]+\\AppData\\Local\\Temp\\[^\s]+"),
]


class UploadStripper(Condenser):
    """Strip ephemeral file upload references from all events in a View.

    Runs unconditionally — no trigger logic needed since stripping is cheap
    and idempotent (already-stripped text won't match patterns).
    """

    def strip_text(self, text: str) -> str:
        """Apply all strip patterns to a text string."""
        result = text
        for pattern in STRIP_PATTERNS:
            result = pattern.sub(REPLACEMENT, result)
        return result

    def condense(self, view: View) -> View:
        """Strip all messages in view, return cleaned View."""
        events = view.events
        cleaned: list[Event] = []
        strip_count = 0

        for e in events:
            new_content = self.strip_text(e.content)
            if new_content != e.content:
                strip_count += 1
                cleaned.append(Event(
                    id=e.id,
                    event_type=e.event_type,
                    source=e.source,
                    content=new_content,
                    metadata={**e.metadata, "upload_stripped": True},
                    condensed=e.condensed,
                ))
            else:
                cleaned.append(e)

        if strip_count:
            log.info(
                f"UploadStripper: stripped ephemeral paths from "
                f"{strip_count}/{len(events)} events"
            )

        return View(cleaned)
