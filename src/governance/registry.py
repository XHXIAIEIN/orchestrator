"""
Registry — unified component & department registry.

Two layers:
  1. Generic Registry class: namespaced key-value store with lazy loading,
     custom loaders, metadata, duplicate detection. (Originally from ChatDev R13.)
  2. Department discovery: scans departments/*/manifest.yaml at import time, builds
     DEPARTMENTS, INTENT_ENTRIES, DEPT_TAGS, etc.

Single source of truth: add a directory + manifest.yaml → system knows about it.
"""
from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from src.core.llm_router import MODEL_SONNET

# Manifest Inheritance (stolen from Axe, Round 3-7)
try:
    from src.governance.manifest_inherit import ManifestInheritanceResolver
    _manifest_resolver = ManifestInheritanceResolver()
except ImportError:
    ManifestInheritanceResolver = None
    _manifest_resolver = None

log = logging.getLogger(__name__)


# ── Generic Registry (from ChatDev R13) ──────────────────────

@dataclass
class _Entry:
    """Internal entry for the generic Registry."""
    name: str
    target: Any = None
    module_path: str | None = None
    attr_name: str | None = None
    loader: Callable | None = None
    metadata: dict = field(default_factory=dict)
    _resolved: Any = field(default=None, repr=False)
    _resolved_flag: bool = field(default=False, repr=False)


class Registry:
    """Namespaced component registry with lazy loading.

    Supports 4 registration modes:
      1. Direct target: register("name", target=obj)
      2. Lazy module: register("name", module_path="mod", attr_name="cls")
      3. Custom loader: register("name", loader=callable)
      4. Metadata only: register("name", metadata={...})
    """

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


# ── Department discovery ─────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parent
while _REPO_ROOT != _REPO_ROOT.parent and not ((_REPO_ROOT / "departments").is_dir() and (_REPO_ROOT / "src").is_dir()):
    _REPO_ROOT = _REPO_ROOT.parent
_DEPT_ROOT = _REPO_ROOT / "departments"


# ── Data structures ────────────────────────────────────────────

@dataclass
class DepartmentEntry:
    """A registered department (built from manifest.yaml)."""
    key: str
    name_zh: str
    description: str
    prompt_prefix: str
    skill_path: str
    tools: str  # comma-separated for backward compat
    tags: list[str] = field(default_factory=list)
    model: str = MODEL_SONNET
    divisions: dict[str, dict] = field(default_factory=dict)


@dataclass
class IntentEntry:
    """A registered intent route (built from manifest intents section)."""
    intent: str
    department: str
    profile: str  # "LOW_LATENCY" | "BALANCED" | "HIGH_QUALITY"
    description: str = ""
    requires_approval: bool = False
    is_default: bool = False


# ── Discovery engine ───────────────────────────────────────────

def _discover_manifests() -> list[dict]:
    """Scan departments/*/manifest.yaml, return raw dicts."""
    manifests = []
    if not _DEPT_ROOT.exists():
        log.warning("registry: departments/ directory not found")
        return manifests

    for dept_dir in sorted(_DEPT_ROOT.iterdir()):
        if not dept_dir.is_dir() or dept_dir.name.startswith((".", "_", "shared")):
            continue
        manifest_path = dept_dir / "manifest.yaml"
        if not manifest_path.exists():
            # Fallback: 没有 manifest 的目录跳过（不再隐式注册）
            log.debug(f"registry: {dept_dir.name}/ has no manifest.yaml, skipped")
            continue
        try:
            raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
            if raw and isinstance(raw, dict):
                # Ensure key matches directory name
                raw.setdefault("key", dept_dir.name)
                if raw["key"] != dept_dir.name:
                    log.warning(
                        f"registry: manifest key '{raw['key']}' != directory '{dept_dir.name}', "
                        f"using directory name"
                    )
                    raw["key"] = dept_dir.name
                manifests.append(raw)
        except Exception as e:
            log.error(f"registry: failed to parse {manifest_path}: {e}")

    # ── Manifest Inheritance: resolve extends chains ──
    if _manifest_resolver:
        try:
            # Register all manifests as potential bases by key
            for raw in manifests:
                _manifest_resolver.register_base(raw["key"], raw)
            # Resolve inheritance for manifests with 'extends' field
            resolved = []
            for raw in manifests:
                if raw.get("extends"):
                    try:
                        resolved_manifest = _manifest_resolver.resolve(raw)
                        # Preserve directory-aligned key
                        resolved_manifest["key"] = raw["key"]
                        resolved.append(resolved_manifest)
                        log.info(f"registry: manifest '{raw['key']}' inherits from '{raw['extends']}'")
                    except Exception as e:
                        log.warning(f"registry: inheritance resolution failed for '{raw['key']}': {e}")
                        resolved.append(raw)
                else:
                    resolved.append(raw)
            manifests = resolved
        except Exception as e:
            log.warning(f"registry: manifest inheritance system error: {e}")

    return manifests


