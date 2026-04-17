# src/governance/condenser/tool_output_pruner.py
"""
Tool Output Pruner — tool-type-aware semantic collapse + content hash dedup (R77).

Upgrade from R39 positional prune: detects tool type (search/read/command/git/ls/write),
applies type-specific semantic collapse, and deduplicates identical tool outputs.

Lineage: R39 PraisonAI positional prune → R77 Hermes semantic collapse.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from typing import Callable

from .base import Condenser, Event, View

log = logging.getLogger(__name__)


@dataclass
class PruneConfig:
    """裁剪配置。"""
    # 触发裁剪的字符阈值
    trigger_chars: int = 500
    # 保留头部字符数
    head_chars: int = 200
    # 保留尾部占比 (剩余部分的百分比)
    tail_ratio: float = 0.20
    # 最小尾部字符数 (即使比例算出来更小)
    tail_min_chars: int = 50
    # 跳过已 condensed 的 event
    skip_condensed: bool = True
    # 只处理 environment source (工具输出)
    tool_sources: tuple[str, ...] = ("environment", "tool")
    # R77: 启用语义折叠
    semantic_collapse: bool = True
    # R77: 启用 content hash 去重
    hash_dedup: bool = True


# ── Tool type detection ──

_TOOL_TYPE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("search", re.compile(r"grep|rg|ripgrep|\d+ match", re.IGNORECASE)),
    ("read", re.compile(r"Read|Content of|cat|File:", re.IGNORECASE)),
    ("command", re.compile(r"^[$>] |exit code|Error:|bash:", re.MULTILINE)),
    ("git", re.compile(r"^git |diff --git|commit [0-9a-f]|On branch", re.MULTILINE)),
    ("ls", re.compile(r"^total \d|^d[rwx-]|listing:", re.MULTILINE)),
    ("write", re.compile(r"wrote|created|saved|Write|Edit", re.IGNORECASE)),
]


def _detect_tool_type(content: str) -> str:
    """Detect tool type from content. First match wins."""
    sample = content[:500]
    for name, pattern in _TOOL_TYPE_PATTERNS:
        if pattern.search(sample):
            return name
    return "unknown"


# ── Semantic collapse functions ──

def _collapse_search(content: str, budget: int) -> str:
    """Collapse search results: keep command + match count + first/last matches."""
    lines = content.split("\n")
    if len(lines) <= 10:
        return content

    # Find command line (usually first) and match count lines
    header_lines = []
    match_lines = []
    summary_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(r"^(\$|>|grep|rg)\s", stripped) or re.match(r"^\d+ match", stripped, re.IGNORECASE):
            header_lines.append(line)
        elif re.search(r"match(es)?\s*(found|total)|results?\s*:|^\d+\s+files?", stripped, re.IGNORECASE):
            summary_lines.append(line)
        else:
            match_lines.append(line)

    if not match_lines:
        return content

    # Keep first 5 + last 2 matches
    kept_matches = match_lines[:5]
    if len(match_lines) > 7:
        omitted = len(match_lines) - 7
        kept_matches.append(f"  … [{omitted} more matches omitted]")
        kept_matches.extend(match_lines[-2:])
    elif len(match_lines) > 5:
        kept_matches.extend(match_lines[5:])

    result_lines = header_lines + kept_matches + summary_lines
    result = "\n".join(result_lines)
    return result[:budget] if len(result) > budget else result


def _collapse_read(content: str, budget: int) -> str:
    """Collapse file read: keep filename + line count + first 8 lines + last 4 lines."""
    lines = content.split("\n")
    if len(lines) <= 15:
        return content

    # First line often has filename/header
    header = lines[:1]
    body = lines[1:]

    kept = header + body[:8]
    if len(body) > 12:
        omitted = len(body) - 12
        kept.append(f"  … [{omitted} lines omitted, {len(lines)} total]")
        kept.extend(body[-4:])
    elif len(body) > 8:
        kept.extend(body[8:])

    result = "\n".join(kept)
    return result[:budget] if len(result) > budget else result


def _collapse_command(content: str, budget: int) -> str:
    """Collapse command output: keep command + all errors (max 10) + last 5 lines + exit code."""
    lines = content.split("\n")
    if len(lines) <= 12:
        return content

    command_lines = []
    error_lines = []
    exit_code_lines = []
    other_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(r"^[$>]\s", stripped):
            command_lines.append(line)
        elif re.search(r"exit code|return code", stripped, re.IGNORECASE):
            exit_code_lines.append(line)
        elif re.search(r"error|traceback|exception|failed|fatal", stripped, re.IGNORECASE):
            error_lines.append(line)
        else:
            other_lines.append(line)

    # Keep: command + errors (max 10) + last 5 output lines + exit code
    kept = command_lines
    kept.extend(error_lines[:10])
    if len(error_lines) > 10:
        kept.append(f"  … [{len(error_lines) - 10} more error lines omitted]")
    if other_lines:
        if len(other_lines) > 5:
            kept.append(f"  … [{len(other_lines) - 5} output lines omitted]")
        kept.extend(other_lines[-5:])
    kept.extend(exit_code_lines)

    result = "\n".join(kept)
    return result[:budget] if len(result) > budget else result


def _collapse_git(content: str, budget: int) -> str:
    """Collapse git output: keep branch/status/changed files/commit hashes/diff stats."""
    lines = content.split("\n")
    if len(lines) <= 15:
        return content

    kept = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Keep key git info lines
        if any(kw in stripped for kw in (
            "On branch", "Your branch", "Changes", "modified:", "new file:",
            "deleted:", "renamed:", "Untracked", "commit ", "Author:", "Date:",
            "files changed", "insertions", "deletions", "->",
        )):
            kept.append(line)
        elif re.match(r"^[+-]{3}\s", stripped):  # diff headers
            kept.append(line)
        elif re.match(r"^@@\s", stripped):  # hunk headers
            kept.append(line)

    if len(kept) > 30:
        result_lines = kept[:25]
        result_lines.append(f"  … [{len(kept) - 30} more git info lines omitted]")
        result_lines.extend(kept[-5:])
        kept = result_lines

    if not kept:
        return content[:budget]

    result = "\n".join(kept)
    return result[:budget] if len(result) > budget else result


# Tool type → collapse function mapping
_COLLAPSE_FN: dict[str, Callable[[str, int], str]] = {
    "search": _collapse_search,
    "read": _collapse_read,
    "command": _collapse_command,
    "git": _collapse_git,
}


class ToolOutputPruner(Condenser):
    """Tool 输出专项裁剪器 — 支持语义折叠和 hash 去重。

    R39 原始策略 (positional):
    - 头部 200 chars + 尾部 20% + 中间省略

    R77 升级 (semantic collapse):
    - 按 tool type 分类，应用不同的折叠策略
    - Content hash 去重（相同输出只保留最后一次）
    - 无法折叠时 fallback 到 positional prune
    """

    def __init__(self, config: PruneConfig | None = None):
        self.config = config or PruneConfig()

    def _positional_prune(self, text: str) -> str:
        """R39 原始 head+tail 位置截断。"""
        c = self.config
        head = text[:c.head_chars]
        remaining = text[c.head_chars:]
        tail_chars = max(c.tail_min_chars, int(len(remaining) * c.tail_ratio))
        tail = remaining[-tail_chars:] if tail_chars < len(remaining) else remaining

        omitted = len(text) - len(head) - len(tail)
        separator = f"\n\n… [{omitted:,} chars pruned by ToolOutputPruner] …\n\n"

        return head + separator + tail

    def prune_text(self, text: str, tool_type: str = "unknown") -> str:
        """对单段文本执行裁剪：语义折叠优先，fallback 到位置截断。"""
        c = self.config
        if len(text) <= c.trigger_chars:
            return text

        budget = max(c.trigger_chars, len(text) // 3)

        # Try semantic collapse if enabled and tool type has a handler
        if c.semantic_collapse and tool_type in _COLLAPSE_FN:
            collapsed = _COLLAPSE_FN[tool_type](text, budget)
            if collapsed and len(collapsed) < len(text):
                return collapsed

        # Fallback: positional prune
        return self._positional_prune(text)

    def _dedup_by_hash(self, events: list[Event]) -> list[Event]:
        """Remove duplicate tool outputs, keeping the last occurrence."""
        # Scan tail→head, record seen hashes
        seen: dict[str, int] = {}  # hash → last-seen index
        tool_sources = self.config.tool_sources

        # First pass: find last occurrence of each hash
        for i in range(len(events) - 1, -1, -1):
            e = events[i]
            if e.source not in tool_sources or len(e.content) < 200:
                continue
            h = hashlib.md5(e.content.encode(), usedforsecurity=False).hexdigest()[:12]
            if h not in seen:
                seen[h] = i

        # Second pass: keep events whose hash matches their last occurrence (or non-tool events)
        result = []
        dedup_count = 0
        for i, e in enumerate(events):
            if e.source not in tool_sources or len(e.content) < 200:
                result.append(e)
                continue
            h = hashlib.md5(e.content.encode(), usedforsecurity=False).hexdigest()[:12]
            if seen.get(h) == i:
                result.append(e)
            else:
                dedup_count += 1

        if dedup_count:
            log.info(f"ToolOutputPruner: deduped {dedup_count} identical tool outputs")

        return result

    def condense(self, view: View) -> View:
        """裁剪 View 中所有 tool 输出：hash 去重 → 语义折叠/位置截断。"""
        events = view.events

        # Phase 1: hash dedup
        if self.config.hash_dedup:
            events = self._dedup_by_hash(events)

        # Phase 2: semantic collapse / positional prune
        pruned: list[Event] = []
        prune_count = 0
        chars_saved = 0

        for e in events:
            if (e.source not in self.config.tool_sources
                    or (self.config.skip_condensed and e.condensed)):
                pruned.append(e)
                continue

            tool_type = _detect_tool_type(e.content)
            new_content = self.prune_text(e.content, tool_type=tool_type)
            if new_content != e.content:
                prune_count += 1
                chars_saved += len(e.content) - len(new_content)
                strategy = "semantic" if (
                    self.config.semantic_collapse and tool_type in _COLLAPSE_FN
                ) else "positional"
                pruned.append(Event(
                    id=e.id,
                    event_type=e.event_type,
                    source=e.source,
                    content=new_content,
                    metadata={
                        **e.metadata,
                        "pruned": True,
                        "original_chars": len(e.content),
                        "tool_type": tool_type,
                        "strategy": strategy,
                    },
                    condensed=True,
                ))
            else:
                pruned.append(e)

        if prune_count:
            log.info(
                f"ToolOutputPruner: pruned {prune_count}/{len(events)} events, "
                f"saved {chars_saved:,} chars"
            )

        return View(pruned)
