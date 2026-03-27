"""
BrowserGuard — 浏览器操作的防御层。
从 browser-use 项目偷师：循环检测 + 页面指纹。

职责：
- PageFingerprint: 轻量级页面状态指纹（URL + 元素数 + DOM 文本哈希）
- ActionLoopDetector: 检测 agent 原地打转，升级式警告

不做决策，只提供信号。调度层自行决定如何处理警告。
"""
import hashlib
import json
import logging
import time
from collections import Counter
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


# ------------------------------------------------------------------
# PageFingerprint
# ------------------------------------------------------------------

@dataclass(frozen=True)
class PageFingerprint:
    """页面状态的轻量级指纹。

    比较两个指纹即可判断页面是否真正发生了变化，
    不需要保存完整 DOM 或截图。
    """
    url: str
    interactive_count: int   # 可交互元素数量
    dom_hash: str            # innerText 的 SHA256 前 16 字符
    timestamp: float = field(default_factory=time.monotonic)

    def same_content(self, other: "PageFingerprint") -> bool:
        """内容相同（忽略 timestamp）。"""
        if not isinstance(other, PageFingerprint):
            return False
        return (
            self.url == other.url
            and self.interactive_count == other.interactive_count
            and self.dom_hash == other.dom_hash
        )

    def __str__(self) -> str:
        return f"[{self.url[:60]}] elements={self.interactive_count} hash={self.dom_hash}"


# JS: 快速统计可交互元素数 + 正文文本
_FINGERPRINT_JS = """
(() => {
    const interactives = document.querySelectorAll(
        'a[href], button, input, textarea, select, [role="button"], [role="link"], [onclick], [tabindex]'
    );
    const text = document.body?.innerText || '';
    return JSON.stringify({
        count: interactives.length,
        text: text.substring(0, 10000)
    });
})()
"""


def page_fingerprint(runtime, page_id: str) -> PageFingerprint | None:
    """采集页面指纹。失败返回 None（不抛异常，guard 层不能炸掉主流程）。"""
    try:
        pages = runtime.list_pages()
        target = next((p for p in pages if p["id"] == page_id), None)
        if not target:
            return None

        cdp = runtime.new_cdp_client(target["webSocketDebuggerUrl"])
        try:
            # 获取当前 URL
            url_result = cdp.send("Runtime.evaluate", {"expression": "location.href"})
            url = url_result.get("result", {}).get("value", "")

            # 获取元素数 + 文本
            fp_result = cdp.send("Runtime.evaluate", {"expression": _FINGERPRINT_JS})
            raw = fp_result.get("result", {}).get("value", "{}")
            data = json.loads(raw)

            text = data.get("text", "")
            dom_hash = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]

            return PageFingerprint(
                url=url,
                interactive_count=data.get("count", 0),
                dom_hash=dom_hash,
            )
        finally:
            cdp.close()
    except Exception as e:
        log.debug(f"browser_guard: fingerprint failed for page {page_id}: {e}")
        return None


# ------------------------------------------------------------------
# ActionLoopDetector
# ------------------------------------------------------------------

# 升级式警告阈值和消息
_LOOP_THRESHOLDS = [
    (5,  "soft",  "相似动作已重复 {n} 次。若有进展可继续，否则考虑换个方法。"),
    (8,  "warn",  "检测到动作循环（{n} 次）。建议尝试完全不同的策略。"),
    (12, "hard",  "严重循环警告：已重复 {n} 次相似动作且无进展，强烈建议停止当前路径。"),
]

_STAGNATION_THRESHOLD = 3  # 连续 N 次指纹相同 → 页面停滞


