"""CLI entry point for security-scan.sh hook.

Usage: python3 _hook_scan.py <tool_name> < content_to_scan

Stdout (if matches found):
  line 1: risk level (REJECT | HIGH)
  line 2+: match summaries

Exit 0 always (decision conveyed via stdout text, not exit code).
"""

import sys
import os

# Locate repo root via argv[0] directory
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.dirname(_THIS_DIR)
_REPO_ROOT = os.path.dirname(_SRC_DIR)
sys.path.insert(0, _REPO_ROOT)

from src.security.scanner import scan_content, highest_risk, format_matches
from src.security.patterns import RiskLevel


def main() -> None:
    tool_name = sys.argv[1] if len(sys.argv) > 1 else "unknown"
    text = sys.stdin.read()

    matches = scan_content(text)
    if not matches:
        return

    risk = highest_risk(matches)
    summary = format_matches(matches)

    if risk in (RiskLevel.REJECT, RiskLevel.HIGH):
        print(risk.value)
        print(summary)


if __name__ == "__main__":
    main()
