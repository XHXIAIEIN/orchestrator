"""Backfill L0/L1 for existing memory files.

One-time migration script. Run: python -m src.governance.context.memory_backfill [memory_dir]
"""
import sys
from pathlib import Path


def backfill_memory_dir(memory_dir: Path) -> dict:
    """Add l0/l1 to memory files missing them.

    Returns: {"updated": N, "skipped": N, "errors": N}
    """
    stats = {"updated": 0, "skipped": 0, "errors": 0}

    for md_file in sorted(memory_dir.glob("*.md")):
        if md_file.name == "MEMORY.md":
            continue

        try:
            content = md_file.read_text(encoding="utf-8")
        except Exception as e:
            print(f"  ERROR reading {md_file.name}: {e}")
            stats["errors"] += 1
            continue

        if not content.startswith("---"):
            stats["skipped"] += 1
            continue

        parts = content.split("---", 2)
        if len(parts) < 3:
            stats["skipped"] += 1
            continue

        frontmatter_text = parts[1].strip()
        body = parts[2].strip()

        # Parse existing frontmatter
        meta = {}
        for line in frontmatter_text.split("\n"):
            if ":" in line:
                key, val = line.split(":", 1)
                meta[key.strip()] = val.strip()

        # Check if l0/l1 already present
        has_l0 = "l0" in meta and meta["l0"]
        has_l1 = "l1" in meta and meta["l1"]

        if has_l0 and has_l1:
            stats["skipped"] += 1
            continue

        # Generate l0 from description or first line
        if not has_l0:
            l0 = meta.get("description", "")
            if not l0:
                for line in body.split("\n"):
                    line = line.strip().lstrip("#").strip()
                    if line and len(line) > 10:
                        l0 = line[:200]
                        break
            if not l0:
                l0 = md_file.stem.replace("_", " ")
            meta["l0"] = l0

        # Generate l1 from first ~1000 chars of body
        if not has_l1:
            l1_text = body[:1000]
            # Try to cut at paragraph boundary
            last_para = l1_text.rfind("\n\n")
            if last_para > 500:
                l1_text = l1_text[:last_para]
            meta["l1"] = ""  # Don't put long l1 in frontmatter, leave it for runtime generation

        # Rebuild frontmatter with l0 added
        new_frontmatter_lines = []
        existing_keys = set()
        for line in frontmatter_text.split("\n"):
            if ":" in line:
                key = line.split(":", 1)[0].strip()
                existing_keys.add(key)
                if key == "l0" and not has_l0:
                    new_frontmatter_lines.append(f"l0: {meta['l0']}")
                else:
                    new_frontmatter_lines.append(line)
            else:
                new_frontmatter_lines.append(line)

        # Add l0 if it wasn't in the original frontmatter
        if "l0" not in existing_keys and meta.get("l0"):
            new_frontmatter_lines.append(f"l0: {meta['l0']}")

        new_content = f"---\n{chr(10).join(new_frontmatter_lines)}\n---\n\n{body}\n"

        try:
            md_file.write_text(new_content, encoding="utf-8")
            print(f"  UPDATED {md_file.name}: l0=\"{meta.get('l0', '')[:60]}\"")
            stats["updated"] += 1
        except Exception as e:
            print(f"  ERROR writing {md_file.name}: {e}")
            stats["errors"] += 1

    return stats


def main():
    if len(sys.argv) > 1:
        memory_dir = Path(sys.argv[1])
    else:
        # Auto-discover
        from src.governance.context.memory_tier import _find_memory_dir
        memory_dir = _find_memory_dir()

    if not memory_dir or not memory_dir.exists():
        print(f"Memory directory not found: {memory_dir}")
        sys.exit(1)

    print(f"Backfilling L0/L1 in: {memory_dir}")
    stats = backfill_memory_dir(memory_dir)
    print(f"\nDone: {stats['updated']} updated, {stats['skipped']} skipped, {stats['errors']} errors")


if __name__ == "__main__":
    main()
