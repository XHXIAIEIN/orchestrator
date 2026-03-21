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
    return registry


def build_enabled_collectors(db, **kwargs) -> list[tuple[str, ICollector]]:
    """构建启用的采集器实例列表。替代 scheduler._build_collectors()。"""
    registry = discover_collectors()
    enabled = []

    for name, cls in registry.items():
        meta = cls.metadata()

        env_key = f"COLLECTOR_{name.upper()}"
        env_val = os.environ.get(env_key)
        if env_val is not None:
            is_on = env_val.lower() in ("true", "1", "yes")
        else:
            is_on = meta.default_enabled

        if not is_on:
            continue

        try:
            instance = cls(db=db)
            enabled.append((name, instance))
        except Exception as e:
            log.error(f"registry: {name} init failed: {e}")

    log.info(f"registry: {len(enabled)}/{len(registry)} collectors enabled")
    return enabled
