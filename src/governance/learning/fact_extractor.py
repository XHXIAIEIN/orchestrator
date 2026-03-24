# src/governance/learning/fact_extractor.py
"""Auto Fact Extraction — proactively extract learnings from agent output.

Stolen from supermemory's ASMR fact extraction. Instead of only learning
from human edits (learn_from_edit.py, passive), this module actively
parses agent output text to find reusable facts, patterns, and decisions.

Extraction targets:
  1. Error → fix mappings ("X failed because Y, fixed by Z")
  2. Configuration discoveries ("setting X to Y resolved the issue")
  3. Codebase facts ("module X depends on Y")
  4. Performance observations ("query X takes N seconds")
  5. Workarounds ("API X doesn't support Y, use Z instead")
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class ExtractedFact:
    """A fact extracted from agent output."""
    pattern_key: str          # dedup key for learnings table
    rule: str                 # the learning rule text
    area: str = "general"     # general | code | ops | test
    source_type: str = "auto_extract"
    confidence: float = 0.0   # 0.0-1.0
    ttl_days: int = 0         # 0 = permanent, >0 = temporary


# ── Extraction Patterns ──

_ERROR_FIX_PATTERNS = [
    # "X failed because Y" / "X 失败因为 Y"
    (r'(?:failed|error|错误|失败)\s*(?:because|因为|由于)\s+(.{10,120})',
     r'(?:fixed|resolved|修复|解决)\s*(?:by|通过|用)\s+(.{10,120})'),
    # "the issue was X" / "problem was X"
    (r'(?:issue|problem|问题)\s*(?:was|是)\s+(.{10,120})',
     r'(?:solution|fix|解决方案)\s*(?:was|是|:)\s*(.{10,120})'),
]

_CONFIG_PATTERNS = [
    # "setting X to Y" / "set X = Y"
    r'(?:setting|set|配置|设置)\s+(\w[\w.]+)\s*(?:to|=|为)\s*([^\s,]+)',
    # "changed X from A to B"
    r'(?:changed|修改)\s+(\w[\w.]+)\s*(?:from|从)\s*\S+\s*(?:to|到|为)\s*([^\s,]+)',
]

_WORKAROUND_PATTERNS = [
    # "X doesn't support Y, use Z instead"
    r"(\w+)\s+(?:doesn't|does not|不支持|不能)\s+(?:support\s+)?(.+?),\s*(?:use|用|改用)\s+(.+?)(?:\s+instead)?(?:\.|$)",
    # "instead of X, use Y"
    r"(?:instead of|而不是)\s+(\S+),?\s*(?:use|用)\s+(\S+)",
]

_DEPENDENCY_PATTERNS = [
    # "X depends on Y" / "X requires Y"
    r'(\w[\w.]+)\s+(?:depends on|requires|依赖|需要)\s+(\w[\w.]+)',
    # "X imports Y"
    r'(\w[\w.]+)\s+(?:imports|导入)\s+(\w[\w.]+)',
]


def extract_facts(
    output: str,
    task_spec: dict = None,
    department: str = "",
) -> list[ExtractedFact]:
    """Extract reusable facts from agent output text.

    Args:
        output: Raw agent output / result text
        task_spec: Optional task spec for context
        department: Department that produced this output

    Returns:
        List of extracted facts, deduplicated and scored
    """
    facts = []
    output_lower = output.lower()

    # 1. Error → Fix mappings
    facts.extend(_extract_error_fixes(output))

    # 2. Configuration discoveries
    facts.extend(_extract_configs(output))

    # 3. Workarounds
    facts.extend(_extract_workarounds(output))

    # 4. Dependency facts
    facts.extend(_extract_dependencies(output))

    # 5. Performance observations
    facts.extend(_extract_performance(output))

    # Deduplicate by pattern_key
    seen = set()
    unique = []
    for f in facts:
        if f.pattern_key not in seen:
            seen.add(f.pattern_key)
            unique.append(f)

    # Sort by confidence
    unique.sort(key=lambda f: f.confidence, reverse=True)

    if unique:
        log.info(f"fact_extractor: extracted {len(unique)} facts from {len(output)} chars output")

    return unique[:15]  # Cap at 15 facts per output


def _extract_error_fixes(text: str) -> list[ExtractedFact]:
    """Extract error→fix patterns."""
    facts = []
    for error_pat, fix_pat in _ERROR_FIX_PATTERNS:
        error_matches = re.findall(error_pat, text, re.IGNORECASE)
        fix_matches = re.findall(fix_pat, text, re.IGNORECASE)

        if error_matches and fix_matches:
            error_desc = error_matches[0].strip()
            fix_desc = fix_matches[0].strip()
            key = f"error_fix:{_normalize_key(error_desc[:40])}"
            facts.append(ExtractedFact(
                pattern_key=key,
                rule=f"错误「{error_desc[:80]}」→ 修复方法：{fix_desc[:80]}",
                area="code",
                confidence=0.7,
            ))

    return facts


def _extract_configs(text: str) -> list[ExtractedFact]:
    """Extract configuration discoveries."""
    facts = []
    for pattern in _CONFIG_PATTERNS:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            if len(match) >= 2:
                key_name = match[0].strip()
                value = match[1].strip()
                if len(key_name) < 3 or len(value) < 1:
                    continue
                pkey = f"config:{_normalize_key(key_name)}"
                facts.append(ExtractedFact(
                    pattern_key=pkey,
                    rule=f"配置 {key_name} = {value}",
                    area="ops",
                    confidence=0.6,
                    ttl_days=90,  # configs may change
                ))

    return facts[:5]


def _extract_workarounds(text: str) -> list[ExtractedFact]:
    """Extract workaround patterns."""
    facts = []
    for pattern in _WORKAROUND_PATTERNS:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            parts = [m.strip() for m in match if m.strip()]
            if len(parts) >= 2:
                pkey = f"workaround:{_normalize_key(parts[0][:30])}"
                rule = " → ".join(parts[:3])
                facts.append(ExtractedFact(
                    pattern_key=pkey,
                    rule=f"变通方案：{rule[:120]}",
                    area="code",
                    confidence=0.65,
                ))

    return facts[:5]


def _extract_dependencies(text: str) -> list[ExtractedFact]:
    """Extract dependency relationships."""
    facts = []
    for pattern in _DEPENDENCY_PATTERNS:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            if len(match) >= 2:
                mod_a = match[0].strip()
                mod_b = match[1].strip()
                if len(mod_a) < 3 or len(mod_b) < 3:
                    continue
                pkey = f"dep:{_normalize_key(mod_a)}:{_normalize_key(mod_b)}"
                facts.append(ExtractedFact(
                    pattern_key=pkey,
                    rule=f"{mod_a} 依赖 {mod_b}",
                    area="code",
                    confidence=0.5,
                    ttl_days=180,  # deps change with refactors
                ))

    return facts[:5]


def _extract_performance(text: str) -> list[ExtractedFact]:
    """Extract performance observations."""
    facts = []

    # "X takes N seconds/ms"
    perf_matches = re.findall(
        r'(\w[\w.]+)\s+(?:takes?|花了|耗时)\s+(\d+(?:\.\d+)?)\s*(seconds?|s|ms|milliseconds?|秒|毫秒)',
        text, re.IGNORECASE,
    )
    for match in perf_matches:
        name = match[0].strip()
        duration = match[1]
        unit = match[2]
        pkey = f"perf:{_normalize_key(name)}"
        facts.append(ExtractedFact(
            pattern_key=pkey,
            rule=f"{name} 耗时 {duration}{unit}",
            area="ops",
            confidence=0.5,
            ttl_days=30,  # perf numbers change frequently
        ))

    return facts[:3]


def _normalize_key(s: str) -> str:
    """Normalize a string for use as a pattern_key component."""
    return re.sub(r'[^a-z0-9_]', '_', s.lower().strip())[:40]


# ── Integration with learnings table ──

def save_extracted_facts(
    db,
    facts: list[ExtractedFact],
    department: str = None,
    task_id: int = None,
    min_confidence: float = 0.5,
) -> int:
    """Save extracted facts to the learnings table.

    Only saves facts above the confidence threshold.
    Uses add_learning which handles dedup via pattern_key.

    Returns number of facts saved.
    """
    saved = 0
    for fact in facts:
        if fact.confidence < min_confidence:
            continue

        try:
            db.add_learning(
                pattern_key=fact.pattern_key,
                rule=fact.rule,
                area=fact.area,
                source_type=fact.source_type,
                department=department,
                task_id=task_id,
            )
            saved += 1
        except Exception as e:
            log.debug(f"Failed to save fact '{fact.pattern_key}': {e}")

    if saved:
        log.info(f"fact_extractor: saved {saved}/{len(facts)} facts to learnings table")

    return saved
