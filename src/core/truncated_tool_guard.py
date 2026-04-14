"""截断工具调用检测器 — 流式截断防护。

偷自 Hermes Agent v0.9 run_agent.py lines 8716-8742 (R59)。

LLM 流式 API 在输出达到 max_tokens 时会截断响应。如果截断发生在
tool_calls 的 JSON arguments 中间，arguments 字段将包含无效 JSON。
执行这样的工具调用会导致 JSON 解析错误或意外行为。

防护策略（3 级）：
  1. 正常路径：JSON 有效 → 直接执行
  2. 首次截断：静默重试同一 API 调用，不把坏响应追加到 messages
  3. 二次截断：拒绝执行，返回 TruncationResult(truncated=True)

用法示例：
    guard = TruncatedToolGuard()

    # 在 API 调用循环中
    response = call_api(messages)
    check = guard.check(response.tool_calls)

    if check.truncated:
        # 拒绝执行，终止本轮
        return {"partial": True, "error": check.error}
    elif check.should_retry:
        # 不追加坏响应，直接重试
        continue  # don't append response to messages first
    else:
        # 正常执行
        guard.reset()
        execute_tool_calls(response.tool_calls)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TruncationResult:
    """工具调用截断检查结果。"""

    # 是否应该重试（首次截断）
    should_retry: bool = False

    # 是否已确认截断，应拒绝执行（二次截断）
    truncated: bool = False

    # 如果 truncated=True，提供给上层的错误描述
    error: str = ""

    # 检测到的无效工具名称列表（用于日志）
    invalid_tools: List[str] = None

    def __post_init__(self):
        if self.invalid_tools is None:
            self.invalid_tools = []


class TruncatedToolGuard:
    """单轮 API 调用的截断防护状态机。

    每个 agent 会话共用一个实例即可（guard 仅追踪当前轮重试次数）。
    调用 reset() 或成功执行 tool calls 后自动清零。
    """

    def __init__(self):
        # 当前轮次的重试次数（0 或 1）
        self._retries: int = 0

    def reset(self) -> None:
        """成功处理一轮 tool calls 后重置计数器。"""
        self._retries = 0

    def check(self, tool_calls: Optional[List[Any]]) -> TruncationResult:
        """检查一批 tool calls 的 JSON 参数是否完整。

        Args:
            tool_calls: API 响应中的 tool_calls 列表。
                每个元素需要有 .function.arguments (str) 或
                ['function']['arguments'] 字段。

        Returns:
            TruncationResult，调用方依据其决定是否重试/拒绝。
        """
        if not tool_calls:
            # 无 tool calls → 无需检查，重置计数
            self.reset()
            return TruncationResult()

        invalid_tools = _find_invalid_json_args(tool_calls)

        if not invalid_tools:
            # 所有参数 JSON 有效
            self.reset()
            return TruncationResult()

        # 发现截断
        tool_names = [t for t in invalid_tools]

        if self._retries < 1:
            # 首次截断：静默重试
            self._retries += 1
            logger.warning(
                "截断工具调用检测：%s — 正在无痕重试（不追加坏响应到 messages）",
                ", ".join(tool_names),
            )
            return TruncationResult(
                should_retry=True,
                invalid_tools=tool_names,
            )

        # 二次截断：拒绝执行
        logger.error(
            "截断工具调用再次发生：%s — 拒绝执行不完整参数",
            ", ".join(tool_names),
        )
        self.reset()  # 重置，以便下轮调用重新计数
        return TruncationResult(
            truncated=True,
            error="Response truncated due to output length limit — refusing to execute incomplete tool arguments",
            invalid_tools=tool_names,
        )

    @property
    def retry_count(self) -> int:
        """当前轮已重试次数。"""
        return self._retries


def _find_invalid_json_args(tool_calls: List[Any]) -> List[str]:
    """返回 JSON arguments 无效的工具名列表。

    支持两种格式：
    - OpenAI SDK 对象：tc.function.name, tc.function.arguments
    - 字典格式：tc['function']['name'], tc['function']['arguments']
    """
    invalid = []
    for tc in tool_calls:
        name, arguments = _extract_name_and_args(tc)
        if arguments is None:
            # 没有 arguments 字段 — 视为有效（无参工具）
            continue
        if not _is_valid_json(arguments):
            invalid.append(name or "<unknown>")
    return invalid


def _extract_name_and_args(tc: Any) -> tuple[Optional[str], Optional[str]]:
    """从 tool call 对象或字典中提取 (name, arguments)。"""
    # 字典格式（如 messages 中存储的格式）
    if isinstance(tc, dict):
        fn = tc.get("function", {})
        if isinstance(fn, dict):
            return fn.get("name"), fn.get("arguments")
        return None, None

    # SDK 对象格式
    fn = getattr(tc, "function", None)
    if fn is not None:
        name = getattr(fn, "name", None)
        arguments = getattr(fn, "arguments", None)
        return name, arguments

    return None, None


def _is_valid_json(text: Any) -> bool:
    """检查字符串是否为有效 JSON。

    空字符串和 None 视为有效（无参工具的惯例）。
    """
    if text is None:
        return True
    if not isinstance(text, str):
        return True  # 已经是 Python 对象，不需要解析
    text = text.strip()
    if not text:
        return True  # 空参数
    try:
        json.loads(text)
        return True
    except (json.JSONDecodeError, ValueError):
        return False
