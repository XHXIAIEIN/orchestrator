# src/governance/safety/taint.py
"""
Taint Tracking — 信息流污点追踪，偷自 OpenFang taint.rs。

核心思想：数据从来源到消费全程携带"污染标签"，到达敏感出口时自动拦截。
不是禁止用某个工具，而是禁止"用外部数据去跑 shell"这种组合。

用法:
    tracker = TaintTracker()
    result = tracker.tag(web_content, TaintLabel.EXTERNAL | TaintLabel.USER_INPUT)
    tracker.check_sink("shell_exec", result)  # raises TaintViolation

    # 数据消毒后显式移除标签
    clean = tracker.declassify(result, TaintLabel.USER_INPUT)
"""
from __future__ import annotations

import hashlib
import logging
from enum import Flag, auto
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


class TaintLabel(Flag):
    """污点标签 — 可叠加（Flag 支持 | 运算）。"""
    NONE = 0
    EXTERNAL = auto()       # 来自外部网络的数据
    USER_INPUT = auto()     # 用户输入（可能含注入）
    PII = auto()            # 个人身份信息
    SECRET = auto()         # API key / 密码 / token
    UNTRUSTED = auto()      # 来自不可信 agent 的数据


# ── Sink 规则：到达出口时检查哪些标签被阻止 ──
SINK_RULES: dict[str, TaintLabel] = {
    # shell 执行 — 阻止外部数据、不可信 agent、原始用户输入
    "shell_exec":   TaintLabel.EXTERNAL | TaintLabel.UNTRUSTED | TaintLabel.USER_INPUT,
    "Bash":         TaintLabel.EXTERNAL | TaintLabel.UNTRUSTED | TaintLabel.USER_INPUT,
    # 网络请求 — 阻止 secret 和 PII 外泄
    "net_fetch":    TaintLabel.SECRET | TaintLabel.PII,
    "WebFetch":     TaintLabel.SECRET | TaintLabel.PII,
    # agent 间消息 — 阻止 secret 泄露
    "agent_msg":    TaintLabel.SECRET,
}

# ── 工具到源标签的映射：这些工具的输出自动打标签 ──
SOURCE_TAGS: dict[str, TaintLabel] = {
    "WebFetch":     TaintLabel.EXTERNAL,
    "WebSearch":    TaintLabel.EXTERNAL,
    "web_fetch":    TaintLabel.EXTERNAL,
    "web_search":   TaintLabel.EXTERNAL,
    "Read":         TaintLabel.NONE,        # 本地文件默认可信
    "Bash":         TaintLabel.NONE,        # shell 输出默认可信
}

# ── 轮询工具：不该被 sink 规则拦截的正常监控操作 ──
POLL_TOOLS = {"docker_ps", "kubectl_get", "git_status", "nvidia_smi"}


class TaintViolation(Exception):
    """污点追踪违规 — 被污染的数据到达了不允许的 sink。"""
    def __init__(self, sink: str, labels: TaintLabel, detail: str = ""):
        self.sink = sink
        self.labels = labels
        super().__init__(f"Taint violation at '{sink}': blocked labels {labels!r}. {detail}")


@dataclass
class TaintedValue:
    """带污点标签的值。"""
    value: str
    labels: TaintLabel = TaintLabel.NONE
    origin: str = ""           # 来源工具名
    content_hash: str = ""     # 内容指纹（截断后的 SHA-256）

    def __post_init__(self):
        if not self.content_hash and self.value:
            self.content_hash = hashlib.sha256(self.value[:2000].encode()).hexdigest()[:16]


