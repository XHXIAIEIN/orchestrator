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
        self.log = logging.getLogger(f"collector.{self.metadata().name}")

    @classmethod
    @abstractmethod
    def metadata(cls) -> CollectorMeta:
        ...

    @abstractmethod
    def collect(self) -> int:
        ...

    def preflight(self) -> tuple[bool, str]:
        return True, "ok"

    def collect_with_metrics(self) -> int:
        """带日志和计时的采集包装器。"""
        meta = self.metadata()
        self.log.info("starting collection")
        t0 = time.time()

        try:
            count = self.collect()
            elapsed = time.time() - t0
            self.log.info(f"done: {count} events in {elapsed:.1f}s")
            self.db.write_log(
                f"[{meta.name}] {count} events, {elapsed:.1f}s",
                "INFO", f"collector.{meta.name}",
            )
            return count
        except Exception as e:
            elapsed = time.time() - t0
            self.log.error(f"failed after {elapsed:.1f}s: {e}")
            self.db.write_log(
                f"[{meta.name}] FAILED: {e}",
                "ERROR", f"collector.{meta.name}",
            )
            return -1
