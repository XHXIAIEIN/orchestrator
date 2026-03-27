"""
SystemMonitor — 背压控制 + 心跳监控 + 生产者-消费者指标采集。

偷自:
  - Firecrawl system-monitor.ts — 背压控制 + heartbeat lock renewal (R13)
  - Agent Lightning — producer-consumer metrics split (R9)

背压: 执行任务前检查系统资源（CPU / RAM），高负载时延迟执行而非硬塞。
心跳: 任务注册 TTL，定期 ping 续命；超时未 ping → 判定死亡 → 释放锁。
采集: 后台线程收集慢指标（CPU/RAM/GPU），消费端只读缓存，永不阻塞。

用法:
    monitor = SystemMonitor()
    if monitor.can_accept():
        execute_task()
    else:
        log.warning("system overloaded, delaying task")

    # 心跳
    hb = monitor.heartbeat
    hb.start()
    hb.register_task("task-1", ttl=30.0)
    hb.ping("task-1")
    print(hb.get_metrics())        # 缓存指标，瞬间返回
    print(hb.get_dead_tasks())     # 超时未 ping 的任务
    hb.stop()
"""
from __future__ import annotations

import logging
import os
import platform
import threading
import time

log = logging.getLogger(__name__)

# 阈值可通过环境变量覆盖
MAX_CPU_PERCENT = float(os.environ.get("MONITOR_MAX_CPU", "85"))
MAX_RAM_PERCENT = float(os.environ.get("MONITOR_MAX_RAM", "90"))
STALL_THRESHOLD = int(os.environ.get("MONITOR_STALL_THRESHOLD", "25"))


class HeartbeatMonitor:
    """心跳监控 + 生产者-消费者指标采集。

    Producer thread: 后台线程定期采集系统指标（CPU/RAM/GPU），慢操作隔离在此。
    Consumer: 任意调用方读缓存值，瞬间返回，永不阻塞。
    Heartbeat: 任务注册 TTL，定期 ping 续命；超时未 ping → alive=False。

    Patterns:
      R13 (Firecrawl) — heartbeat + lock renewal: TTL/2 ping, 超时释放锁
      R9 (Agent Lightning) — producer-consumer split: 采集线程 vs 读缓存
    """

    def __init__(self, collect_interval: float = 5.0):
        self._collect_interval = collect_interval
        self._metrics: dict = {}
        self._lock = threading.Lock()
        self._stop_evt = threading.Event()
        self._collector_thread: threading.Thread | None = None
        self._psutil = _try_import_psutil()

        # task_id → {last_ping: float, ttl: float, alive: bool, lock_id: str|None}
        self._heartbeats: dict[str, dict] = {}
        # 死亡回调: (task_id) → None
        self._on_death_callbacks: list = []

    # ── lifecycle ────────────────────────────────────────────

    def start(self):
        """启动后台采集线程。"""
        if self._collector_thread and self._collector_thread.is_alive():
            return
        self._stop_evt.clear()
        self._collector_thread = threading.Thread(
            target=self._collect_loop, daemon=True, name="heartbeat-collector"
        )
        self._collector_thread.start()
        log.debug("HeartbeatMonitor: collector thread started (interval=%.1fs)", self._collect_interval)

    def stop(self):
        """停止采集线程。"""
        self._stop_evt.set()
        if self._collector_thread:
            self._collector_thread.join(timeout=10)
            log.debug("HeartbeatMonitor: collector thread stopped")

    @property
    def running(self) -> bool:
        return self._collector_thread is not None and self._collector_thread.is_alive()

    # ── producer: background collection ─────────────────────

    def _collect_loop(self):
        """Producer 循环：定期采集指标 + 检查过期心跳。"""
        while not self._stop_evt.is_set():
            metrics = self._collect_metrics()
            dead_tasks: list[str] = []
            with self._lock:
                self._metrics = metrics
                dead_tasks = self._check_expired_heartbeats()
            # 回调在锁外执行，避免死锁
            for task_id in dead_tasks:
                self._fire_death(task_id)
            self._stop_evt.wait(self._collect_interval)

    def _collect_metrics(self) -> dict:
        """采集系统指标（慢操作全放这里）。"""
        if self._psutil is None:
            return {"available": False, "collected_at": time.time()}
        try:
            cpu = self._psutil.cpu_percent(interval=0.1)
            mem = self._psutil.virtual_memory()
            result: dict = {
                "cpu_percent": cpu,
                "ram_used_gb": round(mem.used / (1024 ** 3), 2),
                "ram_total_gb": round(mem.total / (1024 ** 3), 2),
                "ram_percent": mem.percent,
                "collected_at": time.time(),
            }
            # GPU 指标（best-effort，不阻塞）
            gpu = self._collect_gpu()
            if gpu:
                result["gpu"] = gpu
            return result
        except Exception:
            return {"error": "collection_failed", "collected_at": time.time()}

    @staticmethod
    def _collect_gpu() -> dict | None:
        """尝试通过 pynvml 采集 GPU 指标。失败返回 None。"""
        try:
            import pynvml
            pynvml.nvmlInit()
            count = pynvml.nvmlDeviceGetCount()
            gpus = []
            for i in range(count):
                h = pynvml.nvmlDeviceGetHandleByIndex(i)
                mem = pynvml.nvmlDeviceGetMemoryInfo(h)
                util = pynvml.nvmlDeviceGetUtilizationRates(h)
                gpus.append({
                    "index": i,
                    "mem_used_mb": round(mem.used / (1024 ** 2)),
                    "mem_total_mb": round(mem.total / (1024 ** 2)),
                    "gpu_util": util.gpu,
                })
            pynvml.nvmlShutdown()
            return {"devices": gpus}
        except Exception:
            return None

    # ── consumer: read cached metrics (instant) ─────────────

    def get_metrics(self) -> dict:
        """Consumer 端：读缓存指标，瞬间返回。"""
        with self._lock:
            return dict(self._metrics)

    # ── heartbeat API ───────────────────────────────────────

    def register_task(self, task_id: str, ttl: float = 60.0, lock_id: str | None = None):
        """注册任务心跳。建议 ping 间隔 = ttl / 2。"""
        with self._lock:
            self._heartbeats[task_id] = {
                "last_ping": time.time(),
                "ttl": ttl,
                "alive": True,
                "lock_id": lock_id,
            }
        log.debug("HeartbeatMonitor: registered task %s (ttl=%.0fs)", task_id, ttl)

    def ping(self, task_id: str) -> bool:
        """心跳续命。返回 True 表示续命成功，False 表示任务不存在。"""
        with self._lock:
            hb = self._heartbeats.get(task_id)
            if hb is None:
                return False
            hb["last_ping"] = time.time()
            hb["alive"] = True
            return True

    def unregister_task(self, task_id: str):
        """移除任务心跳监控。"""
        with self._lock:
            removed = self._heartbeats.pop(task_id, None)
        if removed:
            log.debug("HeartbeatMonitor: unregistered task %s", task_id)

    def is_alive(self, task_id: str) -> bool:
        """查询任务是否还活着。"""
        with self._lock:
            hb = self._heartbeats.get(task_id)
            return hb["alive"] if hb else False

    def _check_expired_heartbeats(self) -> list[str]:
        """检查超时心跳（在锁内调用）。返回本轮新死亡的 task_id 列表。"""
        now = time.time()
        newly_dead: list[str] = []
        for task_id, hb in self._heartbeats.items():
            if hb["alive"] and (now - hb["last_ping"]) > hb["ttl"]:
                hb["alive"] = False
                newly_dead.append(task_id)
                log.warning(
                    "HeartbeatMonitor: task %s missed heartbeat "
                    "(age=%.1fs, ttl=%.0fs, lock_id=%s)",
                    task_id, now - hb["last_ping"], hb["ttl"], hb.get("lock_id"),
                )
        return newly_dead

    def get_dead_tasks(self) -> list[str]:
        """返回所有已超时的 task_id。"""
        with self._lock:
            return [tid for tid, hb in self._heartbeats.items() if not hb["alive"]]

    def get_heartbeat_summary(self) -> dict:
        """返回所有任务的心跳状态快照。"""
        with self._lock:
            now = time.time()
            return {
                tid: {
                    "alive": hb["alive"],
                    "age_s": round(now - hb["last_ping"], 1),
                    "ttl": hb["ttl"],
                    "lock_id": hb.get("lock_id"),
                }
                for tid, hb in self._heartbeats.items()
            }

    # ── death callbacks ─────────────────────────────────────

    def on_death(self, callback):
        """注册死亡回调。签名: callback(task_id: str) → None。"""
        self._on_death_callbacks.append(callback)

    def _fire_death(self, task_id: str):
        for cb in self._on_death_callbacks:
            try:
                cb(task_id)
            except Exception:
                log.exception("HeartbeatMonitor: death callback failed for %s", task_id)


