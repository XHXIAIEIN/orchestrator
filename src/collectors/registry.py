"""
采集器注册表 — 动态扫描 + 自动发现。
灵感：OpenCLI 的 Manifest 预编译 + discovery.ts。
"""
import importlib
import logging
import os
from pathlib import Path

from src.collectors.base import ICollector, CollectorMeta

log = logging.getLogger(__name__)
_COLLECTORS_DIR = Path(__file__).parent


def discover_collectors() -> dict[str, type[ICollector]]:
    """扫描 src/collectors/*_collector.py，找到 ICollector 子类。"""
    registry = {}
    for py_file in sorted(_COLLECTORS_DIR.glob("*_collector.py")):
        module_name = f"src.collectors.{py_file.stem}"
        try:
            module = importlib.import_module(module_name)
        except Exception as e:
            log.warning(f"registry: failed to import {module_name}: {e}")
            continue

        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (isinstance(attr, type)
                    and issubclass(attr, ICollector)
                    and attr is not ICollector
                    and hasattr(attr, 'metadata')):
                try:
                    meta = attr.metadata()
                    registry[meta.name] = attr
                    log.debug(f"registry: discovered {meta.name}")
                except Exception as e:
                    log.warning(f"registry: {attr_name}.metadata() failed: {e}")

    # 扫描 YAML 声明式采集器
    yaml_dir = _COLLECTORS_DIR / "yaml"
    if yaml_dir.exists():
        try:
            from src.collectors.yaml_runner import YAMLCollector
            for yaml_file in sorted(yaml_dir.glob("*.yaml")):
                try:
                    meta = YAMLCollector.meta_from_yaml(yaml_file)
                    # 创建一个绑定了 yaml_path 的工厂类
                    # 这样 build_enabled_collectors 可以用 cls(db=db) 实例化
                    bound_cls = type(
                        f"YAML_{meta.name}",
                        (YAMLCollector,),
                        {
                            "metadata": classmethod(lambda cls, m=meta: m),
                            "_yaml_path_default": yaml_file,
                            "__init__": lambda self, db, _path=yaml_file, **kw: YAMLCollector.__init__(self, db=db, yaml_path=_path, **kw),
                        }
                    )
                    registry[meta.name] = bound_cls
                    log.debug(f"registry: discovered YAML collector {meta.name} from {yaml_file.name}")
                except Exception as e:
                    log.warning(f"registry: failed to load YAML collector {yaml_file.name}: {e}")
        except ImportError:
            log.warning("registry: yaml_runner not available, skipping YAML collectors")

    return registry


_COLLECTORS_YML = _COLLECTORS_DIR.parent.parent / "config" / "collectors.yml"


def _load_collectors_yml() -> dict[str, bool]:
    """Load config/collectors.yml — returns {name: enabled}."""
    if not _COLLECTORS_YML.exists():
        return {}
    try:
        import yaml
        raw = yaml.safe_load(_COLLECTORS_YML.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        return {k: bool(v) for k, v in raw.items() if v is not None}
    except Exception as e:
        log.warning(f"registry: failed to load {_COLLECTORS_YML}: {e}")
        return {}


def sync_collectors_yml(registry: dict[str, type]) -> None:
    """Sync config/collectors.yml with discovered collectors.

    - New collectors → appended as commented-out entries
    - Removed collectors → marked with '# REMOVED:' prefix
    - Existing entries → untouched (preserve user's enable/disable choices)
    """
    import yaml

    yml_path = _COLLECTORS_YML
    yml_path.parent.mkdir(parents=True, exist_ok=True)

    # Parse existing file preserving comments
    existing_lines = []
    existing_keys = set()
    if yml_path.exists():
        existing_lines = yml_path.read_text(encoding="utf-8").splitlines()
        for line in existing_lines:
            stripped = line.lstrip("# ").strip()
            if ":" in stripped and not stripped.startswith(("#", "REMOVED")):
                key = stripped.split(":")[0].strip()
                if key and not key.startswith(("─", "Orchestrator", "启用", "禁用", "注释", "环境")):
                    existing_keys.add(key)
            # Also catch commented-out collectors like "# steam: true"
            if line.startswith("# ") and ":" in line and "REMOVED" not in line:
                maybe_key = line.lstrip("# ").split(":")[0].strip()
                if maybe_key in registry:
                    existing_keys.add(maybe_key)

    discovered = set(registry.keys())
    new_collectors = discovered - existing_keys
    removed_collectors = existing_keys - discovered

    if not new_collectors and not removed_collectors:
        return  # Nothing to sync

    output_lines = list(existing_lines)

    # Mark removed collectors
    if removed_collectors:
        for i, line in enumerate(output_lines):
            for name in removed_collectors:
                if line.strip().startswith(f"{name}:") or line.strip().startswith(f"# {name}:"):
                    if "REMOVED" not in line:
                        output_lines[i] = f"# REMOVED: {line.lstrip('# ')}"

    # Append new collectors
    if new_collectors:
        output_lines.append("")
        output_lines.append(f"# ── 新发现 ({len(new_collectors)}) ──")
        for name in sorted(new_collectors):
            meta = registry[name].metadata()
            category = meta.category
            default = "true" if meta.default_enabled else "false"
            if meta.default_enabled:
                output_lines.append(f"{name}: {default}")
            else:
                output_lines.append(f"# {name}: {default}")

    yml_path.write_text("\n".join(output_lines) + "\n", encoding="utf-8")
    log.info(f"registry: synced collectors.yml — +{len(new_collectors)} new, -{len(removed_collectors)} removed")


def build_enabled_collectors(db, **kwargs) -> list[tuple[str, ICollector]]:
    """构建启用的采集器实例列表。

    优先级：环境变量 COLLECTOR_{NAME} > config/collectors.yml > meta.default_enabled
    """
    registry = discover_collectors()
    sync_collectors_yml(registry)
    yml_config = _load_collectors_yml()
    enabled = []

    for name, cls in registry.items():
        meta = cls.metadata()

        # Priority 1: env var
        env_key = f"COLLECTOR_{name.upper()}"
        env_val = os.environ.get(env_key)
        if env_val is not None:
            is_on = env_val.lower() in ("true", "1", "yes")
        # Priority 2: config/collectors.yml
        elif name in yml_config:
            is_on = yml_config[name]
        # Priority 3: collector default
        else:
            is_on = meta.default_enabled

        if not is_on:
            continue

        try:
            instance = cls(db=db)
            enabled.append((name, instance))
        except Exception as e:
            log.error(f"registry: {name} init failed: {e}")

    log.info(f"registry: {len(enabled)}/{len(registry)} collectors enabled (yml={len(yml_config)} overrides)")
    return enabled
