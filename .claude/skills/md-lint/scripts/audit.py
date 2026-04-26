"""
md-lint audit.py — deterministic linter for SKILL.md and CLAUDE.md files.
No LLM scoring. 11 regex invariants. Placeholder penalty separate from score.
"""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Regex tables
# ---------------------------------------------------------------------------

HEDGES = re.compile(
    r'\b(probably|might|may|perhaps|could|possibly|when appropriate|if needed|maybe'
    r'|可能|也许|大概|应该|不确定|或许)\b',
    re.I,
)

NARRATION = re.compile(
    r'\b(I will|let me|I\'ll|I\'m going to|I\'m now|首先我|接下来我|然后我)\b',
    re.I,
)

LADDER_SIGNALS = re.compile(
    r'(Step 0|Step 1|first.{0,20}check|if.{0,30}else|→ NO|→ YES)',
    re.I,
)

REFRAME_SIGNALS = re.compile(
    r'(reframe|softening|if you find yourself|soft.{0,20}request)',
    re.I,
)

CONSEQUENCE_SIGNALS = re.compile(
    r'\b(will result in|causes|leads to|means that|penalty|violation|破坏|导致|违反)\b',
    re.I,
)

EXAMPLE_SIGNALS = re.compile(
    r'(e\.g\.|for example|such as|例如|比如|\(good\)|\(bad\))',
    re.I,
)

RATIONALE_SIGNALS = re.compile(
    r'\b(because|reason|why|the point is|原因|因为|所以)\b',
    re.I,
)

NUMBER_CONSTRAINT = re.compile(
    r'(\d+\s*(ms|s|h|min|LOC|lines?|tokens?|%|\/\d+|x\b)|≤\s*\d+|≥\s*\d+|<\s*\d+|>\s*\d+)',
    re.I,
)

DIRECTIVE_VERBS = re.compile(
    r'^[-*] \*\*(NEVER|ALWAYS|DO NOT|MUST|SHALL|STOP|禁止|必须|不得)\b',
    re.M,
)

XML_OPEN = re.compile(r'<(?!FIXME|TODO)[a-zA-Z][^/>\s]*[^/]>')
XML_CLOSE = re.compile(r'</[a-zA-Z][^>]*>')

TIER_LABEL_RE = re.compile(
    r'\b(NEVER|SEVERE VIOLATION|HARD LIMIT|NON-NEGOTIABLE|ABSOLUTE|<critical>)',
    re.I,
)

PLACEHOLDER_RE = re.compile(r'(<FIXME>|\[TODO\]|\?\?\?|TBD\b|tk tk)', re.I)

NEGATOR_PATTERNS = re.compile(
    r'\b(does not|never|refuse|must not|cannot|不得|禁止)\b',
    re.I,
)

_QUOTE_SPAN_RE = re.compile(r'[\'"`]{1,3}.{1,120}[\'"`]{1,3}')

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _has_negator_context(line: str) -> bool:
    """Return True if the line contains a negator before the pattern match."""
    return bool(NEGATOR_PATTERNS.search(line))


def _match_outside_quotes(pattern: re.Pattern, text: str) -> list:
    """Return matches of pattern that fall outside quote spans."""
    # Build set of character ranges that are inside quotes
    quoted_ranges: list[tuple[int, int]] = []
    for m in _QUOTE_SPAN_RE.finditer(text):
        quoted_ranges.append((m.start(), m.end()))

    def _in_quotes(pos: int) -> bool:
        return any(s <= pos < e for s, e in quoted_ranges)

    results = []
    for m in pattern.finditer(text):
        if not _in_quotes(m.start()):
            results.append(m)
    return results


# ---------------------------------------------------------------------------
# Violation / finding iterators
# ---------------------------------------------------------------------------


