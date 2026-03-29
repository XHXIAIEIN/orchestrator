"""
Pattern-Key 自动晋升 — 偷自 self-improving-agent 的 promotion 机制。

同一 Pattern-Key 出现 ≥ threshold 次 → 自动追加到 boot.md Learnings 区块。
晋升后标记为 promoted 防止重复。
"""
from __future__ import annotations

import re
from pathlib import Path

from src.governance.audit.learnings import get_promotable_entries, _parse_entries

LEARNINGS_SECTION = "## Learnings"


def promote_to_boot(boot_path, pattern_key, summary, area):
    path = Path(boot_path)
    text = path.read_text(encoding="utf-8")

    if pattern_key in text:
        return

    entry_line = f"- {summary} [{area}] (auto-promoted: {pattern_key})"

    if LEARNINGS_SECTION in text:
        parts = text.split(LEARNINGS_SECTION, 1)
        after = parts[1]
        next_section = re.search(r"\n## ", after)
        if next_section:
            insert_pos = next_section.start()
            new_after = after[:insert_pos].rstrip() + "\n" + entry_line + "\n" + after[insert_pos:]
        else:
            new_after = after.rstrip() + "\n" + entry_line + "\n"
        text = parts[0] + LEARNINGS_SECTION + new_after
    else:
        text += f"\n{LEARNINGS_SECTION}\n\n{entry_line}\n"

    path.write_text(text, encoding="utf-8")


def mark_as_promoted(learnings_path, pattern_key):
    path = Path(learnings_path)
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    found_key = False
    for i, line in enumerate(lines):
        if f"- Pattern-Key: {pattern_key}" in line:
            found_key = True
        if found_key and "- Status: active" in line:
            lines[i] = "- Status: promoted"
            break
    path.write_text("\n".join(lines), encoding="utf-8")


def scan_and_promote(learnings_path, boot_path, threshold=3):
    promotable = get_promotable_entries(learnings_path, threshold)
    promoted = []
    for entry in promotable:
        promote_to_boot(
            boot_path=boot_path,
            pattern_key=entry.pattern_key,
            summary=entry.summary,
            area=entry.area or "general",
        )
        mark_as_promoted(learnings_path, entry.pattern_key)
        promoted.append(entry.pattern_key)
    return promoted
