"""MessageGenerator — turns a Signal into a human-readable notification string.

Routing logic
-------------
Tier A / D  →  _from_template()   (deterministic, fast, no LLM)
Tier B / C  →  _from_llm()        (LLM-generated, fallback to _fallback())
"""
from __future__ import annotations

import logging
from typing import Any

from src.proactive.signals import Signal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Template registry
# ---------------------------------------------------------------------------
TEMPLATES: dict[str, str] = {
    # Tier A — critical system alerts
    "S1":  "⚠️ **{collector}** 连续失败 {count} 次\n最后错误：`{error}`",
    "S2":  "🔴 容器 **{name}** 状态异常：{status}",
    "S3":  "📦 events.db 已达 **{size_mb}MB**（日增 {delta_mb}MB）",
    "S4":  "❌ Governor 连续 **{count}** 个任务失败\n最近：{last_summary}",
    # Tier D — digest / low-priority informational
    "S11": "⭐ **{repo}** — {event_type}: {title}",
    "S12": "🛡️ **{package}** 发现 {severity} 漏洞：{cve_id}",
}

# Tiers that use deterministic templates (no LLM)
_TEMPLATE_TIERS = {"A", "D"}


class MessageGenerator:
    """Generate notification messages from signals.

    Parameters
    ----------
    llm_router:
        Object with a ``generate(prompt, task_type, max_tokens, temperature)``
        method. Pass ``None`` for template-only mode (Tier B/C will fall back
        to plain text).
    """

    def __init__(self, llm_router: Any | None) -> None:
        self._router = llm_router

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, signal: Signal) -> str:
        """Route signal to the appropriate generation strategy."""
        if signal.tier in _TEMPLATE_TIERS:
            return self._from_template(signal)
        return self._from_llm(signal)

    # ------------------------------------------------------------------
    # Private strategies
    # ------------------------------------------------------------------

    def _from_template(self, signal: Signal) -> str:
        """Render a Tier-A / Tier-D signal using its template.

        Falls back to ``_fallback()`` when:
        - The signal id has no registered template.
        - The template is missing required keys (KeyError).
        """
        template = TEMPLATES.get(signal.id)
        if template is None:
            logger.warning("No template for signal id=%s, using fallback", signal.id)
            return self._fallback(signal)
        try:
            return template.format(**signal.data)
        except KeyError as exc:
            logger.warning(
                "Template for %s missing key %s, using fallback", signal.id, exc
            )
            return self._fallback(signal)

    def _from_llm(self, signal: Signal) -> str:
        """Generate a Tier-B / Tier-C message via the LLM router.

        Falls back to ``_fallback()`` on any failure or when the router is
        unavailable.
        """
        if self._router is None:
            logger.debug("LLM router not set; using fallback for signal %s", signal.id)
            return self._fallback(signal)

        system = (
            "你是 Orchestrator，一个有性格的 AI 管家。"
            "用简洁中文写一条通知消息，不超过 200 字，语气直接，包含数据。"
        )
        user = (
            f"信号标题：{signal.title}\n"
            f"严重程度：{signal.severity}\n"
            f"数据：{signal.data}"
        )
        prompt = f"{system}\n\n{user}"

        try:
            result = self._router.generate(
                prompt=prompt,
                task_type="chat",
                max_tokens=256,
                temperature=0.6,
            )
            return result
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "LLM generation failed for signal %s (%s); using fallback",
                signal.id,
                exc,
            )
            return self._fallback(signal)

    def _fallback(self, signal: Signal) -> str:
        """Plain-text fallback — always safe, never raises."""
        parts = [f"[{signal.tier}] {signal.title}"]
        if signal.data:
            data_str = ", ".join(f"{k}={v}" for k, v in signal.data.items())
            parts.append(data_str)
        return "\n".join(parts)
