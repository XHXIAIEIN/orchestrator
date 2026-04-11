"""R48 (Hermes v0.8): Progressive Directory Discovery.

Agent navigates codebase and learns structure progressively.
Key directories are injected as workspace hints into agent context.

Unlike static file trees (expensive to generate), this builds incrementally
as the agent explores — only what's been touched gets indexed.
"""
import logging
from collections import defaultdict
from pathlib import Path

log = logging.getLogger(__name__)

MAX_HINTS = 20  # cap to avoid context bloat


class DirectoryDiscovery:
    """Tracks which directories an agent has explored. Provides workspace hints."""

    def __init__(self):
        self._visited: dict[str, int] = defaultdict(int)  # path → visit count
        self._descriptions: dict[str, str] = {}  # path → learned description

    def record_visit(self, path: str, description: str = "") -> None:
        """Record that a file/directory was accessed."""
        # Normalize to directory
        p = Path(path)
        dir_path = str(p.parent if p.suffix else p)
        self._visited[dir_path] += 1
        if description:
            self._descriptions[dir_path] = description

    def record_from_tool_use(self, tool_name: str, tool_input: dict) -> None:
        """Extract directory from tool use events automatically."""
        path = tool_input.get("file_path") or tool_input.get("path") or ""
        if path:
            self.record_visit(path)

    def get_hints(self, max_hints: int = MAX_HINTS) -> str:
        """Generate workspace hints sorted by visit frequency."""
        if not self._visited:
            return ""

        # Sort by visit count descending, take top N
        top = sorted(self._visited.items(), key=lambda x: x[1], reverse=True)[:max_hints]

        lines = ["## Workspace Structure (discovered)"]
        for dir_path, count in top:
            desc = self._descriptions.get(dir_path, "")
            suffix = f" — {desc}" if desc else ""
            lines.append(f"- `{dir_path}/` ({count} visits){suffix}")

        return "\n".join(lines)

    def get_stats(self) -> dict:
        return {
            "directories_discovered": len(self._visited),
            "total_visits": sum(self._visited.values()),
            "top_3": sorted(self._visited.items(), key=lambda x: x[1], reverse=True)[:3],
        }


# ── Per-task discovery instances ──
_instances: dict[str, DirectoryDiscovery] = {}


def get_discovery(task_id: str) -> DirectoryDiscovery:
    if task_id not in _instances:
        _instances[task_id] = DirectoryDiscovery()
    return _instances[task_id]


def cleanup_discovery(task_id: str) -> None:
    _instances.pop(task_id, None)
