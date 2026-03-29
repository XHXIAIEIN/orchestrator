"""
三分类错误日志 — 偷自 self-improving-agent 的 .learnings/ 模式。

三个文件分类存储：LEARNINGS（知识）、ERRORS（错误）、FEATURES（缺口）。
每条带 Pattern-Key 做去重和出现次数追踪，满阈值触发晋升。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

MARKER = "<!-- entries below this line are auto-managed -->"

_counters: dict[str, int] = {}


@dataclass
class LearningEntry:
    entry_id: str
    pattern_key: str
    summary: str
    detail: str
    area: str
    occurrences: int = 1
    status: str = "active"
    first_seen: str = ""
    last_seen: str = ""


def _next_id(prefix: str) -> str:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    key = f"{prefix}-{today}"
    _counters[key] = _counters.get(key, 0) + 1
    return f"{prefix}-{today}-{_counters[key]:03d}"


def _parse_entries(text: str) -> list[dict]:
    entries = []
    current = None
    for line in text.split("\n"):
        m = re.match(r"^## ((?:ERR|LRN|FTR)-\d{8}-\d{3}) — (.+)$", line)
        if m:
            if current:
                entries.append(current)
            current = {"id": m.group(1), "summary": m.group(2), "lines": []}
            continue
        if current is not None:
            current["lines"].append(line)
            pk = re.match(r"^- Pattern-Key: (.+)$", line)
            if pk:
                current["pattern_key"] = pk.group(1)
            occ = re.match(r"^- Occurrences: (\d+)$", line)
            if occ:
                current["occurrences"] = int(occ.group(1))
            st = re.match(r"^- Status: (.+)$", line)
            if st:
                current["status"] = st.group(1)
    if current:
        entries.append(current)
    return entries


def _format_entry(e: LearningEntry) -> str:
    return (
        f"\n## {e.entry_id} — {e.summary}\n"
        f"- Pattern-Key: {e.pattern_key}\n"
        f"- Area: {e.area}\n"
        f"- Occurrences: {e.occurrences}\n"
        f"- Status: {e.status}\n"
        f"- First-seen: {e.first_seen}\n"
        f"- Last-seen: {e.last_seen}\n"
        f"- Detail: {e.detail}\n"
    )


def _append_to_file(prefix, pattern_key, summary, detail, area, file_path):
    path = Path(file_path)
    text = path.read_text(encoding="utf-8")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    entries = _parse_entries(text)
    for existing in entries:
        if existing.get("pattern_key") == pattern_key:
            old_occ = existing.get("occurrences", 1)
            new_occ = old_occ + 1
            text = text.replace(f"- Occurrences: {old_occ}", f"- Occurrences: {new_occ}", 1)
            text = re.sub(r"(- Last-seen: ).+", f"\\g<1>{now}", text, count=1)
            path.write_text(text, encoding="utf-8")
            return LearningEntry(
                entry_id=existing["id"], pattern_key=pattern_key,
                summary=summary, detail=detail, area=area,
                occurrences=new_occ, status=existing.get("status", "active"),
                first_seen="", last_seen=now,
            )

    entry = LearningEntry(
        entry_id=_next_id(prefix), pattern_key=pattern_key,
        summary=summary, detail=detail, area=area,
        occurrences=1, status="active", first_seen=now, last_seen=now,
    )
    formatted = _format_entry(entry)
    if MARKER in text:
        text = text.replace(MARKER, MARKER + formatted)
    else:
        text += formatted
    path.write_text(text, encoding="utf-8")
    return entry


def append_error(pattern_key, summary, detail, area, file_path):
    return _append_to_file("ERR", pattern_key, summary, detail, area, file_path)

def append_learning(pattern_key, summary, detail, area, file_path):
    return _append_to_file("LRN", pattern_key, summary, detail, area, file_path)

def append_feature(pattern_key, summary, detail, area, file_path):
    return _append_to_file("FTR", pattern_key, summary, detail, area, file_path)

def get_pattern_occurrences(file_path, pattern_key):
    text = Path(file_path).read_text(encoding="utf-8")
    entries = _parse_entries(text)
    for e in entries:
        if e.get("pattern_key") == pattern_key:
            return e.get("occurrences", 1)
    return 0

def get_promotable_entries(file_path, threshold=3):
    text = Path(file_path).read_text(encoding="utf-8")
    entries = _parse_entries(text)
    result = []
    for e in entries:
        occ = e.get("occurrences", 1)
        status = e.get("status", "active")
        if occ >= threshold and status == "active":
            result.append(LearningEntry(
                entry_id=e["id"], pattern_key=e.get("pattern_key", ""),
                summary=e.get("summary", ""), detail="", area="",
                occurrences=occ, status=status,
            ))
    return result

def check_blast_radius(file_count, max_files):
    return file_count <= max_files
