#!/usr/bin/env python3
"""
marker_upsert.py — marker-bounded ambient upsert for CLAUDE.md (and any markdown file)

Functions:
    upsert_block(path, marker_id, content)  → bool
    remove_block(path, marker_id)           → bool
    _backup_once(path)                      → None
    _atomic_write(path, text)              → None

Marker format:
    <!-- {marker_id}:start -->
    {content}
    <!-- {marker_id}:end -->

CLI usage:
    python3 marker_upsert.py upsert <path> <marker_id> <content_file>
    python3 marker_upsert.py remove <path> <marker_id>
"""

import os
import re
import shutil
import sys
import tempfile


def _backup_once(path: str) -> None:
    """Create a .bak backup of path if the backup does not already exist.
    If path does not exist, skip silently (first-time creation scenario).
    """
    bak = path + ".bak"
    if os.path.exists(path) and not os.path.exists(bak):
        try:
            shutil.copy2(path, bak)
        except Exception:
            pass


def _atomic_write(path: str, text: str) -> None:
    """Write text to path atomically using a sibling temp file + os.replace."""
    dir_ = os.path.dirname(os.path.abspath(path))
    fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        raise


def upsert_block(path: str, marker_id: str, content: str) -> bool:
    """Insert or replace a marker-bounded block in the file at path.

    If the marker block already exists, its content is replaced.
    If it does not exist, the block is appended to the file.
    If the file does not exist, it is created with just the block.

    Returns True on success, False on any failure.
    """
    try:
        start_tag = f"<!-- {marker_id}:start -->"
        end_tag = f"<!-- {marker_id}:end -->"

        _backup_once(path)

        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                original = fh.read()
        else:
            # Ensure parent directory exists
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            original = ""

        block = f"{start_tag}\n{content}\n{end_tag}\n"

        pattern = re.compile(
            re.escape(start_tag) + r".*?" + re.escape(end_tag) + r"\n?",
            re.DOTALL,
        )

        if pattern.search(original):
            new_text = pattern.sub(block, original)
        else:
            # Append: ensure single trailing newline before block
            if original and not original.endswith("\n"):
                new_text = original + "\n" + block
            else:
                new_text = original + block

        _atomic_write(path, new_text)
        return True
    except Exception:
        return False


def remove_block(path: str, marker_id: str) -> bool:
    """Remove a marker-bounded block from the file at path.

    If removing the block leaves only blank lines, the file is deleted.
    Returns True on success (including no-op when marker absent), False on failure.
    """
    try:
        if not os.path.exists(path):
            return True  # nothing to remove

        start_tag = f"<!-- {marker_id}:start -->"
        end_tag = f"<!-- {marker_id}:end -->"

        with open(path, "r", encoding="utf-8") as fh:
            original = fh.read()

        pattern = re.compile(
            re.escape(start_tag) + r".*?" + re.escape(end_tag) + r"\n?",
            re.DOTALL,
        )

        if not pattern.search(original):
            return True  # marker not present, no-op

        new_text = pattern.sub("", original)

        if not new_text.strip():
            os.unlink(path)
        else:
            _atomic_write(path, new_text)

        return True
    except Exception:
        return False


def _cli_main() -> None:
    """CLI entry point: marker_upsert.py upsert <path> <marker_id> <content_file>
                        marker_upsert.py remove <path> <marker_id>
    """
    if len(sys.argv) < 4:
        print(
            "Usage:\n"
            "  marker_upsert.py upsert <path> <marker_id> <content_file>\n"
            "  marker_upsert.py remove <path> <marker_id>",
            file=sys.stderr,
        )
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "upsert":
        if len(sys.argv) < 5:
            print("upsert requires: <path> <marker_id> <content_file>", file=sys.stderr)
            sys.exit(1)
        path, marker_id, content_file = sys.argv[2], sys.argv[3], sys.argv[4]
        try:
            with open(content_file, "r", encoding="utf-8") as fh:
                content = fh.read()
        except Exception as e:
            print(f"Cannot read content_file: {e}", file=sys.stderr)
            sys.exit(1)
        ok = upsert_block(path, marker_id, content)
        sys.exit(0 if ok else 1)

    elif cmd == "remove":
        path, marker_id = sys.argv[2], sys.argv[3]
        ok = remove_block(path, marker_id)
        sys.exit(0 if ok else 1)

    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    _cli_main()