def _build_department(raw: dict) -> DepartmentEntry:
    """Convert raw manifest dict to DepartmentEntry."""
    tools_list = raw.get("policy", {}).get("allowed_tools", [])
    divisions_raw = raw.get("divisions", {})
    divisions = {}
    for div_key, div_cfg in divisions_raw.items():
        if isinstance(div_cfg, str):
            div_cfg = {"description": div_cfg}
        divisions[div_key] = {
            "name_zh": div_cfg.get("name_zh", div_key),
            "description": div_cfg.get("description", ""),
            "exam_dimension": div_cfg.get("exam_dimension"),
        }
    return DepartmentEntry(
        key=raw["key"],
        name_zh=raw.get("name_zh", raw["key"]),
        description=raw.get("description", ""),
        prompt_prefix=raw.get("prompt_prefix", f"你是 Orchestrator {raw.get('name_zh', raw['key'])}。"),
        skill_path=raw.get("skill_path", f"departments/{raw['key']}/SKILL.md"),
        tools=",".join(tools_list) if tools_list else "Read,Glob,Grep",
        tags=raw.get("tags", []),
        model=raw.get("model", "claude-sonnet-4-6"),
        divisions=divisions,
    )


def _build_intents(raw: dict) -> list[IntentEntry]:
    """Extract intent routes from manifest."""
    dept_key = raw["key"]
    intents_raw = raw.get("intents", {})
    entries = []
    for intent_name, intent_cfg in intents_raw.items():
        if isinstance(intent_cfg, str):
            # Shorthand: "code_fix: BALANCED"
            intent_cfg = {"profile": intent_cfg}
        entries.append(IntentEntry(
            intent=intent_name,
            department=dept_key,
            profile=intent_cfg.get("profile", "BALANCED"),
            description=intent_cfg.get("description", ""),
            requires_approval=intent_cfg.get("requires_approval", False),
            is_default=intent_cfg.get("default", False),
        ))
    return entries


# ── Build registries ──────────────────────────────────────────

def _build_all():
    """One-shot build of all registries from manifest discovery."""
    manifests = _discover_manifests()

    departments = {}
    intent_routes = {}
    dept_default_intents = {}
    dept_tags = {}
    descriptions = {}

    # Tag overlap detection
    tag_owners: dict[str, list[str]] = {}

    for raw in manifests:
        dept = _build_department(raw)
        departments[dept.key] = {
            "name": dept.name_zh,
            "skill_path": dept.skill_path,
            "prompt_prefix": dept.prompt_prefix,
            "tools": dept.tools,
            "divisions": dept.divisions,
        }
        dept_tags[dept.key] = dept.tags
        descriptions[dept.key] = dept.description

        for tag in dept.tags:
            tag_owners.setdefault(tag, []).append(dept.key)

        intents = _build_intents(raw)
        for entry in intents:
            intent_routes[entry.intent] = entry
            if entry.is_default:
                dept_default_intents[dept.key] = entry.intent

        # If no explicit default, use first intent
        if dept.key not in dept_default_intents and intents:
            dept_default_intents[dept.key] = intents[0].intent

    # Warn about overlapping tags (Important #6 from review)
    for tag, owners in tag_owners.items():
        if len(owners) > 1:
            log.debug(f"registry: tag '{tag}' shared by {owners} — LLM will disambiguate")

    return departments, intent_routes, dept_default_intents, dept_tags, descriptions


