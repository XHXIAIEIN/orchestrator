"""ComponentSpec — unified component specification and assembly.

Stolen from: microsoft/agent-lightning (Round 8)

Lets configuration drive component wiring instead of hardcoded initialization.
Supports: instance, class, factory callable, registry string, dict config, or None.
"""
from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar, Generic, get_type_hints

log = logging.getLogger(__name__)

T = TypeVar("T")

# ── Global Component Registry ──
# Maps string keys to (module_path, class_name) or factory callables.
_REGISTRY: dict[str, str | Callable] = {}


def register(name: str, target: str | Callable):
    """Register a component by name.

    Args:
        name: Registry key, e.g. "stuck_detector" or "stuck_detector.default"
        target: Either a dotted import path "src.governance.stuck_detector.StuckDetector"
                or a callable factory.
    """
    _REGISTRY[name] = target


def _import_from_path(dotted: str) -> Any:
    """Import 'module.path.ClassName' → class/object."""
    parts = dotted.rsplit(".", 1)
    if len(parts) != 2:
        raise ImportError(f"Invalid dotted path: {dotted!r} (need 'module.Class')")
    module_path, attr_name = parts
    mod = importlib.import_module(module_path)
    return getattr(mod, attr_name)


def build_component(spec: Any, expected_type: type | None = None) -> Any | None:
    """Resolve a ComponentSpec into a live component instance.

    Accepts:
        - None           → None (component disabled)
        - instance of T  → returned as-is
        - type[T]        → T() (call with no args)
        - Callable       → call it
        - str            → look up in registry, then try as dotted import path
        - dict           → {"class": "dotted.path", **kwargs} → import + instantiate

    Args:
        spec: The component specification.
        expected_type: Optional type check on the result.

    Returns:
        Component instance, or None if spec is None or resolution fails.
    """
    if spec is None:
        return None

    result = None

    # Already an instance (not a class, not a callable-that-isn't-a-class)
    if expected_type and isinstance(spec, expected_type):
        return spec

    # It's a class → instantiate
    if isinstance(spec, type):
        try:
            result = spec()
        except Exception as e:
            log.warning(f"ComponentSpec: failed to instantiate {spec.__name__}: {e}")
            return None

    # It's a callable (factory) but not a class
    elif callable(spec) and not isinstance(spec, type):
        try:
            result = spec()
        except Exception as e:
            log.warning(f"ComponentSpec: factory {spec} failed: {e}")
            return None

    # It's a string → registry lookup or dotted import
    elif isinstance(spec, str):
        target = _REGISTRY.get(spec)
        if target is not None:
            # If registry value is also a string, import it
            if isinstance(target, str):
                try:
                    resolved = _import_from_path(target)
                except (ImportError, AttributeError) as e:
                    log.warning(f"ComponentSpec: cannot resolve registry {spec!r} → {target!r}: {e}")
                    return None
                # Classes get instantiated; functions/objects returned as-is
                if isinstance(resolved, type):
                    return build_component(resolved, expected_type)
                # It's a function or other object — return it directly
                return resolved
            return build_component(target, expected_type)
        # Try as dotted import path directly
        try:
            resolved = _import_from_path(spec)
            if isinstance(resolved, type):
                return build_component(resolved, expected_type)
            return resolved  # function or singleton — return as-is
        except (ImportError, AttributeError) as e:
            log.warning(f"ComponentSpec: cannot resolve {spec!r}: {e}")
            return None

    # It's a dict → {"class": "path", **kwargs}
    elif isinstance(spec, dict):
        cls_path = spec.get("class")
        if not cls_path:
            log.warning(f"ComponentSpec: dict spec missing 'class' key: {spec}")
            return None
        try:
            cls = _import_from_path(cls_path)
            kwargs = {k: v for k, v in spec.items() if k != "class"}
            result = cls(**kwargs)
        except Exception as e:
            log.warning(f"ComponentSpec: dict instantiation failed: {e}")
            return None

    else:
        # Assume it's already an instance
        result = spec

    # Type check
    if result is not None and expected_type and not isinstance(result, expected_type):
        log.warning(f"ComponentSpec: {result!r} is not {expected_type.__name__}, returning anyway")

    return result


