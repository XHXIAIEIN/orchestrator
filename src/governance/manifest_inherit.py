"""Agent YAML Inheritance — stolen from Axe.

Department manifests can declare `extends: base` to inherit from a
base template. Only overridden fields need to be specified.

Supports:
- Single inheritance (extends: base_name)
- Deep merge for nested dicts (policy, agent config)
- List override (not merge) for tools, tags
- Multiple inheritance levels (A extends B extends C)

Usage:
    resolver = ManifestInheritanceResolver()
    resolver.register_base("default", {
        "model": "claude-sonnet-4-6",
        "max_turns": 25,
        "policy": {"allowed_tools": ["Read", "Glob", "Grep"]},
    })
    resolved = resolver.resolve({
        "key": "security",
        "extends": "default",
        "policy": {"allowed_tools": ["Read", "Glob", "Grep", "Bash"]},
    })
    # resolved has model, max_turns from default + overridden policy
"""
import copy
import logging
from typing import Optional

log = logging.getLogger(__name__)


def deep_merge(base: dict, override: dict) -> dict:
    """Deep merge two dicts. Override wins for conflicts.

    - Dicts are recursively merged
    - Lists are replaced (not concatenated)
    - Scalars are replaced
    """
    result = copy.deepcopy(base)
    for key, value in override.items():
        if (key in result and isinstance(result[key], dict)
                and isinstance(value, dict)):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


class ManifestInheritanceResolver:
    """Resolve manifest inheritance chains."""

    def __init__(self):
        self._bases: dict[str, dict] = {}
        self._resolved_cache: dict[str, dict] = {}

    def register_base(self, name: str, manifest: dict):
        """Register a base template."""
        self._bases[name] = manifest
        self._resolved_cache.clear()  # invalidate cache
        log.debug(f"manifest_inherit: registered base '{name}'")

    def resolve(self, manifest: dict, max_depth: int = 5) -> dict:
        """Resolve a manifest with inheritance.

        Args:
            manifest: The manifest dict, optionally with 'extends' key.
            max_depth: Maximum inheritance depth (prevents cycles).

        Returns:
            Fully resolved manifest with inherited values.
        """
        extends = manifest.get("extends")
        if not extends:
            return copy.deepcopy(manifest)

        # Check cache
        cache_key = f"{manifest.get('key', '')}:{extends}"
        if cache_key in self._resolved_cache:
            cached = copy.deepcopy(self._resolved_cache[cache_key])
            # Apply current manifest on top of cached base
            result = deep_merge(cached, manifest)
            result.pop("extends", None)
            return result

        # Resolve inheritance chain
        chain = self._resolve_chain(extends, max_depth)

        # Merge chain bottom-up
        base = {}
        for ancestor in chain:
            base = deep_merge(base, ancestor)

        # Apply current manifest on top
        result = deep_merge(base, manifest)
        result.pop("extends", None)

        # Cache
        self._resolved_cache[cache_key] = copy.deepcopy(base)

        return result

    def _resolve_chain(self, name: str, max_depth: int) -> list[dict]:
        """Build the inheritance chain (oldest ancestor first)."""
        chain = []
        current = name
        seen = set()

        while current and max_depth > 0:
            if current in seen:
                log.warning(f"manifest_inherit: cycle detected at '{current}'")
                break
            seen.add(current)

            base = self._bases.get(current)
            if base is None:
                log.warning(f"manifest_inherit: base '{current}' not found")
                break

            chain.append(base)
            current = base.get("extends")
            max_depth -= 1

        chain.reverse()  # oldest ancestor first
        return chain

    def get_bases(self) -> list[str]:
        """List registered base names."""
        return list(self._bases.keys())
