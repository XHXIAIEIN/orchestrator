"""
Decorator-Registry System (R38 — stolen from Inspect AI).

Unified @register decorator for eval components: tasks, scorers, reducers.
Enables CLI discovery (`inspect list tasks`) and cross-package namespace.

Usage:
    @register_eval(name="clawvard_v2", category="agent_competency")
    async def clawvard_v2(sample):
        ...

    # Discovery
    all_evals = list_registered("task")
    eval_fn = get_registered("task", "clawvard_v2")
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger(__name__)


@dataclass
class RegistryEntry:
    """One registered eval component."""
    name: str
    category: str
    component_type: str
    fn: Callable
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "category": self.category,
            "component_type": self.component_type,
            "fn": self.fn.__qualname__,
            "metadata": self.metadata,
        }


# Module-level registry: {component_type: {name: RegistryEntry}}
_REGISTRY: dict[str, dict[str, RegistryEntry]] = {}


def register_eval(
    name: str,
    category: str = "default",
    component_type: str = "task",
    **metadata: Any,
) -> Callable:
    """Decorator factory for registering eval components.

    Args:
        name: unique name within the component_type namespace.
        category: logical grouping (e.g. "agent_competency", "tool_use").
        component_type: "task", "scorer", "reducer", etc.
        **metadata: arbitrary extra metadata stored on the entry.

    Returns:
        Decorator that registers the function and returns it unchanged.
    """
    def decorator(fn: Callable) -> Callable:
        if component_type not in _REGISTRY:
            _REGISTRY[component_type] = {}

        if name in _REGISTRY[component_type]:
            log.warning(
                f"registry: overwriting '{component_type}/{name}' "
                f"(was {_REGISTRY[component_type][name].fn.__qualname__})"
            )

        entry = RegistryEntry(
            name=name,
            category=category,
            component_type=component_type,
            fn=fn,
            metadata=dict(metadata),
        )
        _REGISTRY[component_type][name] = entry

        log.debug(f"registry: registered {component_type}/{name} [{category}]")
        return fn

    return decorator


def list_registered(component_type: str | None = None) -> list[RegistryEntry]:
    """List registered eval components.

    Args:
        component_type: filter by type (e.g. "task"). None returns all entries.

    Returns:
        List of RegistryEntry, sorted by (component_type, name).
    """
    entries: list[RegistryEntry] = []

    if component_type is not None:
        bucket = _REGISTRY.get(component_type, {})
        entries.extend(bucket.values())
    else:
        for bucket in _REGISTRY.values():
            entries.extend(bucket.values())

    return sorted(entries, key=lambda e: (e.component_type, e.name))


def get_registered(component_type: str, name: str) -> RegistryEntry | None:
    """Look up a specific registered component.

    Args:
        component_type: the type namespace ("task", "scorer", etc.).
        name: the registered name.

    Returns:
        RegistryEntry if found, None otherwise.
    """
    return _REGISTRY.get(component_type, {}).get(name)


def clear_registry() -> None:
    """Clear all registered components. Intended for testing."""
    _REGISTRY.clear()
    log.debug("registry: cleared all entries")
