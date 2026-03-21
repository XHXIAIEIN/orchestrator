import json
import sqlite3

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from src.collectors.yaml_runner import YAMLCollector, _expand_env
from src.collectors.base import CollectorMeta
from src.storage.events_db import EventsDB


class TestExpandEnv:
    def test_expand_known_var(self, monkeypatch):
        monkeypatch.setenv("MY_PATH", "/tmp/test")
        assert _expand_env("${MY_PATH}/data") == "/tmp/test/data"

    def test_expand_unknown_var_unchanged(self):
        assert _expand_env("${NONEXISTENT_VAR_XYZ}") == "${NONEXISTENT_VAR_XYZ}"


class TestYAMLCollectorJsonFile:
    def test_collect_json_file(self, tmp_path):
        # 创建测试数据
        data_file = tmp_path / "data.json"
        data_file.write_text(json.dumps([
            {"id": "1", "title": "event one"},
            {"id": "2", "title": "event two"},
        ]))

        config = {
            "name": "test_json",
            "display_name": "Test JSON",
            "category": "experimental",
            "source": {
                "type": "json_file",
                "path": str(data_file),
            },
            "extract": [
                {"field": "id", "key": "id"},
                {"field": "title", "key": "title"},
            ],
            "transform": {
                "source": "test",
                "category": "testing",
                "title": "${title}",
                "dedup_key": "test:${id}",
                "score": 0.5,
                "tags": ["test"],
            },
        }

        db = EventsDB(str(tmp_path / "events.db"))
        collector = YAMLCollector(db=db, config=config)
        count = collector.collect()
        assert count == 2

    def test_collect_deduplicates(self, tmp_path):
        data_file = tmp_path / "data.json"
        data_file.write_text(json.dumps([{"id": "1", "title": "event"}]))

        config = {
            "name": "test_dedup",
            "source": {"type": "json_file", "path": str(data_file)},
            "extract": [{"field": "id", "key": "id"}, {"field": "title", "key": "title"}],
            "transform": {
                "source": "test", "category": "testing",
                "title": "${title}", "dedup_key": "test:${id}",
                "score": 0.5, "tags": ["test"],
            },
        }

        db = EventsDB(str(tmp_path / "events.db"))
        collector = YAMLCollector(db=db, config=config)
        count1 = collector.collect()
        count2 = collector.collect()
        assert count1 == 1
        assert count2 == 0  # dedup


class TestYAMLCollectorCommand:
    def test_collect_command(self, tmp_path):
        config = {
            "name": "test_cmd",
            "source": {
                "type": "command",
                "cmd": "echo hello_world",
                "timeout": 5,
            },
            "extract": [
                {"field": "output", "pattern": "(\\w+)"},
            ],
            "transform": {
                "source": "test_cmd", "category": "testing",
                "title": "cmd: ${output}",
                "dedup_key": "cmd:${output}",
                "score": 0.3, "tags": ["test"],
            },
        }

        db = EventsDB(str(tmp_path / "events.db"))
        collector = YAMLCollector(db=db, config=config)
        count = collector.collect()
        assert count == 1


class TestYAMLCollectorMeta:
    def test_meta_from_yaml(self, tmp_path):
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text("""
name: test_collector
display_name: Test Collector
category: experimental
default_enabled: false
source:
  type: json_file
  path: "${DATA_DIR}/test.json"
transform:
  source: test
  category: testing
""")
        meta = YAMLCollector.meta_from_yaml(yaml_file)
        assert meta.name == "test_collector"
        assert meta.display_name == "Test Collector"
        assert meta.category == "experimental"
        assert meta.default_enabled is False
        assert "DATA_DIR" in meta.env_vars


class TestYAMLCollectorSqlite:
    def test_collect_sqlite(self, tmp_path):
        # 创建测试 SQLite DB
        test_db = tmp_path / "test.db"
        conn = sqlite3.connect(str(test_db))
        conn.execute("CREATE TABLE items (id TEXT, name TEXT)")
        conn.execute("INSERT INTO items VALUES ('a1', 'item_alpha')")
        conn.execute("INSERT INTO items VALUES ('b2', 'item_beta')")
        conn.commit()
        conn.close()

        config = {
            "name": "test_sqlite",
            "source": {
                "type": "sqlite",
                "path": str(test_db),
                "query": "SELECT id, name FROM items",
            },
            "extract": [
                {"field": "id", "key": "id"},
                {"field": "name", "key": "name"},
            ],
            "transform": {
                "source": "test_sqlite", "category": "testing",
                "title": "${name}",
                "dedup_key": "sqlite:${id}",
                "score": 0.4, "tags": ["test"],
            },
        }

        db = EventsDB(str(tmp_path / "events.db"))
        collector = YAMLCollector(db=db, config=config)
        count = collector.collect()
        assert count == 2


class TestYAMLCollectorJq:
    def test_jq_nested(self):
        collector = YAMLCollector.__new__(YAMLCollector)
        data = {"user": {"profile": {"name": "test_user"}}}
        assert collector._jq_get(data, ".user.profile.name") == "test_user"

    def test_jq_missing_key(self):
        collector = YAMLCollector.__new__(YAMLCollector)
        data = {"user": {}}
        assert collector._jq_get(data, ".user.email") is None


class TestRegistryYAMLIntegration:
    def test_registry_discovers_yaml(self):
        """Registry 应该能发现 yaml/ 目录下的采集器。"""
        from src.collectors.registry import discover_collectors
        registry = discover_collectors()
        # system_uptime.yaml 应该被发现（如果存在）
        yaml_dir = Path("src/collectors/yaml")
        if yaml_dir.exists() and list(yaml_dir.glob("*.yaml")):
            # name 来自 YAML 文件内的 name 字段
            assert "system_uptime" in registry
