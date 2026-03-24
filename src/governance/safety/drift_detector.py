# src/governance/safety/drift_detector.py
"""Drift Detection — detect when an agent strays from its assigned task.

Stolen from pro-workflow's drift detection. Monitors agent actions during
execution and flags when the agent appears to be working on something
unrelated to the original task description.

Drift signals:
  1. File edits outside expected scope (writable_paths from blueprint)
  2. Tool usage pattern doesn't match task type
  3. Agent text mentions unrelated topics
  4. Agent keeps exploring without making progress toward goal
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# Minimum turns before drift detection kicks in
MIN_TURNS = 4
# Maximum ratio of off-topic tool calls before flagging
OFF_TOPIC_THRESHOLD = 0.6


@dataclass
class DriftSignal:
    """A single drift indicator."""
    signal_type: str   # "scope_violation" | "off_topic_tools" | "goal_divergence" | "exploration_spiral"
    severity: str      # "low" | "medium" | "high"
    description: str
    turn: int = 0


@dataclass
class DriftReport:
    """Aggregated drift analysis."""
    task_id: int
    signals: list[DriftSignal] = field(default_factory=list)
    drift_score: float = 0.0   # 0.0 = on track, 1.0 = completely drifted

    @property
    def is_drifting(self) -> bool:
        return self.drift_score >= 0.5

    @property
    def should_intervene(self) -> bool:
        """High confidence drift — agent should be stopped or redirected."""
        return self.drift_score >= 0.7

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "drift_score": round(self.drift_score, 2),
            "is_drifting": self.is_drifting,
            "should_intervene": self.should_intervene,
            "signals": [
                {"type": s.signal_type, "severity": s.severity, "desc": s.description}
                for s in self.signals
            ],
        }


class DriftDetector:
    """Monitor agent execution for task drift.

    Feed it the original task spec and each agent turn's data.
    Call check() periodically to get a drift report.
    """

    def __init__(self, task_spec: dict, writable_paths: list[str] = None):
        self.task_spec = task_spec
        self.writable_paths = writable_paths or []
        self._task_keywords = self._extract_keywords(task_spec)
        self._turns: list[dict] = []

    def record_turn(self, turn_data: dict) -> None:
        """Record an agent turn for drift analysis."""
        self._turns.append(turn_data)

    def check(self, task_id: int = 0) -> DriftReport:
        """Run drift analysis on accumulated turns."""
        report = DriftReport(task_id=task_id)

        if len(self._turns) < MIN_TURNS:
            return report

        signals = []
        signals.extend(self._check_scope_violations())
        signals.extend(self._check_off_topic_tools())
        signals.extend(self._check_exploration_spiral())

        report.signals = signals

        # Compute drift score from signals
        if signals:
            severity_weights = {"low": 0.1, "medium": 0.25, "high": 0.5}
            total = sum(severity_weights.get(s.severity, 0.1) for s in signals)
            report.drift_score = min(1.0, total)

        return report

    def _check_scope_violations(self) -> list[DriftSignal]:
        """Check if agent is editing files outside declared writable paths."""
        if not self.writable_paths:
            return []

        signals = []
        for i, turn in enumerate(self._turns):
            tools = turn.get("tools") or turn.get("data", {}).get("tools", [])
            if not tools:
                continue

            for tool in tools:
                tool_name = tool if isinstance(tool, str) else tool.get("tool", "")
                if tool_name not in ("Edit", "Write"):
                    continue

                # Extract file path from tool input
                tool_input = "" if isinstance(tool, str) else str(tool.get("input_preview", ""))
                if not tool_input:
                    continue

                # Simple check: does any writable_path pattern match?
                from fnmatch import fnmatch
                in_scope = any(fnmatch(tool_input, p) for p in self.writable_paths)
                if not in_scope and tool_input:
                    signals.append(DriftSignal(
                        "scope_violation", "medium",
                        f"Edit outside writable scope: {tool_input[:80]}",
                        turn=i,
                    ))

        return signals

    def _check_off_topic_tools(self) -> list[DriftSignal]:
        """Check if tool usage pattern diverges from task type."""
        if not self._task_keywords:
            return []

        recent = self._turns[-6:]
        read_count = 0
        write_count = 0
        search_count = 0
        total = 0

        for turn in recent:
            tools = turn.get("tools") or turn.get("data", {}).get("tools", [])
            for tool in (tools or []):
                name = tool if isinstance(tool, str) else tool.get("tool", "")
                total += 1
                if name in ("Read", "Glob", "Grep"):
                    search_count += 1
                elif name in ("Edit", "Write"):
                    write_count += 1

        if total == 0:
            return []

        # If task asks for code changes but agent is only reading/searching
        task_action = (self.task_spec.get("action") or "").lower()
        expects_write = any(kw in task_action for kw in
                           ["修改", "修复", "实现", "添加", "fix", "implement", "add", "refactor", "重构"])

        signals = []
        if expects_write and total >= 6 and write_count == 0:
            signals.append(DriftSignal(
                "off_topic_tools", "medium",
                f"Task expects writes but last {total} tool calls are all read/search",
            ))

        # If agent is doing excessive exploration (>60% search in late turns)
        if len(self._turns) > 8 and search_count / max(1, total) > OFF_TOPIC_THRESHOLD:
            signals.append(DriftSignal(
                "exploration_spiral", "low",
                f"High search ratio ({search_count}/{total}) in recent turns — possible aimless exploration",
            ))

        return signals

    def _check_exploration_spiral(self) -> list[DriftSignal]:
        """Detect agent exploring without converging on a solution."""
        if len(self._turns) < 8:
            return []

        # Check if agent's text mentions the same files/topics repeatedly without acting
        recent_texts = []
        for turn in self._turns[-8:]:
            text = turn.get("text") or turn.get("data", {}).get("text_preview", "")
            if isinstance(text, list):
                text = " ".join(text)
            recent_texts.append(str(text)[:200])

        # Simple heuristic: if "let me check" or "let me look" appears in >50% of recent turns
        exploration_phrases = ["let me check", "let me look", "让我看看", "我来查", "先看一下"]
        match_count = sum(
            1 for t in recent_texts
            if any(p in t.lower() for p in exploration_phrases)
        )

        signals = []
        if match_count > len(recent_texts) * 0.5:
            signals.append(DriftSignal(
                "exploration_spiral", "medium",
                f"Agent has been exploring without action for {match_count}/{len(recent_texts)} recent turns",
            ))

        return signals

    def _extract_keywords(self, spec: dict) -> set[str]:
        """Extract meaningful keywords from task spec for relevance matching."""
        text = f"{spec.get('action', '')} {spec.get('problem', '')} {spec.get('summary', '')}"
        # Extract file paths, function names, and significant words
        words = set(re.findall(r'[a-zA-Z_]\w{3,}', text.lower()))
        paths = set(re.findall(r'[\w/]+\.\w+', text))
        return words | paths
