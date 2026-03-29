"""
WAL (Write-Ahead Log) Protocol — 偷自 proactive-agent。

关键原则：想回复的冲动是敌人。细节在上下文里看起来很显然，
不写也记得住——这个直觉在 context compaction 后必然崩溃。

扫描每条用户输入的 6 类信号，命中则先写 SESSION-STATE.md 再回复。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SIGNAL_TYPES = [
    "correction", "proper_noun", "preference",
    "decision", "draft_change", "precise_value",
]

_PATTERNS = {
    "correction": [
        re.compile(r"\b(actually|不对|其实应该|纠正|correction)\b", re.IGNORECASE),
        re.compile(r"\bnot\s+\w+[,;]\s*(but|rather|instead)\b", re.IGNORECASE),
        re.compile(r"\bshould\s+be\s+\w+\s+not\b", re.IGNORECASE),
    ],
    "decision": [
        re.compile(r"\b(let'?s\s+(go\s+with|use)|we'?ll\s+use|决定用|就用)\b", re.IGNORECASE),
        re.compile(r"\b(option\s+[A-D]|方案\s*[A-D一二三四])\b", re.IGNORECASE),
        re.compile(r"\b(go\s+with|choose|pick|选)\s+\w+", re.IGNORECASE),
    ],
    "preference": [
        re.compile(r"\b(I\s+prefer|我(喜欢|偏好)|偏好)\b", re.IGNORECASE),
        re.compile(r"\b(use\s+\w+\s+(style|format|indent))", re.IGNORECASE),
        re.compile(r"\b(single\s+quotes|double\s+quotes|tabs|spaces)\b", re.IGNORECASE),
    ],
    "precise_value": [
        re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
        re.compile(r"\b(sk-|pk-|api[_-]?key)[a-zA-Z0-9]+", re.IGNORECASE),
        re.compile(r"https?://\S+"),
        re.compile(r"\b\d+\.\d+\.\d+\b"),
    ],
}


@dataclass
class WALSignal:
    signal_type: str
    matched_text: str
    confidence: float


def scan_for_signals(user_input):
    signals = []
    for signal_type, patterns in _PATTERNS.items():
        for pattern in patterns:
            match = pattern.search(user_input)
            if match:
                signals.append(WALSignal(
                    signal_type=signal_type,
                    matched_text=match.group(0),
                    confidence=0.8,
                ))
                break
    return signals


def write_wal_entry(state_path, section, content):
    path = Path(state_path)
    text = path.read_text(encoding="utf-8")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    entry = f"- [{now}] {content}"
    section_header = f"## {section}"

    if section_header in text:
        parts = text.split(section_header)
        if len(parts) >= 2:
            rest = parts[1]
            next_section = re.search(r"\n## ", rest)
            if next_section:
                insert_pos = next_section.start()
                new_rest = rest[:insert_pos].rstrip() + "\n" + entry + "\n" + rest[insert_pos:]
            else:
                new_rest = rest.rstrip() + "\n" + entry + "\n"
            text = parts[0] + section_header + new_rest
    else:
        text += f"\n{section_header}\n\n{entry}\n"

    path.write_text(text, encoding="utf-8")


def load_session_state(state_path):
    path = Path(state_path)
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    sections = {}
    current_section = None
    current_lines = []
    for line in text.split("\n"):
        m = re.match(r"^## (.+)$", line)
        if m:
            if current_section:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = m.group(1)
            current_lines = []
        elif current_section:
            current_lines.append(line)
    if current_section:
        sections[current_section] = "\n".join(current_lines).strip()
    return sections
