"""
YAML 声明式采集器引擎。
灵感：OpenCLI 的 Pipeline DSL — 用 YAML 声明采集逻辑，运行时由通用引擎执行。

支持的 source 类型：
- json_file: 读 JSON/JSONL 文件
- command: 执行系统命令，解析 stdout
- sqlite: 查询 SQLite DB
- http: HTTP GET 请求
"""
import hashlib
import json
import logging
import os
import re
import sqlite3
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from src.collectors.base import ICollector, CollectorMeta
from src.storage.events_db import EventsDB

log = logging.getLogger(__name__)


def _expand_env(s: str) -> str:
    """展开字符串中的 ${ENV_VAR} 引用。"""
    def replacer(m):
        return os.environ.get(m.group(1), m.group(0))
    return re.sub(r'\$\{(\w+)\}', replacer, s)


class YAMLCollector(ICollector):
    """通用 YAML 声明式采集器。"""

    def __init__(self, db: EventsDB, yaml_path: Path = None, config: dict = None, **kwargs):
        # 不调 super().__init__，因为 base 的 __init__ 会调 self.metadata()
        # 而 YAMLCollector 本身的 metadata() 会 raise NotImplementedError
        if config:
            self.config = config
        elif yaml_path:
            self.config = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        else:
            raise ValueError("YAMLCollector needs yaml_path or config")
        self._yaml_path = yaml_path
        # Must call super().__init__ AFTER self.config is set, because
        # super() calls self.metadata() which needs self.config for bound subclasses.
        # Note: don't shadow self.log — ICollector.log() is a method, not a Logger.
        self.db = db
        self._name = self.config.get("name", "yaml_unknown")
        self._stderr = logging.getLogger(f"collector.{self._name}")
        self._run_id = None

    @classmethod
    def metadata(cls) -> CollectorMeta:
        # YAMLCollector 本身不应被 registry 发现（它是通用引擎）
        # 具体的 YAML 采集器由 registry 通过 meta_from_yaml() 生成
        raise NotImplementedError("Use YAMLCollector.meta_from_yaml() for specific YAML collectors")

    @classmethod
    def meta_from_yaml(cls, yaml_path: Path) -> CollectorMeta:
        """从 YAML 文件提取 metadata，供 registry 使用。"""
        config = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        return CollectorMeta(
            name=config["name"],
            display_name=config.get("display_name", config["name"]),
            category=config.get("category", "experimental"),
            env_vars=cls._extract_env_vars(config),
            event_sources=[config.get("transform", {}).get("source", config["name"])],
            default_enabled=config.get("default_enabled", False),
        )

    @staticmethod
    def _extract_env_vars(config: dict) -> list[str]:
        """从 config 中提取所有 ${ENV_VAR} 引用。"""
        text = yaml.dump(config)
        return list(set(re.findall(r'\$\{(\w+)\}', text)))

    def collect(self) -> int:
        """执行 YAML 定义的采集管道：source → extract → transform → insert。"""
        raw_data = self._read_source()
        if raw_data is None:
            return -1

        items = self._extract(raw_data)
        if not items:
            return 0

        return self._transform_and_insert(items)

    def _read_source(self) -> Optional[Any]:
        """根据 source.type 读取原始数据。"""
        source = self.config.get("source", {})
        src_type = source.get("type", "")

        try:
            if src_type == "json_file":
                return self._read_json_file(source)
            elif src_type == "command":
                return self._read_command(source)
            elif src_type == "sqlite":
                return self._read_sqlite(source)
            elif src_type == "http":
                return self._read_http(source)
            else:
                self.log.error(f"Unknown source type: {src_type}")
                return None
        except Exception as e:
            self.log.error(f"Source read failed: {e}")
            return None

    def _read_json_file(self, source: dict) -> Optional[Any]:
        path = Path(_expand_env(source["path"]))
        if not path.exists():
            self.log.warning(f"JSON file not found: {path}")
            return None
        text = path.read_text(encoding="utf-8")
        # 支持 JSONL（每行一个 JSON）
        if source.get("format") == "jsonl" or path.suffix == ".jsonl":
            return [json.loads(line) for line in text.strip().splitlines() if line.strip()]
        return json.loads(text)

    def _read_command(self, source: dict) -> Optional[str]:
        cmd = _expand_env(source["cmd"])
        timeout = source.get("timeout", 30)
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=timeout
            )
            if result.returncode != 0:
                self.log.warning(f"Command failed (rc={result.returncode}): {result.stderr[:200]}")
            return result.stdout
        except subprocess.TimeoutExpired:
            self.log.error(f"Command timed out after {timeout}s: {cmd[:100]}")
            return None

    def _read_sqlite(self, source: dict) -> Optional[list]:
        db_path = Path(_expand_env(source["path"]))
        if not db_path.exists():
            self.log.warning(f"SQLite DB not found: {db_path}")
            return None
        query = source["query"]
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            self.log.error(f"SQLite query failed: {e}")
            return None

    def _read_http(self, source: dict) -> Optional[str]:
        url = _expand_env(source["url"])
        timeout = source.get("timeout", 10)
        headers = source.get("headers", {})
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8")
        except Exception as e:
            self.log.error(f"HTTP request failed: {e}")
            return None

    def _extract(self, raw_data: Any) -> list[dict]:
        """从原始数据中提取结构化字段。"""
        extract_rules = self.config.get("extract", [])
        if not extract_rules:
            # 没有 extract 规则，如果 raw_data 是 list 直接返回，否则包装
            if isinstance(raw_data, list):
                return raw_data
            return [raw_data] if raw_data else []

        # 如果原始数据是 list，对每个元素应用 extract
        if isinstance(raw_data, list):
            results = []
            for item in raw_data:
                extracted = self._apply_extract(item, extract_rules)
                if extracted:
                    results.append(extracted)
            return results

        # 单个对象
        extracted = self._apply_extract(raw_data, extract_rules)
        return [extracted] if extracted else []

    def _apply_extract(self, item: Any, rules: list) -> Optional[dict]:
        """对单个数据项应用 extract 规则。"""
        result = {}
        for rule in rules:
            field = rule["field"]
            if "jq" in rule:
                # 简单的 jq-like 字段访问: ".key1.key2"
                value = self._jq_get(item, rule["jq"])
            elif "pattern" in rule:
                # 正则提取
                text = str(item) if not isinstance(item, str) else item
                m = re.search(rule["pattern"], text)
                value = m.group(1) if m and m.groups() else (m.group(0) if m else None)
            elif "key" in rule:
                # 直接字典 key
                value = item.get(rule["key"]) if isinstance(item, dict) else None
            else:
                value = None
            result[field] = value
        return result if any(v is not None for v in result.values()) else None

    def _jq_get(self, obj: Any, path: str) -> Any:
        """简单 jq 路径：'.key1.key2' → obj[key1][key2]。"""
        parts = [p for p in path.strip().split(".") if p]
        current = obj
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list) and part.isdigit():
                idx = int(part)
                current = current[idx] if idx < len(current) else None
            else:
                return None
        return current

    def _transform_and_insert(self, items: list[dict]) -> int:
        """把 extracted items 转换为 events 并插入 DB。"""
        transform = self.config.get("transform", {})
        source_name = transform.get("source", self.config.get("name", "yaml"))
        category = transform.get("category", "other")
        score = transform.get("score", 0.3)
        tags = transform.get("tags", [source_name])

        count = 0
        for item in items:
            # 构建 title
            title_template = transform.get("title", str(item))
            title = self._render_template(title_template, item)

            # 构建 dedup_key
            dedup_template = transform.get("dedup_key", f"{source_name}:{hashlib.md5(title.encode()).hexdigest()[:12]}")
            dedup_key = self._render_template(dedup_template, item)

            inserted = self.db.insert_event(
                source=source_name,
                category=category,
                title=title[:200],
                duration_minutes=0,
                score=score,
                tags=tags,
                metadata=item,
                dedup_key=dedup_key,
            )
            if inserted:
                count += 1

        return count

    def _render_template(self, template: str, data: dict) -> str:
        """简单模板渲染：${field_name} → data[field_name]。"""
        def replacer(m):
            key = m.group(1)
            val = data.get(key, m.group(0))
            return str(val) if val is not None else ""
        return re.sub(r'\$\{(\w+)\}', replacer, template)
