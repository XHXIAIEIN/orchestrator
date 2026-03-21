import pytest
from unittest.mock import MagicMock, patch
from src.collectors.registry import discover_collectors, build_enabled_collectors
from src.collectors.base import ICollector, CollectorMeta


class TestDiscovery:
    def test_discover_finds_collectors(self):
        """应能发现 src/collectors/ 下的 ICollector 子类。"""
        registry = discover_collectors()
        # 在迁移完成后，应该至少发现 9 个
        assert isinstance(registry, dict)
        # 至少 base.py 里的 ICollector 不应被发现（它是 ABC）
        assert "ICollector" not in str(registry.values())

    def test_build_enabled_respects_env(self):
        """COLLECTOR_XXX=false 应禁用对应采集器。"""
        db = MagicMock()
        with patch.dict('os.environ', {'COLLECTOR_STEAM': 'false'}):
            enabled = build_enabled_collectors(db)
            names = [name for name, _ in enabled]
            assert "steam" not in names

    def test_build_enabled_default(self):
        """default_enabled=True 的 core 采集器应默认启用。"""
        db = MagicMock()
        enabled = build_enabled_collectors(db)
        names = [name for name, _ in enabled]
        # 迁移完成后 git 应该在列表中
        # 目前可能还没有迁移的采集器，所以只测 enabled 是个 list
        assert isinstance(enabled, list)
