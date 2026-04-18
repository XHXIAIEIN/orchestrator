#!/usr/bin/env python3
"""Smoke test: scan docs/steal/*.md and docs/plans/*.md for conformant YAML frontmatter.

Files without any --- frontmatter block are skipped (forward-only migration).
Exits 0 if zero failures, exits 1 if any failures.
"""

import sys
import pathlib

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

REQUIRED_ALL = {"phase", "status", "gaps"}
REQUIRED_GAP = {"phase", "note", "severity", "resolved"}
VALID_SEVERITY = {"minor", "significant"}

SCRIPT_DIR = pathlib.Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent


def parse_frontmatter(path: pathlib.Path):
    """Return parsed YAML dict if file has frontmatter block, else None."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    try:
        end = lines.index("---", 1)
    except ValueError:
        return None
    fm_text = "\n".join(lines[1:end])
    return yaml.safe_load(fm_text)


def check_gaps(gaps, filepath):
    """Validate each gap entry. Return list of error strings."""
    errors = []
    if not isinstance(gaps, list):
        errors.append(f"gaps must be a list, got {type(gaps).__name__}")
        return errors
    for i, gap in enumerate(gaps):
        if not isinstance(gap, dict):
            errors.append(f"gaps[{i}] must be a mapping, got {type(gap).__name__}")
            continue
        missing = REQUIRED_GAP - gap.keys()
        if missing:
            errors.append(f"gaps[{i}] missing keys: {sorted(missing)}")
        if "severity" in gap and gap["severity"] not in VALID_SEVERITY:
            errors.append(
                f"gaps[{i}].severity must be 'minor' or 'significant', got {gap['severity']!r}"
            )
        if "resolved" in gap and not isinstance(gap["resolved"], bool):
            errors.append(
                f"gaps[{i}].resolved must be bool, got {type(gap['resolved']).__name__}"
            )
    return errors


def check_file(path: pathlib.Path):
    """Return list of error strings for path. Empty list = PASS."""
    fm = parse_frontmatter(path)
    if fm is None:
        return None  # skip — no frontmatter block at all

    # Forward-only migration: skip files that have a frontmatter block but
    # no 'phase' field — these are pre-schema artifacts (old format, not yet migrated).
    if "phase" not in fm:
        return None

    errors = []
    missing = REQUIRED_ALL - fm.keys()
    if missing:
        errors.append(f"missing required fields: {sorted(missing)}")

    if "phase" in fm and not isinstance(fm["phase"], str):
        errors.append(f"phase must be string, got {type(fm['phase']).__name__}")

    if "status" in fm and fm["status"] is None:
        errors.append("status must not be null")

    if "gaps" in fm:
        errors.extend(check_gaps(fm["gaps"], path))

    return errors


def main():
    patterns = ["docs/steal/*.md", "docs/plans/*.md"]
    failures = 0
    checked = 0

    for pattern in patterns:
        for path in sorted(REPO_ROOT.glob(pattern)):
            rel = path.relative_to(REPO_ROOT)
            result = check_file(path)
            if result is None:
                # no frontmatter — skip silently
                continue
            checked += 1
            if result:
                failures += 1
                for err in result:
                    print(f"FAIL: {rel} — {err}")
            else:
                print(f"PASS: {rel}")

    if checked == 0:
        print("INFO: no files with frontmatter found — nothing to check")

    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
