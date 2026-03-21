import pytest
from unittest.mock import MagicMock, patch
from src.collectors.registry import discover_collectors, build_enabled_collectors
from src.collectors.base import ICollector, CollectorMeta


class TestDiscovery:
    def test_discover_finds_collectors(self):
        """应能发现 src/collectors/ 下全部 9 个 ICollector 子类。"""
        registry = discover_collectors()
        assert isinstance(registry, dict)
        assert len(registry) >= 9, f"Expected >= 9 collectors, found {len(registry)}: {sorted(registry.keys())}"
        # ICollector 本身（ABC）不应被发现
        assert "ICollector" not in str(registry.values())
        # 关键采集器必须在
        for name in ("git", "browser", "claude", "network", "vscode", "codebase"):
            assert name in registry, f"Core collector '{name}' not discovered"

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
        assert isinstance(enabled, list)
        assert len(enabled) >= 6, f"Expected >= 6 core collectors enabled, got {len(enabled)}"
        names = [name for name, _ in enabled]
        assert "git" in names, "git collector should be enabled by default"