class TaintTracker:
    """
    会话级污点追踪器。

    在 executor_session 的工具调用链中使用：
    1. 工具返回结果 → tag() 打标签
    2. 结果传入下一个工具 → check_sink() 检查
    3. 数据消毒后 → declassify() 移除标签
    """

    def __init__(self):
        self._store: dict[str, TaintedValue] = {}   # content_hash → TaintedValue
        self._violations: list[dict] = []
        self._declassifications: list[dict] = []

    def tag(self, value: str, labels: TaintLabel, origin: str = "") -> TaintedValue:
        """给数据打上污点标签。"""
        tv = TaintedValue(value=value, labels=labels, origin=origin)
        self._store[tv.content_hash] = tv
        return tv

    def tag_from_tool(self, tool_name: str, output: str) -> TaintedValue:
        """根据工具名自动打标签。"""
        labels = SOURCE_TAGS.get(tool_name, TaintLabel.NONE)
        return self.tag(output, labels, origin=tool_name)

    def merge(self, *values: TaintedValue) -> TaintedValue:
        """合并多个带标签的值 — 标签取并集。"""
        combined_text = "\n".join(v.value for v in values)
        combined_labels = TaintLabel.NONE
        for v in values:
            combined_labels |= v.labels
        origins = ", ".join(v.origin for v in values if v.origin)
        return self.tag(combined_text, combined_labels, origin=f"merged({origins})")

    def check_sink(self, sink_name: str, value: TaintedValue) -> None:
        """
        检查数据是否可以到达指定 sink。

        Raises TaintViolation if blocked labels are present.
        """
        blocked = SINK_RULES.get(sink_name)
        if blocked is None:
            return  # 未配置的 sink 不检查

        violation = value.labels & blocked
        if violation:
            detail = f"Data from '{value.origin}' (hash={value.content_hash}) " \
                     f"carries {value.labels!r}, sink '{sink_name}' blocks {blocked!r}"
            self._violations.append({
                "sink": sink_name,
                "blocked": str(violation),
                "origin": value.origin,
                "hash": value.content_hash,
            })
            log.warning(f"TaintViolation: {detail}")
            raise TaintViolation(sink_name, violation, detail)

    def check_tool_input(self, tool_name: str, input_text: str) -> None:
        """
        检查传给工具的输入是否含有被污染的内容。

        通过内容指纹匹配 — 如果 input 包含之前某个 TaintedValue 的内容片段，
        则检查该 sink 的规则。
        """
        input_hash = hashlib.sha256(input_text[:2000].encode()).hexdigest()[:16]

        # 精确匹配
        if input_hash in self._store:
            self.check_sink(tool_name, self._store[input_hash])
            return

        # 子串匹配：检查 input 是否包含已知的 tainted 内容
        for tv in self._store.values():
            if tv.labels == TaintLabel.NONE:
                continue
            # 只检查足够长的片段（避免误报）
            if len(tv.value) > 50 and tv.value[:200] in input_text:
                self.check_sink(tool_name, tv)
                return

    def declassify(self, value: TaintedValue, labels_to_remove: TaintLabel,
                   reason: str = "") -> TaintedValue:
        """
        显式移除污点标签（数据已消毒后的安全决策）。

        这是一个审计点 — 每次 declassify 都会被记录。
        """
        new_labels = value.labels & ~labels_to_remove
        self._declassifications.append({
            "hash": value.content_hash,
            "removed": str(labels_to_remove),
            "remaining": str(new_labels),
            "reason": reason,
        })
        clean = TaintedValue(
            value=value.value,
            labels=new_labels,
            origin=value.origin,
            content_hash=value.content_hash,
        )
        self._store[clean.content_hash] = clean
        return clean

    def lookup(self, content_hash: str) -> TaintedValue | None:
        """按内容指纹查找。"""
        return self._store.get(content_hash)

    @property
    def violations(self) -> list[dict]:
        return list(self._violations)

    @property
    def stats(self) -> dict:
        """追踪统计。"""
        tainted = sum(1 for v in self._store.values() if v.labels != TaintLabel.NONE)
        return {
            "tracked": len(self._store),
            "tainted": tainted,
            "violations": len(self._violations),
            "declassifications": len(self._declassifications),
        }
