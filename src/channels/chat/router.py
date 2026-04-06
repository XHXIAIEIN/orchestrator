"""Intent classification and local model routing."""
import logging

log = logging.getLogger(__name__)

# ── Intent 分类 — 偷师 kevinzhj/model-router-hook 的信号检测 ──────────────────

_TOOL_SIGNALS = {
    # 系统查询 → query_status
    "查状态", "看状态", "系统状态", "health", "collectors", "采集器",
    # 主机操作 → wake_claude (multi-char phrases to avoid false positives)
    "打开", "运行一下", "执行一下", "跑一下", "帮我改", "帮我修", "帮我写",
    "改代码", "写代码", "改文件", "写文件", "修一下", "修复",
    "呼叫外援", "wake claude", "叫claude",
    "唤醒", "wake remote", "远程唤醒", "启动claude", "wake up",
    "部署", "deploy", "重启", "restart", "git push", "git commit",
    # 派单 → dispatch_task
    "跑场景", "run scenario", "审计一下", "扫描一下",
    # 读文件 → read_file
    "读文件", "看文件", "看日志", "读日志", "cat ",
}

_REASON_SIGNALS = {
    # 需要深度推理的信号 (2+ char phrases to avoid false positives)
    "为什么", "什么原因", "分析一下", "帮我分析",
    "对比一下", "比较一下", "有什么区别",
    "优缺点", "怎么选", "帮我推荐", "你建议", "你觉得该",
    "帮我评估", "解释一下", "什么原理", "什么逻辑",
    "帮我规划", "怎么设计", "架构",
    "帮我debug", "调试一下", "排查一下", "帮我诊断", "root cause",
    "总结一下", "帮我归纳",
}

# 会话惯性：记录每个用户最近的路由决策
_session_intent: dict[str, list[str]] = {}  # chat_id → [last N intents]
_SESSION_INERTIA_WINDOW = 3  # 看最近 N 轮


def _classify_intent(text: str, has_images: bool = False,
                     chat_id: str = "") -> str:
    """
    Classify user intent → routing strategy.

    Returns:
        "tools"   — needs Claude API with tool use
        "vision"  — has images, route to gemma4:26b
        "reason"  — needs deep reasoning, route to deepseek-r1
        "chat"    — casual chat, route to qwen3.5:9b
    """
    t = text.lower()

    # Commands always need tools
    if t.startswith("/"):
        return "tools"

    # Tool signals → Claude API
    if any(s in t for s in _TOOL_SIGNALS):
        return "tools"

    # Images → vision model
    if has_images:
        return "vision"

    # Reasoning signals → deepseek-r1
    if any(s in t for s in _REASON_SIGNALS):
        _record_intent(chat_id, "reason")
        return "reason"

    # Long text (>200 chars) likely needs deeper processing
    if len(text) > 200:
        _record_intent(chat_id, "reason")
        return "reason"

    # Session inertia: if recent turns were reasoning, stay on reasoning model
    if chat_id and _get_session_momentum(chat_id) == "reason":
        _record_intent(chat_id, "reason")
        return "reason"

    _record_intent(chat_id, "chat")
    return "chat"


def _record_intent(chat_id: str, intent: str):
    """Record intent for session inertia tracking."""
    if not chat_id:
        return
    if chat_id not in _session_intent:
        _session_intent[chat_id] = []
    _session_intent[chat_id].append(intent)
    # Keep only last N
    _session_intent[chat_id] = _session_intent[chat_id][-_SESSION_INERTIA_WINDOW:]


def _get_session_momentum(chat_id: str) -> str:
    """Check if recent turns have a consistent intent pattern."""
    history = _session_intent.get(chat_id, [])
    if len(history) < 2:
        return ""
    # If last 2 turns were both "reason", maintain momentum
    if all(h == "reason" for h in history[-2:]):
        return "reason"
    return ""


# ── 本地模型对话 ─────────────────────────────────────────────────────────────

def _chat_local(system_prompt: str, messages: list[dict], text: str) -> str:
    """Call Ollama local model for casual chat. Returns empty string on failure."""
    try:
        from src.core.llm_router import get_router
        router = get_router()
        if not router._ollama_available:
            return ""

        # Build a single prompt from recent context
        recent = messages[-6:]  # last 3 turns
        parts = []
        for m in recent:
            role = m["role"]
            content = m["content"] if isinstance(m["content"], str) else str(m["content"])
            parts.append(f"{role}: {content}")

        prompt = f"{system_prompt}\n\n{''.join(chr(10) + p for p in parts)}\nassistant:"

        result = router.generate(prompt, task_type="chat")
        if result and len(result.strip()) >= 5:
            # Strip thinking tags and XML artifacts from local model output
            import re as _re
            clean = _re.sub(r'<think>.*?</think>', '', result, flags=_re.DOTALL).strip()
            clean = _re.sub(r'<[^>]+>.*?</[^>]+>', '', clean, flags=_re.DOTALL).strip()
            return clean if len(clean) >= 5 else ""
    except Exception as e:
        log.debug(f"chat: local model failed: {e}")
    return ""


def _chat_local_reason(system_prompt: str, messages: list[dict], text: str) -> str:
    """Call deepseek-r1 for reasoning-heavy chat. Returns empty string on failure."""
    try:
        from src.core.llm_router import get_router
        router = get_router()
        if not router._ollama_available:
            return ""

        recent = messages[-6:]
        parts = []
        for m in recent:
            role = m["role"]
            content = m["content"] if isinstance(m["content"], str) else str(m["content"])
            parts.append(f"{role}: {content}")

        prompt = f"{system_prompt}\n\n{''.join(chr(10) + p for p in parts)}\nassistant:"

        result = router.generate(prompt, task_type="chat_reason")
        if result and len(result.strip()) >= 5:
            import re as _re
            # deepseek-r1 outputs <think>...</think> blocks — strip them
            clean = _re.sub(r'<think>.*?</think>', '', result, flags=_re.DOTALL).strip()
            clean = _re.sub(r'<[^>]+>.*?</[^>]+>', '', clean, flags=_re.DOTALL).strip()
            return clean if len(clean) >= 5 else ""
    except Exception as e:
        log.debug(f"chat: local reason failed: {e}")
    return ""


def _chat_local_vision(system_prompt: str, messages: list[dict],
                       text: str, image_paths: list[str]) -> str:
    """Call vision model for image understanding. Ollama preferred, Claude Haiku fallback."""
    try:
        from src.core.llm_router import get_router
        router = get_router()

        prompt = f"{system_prompt}\n\nuser: {text or '请描述这些图片'}\nassistant:"
        result = router.generate(prompt, task_type="vision", images=image_paths)
        if result and len(result.strip()) >= 5:
            import re as _re
            clean = _re.sub(r'<think>.*?</think>', '', result, flags=_re.DOTALL).strip()
            clean = _re.sub(r'<[^>]+>.*?</[^>]+>', '', clean, flags=_re.DOTALL).strip()
            return clean if len(clean) >= 5 else ""
    except Exception as e:
        log.debug(f"chat: local vision failed: {e}")
    return ""
