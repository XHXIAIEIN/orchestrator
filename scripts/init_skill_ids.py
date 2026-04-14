#!/usr/bin/env python3
# scripts/init_skill_ids.py
"""Bootstrap R51 skill tracking for all existing skills.

Scans .claude/skills/*/SKILL.md, generates deterministic .skill_id sidecar
files for any skill that doesn't have one, and appends IMPORTED events to
SOUL/public/skill_store.jsonl.

Idempotent: safe to run multiple times.

Usage:
    python scripts/init_skill_ids.py
    python scripts/init_skill_ids.py --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.skills.lineage import SKILLS_DIR, register_skill  # noqa: E402


def main(dry_run: bool = False) -> None:
    if not SKILLS_DIR.exists():
        print(f"ERROR: skills directory not found: {SKILLS_DIR}")
        sys.exit(1)

    skill_dirs = sorted(
        d for d in SKILLS_DIR.iterdir()
        if d.is_dir() and (d / "SKILL.md").exists()
    )

    if not skill_dirs:
        print("No skills found.")
        return

    print(f"Found {len(skill_dirs)} skill(s) in {SKILLS_DIR}")
    print()

    for skill_dir in skill_dirs:
        id_file = skill_dir / ".skill_id"
        had_id = id_file.exists()

        if dry_run:
            from src.skills.lineage import _skill_id  # noqa: PLC0415
            skill_id = id_file.read_text().strip() if had_id else _skill_id(skill_dir.name)
            status = "EXISTS" if had_id else "NEW"
            print(f"  [{status}] {skill_dir.name} → {skill_id}")
        else:
            skill_id = register_skill(skill_dir)
            status = "OK (existing)" if had_id else "CREATED"
            print(f"  [{status}] {skill_dir.name} → {skill_id}")

    print()
    if dry_run:
        print("Dry run — no files written.")
    else:
        from src.skills.lineage import SKILL_STORE_PATH  # noqa: PLC0415
        print(f"Done. Ledger: {SKILL_STORE_PATH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bootstrap R51 skill IDs")
    parser.add_argument(
        "--dry-run", action="store_true", help="Print what would happen without writing"
    )
    args = parser.parse_args()
    main(dry_run=args.dry_run)
