"""Atomic file write utilities — prevent half-written files on crash.

Stolen from: MemPalace R67 P0.3 (os.replace + fsync pattern)
         +   yoyo-evolve R66 P0-D (atomic JSONL append)

Pattern: write to temp file → fsync → os.replace (atomic on all OS).
For append-only files (JSONL): write line to temp → os.replace temp with
a copy of original + new line. This is heavier but crash-safe.

Simpler alternative for append: just fsync after each write to ensure
durability, accepting that the last line might be partial on hard crash
(JSONL readers should skip malformed trailing lines anyway).
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def atomic_write(path: str | Path, content: str, *, encoding: str = "utf-8") -> None:
    """Atomically write content to a file (full overwrite).

    Writes to a temp file in the same directory, fsyncs, then os.replace.
    If the process crashes mid-write, the original file remains intact.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass  # fsync not supported on this FS (e.g., some network mounts)
        os.replace(tmp_path, str(path))
    except BaseException:
        # Clean up temp file on any failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_write_json(path: str | Path, data: dict | list, **json_kwargs) -> None:
    """Atomically write a JSON file."""
    json_kwargs.setdefault("ensure_ascii", False)
    json_kwargs.setdefault("indent", 2)
    content = json.dumps(data, **json_kwargs)
    atomic_write(path, content)


def atomic_append_jsonl(path: str | Path, entry: dict, *, encoding: str = "utf-8") -> None:
    """Append a single JSONL entry with fsync durability.

    For append-only logs (experiences.jsonl, observations.jsonl), we don't need
    full atomic replace — just ensure each write is flushed + fsynced so partial
    lines don't accumulate on crash. JSONL readers should tolerate a truncated
    last line (standard practice).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with open(path, "a", encoding=encoding) as f:
        f.write(line)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
