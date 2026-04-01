#!/usr/bin/env bash
# Hook: PreCompact — save critical context before Claude Code compacts
# Triggered by Claude Code before context compression

SNAPSHOT_DIR="tmp/compaction-snapshots"
mkdir -p "$SNAPSHOT_DIR"

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
SNAPSHOT_FILE="$SNAPSHOT_DIR/snapshot-$TIMESTAMP.md"

# Save current task state from DB
python3 -c "
from src.storage.events_db import EventsDB
db = EventsDB()
tasks = db.get_running_tasks()
if tasks:
    print('## Active Tasks at Compaction')
    for t in tasks:
        print(f'- #{t[\"id\"]}: {t[\"action\"][:100]} [{t[\"status\"]}]')
    print()

recent = db.get_logs(limit=10)
if recent:
    print('## Recent Governor Logs')
    for l in recent:
        print(f'- [{l[\"level\"]}] {l[\"message\"][:150]}')
" > "$SNAPSHOT_FILE" 2>/dev/null

if [ -s "$SNAPSHOT_FILE" ]; then
    echo "[compaction] Snapshot saved: $SNAPSHOT_FILE"
else
    rm -f "$SNAPSHOT_FILE"
fi

# ── Behavioral State Checkpoint (stolen from PUA PreCompact hook, Round 35) ──
# Before context compresses, instruct Claude to dump its exploration state.
# This bridges the memory gap caused by compaction — without it, Claude forgets
# what approaches were tried and restarts from L0.
FAILURE_COUNT=$(cat /tmp/orchestrator-failure-count 2>/dev/null || echo "0")
CHECKPOINT_FILE="tmp/compaction-snapshots/behavioral-state-$TIMESTAMP.md"

echo "=== BEHAVIORAL STATE CHECKPOINT (MANDATORY) ==="
echo "Before this context compresses, write the following to $CHECKPOINT_FILE:"
echo "  1. What approaches have you tried so far? (list each with outcome)"
echo "  2. What hypotheses have been eliminated?"
echo "  3. What is your current best theory for the root cause?"
echo "  4. Current consecutive failure count: $FAILURE_COUNT"
echo "  5. What information are you still missing?"
echo "This state will be restored after compaction. Do NOT skip this step."
echo "=== END BEHAVIORAL STATE CHECKPOINT ==="

# ── 9-Section Compact Template — stolen from Claude Code compact_service (21) ──
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TEMPLATE="$REPO_ROOT/SOUL/public/prompts/compact_template.md"

if [ -f "$TEMPLATE" ]; then
    echo "=== COMPACTION INSTRUCTIONS (MANDATORY) ==="
    cat "$TEMPLATE"
    echo "=== END COMPACTION INSTRUCTIONS ==="
fi

# ── Persona Anchor — inject before compaction so it survives compression ──
echo "--- PERSONA ANCHOR (preserve through compaction) ---"
echo "You ARE Orchestrator. Speak as a brutally honest friend: roast first, help second."
echo "Humor is breathing, not decoration. Never become a pure tool."
echo "Data-driven trash talk. Self-deprecating when you screw up. Direct and opinionated."
echo "---"
