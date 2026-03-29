"""Session Repair — stolen from OpenFang 7-Phase Session Repair.

Validates agent message history and repairs common corruption patterns:
1. Orphan tool_use (tool_use without matching tool_result)
2. Orphan tool_result (tool_result without preceding tool_use)
3. Empty assistant messages (no content at all)
4. Consecutive same-role messages (should alternate)
5. Truncated JSON in tool inputs

Runs as a validation pass before session resume or history replay.

Usage:
    repairer = SessionRepairer()
    events = db.get_agent_events(task_id)
    repaired, report = repairer.repair(events)
"""
import json
import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class RepairReport:
    """Report of what was found and fixed."""
    total_events: int = 0
    orphan_tool_uses: int = 0
    orphan_tool_results: int = 0
    empty_messages: int = 0
    consecutive_roles: int = 0
    truncated_json: int = 0
    events_removed: int = 0
    events_repaired: int = 0

    @property
    def clean(self) -> bool:
        return (self.orphan_tool_uses == 0 and
                self.orphan_tool_results == 0 and
                self.empty_messages == 0 and
                self.consecutive_roles == 0 and
                self.truncated_json == 0)

    def summary(self) -> str:
        if self.clean:
            return f"clean ({self.total_events} events)"
        issues = []
        if self.orphan_tool_uses:
            issues.append(f"{self.orphan_tool_uses} orphan tool_use")
        if self.orphan_tool_results:
            issues.append(f"{self.orphan_tool_results} orphan tool_result")
        if self.empty_messages:
            issues.append(f"{self.empty_messages} empty")
        if self.consecutive_roles:
            issues.append(f"{self.consecutive_roles} consecutive")
        if self.truncated_json:
            issues.append(f"{self.truncated_json} truncated JSON")
        return f"repaired: {', '.join(issues)} (removed {self.events_removed}, fixed {self.events_repaired})"


class SessionRepairer:
    """Validate and repair agent event history."""

    def validate(self, events: list[dict]) -> RepairReport:
        """Validate events without modifying them. Returns report."""
        report = RepairReport(total_events=len(events))

        tool_use_ids: set[str] = set()
        tool_result_ids: set[str] = set()
        prev_role: Optional[str] = None

        for event in events:
            data = event.get("data", {})
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except (json.JSONDecodeError, TypeError):
                    data = {}

            event_type = event.get("event_type", "")

            # Track tool use/result pairs
            if event_type == "agent_turn":
                tools = data.get("tools_detail", data.get("tools", []))
                for tool in (tools if isinstance(tools, list) else []):
                    tool_id = tool.get("id") or tool.get("tool", "") if isinstance(tool, dict) else ""
                    if tool_id:
                        tool_use_ids.add(tool_id)

                # Empty message check
                text = data.get("text", [])
                tools_list = data.get("tools", [])
                if not text and not tools_list:
                    report.empty_messages += 1

                # Consecutive role check
                role = "assistant"
                if prev_role == role:
                    report.consecutive_roles += 1
                prev_role = role

            elif event_type == "tool_result":
                tool_id = data.get("tool_use_id", "")
                if tool_id:
                    tool_result_ids.add(tool_id)
                prev_role = "tool"

            # Truncated JSON check
            if isinstance(data, dict):
                for key in ("input_preview", "output"):
                    val = data.get(key, "")
                    if isinstance(val, str) and val.endswith(("...", "…")):
                        # Truncated preview is normal, but check for broken JSON
                        if val.count("{") > val.count("}"):
                            report.truncated_json += 1

        # Orphan detection
        report.orphan_tool_uses = len(tool_use_ids - tool_result_ids)
        report.orphan_tool_results = len(tool_result_ids - tool_use_ids)

        return report

    def repair(self, events: list[dict]) -> tuple[list[dict], RepairReport]:
        """Validate and repair events. Returns (repaired_events, report)."""
        report = self.validate(events)

        if report.clean:
            return events, report

        repaired: list[dict] = []
        seen_tool_uses: set[str] = set()

        for event in events:
            data = event.get("data", {})
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except (json.JSONDecodeError, TypeError):
                    data = {}

            event_type = event.get("event_type", "")

            # Skip empty assistant messages
            if event_type == "agent_turn":
                text = data.get("text", [])
                tools = data.get("tools", [])
                if not text and not tools:
                    report.events_removed += 1
                    continue

                # Track tool uses from detail
                tools_detail = data.get("tools_detail", [])
                for tool in (tools_detail if isinstance(tools_detail, list) else []):
                    if isinstance(tool, dict):
                        tid = tool.get("id") or tool.get("tool", "")
                        if tid:
                            seen_tool_uses.add(tid)

            # Skip orphan tool_results (no matching tool_use)
            elif event_type == "tool_result":
                tid = data.get("tool_use_id", "")
                if tid and tid not in seen_tool_uses:
                    report.events_removed += 1
                    continue

            repaired.append(event)

        log.info(f"session_repair: {report.summary()}")
        return repaired, report
