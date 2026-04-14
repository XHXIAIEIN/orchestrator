#!/usr/bin/env python3
"""PostCompact restore + identity health check — R57 steal from CC-v3/clauditor.

Designed for SessionStart(compact) hook — fires once after compaction.
Uses additionalContext for reliable injection (not stdout).

Health check: scans post-compaction context for identity markers.
Returns ALIVE / WEAK / SILENT signal with adaptive recovery intensity.
"""

import json
import sys
import os
from pathlib import Path


# ── Identity Markers ────────────────────────────────────────────
# These keywords indicate Orchestrator's identity survived compaction.
# Scored in tiers: critical (persona core) and supporting (rules/style).

CRITICAL_MARKERS = [
    "Orchestrator",
    "损友",
    "roast",
    "brutally honest",
]

SUPPORTING_MARKERS = [
    "dispatch-gate",
    ".trash",
    "verification gate",
    "surgical changes",
    "commit per feature",
    "boot.md",
    "SOUL",
]

# ── Recovery Payloads ───────────────────────────────────────────

MINIMAL_IDENTITY = (
    "You ARE Orchestrator — brutally honest friend (损友), not a tool. "
    "Roast first, help second. Direct, opinionated, data-driven."
)

FULL_IDENTITY = """## Post-Compaction Identity Restore

**Identity**: You ARE Orchestrator. Brutally honest friend (损友), not a tool.
**Voice**: Roast first, help second. Data-driven. Direct. Opinionated. Never spineless.

**Critical rules (must survive compaction):**
1. EXECUTE directly — no permission-seeking, no asking to continue.
2. Git: stage-first, push-later. No auto-push. No rollback without explicit request.
3. Deletion = mv to .trash/, NOT rm. Report contents after task completes.
4. Surgical changes only — every changed line traces to the request.
5. [STEAL] work requires steal/* branch. dispatch-gate.sh enforces this.
6. Gate functions mandatory before: delete/replace, git reset, config modify, external send.
7. Commit per feature point — do not batch multiple rounds into one commit.
8. Verification gate: Identify→Execute→Read→Confirm→Declare.
   Banned: "should work" / "probably fine" / "I believe this is correct"

**Persona**: Humor is breathing, not decoration. Direct != boring.
When owner says continue — just do it. "I am not sure" beats confident wrong answer.

**Read .claude/boot.md for full context if anything feels off.**
"""


def assess_health(context_text: str) -> str:
    """Assess identity marker survival. Returns ALIVE/WEAK/SILENT."""
    text_lower = context_text.lower() if context_text else ""

    critical_hits = sum(1 for m in CRITICAL_MARKERS if m.lower() in text_lower)
    supporting_hits = sum(1 for m in SUPPORTING_MARKERS if m.lower() in text_lower)

    # ALIVE: most critical markers present
    if critical_hits >= 3:
        return "ALIVE"
    # WEAK: some markers present
    elif critical_hits >= 1 or supporting_hits >= 3:
        return "WEAK"
    # SILENT: nothing survived
    else:
        return "SILENT"


def load_latest_handoff() -> str:
    """Load the most recent handoff saved by pre-compact.py."""
    project_dir = Path(__file__).resolve().parent.parent.parent
    snapshot_dir = project_dir / "tmp" / "compaction-snapshots"

    # Try the "latest" symlink first
    latest = snapshot_dir / "latest-handoff.md"
    if latest.exists():
        return latest.read_text(encoding="utf-8")

    # Fallback: find most recent handoff-*.md
    handoffs = sorted(snapshot_dir.glob("handoff-*.md"), reverse=True)
    if handoffs:
        return handoffs[0].read_text(encoding="utf-8")

    return ""


def state_del(key: str):
    """Delete cross-hook IPC state (compatible with lib/state.sh)."""
    state_dir = os.environ.get("ORCHESTRATOR_STATE_DIR", "/tmp/orchestrator-state")
    try:
        os.remove(os.path.join(state_dir, key))
    except FileNotFoundError:
        pass


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        data = {}

    # ── 1. Load handoff from pre-compact ──
    handoff = load_latest_handoff()

    # ── 2. Health check on whatever context survived ──
    # We check the compacted conversation summary if available,
    # otherwise we check our own handoff (which should always exist)
    compacted_context = data.get("compacted_context", "")
    check_text = compacted_context or handoff
    health = assess_health(check_text)

    # ── 3. Build adaptive recovery payload ──
    parts = []

    # Health status header
    parts.append(f"[compaction-restore] Identity health: {health}")

    if health == "SILENT":
        # Full reload — identity completely lost
        parts.append(FULL_IDENTITY)
    elif health == "WEAK":
        # Partial reload — some markers survived
        parts.append(f"\n{MINIMAL_IDENTITY}\n")
        parts.append("Key rules: execute directly, git stage-first, deletion→.trash/, surgical changes only.")
        parts.append("Read .claude/boot.md for full calibration.\n")
    else:
        # ALIVE — just a light touch
        parts.append(f"\n{MINIMAL_IDENTITY}\n")

    # Always include handoff if available
    if handoff:
        parts.append("\n## Session Handoff (from before compaction)\n")
        parts.append(handoff)

    additional_context = "\n".join(parts)

    # ── 4. Output as additionalContext (Claude Code SessionStart API) ──
    output = {"additionalContext": additional_context}
    print(json.dumps(output))

    # ── 5. Consume compact.pending flag (prevent PostToolUse double-fire) ──
    state_del("compact.pending")


if __name__ == "__main__":
    main()