# ── Batch Assembly ──

def build_components(specs: dict[str, Any], type_hints: dict[str, type] | None = None) -> dict[str, Any]:
    """Build multiple components from a spec dict.

    Args:
        specs: {"name": spec, ...}
        type_hints: Optional {"name": expected_type, ...}

    Returns:
        {"name": instance_or_None, ...}
    """
    type_hints = type_hints or {}
    return {
        name: build_component(spec, type_hints.get(name))
        for name, spec in specs.items()
    }


# ── Default Registrations ──
# These are the components currently hardcoded in executor_session.py.
# Registry allows swapping them via config without code changes.

_DEFAULTS = {
    "stuck_detector":       "src.governance.stuck_detector.StuckDetector",
    "taint_tracker":        "src.governance.safety.taint.TaintTracker",
    "context_budget":       "src.core.context_budget.ContextBudget",
    "context_ledger":       "src.core.context_budget.ContextLedger",
    "runtime_supervisor":   "src.governance.supervisor.RuntimeSupervisor",
    "doom_loop_checker":    "src.governance.safety.doom_loop.check_doom_loop",
    "agent_semaphore":      "src.governance.safety.agent_semaphore.AgentSemaphore",
    "token_accountant":     "src.governance.budget.token_budget.TokenAccountant",
    "rate_limiter":         "src.core.rate_limiter.RateLimiter",
    "artifact_store":       "src.governance.context.artifact_store.ArtifactStore",
    "thinking_tracker":     "src.governance.budget.thinking_budget.ThinkingTracker",
}

for _name, _path in _DEFAULTS.items():
    register(_name, _path)


# ── Entry Point Plugin Discovery (stolen from VibeVoice, Round 17) ──
# VibeVoice registers vLLM plugins via pyproject.toml entry points:
#   [project.entry-points."vllm.general_plugins"]
#   vibevoice = "vllm_plugin:register_vibevoice"
#
# For Orchestrator: any package can declare plugins via:
#   [project.entry-points."orchestrator.plugins"]
#   my_collector = "my_package:register_plugin"
#
# The register function receives the global `register` callable and
# should call it to register components:
#   def register_plugin(reg):
#       reg("my_collector", "my_package.collector.MyCollector")

PLUGIN_ENTRY_POINT_GROUP = "orchestrator.plugins"
_plugins_discovered = False


def discover_plugins(group: str = PLUGIN_ENTRY_POINT_GROUP) -> int:
    """Scan installed packages for Orchestrator plugins via entry points.

    Each entry point should be a callable that accepts our `register` function
    and calls it to register components. Like VibeVoice's register_vibevoice()
    that registers Config/Tokenizer/Processor/Model in one shot.

    Returns:
        Number of plugins successfully loaded.
    """
    global _plugins_discovered
    if _plugins_discovered:
        return 0

    count = 0
    try:
        from importlib.metadata import entry_points
        # Python 3.12+ returns SelectableGroups; 3.9+ uses group= kwarg
        try:
            eps = entry_points(group=group)
        except TypeError:
            eps = entry_points().get(group, [])

        for ep in eps:
            try:
                plugin_register = ep.load()
                plugin_register(register)
                count += 1
                log.info(f"Plugin: loaded {ep.name} from {ep.value}")
            except Exception as e:
                log.warning(f"Plugin: failed to load {ep.name}: {e}")

    except ImportError:
        log.debug("Plugin discovery: importlib.metadata not available")

    _plugins_discovered = True
    if count:
        log.info(f"Plugin discovery: loaded {count} plugin(s) from '{group}'")
    return count


# Auto-discover on import (lazy — only runs once)
discover_plugins()
