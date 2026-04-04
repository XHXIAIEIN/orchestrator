# src/governance/skill_cas.py
"""Skill CAS Distribution — content-addressable storage for skills.

Source: LobeHub skill marketplace (Round 16)

Problem: Skills (SKILL.md files) can be duplicated, forked, and versioned
across departments. Without a dedup layer, the same skill logic gets
copied into multiple places, making updates fragile and inconsistent.

Solution: Content-Addressable Storage (CAS) — hash skill content to produce
a unique key. Two skills with identical content share the same hash and are
considered the same version. Updates produce new hashes; old versions remain
for rollback.

Architecture:
    skill_store/
        index.json          ← manifest: name → [versions]
        <hash[:8]>.md       ← actual skill content, named by content hash

Features:
    - Hash-based dedup: identical skills are stored once
    - Version history: each skill name tracks ordered list of content hashes
    - Dependency resolution: skills can declare deps on other skills
    - Install/upgrade: atomic update (write new → update index → done)
    - Rollback: revert to previous hash in version list
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_STORE_PATH = REPO_ROOT / "data" / "skill_store"


def content_hash(content: str) -> str:
    """Compute SHA-256 hash of skill content, return first 16 hex chars."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


@dataclass
class SkillVersion:
    """A single version of a skill in the CAS."""
    hash: str
    timestamp: float = 0.0
    description: str = ""
    dependencies: list[str] = field(default_factory=list)


@dataclass
class SkillEntry:
    """A skill with its version history."""
    name: str
    current_hash: str = ""
    versions: list[SkillVersion] = field(default_factory=list)

    @property
    def version_count(self) -> int:
        return len(self.versions)

    def previous_hash(self) -> str | None:
        """Get the hash before the current one (for rollback)."""
        if len(self.versions) < 2:
            return None
        return self.versions[-2].hash


class SkillCAS:
    """Content-Addressable Storage for skills.

    Usage:
        cas = SkillCAS()

        # Install a skill
        result = cas.install("my-skill", skill_content, description="v1")

        # Check if content already exists
        assert cas.exists(result["hash"])

        # Upgrade (new content → new hash)
        cas.install("my-skill", new_content, description="v2")

        # Rollback
        cas.rollback("my-skill")

        # Resolve skill content by name
        content = cas.resolve("my-skill")
    """

    def __init__(self, store_path: Path | None = None):
        self.store_path = store_path or DEFAULT_STORE_PATH
        self.store_path.mkdir(parents=True, exist_ok=True)
        self.index_path = self.store_path / "index.json"
        self._index: dict[str, SkillEntry] = {}
        self._load_index()

    def _load_index(self) -> None:
        """Load index from disk."""
        if not self.index_path.exists():
            self._index = {}
            return
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
            for name, entry_data in data.items():
                versions = [
                    SkillVersion(
                        hash=v["hash"],
                        timestamp=v.get("timestamp", 0),
                        description=v.get("description", ""),
                        dependencies=v.get("dependencies", []),
                    )
                    for v in entry_data.get("versions", [])
                ]
                self._index[name] = SkillEntry(
                    name=name,
                    current_hash=entry_data.get("current_hash", ""),
                    versions=versions,
                )
        except Exception as e:
            log.warning(f"skill_cas: failed to load index: {e}")
            self._index = {}

    def _save_index(self) -> None:
        """Persist index to disk."""
        data = {}
        for name, entry in self._index.items():
            data[name] = {
                "current_hash": entry.current_hash,
                "versions": [
                    {
                        "hash": v.hash,
                        "timestamp": v.timestamp,
                        "description": v.description,
                        "dependencies": v.dependencies,
                    }
                    for v in entry.versions
                ],
            }
        self.index_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _content_path(self, h: str) -> Path:
        """Get the file path for a content hash."""
        return self.store_path / f"{h}.md"

    def exists(self, h: str) -> bool:
        """Check if content with this hash exists in the store."""
        return self._content_path(h).exists()

    def install(self, name: str, content: str, *,
                description: str = "",
                dependencies: list[str] | None = None,
                timestamp: float = 0.0) -> dict:
        """Install or upgrade a skill.

        Returns dict with hash, is_new, is_update, is_noop.
        """
        import time as _time

        h = content_hash(content)
        ts = timestamp or _time.time()
        deps = dependencies or []

        entry = self._index.get(name)

        # Case 1: Same content as current version → no-op
        if entry and entry.current_hash == h:
            return {"hash": h, "is_new": False, "is_update": False, "is_noop": True}

        # Write content to CAS (dedup: skip if hash exists)
        content_file = self._content_path(h)
        if not content_file.exists():
            content_file.write_text(content, encoding="utf-8")

        version = SkillVersion(
            hash=h, timestamp=ts, description=description, dependencies=deps,
        )

        if entry is None:
            # Case 2: New skill
            entry = SkillEntry(name=name, current_hash=h, versions=[version])
            self._index[name] = entry
            self._save_index()
            log.info(f"skill_cas: installed new skill '{name}' ({h})")
            return {"hash": h, "is_new": True, "is_update": False, "is_noop": False}

        # Case 3: Update (new version)
        entry.versions.append(version)
        entry.current_hash = h
        self._save_index()
        log.info(f"skill_cas: updated '{name}' → {h} (v{entry.version_count})")
        return {"hash": h, "is_new": False, "is_update": True, "is_noop": False}

    def resolve(self, name: str) -> str | None:
        """Resolve skill name to its current content."""
        entry = self._index.get(name)
        if not entry or not entry.current_hash:
            return None
        path = self._content_path(entry.current_hash)
        if not path.exists():
            log.warning(f"skill_cas: content missing for '{name}' ({entry.current_hash})")
            return None
        return path.read_text(encoding="utf-8")

    def rollback(self, name: str) -> bool:
        """Rollback skill to previous version.

        Returns True if rollback succeeded, False if no previous version.
        """
        entry = self._index.get(name)
        if not entry:
            return False

        prev = entry.previous_hash()
        if not prev:
            log.info(f"skill_cas: no previous version for '{name}'")
            return False

        # Remove current version from history
        entry.versions.pop()
        entry.current_hash = prev
        self._save_index()
        log.info(f"skill_cas: rolled back '{name}' → {prev}")
        return True

    def list_skills(self) -> list[dict]:
        """List all skills in the CAS."""
        return [
            {
                "name": entry.name,
                "current_hash": entry.current_hash,
                "versions": entry.version_count,
            }
            for entry in self._index.values()
        ]

    def resolve_dependencies(self, name: str) -> list[str]:
        """Resolve transitive dependencies for a skill.

        Returns ordered list of skill names (deps first, target last).
        """
        visited: set[str] = set()
        order: list[str] = []

        def _walk(n: str) -> None:
            if n in visited:
                return
            visited.add(n)
            entry = self._index.get(n)
            if entry and entry.versions:
                for dep in entry.versions[-1].dependencies:
                    _walk(dep)
            order.append(n)

        _walk(name)
        return order
