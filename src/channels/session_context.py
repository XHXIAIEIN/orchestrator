"""会话上下文变量 — 用 ContextVar 替代 os.environ 做并发会话隔离。

偷自 Hermes Agent v0.9 gateway/session_context.py (R59)。

背景
----
Channel 层以多线程/asyncio 并发处理消息。旧做法是把会话元数据写入
os.environ，但 os.environ 是进程全局的——两条消息同时到达时，B 的
写入会覆盖 A 的值，导致通知和工具调用路由到错误的会话。

ContextVar 值是 task-local 的：每个 asyncio task（及其 spawn 的
run_in_executor 线程）各自持有独立副本，并发消息不会互相干扰。

向后兼容
--------
``get_session_env(name, default="")`` 镜像旧的
``os.getenv("ORCHESTRATOR_SESSION_*", ...)`` 调用，三级回退：
  1. ContextVar（Gateway 并发模式）
  2. os.environ（CLI / cron / 测试模式）
  3. default

用法
----
    # 消息处理器入口
    tokens = set_session_vars(
        platform="telegram",
        chat_id="123456789",
        user_id="987654321",
        session_key="sess_abc",
    )
    try:
        await handle_message(...)
    finally:
        clear_session_vars(tokens)

    # 工具/回调内部（无需关心并发）
    from src.channels.session_context import get_session_env
    platform = get_session_env("ORCHESTRATOR_SESSION_PLATFORM")
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from typing import List

# ---------------------------------------------------------------------------
# Per-task session ContextVar 定义
# ---------------------------------------------------------------------------

_SESSION_PLATFORM: ContextVar[str] = ContextVar("ORCHESTRATOR_SESSION_PLATFORM", default="")
_SESSION_CHAT_ID: ContextVar[str] = ContextVar("ORCHESTRATOR_SESSION_CHAT_ID", default="")
_SESSION_CHAT_NAME: ContextVar[str] = ContextVar("ORCHESTRATOR_SESSION_CHAT_NAME", default="")
_SESSION_THREAD_ID: ContextVar[str] = ContextVar("ORCHESTRATOR_SESSION_THREAD_ID", default="")
_SESSION_USER_ID: ContextVar[str] = ContextVar("ORCHESTRATOR_SESSION_USER_ID", default="")
_SESSION_USER_NAME: ContextVar[str] = ContextVar("ORCHESTRATOR_SESSION_USER_NAME", default="")
_SESSION_KEY: ContextVar[str] = ContextVar("ORCHESTRATOR_SESSION_KEY", default="")

# 名称 → ContextVar 的映射，供 get_session_env() 按字符串查找
_VAR_MAP: dict[str, ContextVar[str]] = {
    "ORCHESTRATOR_SESSION_PLATFORM":  _SESSION_PLATFORM,
    "ORCHESTRATOR_SESSION_CHAT_ID":   _SESSION_CHAT_ID,
    "ORCHESTRATOR_SESSION_CHAT_NAME": _SESSION_CHAT_NAME,
    "ORCHESTRATOR_SESSION_THREAD_ID": _SESSION_THREAD_ID,
    "ORCHESTRATOR_SESSION_USER_ID":   _SESSION_USER_ID,
    "ORCHESTRATOR_SESSION_USER_NAME": _SESSION_USER_NAME,
    "ORCHESTRATOR_SESSION_KEY":       _SESSION_KEY,
}

# 变量顺序必须与 set_session_vars() 的 .set() 调用顺序一一对应，
# clear_session_vars() 依赖此顺序进行 reset()
_VAR_ORDER: list[ContextVar[str]] = [
    _SESSION_PLATFORM,
    _SESSION_CHAT_ID,
    _SESSION_CHAT_NAME,
    _SESSION_THREAD_ID,
    _SESSION_USER_ID,
    _SESSION_USER_NAME,
    _SESSION_KEY,
]


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------

def set_session_vars(
    platform: str = "",
    chat_id: str = "",
    chat_name: str = "",
    thread_id: str = "",
    user_id: str = "",
    user_name: str = "",
    session_key: str = "",
) -> List:
    """设置所有会话 ContextVar，返回 reset tokens 列表。

    在消息处理器的 finally 块中调用 ``clear_session_vars(tokens)``
    以恢复先前的值，确保上下文不会泄漏到其他会话。

    Returns
    -------
    list
        Token 对象列表（每个 ContextVar 对应一个），传给
        ``clear_session_vars()`` 使用。
    """
    return [
        _SESSION_PLATFORM.set(platform),
        _SESSION_CHAT_ID.set(chat_id),
        _SESSION_CHAT_NAME.set(chat_name),
        _SESSION_THREAD_ID.set(thread_id),
        _SESSION_USER_ID.set(user_id),
        _SESSION_USER_NAME.set(user_name),
        _SESSION_KEY.set(session_key),
    ]


def clear_session_vars(tokens: List) -> None:
    """将会话 ContextVar 恢复为处理器调用前的值。

    Parameters
    ----------
    tokens:
        ``set_session_vars()`` 返回的 token 列表。
    """
    if not tokens:
        return
    for var, token in zip(_VAR_ORDER, tokens):
        var.reset(token)


def get_session_env(name: str, default: str = "") -> str:
    """按名称读取会话 ContextVar（``os.getenv`` 的并发安全替代品）。

    解析优先级：
    1. ContextVar — Gateway 并发模式（最高优先级）
    2. os.environ — CLI / cron / 测试模式兼容
    3. default — 最终兜底

    Parameters
    ----------
    name:
        变量名，形如 ``"ORCHESTRATOR_SESSION_PLATFORM"``。
    default:
        若三级均未命中时返回的默认值。
    """
    var = _VAR_MAP.get(name)
    if var is not None:
        value = var.get()
        if value:
            return value
    return os.getenv(name, default)


def get_current_session() -> dict[str, str]:
    """返回当前 task 的完整会话上下文快照（用于调试/日志）。"""
    return {
        "platform":  _SESSION_PLATFORM.get(),
        "chat_id":   _SESSION_CHAT_ID.get(),
        "chat_name": _SESSION_CHAT_NAME.get(),
        "thread_id": _SESSION_THREAD_ID.get(),
        "user_id":   _SESSION_USER_ID.get(),
        "user_name": _SESSION_USER_NAME.get(),
        "session_key": _SESSION_KEY.get(),
    }
