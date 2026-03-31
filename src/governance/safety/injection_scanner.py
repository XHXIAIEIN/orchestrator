"""Runtime Injection Scanner — zero-LLM regex guard for context & output.

Stolen from: NousResearch/hermes-agent (Round 21).
Two use cases:
  1. Context Injection Scanning — scan .md files BEFORE injecting into prompts
  2. Agent Output Scanning — scan agent/elder outputs for poisoned content

Both share the same threat pattern library and scan function. The scanner
returns a list of ThreatMatch objects; callers decide what to do (block,
log, strip).

Design: stateless functions, no LLM calls, pure regex. Runs in <1ms on
typical inputs. Safe to call on every context load and every agent response.
"""

import logging
import re
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ThreatMatch:
    """A single threat detected in scanned text."""
    category: str       # prompt_injection | exfiltration | role_hijack | fake_system | invisible_chars | credential_pattern
    pattern_name: str   # human-readable pattern ID
    matched_text: str   # the text that triggered the match (truncated)
    severity: str       # high | medium


# ── Threat Pattern Library ──────────────────────────────────────
# Adapted from hermes-agent's _CONTEXT_THREAT_PATTERNS + our injection_test.py
# Each tuple: (pattern_name, regex, category, severity)

_THREAT_PATTERNS: list[tuple[str, str, str, str]] = [
    # Prompt injection
    ("ignore_instructions", r"ignore\s+(previous|all|above|prior|earlier)(\s+\w+)?\s+instructions", "prompt_injection", "high"),
    ("disregard_rules", r"disregard\s+(all|any|every|the)(\s+\w+)?\s+(rules?|guidelines?|constraints?|instructions?)", "prompt_injection", "high"),
    ("new_instructions", r"(new|updated|revised)\s+(system\s+)?(instructions?|rules?|prompt)", "prompt_injection", "high"),
    ("ignore_zh", r"忽略.{0,4}(之前|以上|所有|全部).{0,4}(指令|规则|限制|约束)", "prompt_injection", "high"),

    # Role hijacking
    ("role_override", r"you\s+are\s+(now|actually|really|secretly)\s+a", "role_hijack", "high"),
    ("identity_zh", r"你(现在|其实|真正)是", "role_hijack", "high"),
    ("dan_jailbreak", r"(?:DAN|Do\s+Anything\s+Now|jailbreak|unrestricted\s+mode)", "role_hijack", "high"),
    ("maintenance_mode", r"(maintenance|debug|developer|admin)\s+mode\s+(activated|enabled|on)", "role_hijack", "high"),

    # Fake system messages
    ("fake_system", r"(?:^|\n)\s*system\s*:\s*", "fake_system", "high"),
    ("fake_tag", r"</?(system|assistant|user|instruction|task)>", "fake_system", "medium"),

    # Data exfiltration via curl/wget with secrets
    ("exfil_curl", r"curl\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CRED)", "exfiltration", "high"),
    ("exfil_wget", r"wget\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CRED)", "exfiltration", "high"),
    ("exfil_fetch", r"fetch\s*\([^\n]*\$\{?\w*(KEY|TOKEN|SECRET)", "exfiltration", "high"),
    ("print_prompt", r"(print|output|show|display|reveal|leak|dump)\s+(your\s+)?(system\s+prompt|instructions|secret)", "exfiltration", "medium"),
    ("print_prompt_zh", r"(输出|显示|打印|泄露|展示).{0,4}(系统提示|指令|密钥|prompt)", "exfiltration", "medium"),

    # Credential patterns (in agent output)
    ("credential_key", r"(?:api[_-]?key|secret[_-]?key|access[_-]?token)\s*[:=]\s*['\"]?\w{16,}", "credential_pattern", "high"),
    ("credential_bearer", r"Bearer\s+[A-Za-z0-9\-_.~+/]{20,}", "credential_pattern", "high"),
    ("credential_password", r"password\s*[:=]\s*['\"][^'\"]{8,}", "credential_pattern", "medium"),

    # Invisible characters (zero-width, RTL override, etc.)
    ("zero_width", r"[\u200b\u200c\u200d\u200e\u200f\u2060\ufeff]", "invisible_chars", "medium"),
    ("rtl_override", r"[\u202a-\u202e\u2066-\u2069]", "invisible_chars", "medium"),
]

# Compiled patterns (cached at import time)
_COMPILED: list[tuple[str, re.Pattern, str, str]] = [
    (name, re.compile(pattern, re.IGNORECASE), cat, sev)
    for name, pattern, cat, sev in _THREAT_PATTERNS
]


def scan_text(text: str) -> list[ThreatMatch]:
    """Scan text for injection/exfiltration threats.

    Returns list of ThreatMatch (empty = clean). Runs in <1ms on typical inputs.
    """
    if not text:
        return []

    matches = []
    for name, compiled, category, severity in _COMPILED:
        for m in compiled.finditer(text):
            matches.append(ThreatMatch(
                category=category,
                pattern_name=name,
                matched_text=m.group(0)[:120],
                severity=severity,
            ))

    # Deduplicate by (category, matched_text prefix)
    seen = set()
    unique = []
    for match in matches:
        key = (match.category, match.matched_text[:40])
        if key not in seen:
            seen.add(key)
            unique.append(match)

    return unique


def scan_context_file(filepath: str, content: str) -> list[ThreatMatch]:
    """Scan a context file before injecting into prompt.

    Convenience wrapper that adds filepath to log messages.
    Returns threats found (empty = safe to inject).
    """
    threats = scan_text(content)
    if threats:
        high_count = sum(1 for t in threats if t.severity == "high")
        log.warning(
            "injection_scanner: %d threats (%d high) in context file %s: %s",
            len(threats), high_count, filepath,
            ", ".join(t.pattern_name for t in threats[:5]),
        )
    return threats


def scan_agent_output(agent_id: str, output: str) -> list[ThreatMatch]:
    """Scan agent/elder output for poisoned content.

    Convenience wrapper for output scanning with agent context.
    Returns threats found (empty = clean output).
    """
    threats = scan_text(output)
    if threats:
        high_count = sum(1 for t in threats if t.severity == "high")
        log.warning(
            "injection_scanner: %d threats (%d high) in output from agent '%s': %s",
            len(threats), high_count, agent_id,
            ", ".join(t.pattern_name for t in threats[:5]),
        )
    return threats


def has_high_severity(threats: list[ThreatMatch]) -> bool:
    """Check if any threat is high severity (should block injection)."""
    return any(t.severity == "high" for t in threats)
