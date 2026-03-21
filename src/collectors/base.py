"""
ICollector 协议 — 所有采集器的统一基类。
灵感：OpenCLI 的 adapter interface + metadata 声明。
"""
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from src.storage.events_db import EventsDB


COLLECTOR_TIMEOUTS = {
    "subprocess": int(os.environ.get("COLLECTOR_TIMEOUT_SUBPROCESS", "30")),
    "http": int(os.environ.get("COLLECTOR_TIMEOUT_HTTP", "10")),
    "file_io": int(os.environ.get("COLLECTOR_TIMEOUT_FILE", "5")),
}


@dataclass
class CollectorMeta:
    """采集器自我描述。"""
    name: str
    display_name: str
    category: str                      # "core" | "optional" | "experimental"
    env_vars: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    event_sources: list[str] = field(default_factory=list)
    default_enabled: bool = True


class ICollector(ABC):
    """采集器统一协议。"""

    def __init__(self, db: EventsDB, **kwargs):
        self.db = db
        self._name = self.metadata().name
        self._stderr = logging.getLogger(f"collector.{self._name}")

    @classmethod
    @abstractmethod
    def metadata(cls) -> CollectorMeta:
        ...

    @abstractmethod
    def collect(self) -> int:
        ...

    def preflight(self) -> tuple[bool, str]:
        return True, "ok"

    def log(self, message: str, level: str = "INFO"):
        """写日志：DB 为主，stderr 为安全网。

        DB 挂了不能往 DB 写"DB 挂了"，所以 stderr 永远兜底。
        """
        self._stderr.log(
            getattr(logging, level, logging.INFO), message,
        )
        try:
            self.db.write_log(
                f"[{self._name}] {message}",
                level, f"collector.{self._name}",
            )
        except Exception:
            # DB 写入失败 — stderr 已经记了，不再尝试
            pass

    def collect_with_metrics(self) -> int:
        """带日志和计时的采集包装器。"""
        self.log("starting collection")
        t0 = time.time()

        try:
            count = self.collect()
            elapsed = time.time() - t0
            self.log(f"done: {count} events in {elapsed:.1f}s")
            return count
        except Exception as e:
            elapsed = time.time() - t0
            self.log(f"FAILED after {elapsed:.1f}s: {e}", "ERROR")
            return -1
