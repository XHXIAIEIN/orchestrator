"""
ICollector 协议 — 所有采集器的统一基类。
灵感：OpenCLI 的 adapter interface + metadata 声明。
"""
import logging
import os
import time
import uuid
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
        self._run_id = None  # 由 collect_with_metrics() 设置

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
        """汇总日志：终端看这个判断状态。DB + stderr 双写。"""
        self._stderr.log(
            getattr(logging, level, logging.INFO), message,
        )
        try:
            self.db.write_log(
                f"[{self._name}] {message}",
                level, f"collector.{self._name}",
                run_id=self._run_id,
            )
        except Exception:
            pass

    def trace(self, step: str, detail: str, level: str = "DEBUG"):
        """分段追踪：有问题时查 DB 看细节。

        终端不显示（DEBUG 级别），只写 DB。
        用法：
            self.trace("scan", "found 3 repos")
            self.trace("parse", "orchestrator: 8 commits, 2 skipped")
            self.trace("dedup", "14 new, 3 already existed")
        """
        self._stderr.debug(f"[{step}] {detail}")
        try:
            self.db.write_log(
                f"[{self._name}] {detail}",
                level, f"collector.{self._name}",
                run_id=self._run_id,
                step=step,
            )
        except Exception:
            pass

    def collect_with_metrics(self) -> int:
        """带追踪的采集包装器。

        每次调用生成唯一 run_id，汇总 + 分段追踪都绑定到这个 run_id。
        终端看汇总，有问题查 DB：
            SELECT * FROM logs WHERE run_id = 'xxx' ORDER BY id
        """
        self._run_id = uuid.uuid4().hex[:8]
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
        finally:
            self._run_id = None
