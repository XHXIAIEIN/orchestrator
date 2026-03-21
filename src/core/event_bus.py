"""
Event Bus — 轻量级进程内事件总线 + 四级优先队列。

voice-ai 启发：critical/input/output/low 独立处理，紧急任务不被低优任务阻塞。
Paperclip 启发：Wakeup Coalescing — 合并重复唤醒，防事件风暴。
ComposioHQ 启发：反应式配置 — 事件→动作声明式映射。

架构：
  - SQLite-backed 持久队列（重启不丢事件）
  - 四级优先级（CRITICAL > HIGH > NORMAL > LOW）
  - 订阅者模式（handler 注册到 event_type）
  - Wakeup Coalescing（同类事件 N 秒内只触发一次）
"""
import json
import logging
import sqlite3
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class Priority(IntEnum):
    CRITICAL = 0   # 告警、安全事件 — 立即处理
    HIGH = 1       # 用户请求、任务完成回调
    NORMAL = 2     # 定时任务、采集完成
    LOW = 3        # 日志聚合、统计更新


@dataclass
class Event:
    """总线事件。"""
    event_type: str          # e.g. "task.completed", "collector.failed", "gate.failed"
    payload: dict            # 事件数据
    priority: Priority = Priority.NORMAL
    source: str = ""         # 发送者
    event_id: str = ""       # 唯一 ID（自动生成）
    timestamp: str = ""      # ISO 时间戳
    coalesce_key: str = ""   # 合并键：相同 key 的事件在窗口内只触发一次

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if not self.event_id:
            import hashlib
            raw = f"{self.event_type}:{self.timestamp}:{id(self)}"
            self.event_id = hashlib.md5(raw.encode()).hexdigest()[:12]


# ── Reactive Rules ──
# 事件→动作声明式配置

@dataclass
class ReactiveRule:
    """反应式规则：事件触发 → 执行动作。"""
    event_pattern: str       # 匹配的事件类型（支持 * 通配）
    action: str              # 动作标识
    params: dict = field(default_factory=dict)
    max_retries: int = 0
    cooldown_s: int = 0      # 冷却时间（秒）


# 默认反应式规则
DEFAULT_RULES: list[ReactiveRule] = [
    ReactiveRule("task.failed", "log_failure", {"level": "WARNING"}),
    ReactiveRule("task.gate_failed", "log_failure", {"level": "ERROR"}),
    ReactiveRule("collector.failed", "create_repair_task", {"department": "operations"}),
    ReactiveRule("task.escalated", "notify_human", {}),
    ReactiveRule("doom_loop.*", "kill_task", {}),
]


class EventBus:
    """进程内事件总线，SQLite-backed。"""

    def __init__(self, db_path: str = None):
        self._db_path = db_path or str(_REPO_ROOT / "data" / "event_bus.db")
        self._handlers: dict[str, list[Callable]] = defaultdict(list)
        self._coalesce_cache: dict[str, float] = {}  # coalesce_key → last_trigger_time
        self._coalesce_window = 30  # 默认 30 秒合并窗口
        self._rules = list(DEFAULT_RULES)
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS event_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT UNIQUE,
                event_type TEXT NOT NULL,
                priority INTEGER NOT NULL DEFAULT 2,
                payload TEXT NOT NULL DEFAULT '{}',
                source TEXT DEFAULT '',
                coalesce_key TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                created_at TEXT NOT NULL,
                processed_at TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_eq_status ON event_queue(status, priority)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_eq_type ON event_queue(event_type)")
        conn.commit()
        conn.close()

    def subscribe(self, event_type: str, handler: Callable):
        """订阅事件。event_type 支持 * 通配。"""
        with self._lock:
            self._handlers[event_type].append(handler)
        log.debug(f"event_bus: subscribed {handler.__name__} to '{event_type}'")

    def publish(self, event: Event) -> bool:
        """发布事件到总线。"""
        # Wakeup Coalescing
        if event.coalesce_key:
            now = time.time()
            last = self._coalesce_cache.get(event.coalesce_key, 0)
            if now - last < self._coalesce_window:
                log.debug(f"event_bus: coalesced event {event.event_type} "
                          f"(key={event.coalesce_key})")
                return False
            self._coalesce_cache[event.coalesce_key] = now

        # 持久化到 DB
        try:
            conn = sqlite3.connect(self._db_path)
            conn.execute(
                "INSERT OR IGNORE INTO event_queue "
                "(event_id, event_type, priority, payload, source, coalesce_key, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
                (event.event_id, event.event_type, event.priority.value,
                 json.dumps(event.payload, ensure_ascii=False, default=str),
                 event.source, event.coalesce_key, event.timestamp)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            log.warning(f"event_bus: failed to persist event: {e}")

        # 同步分发给 handler
        self._dispatch(event)
        return True

    def _dispatch(self, event: Event):
        """分发事件给匹配的 handler。"""
        with self._lock:
            handlers = list(self._handlers.get(event.event_type, []))
            # 通配符匹配
            for pattern, hs in self._handlers.items():
                if pattern != event.event_type and self._match_pattern(pattern, event.event_type):
                    handlers.extend(hs)

        for handler in handlers:
            try:
                handler(event)
            except Exception as e:
                log.error(f"event_bus: handler {handler.__name__} failed: {e}")

        # 反应式规则
        for rule in self._rules:
            if self._match_pattern(rule.event_pattern, event.event_type):
                self._execute_rule(rule, event)

    def _execute_rule(self, rule: ReactiveRule, event: Event):
        """执行反应式规则。"""
        log.info(f"event_bus: rule triggered: {rule.event_pattern} → {rule.action}")
        # 规则执行是声明式的，实际动作由外部注册
        # 这里只记录，具体执行由 handler 负责
        try:
            conn = sqlite3.connect(self._db_path)
            conn.execute(
                "UPDATE event_queue SET status = 'processed', processed_at = ? WHERE event_id = ?",
                (datetime.now(timezone.utc).isoformat(), event.event_id)
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

    @staticmethod
    def _match_pattern(pattern: str, event_type: str) -> bool:
        """简单通配符匹配。* 匹配任意后缀。"""
        if pattern == event_type:
            return True
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            return event_type.startswith(prefix)
        return False

    def get_pending_events(self, priority: Priority = None, limit: int = 50) -> list[dict]:
        """获取待处理事件（按优先级排序）。"""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        if priority is not None:
            rows = conn.execute(
                "SELECT * FROM event_queue WHERE status = 'pending' AND priority <= ? "
                "ORDER BY priority ASC, id ASC LIMIT ?",
                (priority.value, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM event_queue WHERE status = 'pending' "
                "ORDER BY priority ASC, id ASC LIMIT ?",
                (limit,)
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_stats(self) -> dict:
        """获取事件总线统计。"""
        conn = sqlite3.connect(self._db_path)
        pending = conn.execute(
            "SELECT priority, COUNT(*) as cnt FROM event_queue "
            "WHERE status = 'pending' GROUP BY priority"
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM event_queue").fetchone()[0]
        processed = conn.execute(
            "SELECT COUNT(*) FROM event_queue WHERE status = 'processed'"
        ).fetchone()[0]
        conn.close()

        return {
            "total": total,
            "processed": processed,
            "pending_by_priority": {
                Priority(r[0]).name: r[1] for r in pending
            },
        }


# ── 全局单例 ──
_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus
