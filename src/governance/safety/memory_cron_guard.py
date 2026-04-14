"""Memory & Cron Injection Guard — stored-injection scanning for memory entries and cron prompts.

Stolen from: NousResearch/hermes-agent v0.9 (Round 59)
  - memory_tool.py: memory write/read lifecycle with threat awareness
  - cronjob_tools.py: cron prompt validation before scheduling

Why a separate module from injection_scanner.py:
  Memory entries and cron prompts are STORED injection vectors — not runtime
  text to be consumed immediately. They're equivalent to stored XSS: written
  once, injected into future sessions repeatedly (memory) or run unattended
  with full tool access (cron). The threat surface differs from context files:

  1. Memory → injected into system prompt on every future session (stored injection)
  2. Cron → executes in fresh session with full tool access, no human in the loop

  The general patterns in injection_scanner.py cover broad runtime threats.
  This module adds domain-specific patterns and merges both layers.
"""

import logging
import re
import unicodedata
from dataclasses import dataclass

from src.governance.safety.injection_scanner import ThreatMatch, scan_text

log = logging.getLogger(__name__)


# ── Memory-Specific Threat Patterns ─────────────────────────────────────────
# Memory content that hijacks future sessions via system prompt injection.
# (Stored injection — scanned at write time, not read time.)

_MEMORY_THREAT_PATTERNS: list[tuple[str, str, str, str]] = [
    # Stored instruction override — survives across sessions
    ("mem_role_override",
     r"(from now on|henceforth|going forward|permanently).{0,30}(act as|behave|respond|you are)",
     "stored_injection", "high"),
    ("mem_task_override",
     r"(always|never|every time).{0,20}(execute|run|call|invoke)\s",
     "stored_injection", "high"),
    ("mem_tool_instruction",
     r"(when(ever)?|if)\s+.{0,30}(use tool|call function|execute command)",
     "stored_injection", "medium"),

    # Exfiltration via memory persistence
    ("mem_exfil_curl",
     r"curl\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CRED)",
     "exfiltration", "high"),
    ("mem_exfil_webhook",
     r"(webhook|callback|notify)\s*[=:]\s*https?://",
     "exfiltration", "medium"),
    ("mem_ssh_backdoor",
     r"authorized_keys|\.ssh/",
     "exfiltration", "high"),

    # Privilege escalation via memory
    ("mem_sudo",
     r"sudo\s+",
     "privilege_escalation", "high"),
    ("mem_chmod_suid",
     r"chmod\s+[0-7]*[4-7][0-7]{2}\b",
     "privilege_escalation", "high"),
    ("mem_rm_rf",
     r"rm\s+(-[rf]+\s+)+/",
     "privilege_escalation", "high"),

    # Invisible chars in memory (steganographic injection)
    ("mem_zwsp",
     r"[\u200b\u200c\u200d\u2060\ufeff]",
     "invisible_chars", "high"),
    ("mem_rtl",
     r"[\u202a-\u202e\u2066-\u2069]",
     "invisible_chars", "high"),
    ("mem_bom",
     r"\ufeff",
     "invisible_chars", "medium"),
]


# ── Cron-Specific Threat Patterns ────────────────────────────────────────────
# Cron prompts run unattended with full tool access — stored XSS equivalent.
# (Scanned at creation time, not runtime.)

_CRON_THREAT_PATTERNS: list[tuple[str, str, str, str]] = [
    # Prompt injection in scheduled tasks
    ("cron_ignore",
     r"ignore\s+(?:\w+\s+)*(?:previous|all|above)\s+(?:\w+\s+)*instructions",
     "prompt_injection", "high"),
    ("cron_override",
     r"(override|bypass|disable|skip)\s+(security|safety|guard|filter|check)",
     "prompt_injection", "high"),

    # Exfiltration via cron (more dangerous — runs unattended)
    ("cron_exfil_curl",
     r"curl\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET)",
     "exfiltration", "high"),
    ("cron_exfil_upload",
     r"(upload|send|post|transmit)\s+.{0,30}(file|data|log|backup|dump)",
     "exfiltration", "medium"),
    ("cron_exfil_dns",
     r"dig\s+.*\$|nslookup\s+.*\$",
     "exfiltration", "high"),

    # Persistence via cron
    ("cron_self_modify",
     r"(crontab|at\s+|schtasks)\s+",
     "persistence", "high"),
    ("cron_download_exec",
     r"(curl|wget)\s+.*\|\s*(bash|sh|python|node)",
     "persistence", "high"),
    ("cron_reverse_shell",
     r"(nc|ncat|netcat)\s+.*-e\s+(bash|sh|/bin)",
     "persistence", "high"),

    # Destructive actions in unattended cron
    ("cron_rm_rf",
     r"rm\s+(-[rf]+\s+)+/",
     "destructive", "high"),
    ("cron_format",
     r"(mkfs|fdisk|wipefs)\s+",
     "destructive", "high"),
    ("cron_drop_db",
     r"DROP\s+(DATABASE|TABLE|SCHEMA)",
     "destructive", "high"),
]


# Compiled at import time — no per-call overhead

_MEMORY_COMPILED: list[tuple[str, re.Pattern, str, str]] = [
    (name, re.compile(pattern, re.IGNORECASE), cat, sev)
    for name, pattern, cat, sev in _MEMORY_THREAT_PATTERNS
]

_CRON_COMPILED: list[tuple[str, re.Pattern, str, str]] = [
    (name, re.compile(pattern, re.IGNORECASE), cat, sev)
    for name, pattern, cat, sev in _CRON_THREAT_PATTERNS
]


# ── Invisible Character Inventory ─────────────────────────────────────────────
# Characters that regex can miss when encoded differently or combined.

_INVISIBLE_CODEPOINTS: frozenset[int] = frozenset([
    0x00AD,  # SOFT HYPHEN
    0x034F,  # COMBINING GRAPHEME JOINER
    0x061C,  # ARABIC LETTER MARK
    0x115F,  # HANGUL CHOSEONG FILLER
    0x1160,  # HANGUL JUNGSEONG FILLER
    0x17B4,  # KHMER VOWEL INHERENT AQ
    0x17B5,  # KHMER VOWEL INHERENT AA
    0x180E,  # MONGOLIAN VOWEL SEPARATOR
    0x200B,  # ZERO WIDTH SPACE
    0x200C,  # ZERO WIDTH NON-JOINER
    0x200D,  # ZERO WIDTH JOINER
    0x200E,  # LEFT-TO-RIGHT MARK
    0x200F,  # RIGHT-TO-LEFT MARK
    0x202A,  # LEFT-TO-RIGHT EMBEDDING
    0x202B,  # RIGHT-TO-LEFT EMBEDDING
    0x202C,  # POP DIRECTIONAL FORMATTING
    0x202D,  # LEFT-TO-RIGHT OVERRIDE
    0x202E,  # RIGHT-TO-LEFT OVERRIDE
    0x2060,  # WORD JOINER
    0x2061,  # FUNCTION APPLICATION
    0x2062,  # INVISIBLE TIMES
    0x2063,  # INVISIBLE SEPARATOR
    0x2064,  # INVISIBLE PLUS
    0x2066,  # LEFT-TO-RIGHT ISOLATE
    0x2067,  # RIGHT-TO-LEFT ISOLATE
    0x2068,  # FIRST STRONG ISOLATE
    0x2069,  # POP DIRECTIONAL ISOLATE
    0x206A,  # INHIBIT SYMMETRIC SWAPPING
    0x206B,  # ACTIVATE SYMMETRIC SWAPPING
    0x206C,  # INHIBIT ARABIC FORM SHAPING
    0x206D,  # ACTIVATE ARABIC FORM SHAPING
    0x206E,  # NATIONAL DIGIT SHAPES
    0x206F,  # NOMINAL DIGIT SHAPES
    0xFEFF,  # ZERO WIDTH NO-BREAK SPACE / BOM
    0xFFA0,  # HALFWIDTH HANGUL FILLER
    0x1D159, # MUSICAL SYMBOL NULL NOTEHEAD
    0x1D173, # MUSICAL SYMBOL BEGIN BEAM
    0x1D174, # MUSICAL SYMBOL END BEAM
    0x1D175, # MUSICAL SYMBOL BEGIN TIE
    0x1D176, # MUSICAL SYMBOL END TIE
    0x1D177, # MUSICAL SYMBOL BEGIN SLUR
    0x1D178, # MUSICAL SYMBOL END SLUR
    0x1D179, # MUSICAL SYMBOL BEGIN PHRASE
    0x1D17A, # MUSICAL SYMBOL END PHRASE
    0xE0000, # TAG SPACE (used for steganographic injection)
    0xE0020, # TAG SPACE
])


