"""后台进程输出监控 — substring 匹配 + 3 级降级保护。

偷自 Hermes Agent v0.9 tools/process_registry.py lines 62-227 (R59)。

核心设计
--------
WatchPatternMonitor 监控后台进程的标准输出，逐行做 substring 匹配，
命中时通过 notification_callback 通知调用方。

3 级降级（防止监控本身成为性能问题）：
  1. 正常通知 — 匹配即回调
  2. 限流（rate limit）— 超过 8 次/10s 后静默丢弃，记录 suppressed 计数
  3. Kill switch — 持续过载超过 45s 后永久禁用该 monitor，
     发出一条 "watch_disabled" 通知后停止所有回调

"监控必须能保护自己免受自身功能的伤害"：
一个疯狂产生输出的进程如果不断触发通知，通知本身（→ agent 处理
→ API 调用 → 更多 token）会成为新的性能问题。kill switch 是最后防线。

用法
----
    def on_match(event: WatchEvent) -> None:
        if event.type == WatchEventType.MATCH:
            print(f"匹配到 {event.pattern!r}: {event.output}")
        elif event.type == WatchEventType.DISABLED:
            print(f"监控已因过载被禁用: {event.suppressed} 次被抑制")

    monitor = WatchPatternMonitor(
        patterns=["ERROR", "WARN", "task complete"],
        notification_callback=on_match,
    )
    monitor.feed("2024-01-01 ERROR: disk full")
    monitor.feed("2024-01-01 INFO: heartbeat")  # 不匹配，不触发
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, List, Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 速率限制参数
# ---------------------------------------------------------------------------

WATCH_MAX_PER_WINDOW: int = 8    # 每滑动窗口最多投递的通知数
WATCH_WINDOW_SECONDS: float = 10.0  # 滑动窗口长度（秒）
WATCH_OVERLOAD_KILL_SECONDS: float = 45.0  # 持续过载多少秒后永久禁用


# ---------------------------------------------------------------------------
# 数据类型
# ---------------------------------------------------------------------------

class WatchEventType(str, Enum):
    """WatchPatternMonitor 投递的事件类型。"""

    MATCH = "watch_match"         # 正常匹配
    DISABLED = "watch_disabled"   # 因持续过载被永久禁用


@dataclass
class WatchEvent:
    """监控回调的事件载荷。"""

    type: WatchEventType
    pattern: Optional[str] = None      # 触发匹配的 pattern（MATCH 时有值）
    output: str = ""                   # 匹配的行内容（最多 20 行 / 2000 字符）
    suppressed: int = 0                # 被限流丢弃的通知数（本次投递前累积值）
    message: str = ""                  # 人类可读的描述（DISABLED 时有值）


# 通知回调签名
NotificationCallback = Callable[[WatchEvent], None]


# ---------------------------------------------------------------------------
# 核心类
# ---------------------------------------------------------------------------

@dataclass
class _RateState:
    """速率限制的内部状态（由 _lock 保护）。"""

    window_hits: int = 0           # 当前窗口内已投递的通知数
    window_start: float = field(default_factory=time.time)
    overload_since: float = 0.0    # 持续过载的开始时间（0 = 未过载）
    suppressed: int = 0            # 累计被抑制的通知数
    total_hits: int = 0            # 累计已投递的通知数
    disabled: bool = False         # 是否已被 kill switch 永久禁用


class WatchPatternMonitor:
    """后台进程输出的 substring 模式监控器。

    线程安全。可从任意线程调用 feed()，callback 也在 feed() 调用线程执行。

    Parameters
    ----------
    patterns:
        substring 列表。每行只要包含其中任意一个，即触发通知。
        使用 substring（非正则）以最大化扫描速度。
    notification_callback:
        匹配或禁用事件发生时调用的函数。签名：``(WatchEvent) -> None``。
        回调在 feed() 调用线程执行，**不得阻塞**。
    max_per_window:
        每个滑动窗口内最多投递的通知数。默认 8。
    window_seconds:
        滑动窗口长度（秒）。默认 10。
    overload_kill_seconds:
        持续过载多久后触发 kill switch。默认 45 秒。
    """

    def __init__(
        self,
        patterns: List[str],
        notification_callback: NotificationCallback,
        max_per_window: int = WATCH_MAX_PER_WINDOW,
        window_seconds: float = WATCH_WINDOW_SECONDS,
        overload_kill_seconds: float = WATCH_OVERLOAD_KILL_SECONDS,
    ):
        self._patterns = list(patterns)
        self._callback = notification_callback
        self._max_per_window = max_per_window
        self._window_seconds = window_seconds
        self._overload_kill_seconds = overload_kill_seconds

        self._state = _RateState()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    @property
    def disabled(self) -> bool:
        """是否已被 kill switch 永久禁用。"""
        with self._lock:
            return self._state.disabled

    @property
    def patterns(self) -> List[str]:
        """当前监控的 pattern 列表（只读副本）。"""
        return list(self._patterns)

    def add_pattern(self, pattern: str) -> None:
        """动态添加一个 pattern（线程安全）。"""
        with self._lock:
            if pattern not in self._patterns:
                self._patterns.append(pattern)

    def remove_pattern(self, pattern: str) -> bool:
        """移除一个 pattern。返回 True 表示成功移除，False 表示不存在。"""
        with self._lock:
            try:
                self._patterns.remove(pattern)
                return True
            except ValueError:
                return False

    def feed(self, text: str) -> None:
        """向监控器投入新的输出文本（可以是多行）。

        快速路径：若 patterns 为空或已被禁用，直接返回。
        """
        if not self._patterns:
            return
        with self._lock:
            if self._state.disabled:
                return

        # 扫描匹配（在锁外执行，避免持锁进行字符串操作）
        matched_lines, first_pattern = self._scan(text)
        if not matched_lines:
            return

        self._process_matches(matched_lines, first_pattern)

    def stats(self) -> dict:
        """返回速率统计（用于监控/日志）。"""
        with self._lock:
            return {
                "disabled": self._state.disabled,
                "total_hits": self._state.total_hits,
                "suppressed": self._state.suppressed,
                "window_hits": self._state.window_hits,
                "patterns": len(self._patterns),
            }

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    def _scan(self, text: str) -> tuple[list[str], Optional[str]]:
        """逐行扫描 text，返回 (匹配行列表, 第一个命中 pattern)。

        使用 substring 匹配（非正则），每行只记录第一个命中的 pattern。
        """
        matched_lines: list[str] = []
        first_pattern: Optional[str] = None

        # 快照 patterns，避免持锁扫描
        patterns = list(self._patterns)

        for line in text.splitlines():
            for pat in patterns:
                if pat in line:
                    matched_lines.append(line.rstrip())
                    if first_pattern is None:
                        first_pattern = pat
                    break  # 每行只匹配第一个 pattern

        return matched_lines, first_pattern

    def _process_matches(self, matched_lines: list[str], first_pattern: Optional[str]) -> None:
        """在锁内决定是否投递通知，并处理速率限制和 kill switch。"""
        now = time.time()
        callback_event: Optional[WatchEvent] = None

        with self._lock:
            st = self._state

            # 重置过期窗口
            if now - st.window_start >= self._window_seconds:
                st.window_hits = 0
                st.window_start = now

            if st.window_hits >= self._max_per_window:
                # --- 限流路径 ---
                st.suppressed += len(matched_lines)

                # 更新过载计时
                if st.overload_since == 0.0:
                    st.overload_since = now
                elif now - st.overload_since > self._overload_kill_seconds:
                    # Kill switch：永久禁用
                    st.disabled = True
                    callback_event = WatchEvent(
                        type=WatchEventType.DISABLED,
                        suppressed=st.suppressed,
                        message=(
                            f"Watch patterns 已禁用：持续过载 "
                            f"{self._overload_kill_seconds:.0f}s，"
                            f"累计抑制 {st.suppressed} 条通知。"
                            f"请手动 poll 进程输出。"
                        ),
                    )
            else:
                # --- 正常投递路径 ---
                st.window_hits += 1
                st.total_hits += 1
                # 收到一次正常投递，清除过载计时
                st.overload_since = 0.0

                suppressed_snapshot = st.suppressed
                st.suppressed = 0  # 清零，已通过本次通知上报

                # 裁剪输出：最多 20 行 / 2000 字符
                output = "\n".join(matched_lines[:20])
                if len(output) > 2000:
                    output = output[:2000] + "\n...(truncated)"

                callback_event = WatchEvent(
                    type=WatchEventType.MATCH,
                    pattern=first_pattern,
                    output=output,
                    suppressed=suppressed_snapshot,
                )

        # 锁外执行回调（避免持锁期间 callback 死锁）
        if callback_event is not None:
            try:
                self._callback(callback_event)
            except Exception:
                log.exception("WatchPatternMonitor: notification callback 抛出异常")
