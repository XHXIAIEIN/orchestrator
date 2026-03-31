"""ContextWriter — populates context_store before task dispatch.

Main process (or dispatch pipeline) calls ContextWriter to pre-populate
the DB with context layers. Sub-agents then read on demand via ctx_read.
"""
from __future__ import annotations

import logging
from pathlib import Path

from src.storage.events_db import EventsDB

log = logging.getLogger(__name__)

_KEY_LAYER_MAP = {
    "identity:": 0,
    "catalog": 0,
    "session:": 1,
    "chain:": 1,
    "file:": 2,
    "memory:": 2,
    "conversation:": 2,
    "codebase:": 3,
    "history:": 3,
}


def _key_to_layer(key: str) -> int:
    """Derive layer from key prefix."""
    if key == "catalog":
        return 0
    for prefix, layer in _KEY_LAYER_MAP.items():
        if key.startswith(prefix):
            return layer
    return 2  # default to L2


def _load_identity_briefing(dept_key: str) -> str:
    """Load a one-paragraph identity briefing for the department."""
    skill_path = Path(f"departments/{dept_key}/SKILL.md")
    if skill_path.exists():
        text = skill_path.read_text(encoding="utf-8")
        paragraphs = text.split("\n\n")
        return paragraphs[0][:500] if paragraphs else f"Department: {dept_key}"
    return f"You are a sub-agent in the {dept_key} department of the Orchestrator system."


class ContextWriter:
    """Writes context layers to DB before task dispatch."""

    def __init__(self, db: EventsDB, session_id: str):
        self.db = db
        self.session_id = session_id

    def write_layer0(self, task: dict, dept_key: str):
        """Always written. Identity + context catalog."""
        briefing = _load_identity_briefing(dept_key)
        self._upsert("identity:briefing", briefing)
        catalog = self._build_catalog()
        self._upsert("catalog", catalog)

    def write_layer1(self, conversation_summary: str = "",
                     git_diff: str = "", chain_outputs: dict | None = None):
        """Session state. Written by dispatch pipeline."""
        if conversation_summary:
            self._upsert("session:conversation_summary", conversation_summary)
        if git_diff:
            self._upsert("session:git_diff", git_diff)
        for task_id, output in (chain_outputs or {}).items():
            self._upsert(f"chain:{task_id}", output)

    def write_chain_output(self, task_id: int, output: str):
        """Store a completed task's output for chain continuity."""
        self._upsert(f"chain:{task_id}", output)

    def write_file(self, path: str, content: str):
        """Store file content for agent retrieval."""
        self._upsert(f"file:{path}", content)

    def write_memory(self, category: str, content: str):
        """Store memory entry for agent retrieval."""
        self._upsert(f"memory:{category}", content)

    def write_conversation_full(self, transcript: str, expires_hours: int = 1):
        """Store full conversation transcript (L3, expensive)."""
        from datetime import datetime, timezone, timedelta
        expires = (datetime.now(timezone.utc) + timedelta(hours=expires_hours)).isoformat()
        self.db.upsert_context(
            self.session_id, 3, "conversation:full",
            transcript, expires_at=expires,
        )

    def _upsert(self, key: str, content: str):
        layer = _key_to_layer(key)
        self.db.upsert_context(self.session_id, layer, key, content)

    def _build_catalog(self) -> str:
        """List all available context keys for this session."""
        rows = self.db.list_context_keys(self.session_id)
        lines = [
            "## Available Context",
            "Use `python scripts/ctx_read.py --session {session_id} --key <key>` to read.",
            "",
        ]
        current_layer = -1
        for row in rows:
            if row["layer"] != current_layer:
                current_layer = row["layer"]
                lines.append(f"### Layer {current_layer}")
            lines.append(f"  - `{row['key']}` (~{row['token_est']} tokens)")
        if not rows:
            lines.append("  (no context available yet)")
        return "\n".join(lines)
