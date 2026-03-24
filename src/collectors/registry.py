"""
采集器注册表 — manifest 驱动的自动发现。

模式同 departments/manifest.yaml：
  - 每个采集器有 {name}.manifest.yaml 声明身份和配置
  - registry 扫描所有 manifest → 发现采集器 → 按 enabled 字段决定是否启用
  - 新增采集器 = 放一个 .py + .manifest.yaml，零代码改动
  - 禁用采集器 = 改 manifest 里的 enabled: false

优先级：env COLLECTOR_{NAME} > manifest.yaml enabled > 默认 true
"""
import importlib
import logging
import os
from pathlib import Path

import yaml

from src.collectors.base import ICollector, CollectorMeta

log = logging.getLogger(__name__)
_COLLECTORS_DIR = Path(__file__).parent


def _load_manifest(path: Path) -> dict | None:
    """Load a single collector manifest.yaml."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except Exception as e:
        log.warning(f"registry: failed to load {path.name}: {e}")
        return None


def _find_collector_class(module) -> type[ICollector] | None:
    """Find ICollector subclass in a module."""
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if (isinstance(attr, type)
                and issubclass(attr, ICollector)
                and attr is not ICollector):
            return attr
    return None


def discover_collectors() -> dict[str, dict]:
    """Auto-discover collectors from {name}/manifest.yaml directories.

    Same pattern as departments/. Each collector lives in:
        src/collectors/{name}/
        ├── manifest.yaml   (identity + config)
        ├── collector.py    (ICollector subclass)
        └── __init__.py

    YAML-only collectors have manifest.yaml but no collector.py (uses yaml_runner).

    Returns {name: {"manifest": dict, "cls": type[ICollector], "path": Path}}.
    """
    registry = {}

    for subdir in sorted(_COLLECTORS_DIR.iterdir()):
        if not subdir.is_dir() or subdir.name.startswith(("_", ".")):
            continue

        manifest_path = subdir / "manifest.yaml"
        if not manifest_path.exists():
            continue

        manifest = _load_manifest(manifest_path)
        if not manifest or "name" not in manifest:
            continue

        name = manifest["name"]
        collector_py = subdir / "collector.py"

        if collector_py.exists():
            module_name = f"src.collectors.{subdir.name}.collector"
            try:
                module = importlib.import_module(module_name)
                cls = _find_collector_class(module)
                if cls:
                    registry[name] = {"manifest": manifest, "cls": cls, "path": manifest_path}
                    log.debug(f"registry: discovered {name}")
            except Exception as e:
                log.warning(f"registry: {name}/collector.py import failed: {e}")
        else:
            _register_yaml_collector(registry, name, manifest, manifest_path)

    return registry


def _register_yaml_collector(registry: dict, name: str, manifest: dict, path: Path):
    """Register a YAML-only collector using yaml_runner."""
    try:
        from src.collectors.yaml_runner import YAMLCollector
        meta_obj = YAMLCollector.meta_from_yaml(path)
        bound_cls = type(
            f"YAML_{name}",
            (YAMLCollector,),
            {
                "metadata": classmethod(lambda cls, m=meta_obj: m),
                "__init__": lambda self, db, _p=path, **kw: YAMLCollector.__init__(self, db=db, yaml_path=_p, **kw),
            }
        )
        registry[name] = {"manifest": manifest, "cls": bound_cls, "path": path}
        log.debug(f"registry: discovered {name} (yaml)")
    except Exception as e:
        log.warning(f"registry: yaml collector {name} failed: {e}")


def build_enabled_collectors(db, **kwargs) -> list[tuple[str, ICollector]]:
    """Build list of enabled collector instances.

    Priority: env COLLECTOR_{NAME} > manifest enabled > default true.
    """
    registry = discover_collectors()
    enabled = []

    for name, entry in registry.items():
        manifest = entry["manifest"]
        cls = entry["cls"]

        # Priority 1: env var override
        env_key = f"COLLECTOR_{name.upper()}"
        env_val = os.environ.get(env_key)
        if env_val is not None:
            is_on = env_val.lower() in ("true", "1", "yes")
        else:
            # Priority 2: manifest enabled field
            is_on = manifest.get("enabled", True)

        if not is_on:
            continue

        try:
            instance = cls(db=db)
            enabled.append((name, instance))
        except Exception as e:
            log.error(f"registry: {name} init failed: {e}")

    log.info(f"registry: {len(enabled)}/{len(registry)} collectors enabled")
    return enabled


def list_collectors() -> list[dict]:
    """List all discovered collectors with their manifest info. For dashboard/CLI."""
    registry = discover_collectors()
    result = []
    for name, entry in sorted(registry.items()):
        m = entry["manifest"]
        env_key = f"COLLECTOR_{name.upper()}"
        env_val = os.environ.get(env_key)
        effective = env_val.lower() in ("true", "1", "yes") if env_val else m.get("enabled", True)
        result.append({
            "name": name,
            "display_name": m.get("display_name", name),
            "category": m.get("category", "unknown"),
            "enabled": effective,
            "env_override": env_val is not None,
            "manifest": str(entry["path"]),
        })
    return result
