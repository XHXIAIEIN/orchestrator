"""Content Replacement State — tracks oversized tool outputs replaced with summaries.

Stolen from Claude Code v2.1.88 query.ts ContentReplacementState.
When tool results exceed a configured threshold, the full output is replaced
with a truncated summary + reference ID. Child agents (sub-tasks) inherit
the parent's replacement records to avoid re-transmitting large blobs.

The replaced content is NOT stored in this module — it stays in the
context_store (L1 layer) or events.db agent_events table, addressable
by the reference ID.
"""
import hashlib
import logging
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# Default threshold: 8K chars (~2K tokens). Tool outputs larger than this
# get replaced with a summary header + truncated preview.
DEFAULT_MAX_CHARS = 8_000

# Preview size: how many chars of the original to keep in the summary
PREVIEW_CHARS = 500


@dataclass(frozen=True)
class ReplacementRecord:
    """One replacement event."""
    ref_id: str          # Unique reference ID for retrieval
    task_id: int
    tool_name: str       # Which tool produced the oversized output
    original_length: int # Length of original content
    replaced_at: float   # time.time()
    preview: str         # First PREVIEW_CHARS of original


@dataclass
class ContentReplacementState:
    """Tracks all content replacements within an execution context.

    Serializable: use to_dict()/from_dict() for passing to child agents.
    """
    records: list[ReplacementRecord] = field(default_factory=list)
    max_chars: int = DEFAULT_MAX_CHARS

    def replace_if_oversized(self, content: str, task_id: int, tool_name: str) -> tuple[str, ReplacementRecord | None]:
        """Check content size and replace if over threshold.

        Returns:
            (content, None) if under threshold — content unchanged
            (summary, record) if replaced — summary contains ref_id + preview
        """
        if len(content) <= self.max_chars:
            return content, None

        # Generate stable reference ID from content hash
        content_hash = hashlib.sha256(content.encode('utf-8', errors='replace')).hexdigest()[:12]
        ref_id = f"ref:{task_id}:{tool_name}:{content_hash}"

        preview = content[:PREVIEW_CHARS]
        record = ReplacementRecord(
            ref_id=ref_id,
            task_id=task_id,
            tool_name=tool_name,
            original_length=len(content),
            replaced_at=time.time(),
            preview=preview,
        )
        self.records.append(record)

        summary = (
            f"[Content replaced: {ref_id}]\n"
            f"Original: {len(content)} chars from {tool_name}\n"
            f"Preview:\n{preview}\n"
            f"[...truncated {len(content) - PREVIEW_CHARS} chars. Use ref_id to retrieve full content.]"
        )

        log.info(
            f"ContentReplacement: replaced {tool_name} output "
            f"({len(content)} chars) → ref={ref_id}"
        )

        return summary, record

    def get_record(self, ref_id: str) -> ReplacementRecord | None:
        """Look up a replacement record by ref_id."""
        for r in self.records:
            if r.ref_id == ref_id:
                return r
        return None

    def to_dict(self) -> dict:
        """Serialize for passing to child agents."""
        return {
            "max_chars": self.max_chars,
            "records": [
                {
                    "ref_id": r.ref_id,
                    "task_id": r.task_id,
                    "tool_name": r.tool_name,
                    "original_length": r.original_length,
                    "replaced_at": r.replaced_at,
                    "preview": r.preview,
                }
                for r in self.records
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ContentReplacementState":
        """Deserialize — used when child agent inherits parent's state."""
        state = cls(max_chars=data.get("max_chars", DEFAULT_MAX_CHARS))
        for r in data.get("records", []):
            state.records.append(ReplacementRecord(**r))
        return state

    @classmethod
    def inherit(cls, parent: "ContentReplacementState") -> "ContentReplacementState":
        """Create a child state that inherits all parent records (read-only copy).

        Child can add new records but won't modify parent's list.
        """
        child = cls(max_chars=parent.max_chars)
        child.records = list(parent.records)  # Shallow copy — records are frozen
        return child

    def __len__(self) -> int:
        return len(self.records)

    def __repr__(self) -> str:
        return f"ContentReplacementState(records={len(self.records)}, max_chars={self.max_chars})"