# ── Capability Registry (stolen from OpenAkita) ──────────────
# Central registry mapping capabilities → tools. Departments declare
# what capabilities they NEED, the registry resolves which tools satisfy.
try:
    from src.governance.capability_registry import build_default_registry, CapabilityRegistry
    _capability_registry: CapabilityRegistry | None = build_default_registry()
except ImportError:
    _capability_registry = None
    CapabilityRegistry = None


# ── Module-level singletons (built on import) ─────────────────

_departments, _intent_routes, _dept_default_intents, _dept_tags, _descriptions = _build_all()

# Public API — drop-in replacements for hardcoded dicts
DEPARTMENTS: dict[str, dict] = _departments
INTENT_ENTRIES: dict[str, IntentEntry] = _intent_routes
DEPT_DEFAULT_INTENTS: dict[str, str] = _dept_default_intents
DEPT_TAGS: dict[str, list[str]] = _dept_tags
VALID_DEPARTMENTS: set[str] = set(_departments.keys())
_manifest_descriptions: dict[str, str] = _descriptions


def get_department(key: str) -> dict:
    """Get department config by key. Falls back to engineering."""
    return DEPARTMENTS.get(key, DEPARTMENTS.get("engineering", {}))


def get_capability_registry():
    """Get the global CapabilityRegistry instance (from OpenAkita)."""
    return _capability_registry


def resolve_tools_for_capabilities(capabilities: list[str], max_tier: str = "system") -> list[str]:
    """Resolve capability requirements to tool names via the global CapabilityRegistry."""
    if _capability_registry:
        return _capability_registry.resolve(capabilities, max_tier=max_tier)
    return []


def get_tags_for_prompt() -> str:
    """Generate a department+tags summary for injection into LLM intent prompts."""
    lines = []
    for dept_key, tags in sorted(DEPT_TAGS.items()):
        dept = DEPARTMENTS.get(dept_key, {})
        name_zh = dept.get("name", dept_key)
        desc = _manifest_descriptions.get(dept_key, "")
        tag_str = ", ".join(tags) if tags else "(no tags)"
        lines.append(f"- {dept_key} ({name_zh}): {desc} — tags: {tag_str}")
    return "\n".join(lines)


def get_intents_for_prompt() -> str:
    """Generate intent list grouped by department for LLM prompt injection."""
    from collections import defaultdict
    by_dept = defaultdict(list)
    for intent_name, entry in sorted(INTENT_ENTRIES.items()):
        by_dept[entry.department].append(intent_name)

    lines = []
    for dept_key in sorted(by_dept.keys()):
        dept = DEPARTMENTS.get(dept_key, {})
        name_zh = dept.get("name", dept_key)
        intents = " / ".join(by_dept[dept_key])
        lines.append(f"{name_zh}: {intents}")
    return "\n".join(lines)


def reload():
    """Hot-reload manifests (for dev/testing).

    Uses in-place mutation (.clear() + .update()) so all consumers holding
    references to these dicts/sets see the new data without re-importing.
    """
    new_depts, new_intents, new_defaults, new_tags, new_descs = _build_all()

    DEPARTMENTS.clear()
    DEPARTMENTS.update(new_depts)
    INTENT_ENTRIES.clear()
    INTENT_ENTRIES.update(new_intents)
    DEPT_DEFAULT_INTENTS.clear()
    DEPT_DEFAULT_INTENTS.update(new_defaults)
    DEPT_TAGS.clear()
    DEPT_TAGS.update(new_tags)
    VALID_DEPARTMENTS.clear()
    VALID_DEPARTMENTS.update(new_depts.keys())
    _manifest_descriptions.clear()
    _manifest_descriptions.update(new_descs)

    # Clear intent prompt cache so it rebuilds from new manifests
    import src.gateway.intent as _intent_mod
    _intent_mod._intent_prompt_cache = None

    log.info(f"registry: reloaded {len(DEPARTMENTS)} departments, {len(INTENT_ENTRIES)} intents")