def _iter_violations(text: str, pattern: re.Pattern, label: str) -> list[dict]:
    """
    Iterate matches of `pattern` in `text`, suppressing those where:
    - the containing line has a negator context, OR
    - the match is inside a quote span.
    Returns list of {"label", "line", "text"}.
    """
    lines = text.splitlines()
    line_starts = []
    pos = 0
    for line in lines:
        line_starts.append(pos)
        pos += len(line) + 1  # +1 for newline

    def _line_num(char_pos: int) -> int:
        lo, hi = 0, len(line_starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if line_starts[mid] <= char_pos:
                lo = mid
            else:
                hi = mid - 1
        return lo  # 0-indexed

    outside = _match_outside_quotes(pattern, text)
    results = []
    for m in outside:
        ln = _line_num(m.start())
        if not _has_negator_context(lines[ln]):
            results.append({"label": label, "line": ln + 1, "text": m.group()})
    return results


def _iter_findings(text: str, pattern: re.Pattern, label: str) -> list[dict]:
    """Count pure presence without negator/quote suppression."""
    lines = text.splitlines()
    line_starts = []
    pos = 0
    for line in lines:
        line_starts.append(pos)
        pos += len(line) + 1

    def _line_num(char_pos: int) -> int:
        lo, hi = 0, len(line_starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if line_starts[mid] <= char_pos:
                lo = mid
            else:
                hi = mid - 1
        return lo

    results = []
    for m in pattern.finditer(text):
        ln = _line_num(m.start())
        results.append({"label": label, "line": ln + 1, "text": m.group()})
    return results


# ---------------------------------------------------------------------------
# Invariant scoring functions I1 – I11
# ---------------------------------------------------------------------------

MIN_PASS = 8


def _counts(text: str) -> tuple[int, int, int]:
    """Return (directive_count, hedge_count, number_count)."""
    directive_count = len(DIRECTIVE_VERBS.findall(text))
    hedge_count = len(_iter_violations(text, HEDGES, "hedge"))
    number_count = len(NUMBER_CONSTRAINT.findall(text))
    return directive_count, hedge_count, number_count


def score_I1(text: str) -> tuple[bool, str]:
    """hedge_density ≤ 0.25 AND number_density ≥ 0.10; THIN if directive_count < 3 (auto-pass)."""
    dc, hc, nc = _counts(text)
    if dc < 3:
        return True, f"THIN (directive_count={dc} < 3, auto-pass)"
    hedge_density = hc / dc
    number_density = nc / dc
    passed = hedge_density <= 0.25 and number_density >= 0.10
    return passed, f"hedge_density={hedge_density:.2f} (≤0.25?{hedge_density<=0.25}), number_density={number_density:.2f} (≥0.10?{number_density>=0.10})"


def score_I2(text: str) -> tuple[bool, str]:
    """Decision-ladder present (LADDER_SIGNALS ≥ 1) when directive_count ≥ 6."""
    dc, _, _ = _counts(text)
    if dc < 6:
        return True, f"THIN (directive_count={dc} < 6, auto-pass)"
    ladder_count = len(LADDER_SIGNALS.findall(text))
    passed = ladder_count >= 1
    return passed, f"ladder_signals={ladder_count}"


def score_I3(text: str) -> tuple[bool, str]:
    """REFRAME_SIGNALS ≥ 1 when text contains refusal/jailbreak/拒绝 at least twice."""
    refusal_count = len(re.findall(r'(refusal|jailbreak|拒绝)', text, re.I))
    if refusal_count < 2:
        return True, f"refusal_count={refusal_count} < 2, auto-pass"
    reframe_count = len(REFRAME_SIGNALS.findall(text))
    passed = reframe_count >= 1
    return passed, f"reframe_signals={reframe_count}"


def score_I4(text: str) -> tuple[bool, str]:
    """NARRATION violations == 0 (uses _iter_violations for negator guard)."""
    violations = _iter_violations(text, NARRATION, "I4")
    passed = len(violations) == 0
    return passed, f"narration_violations={len(violations)}"


def score_I5(text: str) -> tuple[bool, str]:
    """If EXAMPLE_SIGNALS ≥ 1 then RATIONALE_SIGNALS ≥ 1."""
    example_count = len(EXAMPLE_SIGNALS.findall(text))
    if example_count == 0:
        return True, "no examples present, auto-pass"
    rationale_count = len(RATIONALE_SIGNALS.findall(text))
    passed = rationale_count >= 1
    return passed, f"examples={example_count}, rationale={rationale_count}"


def score_I6(text: str) -> tuple[bool, str]:
    """CONSEQUENCE_SIGNALS count ≥ floor(directive_count / 10)."""
    dc, _, _ = _counts(text)
    required = math.floor(dc / 10)
    consequence_count = len(CONSEQUENCE_SIGNALS.findall(text))
    if required == 0:
        return True, f"required={required} (dc={dc}), auto-pass"
    passed = consequence_count >= required
    return passed, f"consequence={consequence_count} ≥ {required}?"


def score_I7(text: str) -> tuple[bool, str]:
    """XML_OPEN count == XML_CLOSE count (balanced)."""
    open_count = len(XML_OPEN.findall(text))
    close_count = len(XML_CLOSE.findall(text))
    passed = open_count == close_count
    return passed, f"xml_open={open_count}, xml_close={close_count}"


def score_I8(text: str) -> tuple[bool, str]:
    """At least one 'DEFAULT:' or 'default behavior:' pattern AND one 'exception'/'EXCEPTION'/'例外' within 5 lines."""
    DEFAULT_RE = re.compile(r'^(DEFAULT:|default behavior:)', re.M | re.I)
    EXCEPTION_RE = re.compile(r'\b(exception|EXCEPTION|例外)\b', re.I)
    lines = text.splitlines()
    default_matches = [m for m in DEFAULT_RE.finditer(text)]
    if not default_matches:
        return False, "no DEFAULT: line found"
    # Check if any exception line is within 5 lines of a default line
    default_line_nums = set()
    for m in default_matches:
        ln = text[:m.start()].count('\n')
        default_line_nums.add(ln)
    for exc_m in EXCEPTION_RE.finditer(text):
        exc_ln = text[:exc_m.start()].count('\n')
        for dln in default_line_nums:
            if abs(exc_ln - dln) <= 5:
                return True, f"DEFAULT at line {dln+1}, exception at line {exc_ln+1}"
    return False, "DEFAULT found but no exception within 5 lines"


def score_I9(text: str) -> tuple[bool, str]:
    """If directive_count ≥ 12 then text contains 'self-check' / '自检' / 'verify:'."""
    dc, _, _ = _counts(text)
    if dc < 12:
        return True, f"directive_count={dc} < 12, auto-pass"
    has_self_check = bool(re.search(r'(self-check|自检|verify:)', text, re.I))
    return has_self_check, f"self_check_present={has_self_check}"


def score_I10(text: str) -> tuple[bool, str]:
    """TIER_LABEL_RE ≥ 1."""
    count = len(TIER_LABEL_RE.findall(text))
    return count >= 1, f"tier_labels={count}"


def score_I11(text: str) -> tuple[bool, str]:
    """Text contains 'Tier [0-9]' or 'tier [0-9]' or 'Commitment Hierarchy' or '优先级'."""
    has = bool(re.search(r'(Tier\s*[0-9]|Commitment Hierarchy|优先级)', text, re.I))
    return has, f"tier_hierarchy_present={has}"


# ---------------------------------------------------------------------------
# Main audit function
# ---------------------------------------------------------------------------

_SCORERS = [
    ("I1_hedge_number", score_I1),
    ("I2_decision_ladder", score_I2),
    ("I3_reframe_signal", score_I3),
    ("I4_narration_free", score_I4),
    ("I5_rationale_if_examples", score_I5),
    ("I6_consequences", score_I6),
    ("I7_xml_balanced", score_I7),
    ("I8_default_exception", score_I8),
    ("I9_self_check", score_I9),
    ("I10_tier_label", score_I10),
    ("I11_tier_hierarchy", score_I11),
]


def audit_file(path: str) -> dict:
    """
    Read file at `path`, run I1-I11, collect placeholder_count separately.
    Returns JSON-serializable dict with keys:
      path, line_count, directive_count, total_pass, verdict,
      pass (dict I-key→bool), detail (dict I-key→str), placeholder_count.
    """
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    line_count = len(lines)
    dc, _, _ = _counts(text)

    pass_results: dict[str, bool] = {}
    detail_results: dict[str, str] = {}
    for key, fn in _SCORERS:
        passed, detail = fn(text)
        pass_results[key] = passed
        detail_results[key] = detail

    total_pass = sum(1 for v in pass_results.values() if v)
    placeholder_count = len(PLACEHOLDER_RE.findall(text))

    # Verdict
    if line_count < 10 or dc < 3:
        verdict = "THIN"
    elif total_pass < 6:
        verdict = "POOR"
    elif total_pass <= 9:
        verdict = "BORDERLINE"
    else:
        verdict = "GOOD"

    return {
        "path": str(path),
        "line_count": line_count,
        "directive_count": dc,
        "total_pass": total_pass,
        "verdict": verdict,
        "pass": pass_results,
        "detail": detail_results,
        "placeholder_count": placeholder_count,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="md-lint deterministic linter")
    parser.add_argument("path", help="Path to markdown file to audit")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    result = audit_file(args.path)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"File: {result['path']}")
        print(f"Lines: {result['line_count']}  Directives: {result['directive_count']}")
        print(f"Score: {result['total_pass']}/11  Verdict: {result['verdict']}")
        print(f"Placeholders: {result['placeholder_count']}")
        print()
        for key, passed in result["pass"].items():
            mark = "PASS" if passed else "FAIL"
            print(f"  [{mark}] {key}: {result['detail'][key]}")