class SystemMonitor:
    """轻量系统资源监控器 + 心跳组件。"""

    def __init__(self):
        self._reject_streak = 0
        self._stalled = False
        self._psutil = _try_import_psutil()
        self._heartbeat = HeartbeatMonitor()

    @property
    def heartbeat(self) -> HeartbeatMonitor:
        """心跳监控组件。"""
        return self._heartbeat

    @property
    def stalled(self) -> bool:
        """连续拒绝次数超阈值，视为系统卡死。"""
        return self._stalled

    def can_accept(self) -> bool:
        """检查系统是否有余力接受新任务。"""
        if self._psutil is None:
            # psutil 不可用时不阻塞
            return True

        try:
            cpu = self._psutil.cpu_percent(interval=0.5)
            ram = self._psutil.virtual_memory().percent
        except Exception:
            return True

        if cpu > MAX_CPU_PERCENT or ram > MAX_RAM_PERCENT:
            self._reject_streak += 1
            if self._reject_streak >= STALL_THRESHOLD and not self._stalled:
                self._stalled = True
                log.error(f"SystemMonitor: STALLED — {self._reject_streak} consecutive rejections "
                          f"(cpu={cpu:.0f}%, ram={ram:.0f}%)")
            else:
                log.info(f"SystemMonitor: overloaded (cpu={cpu:.0f}%, ram={ram:.0f}%, "
                         f"streak={self._reject_streak})")
            return False

        # 恢复
        if self._reject_streak > 0:
            log.info(f"SystemMonitor: recovered after {self._reject_streak} rejections "
                     f"(cpu={cpu:.0f}%, ram={ram:.0f}%)")
        self._reject_streak = 0
        self._stalled = False
        return True

    def snapshot(self) -> dict:
        """当前系统快照，方便日志 / 调试。

        优先从 HeartbeatMonitor 缓存读指标（如果采集线程在跑）。
        """
        cached = self._heartbeat.get_metrics()
        if cached and "cpu_percent" in cached:
            result = {
                "cpu_percent": cached["cpu_percent"],
                "ram_percent": cached.get("ram_percent"),
                "ram_available_gb": round(
                    (cached.get("ram_total_gb", 0) - cached.get("ram_used_gb", 0)), 1
                ) if cached.get("ram_total_gb") else None,
                "reject_streak": self._reject_streak,
                "stalled": self._stalled,
                "heartbeat_collector": True,
                "collected_at": cached.get("collected_at"),
            }
            if cached.get("gpu"):
                result["gpu"] = cached["gpu"]
            hb_summary = self._heartbeat.get_heartbeat_summary()
            if hb_summary:
                result["heartbeats"] = hb_summary
            return result

        # fallback: 直接采集（采集线程没启动时）
        if self._psutil is None:
            return {"available": False}
        try:
            return {
                "cpu_percent": self._psutil.cpu_percent(interval=0.1),
                "ram_percent": self._psutil.virtual_memory().percent,
                "ram_available_gb": round(self._psutil.virtual_memory().available / (1024**3), 1),
                "reject_streak": self._reject_streak,
                "stalled": self._stalled,
                "heartbeat_collector": False,
            }
        except Exception:
            return {"available": False}


def _try_import_psutil():
    """尝试导入 psutil，不可用时返回 None（不阻塞启动）。"""
    try:
        import psutil
        return psutil
    except ImportError:
        log.info("SystemMonitor: psutil not installed, backpressure disabled")
        return None


# 模块级单例
_monitor = None

def get_monitor() -> SystemMonitor:
    global _monitor
    if _monitor is None:
        _monitor = SystemMonitor()
    return _monitor