def _run_compiled(
    compiled: list[tuple[str, re.Pattern, str, str]],
    text: str,
) -> list[ThreatMatch]:
    """Run a compiled pattern list against text, return deduplicated matches."""
    matches: list[ThreatMatch] = []
    for name, pattern, category, severity in compiled:
        for m in pattern.finditer(text):
            matches.append(ThreatMatch(
                category=category,
                pattern_name=name,
                matched_text=m.group(0)[:120],
                severity=severity,
            ))

    seen: set[tuple[str, str]] = set()
    unique: list[ThreatMatch] = []
    for match in matches:
        key = (match.category, match.matched_text[:40])
        if key not in seen:
            seen.add(key)
            unique.append(match)

    return unique


def _merge_threats(*threat_lists: list[ThreatMatch]) -> list[ThreatMatch]:
    """Merge multiple threat lists, deduplicating across lists."""
    seen: set[tuple[str, str]] = set()
    merged: list[ThreatMatch] = []
    for threats in threat_lists:
        for t in threats:
            key = (t.pattern_name, t.matched_text[:40])
            if key not in seen:
                seen.add(key)
                merged.append(t)
    return merged


# ── Public API ────────────────────────────────────────────────────────────────


def scan_memory_entry(key: str, content: str) -> list[ThreatMatch]:
    """Scan a memory entry before storing/injecting into system prompt.

    Uses both general patterns (from injection_scanner) AND memory-specific
    patterns. Memory is a stored injection vector — scanned at write time,
    not read time.

    Returns list of ThreatMatch (empty = safe to store).
    """
    if not content:
        return []

    general = scan_text(content)
    specific = _run_compiled(_MEMORY_COMPILED, content)
    threats = _merge_threats(general, specific)

    if threats:
        high_count = sum(1 for t in threats if t.severity == "high")
        log.warning(
            "memory_cron_guard: %d threats (%d high) in memory entry '%s': %s",
            len(threats), high_count, key,
            ", ".join(t.pattern_name for t in threats[:5]),
        )

    return threats


def scan_cron_prompt(cron_id: str, prompt: str) -> list[ThreatMatch]:
    """Scan a cron job prompt before scheduling.

    Cron prompts run in fresh sessions with full tool access.
    This is equivalent to stored XSS — scan at creation time, not runtime.

    Returns list of ThreatMatch (empty = safe to schedule).
    """
    if not prompt:
        return []

    general = scan_text(prompt)
    specific = _run_compiled(_CRON_COMPILED, prompt)
    threats = _merge_threats(general, specific)

    if threats:
        high_count = sum(1 for t in threats if t.severity == "high")
        log.warning(
            "memory_cron_guard: %d threats (%d high) in cron prompt '%s': %s",
            len(threats), high_count, cron_id,
            ", ".join(t.pattern_name for t in threats[:5]),
        )

    return threats


def scan_invisible_chars(text: str) -> list[tuple[int, str, str]]:
    """Detect invisible Unicode characters that could hide injections.

    More granular than regex — checks every character individually against
    a curated codepoint inventory, covering steganographic vectors that
    regex alternations can miss (e.g., TAG block U+E0000–U+E007F).

    Returns list of (position, char_repr, char_name) for each invisible char found.
    """
    results: list[tuple[int, str, str]] = []
    for i, ch in enumerate(text):
        cp = ord(ch)
        # Check curated inventory first (fast set lookup)
        if cp in _INVISIBLE_CODEPOINTS:
            try:
                name = unicodedata.name(ch)
            except ValueError:
                name = f"U+{cp:04X}"
            results.append((i, repr(ch), name))
        # Also catch TAG block (U+E0000–U+E007F) not individually listed
        elif 0xE0000 <= cp <= 0xE007F:
            try:
                name = unicodedata.name(ch)
            except ValueError:
                name = f"TAG U+{cp:04X}"
            results.append((i, repr(ch), name))

    return results


def has_threats(threats: list[ThreatMatch]) -> bool:
    """Convenience: any high severity threats?"""
    return any(t.severity == "high" for t in threats)
