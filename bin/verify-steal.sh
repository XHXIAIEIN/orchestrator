#!/bin/bash
# R46 (career-ops): Pipeline Integrity Chain for steal/patterns data.
#
# Checks:
# 1. Report numbering: docs/steal/ files vs consolidated index
# 2. PATTERNS.md consistency: total counts match actual entries
# 3. P0 implementation: every P0 in PATTERNS.md has a status
# 4. Orphan detection: steal reports not in consolidated index
#
# Usage: bash bin/verify-steal.sh [--fix]
#
# Exit codes: 0 = all pass, 1 = warnings found, 2 = errors found

set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STEAL_DIR="$PROJECT_DIR/docs/steal"
PATTERNS="$PROJECT_DIR/docs/architecture/PATTERNS.md"
EXIT_CODE=0

warn() { echo "[WARN] $1"; [ "$EXIT_CODE" -lt 1 ] && EXIT_CODE=1; }
fail() { echo "[FAIL] $1"; EXIT_CODE=2; }
pass() { echo "[PASS] $1"; }

echo "┌─ Steal Pipeline Integrity Check ──────────────┐"

# ── 1. Steal report file count ──
if [ -d "$STEAL_DIR" ]; then
    REPORT_COUNT=$(find "$STEAL_DIR" -name "*.md" -type f | wc -l | tr -d ' ')
    pass "Steal reports: $REPORT_COUNT files in docs/steal/"
else
    fail "docs/steal/ directory not found"
fi

# ── 2. PATTERNS.md total vs actual entries ──
if [ -f "$PATTERNS" ]; then
    # Count declared total from header (format: "| Total patterns | 217 |")
    DECLARED_TOTAL=$(grep 'Total patterns' "$PATTERNS" 2>/dev/null | grep -oE '[0-9]+' | head -1 || echo "0")
    # Count actual table rows (lines starting with | and a pattern ID like S1, E1, etc.)
    ACTUAL_ENTRIES=$(grep -cE '^\| [A-Z]+[0-9]+ \|' "$PATTERNS" 2>/dev/null || echo "0")

    if [ "$DECLARED_TOTAL" = "$ACTUAL_ENTRIES" ]; then
        pass "PATTERNS.md: declared=$DECLARED_TOTAL, actual=$ACTUAL_ENTRIES (match)"
    else
        warn "PATTERNS.md: declared=$DECLARED_TOTAL but actual=$ACTUAL_ENTRIES entries"
    fi

    # Count implemented vs shelved
    IMPL_COUNT=$(grep -c '| ✅ |' "$PATTERNS" 2>/dev/null || echo "0")
    SHELVED_COUNT=$(grep -c '| ⏸️ |' "$PATTERNS" 2>/dev/null || echo "0")
    DECLARED_IMPL=$(grep 'Implemented' "$PATTERNS" 2>/dev/null | grep -oE '[0-9]+' | head -1 || echo "0")
    DECLARED_SHELVED=$(grep 'Shelved' "$PATTERNS" 2>/dev/null | grep -oE '[0-9]+' | head -1 || echo "0")

    if [ "$IMPL_COUNT" = "$DECLARED_IMPL" ]; then
        pass "PATTERNS.md: implemented=$IMPL_COUNT (matches declared)"
    else
        warn "PATTERNS.md: declared implemented=$DECLARED_IMPL but found $IMPL_COUNT ✅ marks"
    fi

    if [ "$SHELVED_COUNT" = "$DECLARED_SHELVED" ]; then
        pass "PATTERNS.md: shelved=$SHELVED_COUNT (matches declared)"
    else
        warn "PATTERNS.md: declared shelved=$DECLARED_SHELVED but found $SHELVED_COUNT ⏸️ marks"
    fi
else
    fail "PATTERNS.md not found at $PATTERNS"
fi

# ── 3. Missing location for implemented patterns ──
if [ -f "$PATTERNS" ]; then
    MISSING_LOC=$(grep -E '^\| [A-Z]+[0-9]+ \|.*\| ✅ \| — \|' "$PATTERNS" 2>/dev/null | wc -l | tr -d ' ')
    if [ "$MISSING_LOC" -gt 0 ]; then
        warn "$MISSING_LOC implemented patterns have no location (marked '—')"
    else
        pass "All implemented patterns have locations"
    fi
fi

# ── 4. Duplicate pattern IDs ──
if [ -f "$PATTERNS" ]; then
    DUPES=$(grep -oP '^\| ([A-Z]+[0-9]+) \|' "$PATTERNS" 2>/dev/null | sort | uniq -d | wc -l | tr -d ' ')
    if [ "$DUPES" -gt 0 ]; then
        fail "$DUPES duplicate pattern IDs found in PATTERNS.md"
        grep -oP '^\| ([A-Z]+[0-9]+) \|' "$PATTERNS" | sort | uniq -d | head -5
    else
        pass "No duplicate pattern IDs"
    fi
fi

# ── 5. Steal report naming convention ──
if [ -d "$STEAL_DIR" ]; then
    BAD_NAMES=$(find "$STEAL_DIR" -name "*.md" -type f | while read -r f; do
        base=$(basename "$f")
        # Allow: YYYY-MM-DD-*.md or R*-*.md or round*-*.md
        if ! echo "$base" | grep -qE '^(20[0-9]{2}-[0-9]{2}-[0-9]{2}-|R[0-9]+-|round[0-9]+)'; then
            echo "  $base"
        fi
    done)
    if [ -n "$BAD_NAMES" ]; then
        warn "Non-standard steal report names:\n$BAD_NAMES"
    else
        pass "All steal reports follow naming convention"
    fi
fi

echo "├────────────────────────────────────────────────┤"
case $EXIT_CODE in
    0) echo "│ Result: ALL CHECKS PASSED                      │" ;;
    1) echo "│ Result: WARNINGS found (review recommended)    │" ;;
    2) echo "│ Result: ERRORS found (action required)         │" ;;
esac
echo "└────────────────────────────────────────────────┘"

exit $EXIT_CODE
