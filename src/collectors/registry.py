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


def discover_collectors() -> dict[str, dict]:
    """Scan for *.manifest.yaml, load each, and resolve the Python class.

    Returns {name: {"manifest": dict, "cls": type[ICollector]}}.
    """
    registry = {}

    for manifest_path in sorted(_COLLECTORS_DIR.glob("*.manifest.yaml")):
        manifest = _load_manifest(manifest_path)
        if not manifest or "name" not in manifest:
            continue

        name = manifest["name"]
        py_stem = f"{name}_collector"
        module_name = f"src.collectors.{py_stem}"

        try:
            module = importlib.import_module(module_name)
        except Exception as e:
            log.warning(f"registry: manifest '{name}' found but {py_stem}.py failed to import: {e}")
            continue

        # Find ICollector subclass in the module
        cls = None
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (isinstance(attr, type)
                    and issubclass(attr, ICollector)
                    and attr is not ICollector):
                cls = attr
                break

        if cls is None:
            log.warning(f"registry: {py_stem}.py has no ICollector subclass")
            continue

        registry[name] = {"manifest": manifest, "cls": cls, "path": manifest_path}
        log.debug(f"registry: discovered {name} ({manifest.get('display_name', name)})")

    # Also discover YAML-declared collectors (yaml/ subdirectory)
    yaml_dir = _COLLECTORS_DIR / "yaml"
    if yaml_dir.exists():
        try:
            from src.collectors.yaml_runner import YAMLCollector
            for yaml_file in sorted(yaml_dir.glob("*.yaml")):
                try:
                    meta = YAMLCollector.meta_from_yaml(yaml_file)
                    bound_cls = type(
                        f"YAML_{meta.name}",
                        (YAMLCollector,),
                        {
                            "metadata": classmethod(lambda cls, m=meta: m),
                            "_yaml_path_default": yaml_file,
                            "__init__": lambda self, db, _path=yaml_file, **kw: YAMLCollector.__init__(self, db=db, yaml_path=_path, **kw),
                        }
                    )
                    registry[meta.name] = {
                        "manifest": {"name": meta.name, "display_name": meta.display_name,
                                     "category": meta.category, "enabled": meta.default_enabled},
                        "cls": bound_cls,
                        "path": yaml_file,
                    }
                except Exception as e:
                    log.warning(f"registry: YAML collector {yaml_file.name} failed: {e}")
        except ImportError:
            pass

    return registry


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