class ActionLoopDetector:
    """检测 agent 浏览器操作中的循环和停滞。

    从 browser-use 偷师的核心策略：
    1. 动作规范化 → 去重比较
    2. 连续相同动作计数 → 升级式警告
    3. 页面指纹对比 → 停滞检测（动作在跑但页面没变）

    不阻止执行，只返回警告信号。
    """

    def __init__(self, max_history: int = 20):
        self._max_history = max_history
        self._actions: list[str] = []
        self._fingerprints: list[PageFingerprint] = []

    @staticmethod
    def normalize(action: str, **kwargs) -> str:
        """将动作规范化为可比较的字符串。

        规则（从 browser-use 学的）：
        - navigate: 用完整 URL
        - click: 用 selector（小写）
        - fill: 用 selector（忽略具体文本，因为填不同文本到同一输入框也算循环）
        - search: 按 token 排序（忽略词序）
        - 其他: 原样
        """
        action = action.lower().strip()

        selector = kwargs.get("selector", "")
        url = kwargs.get("url", "")
        query = kwargs.get("query", "")

        if action == "navigate":
            return f"navigate:{url}"
        elif action == "click":
            return f"click:{selector.lower()}"
        elif action == "fill":
            return f"fill:{selector.lower()}"
        elif action == "search":
            tokens = sorted(query.lower().split())
            return f"search:{' '.join(tokens)}"
        elif action == "scroll":
            direction = kwargs.get("direction", "down")
            return f"scroll:{direction}"
        else:
            return action

    def record(
        self,
        action: str,
        fingerprint: PageFingerprint | None = None,
        **kwargs,
    ) -> list[str]:
        """记录一次动作，返回警告列表（空 = 一切正常）。

        Args:
            action: 动作名称（navigate/click/fill/scroll/...）
            fingerprint: 操作后的页面指纹（可选）
            **kwargs: 传给 normalize 的参数（selector, url, query, direction）

        Returns:
            警告消息列表。空列表表示无异常。
        """
        normalized = self.normalize(action, **kwargs)

        # 入队，保持历史长度
        self._actions.append(normalized)
        if len(self._actions) > self._max_history:
            self._actions.pop(0)

        if fingerprint:
            self._fingerprints.append(fingerprint)
            if len(self._fingerprints) > self._max_history:
                self._fingerprints.pop(0)

        warnings = []

        # 检查 1: 动作循环
        loop_warn = self._check_action_loop(normalized)
        if loop_warn:
            warnings.append(loop_warn)

        # 检查 2: 页面停滞
        stagnation_warn = self._check_stagnation()
        if stagnation_warn:
            warnings.append(stagnation_warn)

        return warnings

    def _check_action_loop(self, latest: str) -> str | None:
        """检查最近动作中是否有重复循环。"""
        if len(self._actions) < 3:
            return None

        # 统计最近动作中与最新动作相同的次数
        recent = self._actions[-self._max_history:]
        count = sum(1 for a in recent if a == latest)

        # 从最严格的阈值开始检查
        for threshold, level, template in reversed(_LOOP_THRESHOLDS):
            if count >= threshold:
                msg = template.format(n=count)
                log.warning(f"browser_guard: loop detected [{level}] — {latest} x{count}")
                return msg

        return None

    def _check_stagnation(self) -> str | None:
        """检查页面是否停滞（多次操作后页面内容未变化）。"""
        if len(self._fingerprints) < _STAGNATION_THRESHOLD:
            return None

        recent = self._fingerprints[-_STAGNATION_THRESHOLD:]
        baseline = recent[0]

        if all(baseline.same_content(fp) for fp in recent[1:]):
            msg = (
                f"页面停滞：连续 {_STAGNATION_THRESHOLD} 次操作后页面内容未变化。"
                f"动作可能没有产生预期效果。当前页面: {baseline.url[:60]}"
            )
            log.warning(f"browser_guard: stagnation detected — {baseline}")
            return msg

        return None

    def reset(self) -> None:
        """重置状态（切换任务时调用）。"""
        self._actions.clear()
        self._fingerprints.clear()

    @property
    def stats(self) -> dict:
        """当前状态摘要。"""
        action_counts = Counter(self._actions)
        most_common = action_counts.most_common(3)
        return {
            "total_actions": len(self._actions),
            "unique_actions": len(action_counts),
            "most_repeated": most_common,
            "fingerprints_tracked": len(self._fingerprints),
        }


# ── 模块级单例（跨调用追踪状态，随 scheduler 生命周期存在）──
_loop_detector = ActionLoopDetector()


def get_loop_detector() -> ActionLoopDetector:
    """获取全局 guard 实例（供外部查看 stats 或 reset）。"""
    return _loop_detector
