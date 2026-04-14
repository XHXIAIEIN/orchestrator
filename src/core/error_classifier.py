"""API 错误分类器 — 结构化故障转移与恢复策略。

偷自 Hermes Agent v0.9 agent/error_classifier.py (R59)。

将散落在各处的 try/except 字符串匹配替换为集中的分类管线，
由 `ClassifiedError` 的 4 个恢复布尔值驱动后续策略：
  retryable / should_compress / should_rotate_credential / should_fallback

FailoverReason 枚举定义了 12 种失败原因，覆盖从鉴权到上下文溢出的全部情形。

用法示例：
    from src.core.error_classifier import classify_api_error, FailoverReason

    try:
        response = llm_call(...)
    except Exception as e:
        err = classify_api_error(e, provider="anthropic", model="claude-3-5-sonnet")
        if err.should_rotate_credential:
            rotate_key()
        elif err.should_compress:
            compress_context()
        elif err.retryable:
            retry_with_backoff()
        else:
            raise
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ── 错误分类枚举 ────────────────────────────────────────────────

class FailoverReason(enum.Enum):
    """API 调用失败原因 — 决定恢复策略。"""

    # 鉴权 / 授权
    auth = "auth"                        # 瞬态 auth (401/403) — 刷新/轮换
    auth_permanent = "auth_permanent"    # 刷新后仍失败 — 中止

    # 计费 / 配额
    billing = "billing"                  # 402 或确认的余额耗尽 — 立即轮换
    rate_limit = "rate_limit"            # 429 或配额节流 — 退避后轮换

    # 服务端
    overloaded = "overloaded"            # 503/529 — 服务商过载，退避
    server_error = "server_error"        # 500/502 — 内部错误，重试

    # 传输
    timeout = "timeout"                  # 连接/读取超时 — 重建客户端后重试

    # 上下文 / 载荷
    context_overflow = "context_overflow"   # 上下文过长 — 压缩，不换服务商
    payload_too_large = "payload_too_large" # 413 — 压缩载荷

    # 模型
    model_not_found = "model_not_found"  # 404 或无效模型 — 切换模型

    # 请求格式
    format_error = "format_error"        # 400 bad request — 中止或去除后重试

    # 服务商专有
    thinking_signature = "thinking_signature"  # Anthropic thinking block 签名无效
    long_context_tier = "long_context_tier"    # Anthropic "extra usage" tier 门控

    # 兜底
    unknown = "unknown"                  # 无法分类 — 退避后重试


# ── 分类结果 ─────────────────────────────────────────────────────

@dataclass
class ClassifiedError:
    """API 错误的结构化分类，附恢复动作提示。"""

    reason: FailoverReason
    status_code: Optional[int] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    message: str = ""
    error_context: Dict[str, Any] = field(default_factory=dict)

    # 恢复动作提示 — 调用方检查这些 bool 而非重新分类错误
    retryable: bool = True
    should_compress: bool = False
    should_rotate_credential: bool = False
    should_fallback: bool = False

    @property
    def is_auth(self) -> bool:
        return self.reason in (FailoverReason.auth, FailoverReason.auth_permanent)


# ── 服务商专有模式 ─────────────────────────────────────────────

# 确认计费耗尽的模式（非瞬态限流）
_BILLING_PATTERNS = [
    "insufficient credits",
    "insufficient_quota",
    "credit balance",
    "credits have been exhausted",
    "top up your credits",
    "payment required",
    "billing hard limit",
    "exceeded your current quota",
    "account is deactivated",
    "plan does not include",
]

# 限流模式（瞬态，会自动恢复）
_RATE_LIMIT_PATTERNS = [
    "rate limit",
    "rate_limit",
    "too many requests",
    "throttled",
    "requests per minute",
    "tokens per minute",
    "requests per day",
    "try again in",
    "please retry after",
    "resource_exhausted",
    "rate increased too quickly",
]

# 需要歧义消解的用量限制模式（可能是计费也可能是限流）
_USAGE_LIMIT_PATTERNS = [
    "usage limit",
    "quota",
    "limit exceeded",
    "key limit exceeded",
]

# 确认用量限制为瞬态的信号
_USAGE_LIMIT_TRANSIENT_SIGNALS = [
    "try again",
    "retry",
    "resets at",
    "reset in",
    "wait",
    "requests remaining",
    "periodic",
    "window",
]

# 载荷过大模式（从消息文本检测，无 status_code 属性时适用）
_PAYLOAD_TOO_LARGE_PATTERNS = [
    "request entity too large",
    "payload too large",
    "error code: 413",
]

# 上下文溢出模式
_CONTEXT_OVERFLOW_PATTERNS = [
    "context length",
    "context size",
    "maximum context",
    "token limit",
    "too many tokens",
    "reduce the length",
    "exceeds the limit",
    "context window",
    "prompt is too long",
    "prompt exceeds max length",
    "max_tokens",
    "maximum number of tokens",
    # vLLM / 本地推理服务器
    "exceeds the max_model_len",
    "max_model_len",
    "prompt length",
    "input is too long",
    "maximum model length",
    # Ollama
    "context length exceeded",
    "truncating input",
    # llama.cpp / llama-server
    "slot context",
    "n_ctx_slot",
    # 中文错误消息（部分服务商返回）
    "超过最大长度",
    "上下文长度",
]

# 模型未找到模式
_MODEL_NOT_FOUND_PATTERNS = [
    "is not a valid model",
    "invalid model",
    "model not found",
    "model_not_found",
    "does not exist",
    "no such model",
    "unknown model",
    "unsupported model",
]

# 鉴权模式（非状态码信号）
_AUTH_PATTERNS = [
    "invalid api key",
    "invalid_api_key",
    "authentication",
    "unauthorized",
    "forbidden",
    "invalid token",
    "token expired",
    "token revoked",
    "access denied",
]

# 传输错误类型名称
_TRANSPORT_ERROR_TYPES = frozenset({
    "ReadTimeout", "ConnectTimeout", "PoolTimeout",
    "ConnectError", "RemoteProtocolError",
    "ConnectionError", "ConnectionResetError",
    "ConnectionAbortedError", "BrokenPipeError",
    "TimeoutError", "ReadError",
    "ServerDisconnectedError",
    "APIConnectionError",
    "APITimeoutError",
})

# 服务器断连模式
_SERVER_DISCONNECT_PATTERNS = [
    "server disconnected",
    "peer closed connection",
    "connection reset by peer",
    "connection was closed",
    "network connection lost",
    "unexpected eof",
    "incomplete chunked read",
]


# ── 分类管线主入口 ──────────────────────────────────────────────

def classify_api_error(
    error: Exception,
    *,
    provider: str = "",
    model: str = "",
    approx_tokens: int = 0,
    context_length: int = 200000,
    num_messages: int = 0,
) -> ClassifiedError:
    """将 API 异常分类为结构化恢复建议。

    优先级管线：
      1. 服务商专有模式（thinking sig、tier gate）
      2. HTTP 状态码 + 消息感知细化
      3. 结构化错误码分类（来自响应体）
      4. 消息模式匹配（计费 vs 限流 vs 上下文 vs 鉴权）
      5. 传输错误启发式
      6. 服务器断连 + 大会话 → 上下文溢出
      7. 兜底：unknown（退避后重试）

    Args:
        error: API 调用抛出的异常。
        provider: 当前服务商名称（如 "openrouter"、"anthropic"）。
        model: 当前模型 slug。
        approx_tokens: 当前上下文的估算 token 数。
        context_length: 当前模型的最大上下文长度。
        num_messages: 消息历史条数（辅助判断大会话）。

    Returns:
        ClassifiedError，含失败原因和恢复动作提示。
    """
    status_code = _extract_status_code(error)
    error_type = type(error).__name__
    body = _extract_error_body(error)
    error_code = _extract_error_code(body)

    # 构建综合消息字符串用于模式匹配
    # str(error) 可能不包含响应体（如 OpenAI SDK 的 APIStatusError）
    # 同时提取 metadata.raw 以处理 OpenRouter 包装的上游服务商错误
    _raw_msg = str(error).lower()
    _body_msg = ""
    _metadata_msg = ""
    if isinstance(body, dict):
        _err_obj = body.get("error", {})
        if isinstance(_err_obj, dict):
            _body_msg = (_err_obj.get("message") or "").lower()
            _metadata = _err_obj.get("metadata", {})
            if isinstance(_metadata, dict):
                _raw_json = _metadata.get("raw") or ""
                if isinstance(_raw_json, str) and _raw_json.strip():
                    try:
                        import json
                        _inner = json.loads(_raw_json)
                        if isinstance(_inner, dict):
                            _inner_err = _inner.get("error", {})
                            if isinstance(_inner_err, dict):
                                _metadata_msg = (_inner_err.get("message") or "").lower()
                    except (json.JSONDecodeError, TypeError):
                        pass
        if not _body_msg:
            _body_msg = (body.get("message") or "").lower()

    parts = [_raw_msg]
    if _body_msg and _body_msg not in _raw_msg:
        parts.append(_body_msg)
    if _metadata_msg and _metadata_msg not in _raw_msg and _metadata_msg not in _body_msg:
        parts.append(_metadata_msg)
    error_msg = " ".join(parts)
    provider_lower = (provider or "").strip().lower()
    model_lower = (model or "").strip().lower()

    def _result(reason: FailoverReason, **overrides) -> ClassifiedError:
        defaults = {
            "reason": reason,
            "status_code": status_code,
            "provider": provider,
            "model": model,
            "message": _extract_message(error, body),
        }
        defaults.update(overrides)
        return ClassifiedError(**defaults)

    # ── 1. 服务商专有模式（最高优先级）────────────────────────

    # Anthropic thinking block 签名无效 (400)
    # 不限制 provider — OpenRouter 代理 Anthropic 错误时 provider 可能是 "openrouter"
    if (
        status_code == 400
        and "signature" in error_msg
        and "thinking" in error_msg
    ):
        return _result(
            FailoverReason.thinking_signature,
            retryable=True,
            should_compress=False,
        )

    # Anthropic 长上下文 tier 门控 (429 "extra usage" + "long context")
    if (
        status_code == 429
        and "extra usage" in error_msg
        and "long context" in error_msg
    ):
        return _result(
            FailoverReason.long_context_tier,
            retryable=True,
            should_compress=True,
        )

    # ── 2. HTTP 状态码分类 ─────────────────────────────────────

    if status_code is not None:
        classified = _classify_by_status(
            status_code, error_msg, error_code, body,
            provider=provider_lower, model=model_lower,
            approx_tokens=approx_tokens, context_length=context_length,
            num_messages=num_messages,
            result_fn=_result,
        )
        if classified is not None:
            return classified

    # ── 3. 错误码分类 ──────────────────────────────────────────

    if error_code:
        classified = _classify_by_error_code(error_code, error_msg, _result)
        if classified is not None:
            return classified

    # ── 4. 消息模式匹配（无状态码） ────────────────────────────

    classified = _classify_by_message(
        error_msg, error_type,
        approx_tokens=approx_tokens,
        context_length=context_length,
        result_fn=_result,
    )
    if classified is not None:
        return classified

    # ── 5. 服务器断连 + 大会话 → 上下文溢出 ──────────────────
    # 必须在通用传输错误捕获之前 — 大会话上的断连更可能是上下文溢出

    is_disconnect = any(p in error_msg for p in _SERVER_DISCONNECT_PATTERNS)
    if is_disconnect and not status_code:
        is_large = approx_tokens > context_length * 0.6 or approx_tokens > 120000 or num_messages > 200
        if is_large:
            return _result(
                FailoverReason.context_overflow,
                retryable=True,
                should_compress=True,
            )
        return _result(FailoverReason.timeout, retryable=True)

    # ── 6. 传输 / 超时启发式 ───────────────────────────────────

    if error_type in _TRANSPORT_ERROR_TYPES or isinstance(error, (TimeoutError, ConnectionError, OSError)):
        return _result(FailoverReason.timeout, retryable=True)

    # ── 7. 兜底：unknown ───────────────────────────────────────

    return _result(FailoverReason.unknown, retryable=True)


# ── 状态码分类 ──────────────────────────────────────────────────

def _classify_by_status(
    status_code: int,
    error_msg: str,
    error_code: str,
    body: dict,
    *,
    provider: str,
    model: str,
    approx_tokens: int,
    context_length: int,
    num_messages: int = 0,
    result_fn,
) -> Optional[ClassifiedError]:
    """基于 HTTP 状态码分类，并结合消息内容细化。"""

    if status_code == 401:
        return result_fn(
            FailoverReason.auth,
            retryable=False,
            should_rotate_credential=True,
            should_fallback=True,
        )

    if status_code == 403:
        # OpenRouter 403 "key limit exceeded" 实际上是计费问题
        if "key limit exceeded" in error_msg or "spending limit" in error_msg:
            return result_fn(
                FailoverReason.billing,
                retryable=False,
                should_rotate_credential=True,
                should_fallback=True,
            )
        return result_fn(
            FailoverReason.auth,
            retryable=False,
            should_fallback=True,
        )

    if status_code == 402:
        return _classify_402(error_msg, result_fn)

    if status_code == 404:
        return result_fn(
            FailoverReason.model_not_found,
            retryable=False,
            should_fallback=True,
        )

    if status_code == 413:
        return result_fn(
            FailoverReason.payload_too_large,
            retryable=True,
            should_compress=True,
        )

    if status_code == 429:
        # long_context_tier 已在第 1 步检查；这里是普通限流
        return result_fn(
            FailoverReason.rate_limit,
            retryable=True,
            should_rotate_credential=True,
            should_fallback=True,
        )

    if status_code == 400:
        return _classify_400(
            error_msg, error_code, body,
            provider=provider, model=model,
            approx_tokens=approx_tokens,
            context_length=context_length,
            num_messages=num_messages,
            result_fn=result_fn,
        )

    if status_code in (500, 502):
        return result_fn(FailoverReason.server_error, retryable=True)

    if status_code in (503, 529):
        return result_fn(FailoverReason.overloaded, retryable=True)

    # 其他 4xx — 不可重试
    if 400 <= status_code < 500:
        return result_fn(
            FailoverReason.format_error,
            retryable=False,
            should_fallback=True,
        )

    # 其他 5xx — 可重试
    if 500 <= status_code < 600:
        return result_fn(FailoverReason.server_error, retryable=True)

    return None


def _classify_402(error_msg: str, result_fn) -> ClassifiedError:
    """歧义消解 402：计费耗尽 vs 瞬态用量限制。

    关键洞察：部分 402 是伪装成付款错误的瞬态限流。
    "Usage limit, try again in 5 minutes" 不是计费问题 — 是周期性配额。
    """
    has_usage_limit = any(p in error_msg for p in _USAGE_LIMIT_PATTERNS)
    has_transient_signal = any(p in error_msg for p in _USAGE_LIMIT_TRANSIENT_SIGNALS)

    if has_usage_limit and has_transient_signal:
        # 瞬态配额 — 按限流处理，不是计费
        return result_fn(
            FailoverReason.rate_limit,
            retryable=True,
            should_rotate_credential=True,
            should_fallback=True,
        )

    # 确认计费耗尽
    return result_fn(
        FailoverReason.billing,
        retryable=False,
        should_rotate_credential=True,
        should_fallback=True,
    )


def _classify_400(
    error_msg: str,
    error_code: str,
    body: dict,
    *,
    provider: str,
    model: str,
    approx_tokens: int,
    context_length: int,
    num_messages: int = 0,
    result_fn,
) -> ClassifiedError:
    """分类 400 Bad Request：上下文溢出、格式错误或通用。"""

    # 上下文溢出
    if any(p in error_msg for p in _CONTEXT_OVERFLOW_PATTERNS):
        return result_fn(
            FailoverReason.context_overflow,
            retryable=True,
            should_compress=True,
        )

    # 部分服务商将模型未找到返回为 400（如 OpenRouter）
    if any(p in error_msg for p in _MODEL_NOT_FOUND_PATTERNS):
        return result_fn(
            FailoverReason.model_not_found,
            retryable=False,
            should_fallback=True,
        )

    # 部分服务商将限流/计费错误返回为 400
    if any(p in error_msg for p in _RATE_LIMIT_PATTERNS):
        return result_fn(
            FailoverReason.rate_limit,
            retryable=True,
            should_rotate_credential=True,
            should_fallback=True,
        )
    if any(p in error_msg for p in _BILLING_PATTERNS):
        return result_fn(
            FailoverReason.billing,
            retryable=False,
            should_rotate_credential=True,
            should_fallback=True,
        )

    # 通用 400 + 大会话 → 可能是上下文溢出
    # Anthropic 有时在上下文过大时返回裸 "Error" 消息
    err_body_msg = ""
    if isinstance(body, dict):
        err_obj = body.get("error", {})
        if isinstance(err_obj, dict):
            err_body_msg = (err_obj.get("message") or "").strip().lower()
        if not err_body_msg:
            err_body_msg = (body.get("message") or "").strip().lower()
    is_generic = len(err_body_msg) < 30 or err_body_msg in ("error", "")
    is_large = approx_tokens > context_length * 0.4 or approx_tokens > 80000 or num_messages > 80

    if is_generic and is_large:
        return result_fn(
            FailoverReason.context_overflow,
            retryable=True,
            should_compress=True,
        )

    # 不可重试的格式错误
    return result_fn(
        FailoverReason.format_error,
        retryable=False,
        should_fallback=True,
    )


# ── 错误码分类 ─────────────────────────────────────────────────

def _classify_by_error_code(
    error_code: str, error_msg: str, result_fn,
) -> Optional[ClassifiedError]:
    """基于响应体中的结构化错误码分类。"""
    code_lower = error_code.lower()

    if code_lower in ("resource_exhausted", "throttled", "rate_limit_exceeded"):
        return result_fn(
            FailoverReason.rate_limit,
            retryable=True,
            should_rotate_credential=True,
        )

    if code_lower in ("insufficient_quota", "billing_not_active", "payment_required"):
        return result_fn(
            FailoverReason.billing,
            retryable=False,
            should_rotate_credential=True,
            should_fallback=True,
        )

    if code_lower in ("model_not_found", "model_not_available", "invalid_model"):
        return result_fn(
            FailoverReason.model_not_found,
            retryable=False,
            should_fallback=True,
        )

    if code_lower in ("context_length_exceeded", "max_tokens_exceeded"):
        return result_fn(
            FailoverReason.context_overflow,
            retryable=True,
            should_compress=True,
        )

    return None


# ── 消息模式分类 ──────────────────────────────────────────────

def _classify_by_message(
    error_msg: str,
    error_type: str,
    *,
    approx_tokens: int,
    context_length: int,
    result_fn,
) -> Optional[ClassifiedError]:
    """基于错误消息模式分类（无状态码时适用）。"""

    # 载荷过大
    if any(p in error_msg for p in _PAYLOAD_TOO_LARGE_PATTERNS):
        return result_fn(
            FailoverReason.payload_too_large,
            retryable=True,
            should_compress=True,
        )

    # 用量限制需要同 402 一样的歧义消解
    has_usage_limit = any(p in error_msg for p in _USAGE_LIMIT_PATTERNS)
    if has_usage_limit:
        has_transient_signal = any(p in error_msg for p in _USAGE_LIMIT_TRANSIENT_SIGNALS)
        if has_transient_signal:
            return result_fn(
                FailoverReason.rate_limit,
                retryable=True,
                should_rotate_credential=True,
                should_fallback=True,
            )
        return result_fn(
            FailoverReason.billing,
            retryable=False,
            should_rotate_credential=True,
            should_fallback=True,
        )

    # 计费模式
    if any(p in error_msg for p in _BILLING_PATTERNS):
        return result_fn(
            FailoverReason.billing,
            retryable=False,
            should_rotate_credential=True,
            should_fallback=True,
        )

    # 限流模式
    if any(p in error_msg for p in _RATE_LIMIT_PATTERNS):
        return result_fn(
            FailoverReason.rate_limit,
            retryable=True,
            should_rotate_credential=True,
            should_fallback=True,
        )

    # 上下文溢出模式
    if any(p in error_msg for p in _CONTEXT_OVERFLOW_PATTERNS):
        return result_fn(
            FailoverReason.context_overflow,
            retryable=True,
            should_compress=True,
        )

    # 鉴权模式
    # 鉴权错误不应直接重试 — 相同密钥必然再次失败
    # retryable=False 确保调用方触发凭据轮换或服务商切换
    if any(p in error_msg for p in _AUTH_PATTERNS):
        return result_fn(
            FailoverReason.auth,
            retryable=False,
            should_rotate_credential=True,
            should_fallback=True,
        )

    # 模型未找到模式
    if any(p in error_msg for p in _MODEL_NOT_FOUND_PATTERNS):
        return result_fn(
            FailoverReason.model_not_found,
            retryable=False,
            should_fallback=True,
        )

    return None


# ── 辅助函数 ──────────────────────────────────────────────────

def _extract_status_code(error: Exception) -> Optional[int]:
    """遍历异常及其原因链，查找 HTTP 状态码。"""
    current = error
    for _ in range(5):  # 最大深度防止无限循环
        code = getattr(current, "status_code", None)
        if isinstance(code, int):
            return code
        # 部分 SDK 用 .status 而非 .status_code
        code = getattr(current, "status", None)
        if isinstance(code, int) and 100 <= code < 600:
            return code
        cause = getattr(current, "__cause__", None) or getattr(current, "__context__", None)
        if cause is None or cause is current:
            break
        current = cause
    return None


def _extract_error_body(error: Exception) -> dict:
    """从 SDK 异常中提取结构化错误体。"""
    body = getattr(error, "body", None)
    if isinstance(body, dict):
        return body
    response = getattr(error, "response", None)
    if response is not None:
        try:
            json_body = response.json()
            if isinstance(json_body, dict):
                return json_body
        except Exception:
            pass
    return {}


def _extract_error_code(body: dict) -> str:
    """从响应体中提取错误码字符串。"""
    if not body:
        return ""
    error_obj = body.get("error", {})
    if isinstance(error_obj, dict):
        code = error_obj.get("code") or error_obj.get("type") or ""
        if isinstance(code, str) and code.strip():
            return code.strip()
    code = body.get("code") or body.get("error_code") or ""
    if isinstance(code, (str, int)):
        return str(code).strip()
    return ""


def _extract_message(error: Exception, body: dict) -> str:
    """提取最具信息量的错误消息。"""
    if body:
        error_obj = body.get("error", {})
        if isinstance(error_obj, dict):
            msg = error_obj.get("message", "")
            if isinstance(msg, str) and msg.strip():
                return msg.strip()[:500]
        msg = body.get("message", "")
        if isinstance(msg, str) and msg.strip():
            return msg.strip()[:500]
    return str(error)[:500]
