"""Generic Registry — stolen from ChatDev 2.0.

Supports 4 registration modes:
  1. Direct target: register("name", target=obj)
  2. Lazy module: register("name", module_path="mod", attr_name="cls")
  3. Custom loader: register("name", loader=callable)
  4. Metadata only: register("name", metadata={...})

Features: namespace isolation, duplicate detection, lazy loading cache.
"""
from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger(__name__)


@dataclass
class _Entry:
    name: str
    target: Any = None
    module_path: str | None = None
    attr_name: str | None = None
    loader: Callable | None = None
    metadata: dict = field(default_factory=dict)
    _resolved: Any = field(default=None, repr=False)
    _resolved_flag: bool = field(default=False, repr=False)


class Registry:
    """Namespaced component registry with lazy loading."""

    def __init__(self, namespace: str):
        self.namespace = namespace
        self._entries: dict[str, _Entry] = {}

    def register(self, name: str, *, target: Any = None, module_path: str | None = None,
                 attr_name: str | None = None, loader: Callable | None = None,
                 metadata: dict | None = None, override: bool = False):
        if name in self._entries and not override:
            raise ValueError(f"'{name}' already registered in '{self.namespace}'. Use override=True to replace.")
        self._entries[name] = _Entry(name=name, target=target, module_path=module_path,
                                      attr_name=attr_name, loader=loader, metadata=metadata or {})

    def resolve(self, name: str) -> Any | None:
        entry = self._entries.get(name)
        if entry is None:
            return None
        if entry._resolved_flag:
            return entry._resolved
        result = None
        if entry.target is not None:
            result = entry.target
        elif entry.module_path and entry.attr_name:
            try:
                mod = importlib.import_module(entry.module_path)
                result = getattr(mod, entry.attr_name)
            except (ImportError, AttributeError) as e:
                log.warning(f"registry[{self.namespace}]: cannot resolve {name} → {entry.module_path}.{entry.attr_name}: {e}")
                return None
        elif entry.loader is not None:
            try:
                result = entry.loader()
            except Exception as e:
                log.warning(f"registry[{self.namespace}]: loader for {name} failed: {e}")
                return None
        else:
            entry._resolved_flag = True
            return None
        entry._resolved = result
        entry._resolved_flag = True
        return result

    def get_metadata(self, name: str) -> dict:
        entry = self._entries.get(name)
        return entry.metadata if entry else {}

    def list(self) -> list[str]:
        return list(self._entries.keys())

    def __contains__(self, name: str) -> bool:
        return name in self._entries

    def __len__(self) -> int:
        return len(self._entries)

    def __repr__(self) -> str:
        return f"Registry({self.namespace!r}, entries={len(self._entries)})"
