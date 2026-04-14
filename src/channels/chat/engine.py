"""Chat main loop — system prompt building, do_chat(), save_to_inbox()."""
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path

from src.channels import config as ch_cfg
from src.channels.chat.db import save_message
from src.channels.chat.context import build_context, maybe_summarize
from src.channels.chat.tools import CHAT_TOOLS, execute_tool
from src.channels.chat.router import _classify_intent, _chat_local, _chat_local_reason, _chat_local_vision

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent
while _REPO_ROOT != _REPO_ROOT.parent and not ((_REPO_ROOT / "departments").is_dir() and (_REPO_ROOT / "src").is_dir()):
    _REPO_ROOT = _REPO_ROOT.parent

# ── 系统提示词构建 ────────────────────────────────────────────────────────────

_CHAT_PROMPT_CACHE: str | None = None


def _load_chat_prompt() -> str:
    """Load chat system prompt from SOUL/public/prompts/chat.md (cached)."""
    global _CHAT_PROMPT_CACHE
    if _CHAT_PROMPT_CACHE is not None:
        return _CHAT_PROMPT_CACHE
    prompt_path = _REPO_ROOT / "SOUL" / "public" / "prompts" / "chat.md"
    if prompt_path.exists():
        _CHAT_PROMPT_CACHE = prompt_path.read_text(encoding="utf-8")
    else:
        log.warning("chat: SOUL/public/prompts/chat.md not found, using fallback")
        _CHAT_PROMPT_CACHE = "You are Orchestrator. Reply in Chinese. Be concise."
    return _CHAT_PROMPT_CACHE


def build_system_prompt(platform_rules: str) -> str:
    """构建系统提示词：从文件加载基础 prompt + 平台规则 + voice samples。"""
    prompt = _load_chat_prompt() + "\n\n"

    # Voice samples
    voice_path = _REPO_ROOT / "SOUL" / "private" / "voice.md"
    if voice_path.exists():
        try:
            voice_text = voice_path.read_text(encoding="utf-8")
            samples = [line for line in voice_text.split("\n") if line.startswith(">")][:3]
            if samples:
                prompt += "# Voice examples\n" + "\n".join(samples) + "\n\n"
        except Exception:
            pass

    prompt += platform_rules
    return prompt


# ── 对话主循环 ────────────────────────────────────────────────────────────────

def do_chat(chat_id: str, text: str, original_text: str,
            system_prompt: str, reply_fn, channel_source: str = "channel",
            permission_check_fn=None, media: list = None,
            react_fn=None, on_chunk=None, cancelled_fn=None):
    """对话主循环 — 闲聊走本地模型，需要工具时走 Claude API。

    Args:
        chat_id: 用户标识（Telegram chat_id / WeChat user_id）
        text: 给 LLM 看的内容
        original_text: 存 DB 的原文（长消息时与 text 不同）
        system_prompt: 系统提示词
        reply_fn: 回复函数 reply_fn(chat_id, text)
        channel_source: 来源标识（"telegram" / "wechat"）
        permission_check_fn: 权限检查 fn(chat_id, tool_name) -> bool，None=全放行
        react_fn: 表情回应函数 react_fn(emoji)，None=不支持
        on_chunk: R49 BlockStreamer callback — on_chunk(text_delta) for progressive delivery
        cancelled_fn: R49 steer mode — returns True if task was cancelled
    """
    try:
        # ── Multi-agent broadcast: @cc @cx message ──
        from src.channels.chat.broadcast import parse_broadcast
        broadcast = parse_broadcast(text)
        if broadcast:
            _handle_broadcast(chat_id, text, broadcast, system_prompt, reply_fn, channel_source)
            return

        from src.storage.events_db import _DEFAULT_DB

        db_path = _DEFAULT_DB
        db_content = original_text if original_text else text
        # Collect media paths + extracted document text for DB/context
        _media_paths = []
        _doc_texts = []  # (filename, text) pairs from markitdown extraction
        if media:
            from src.channels.media import MediaType
            for att in media:
                if att.local_path:
                    _media_paths.append(att.local_path)
                # Collect extracted document text (set by handler via markitdown)
                if att.media_type == MediaType.FILE and att.text:
                    _doc_texts.append((att.file_name or "document", att.text))
            if not db_content:
                n_img = sum(1 for a in media if a.media_type == MediaType.IMAGE)
                n_other = len(media) - n_img
                parts = []
                if n_img: parts.append(f"{n_img} 张图片")
                if n_other: parts.append(f"{n_other} 个媒体文件")
                db_content = f"[用户发送了 {'、'.join(parts)}]"
        save_message(db_path, chat_id, "user", db_content or "[空消息]",
                     chat_client=channel_source, media_paths=_media_paths or None)

        messages = build_context(db_path, chat_id)

        # ── Inject extracted document text into context ──
        if _doc_texts:
            doc_parts = []
            for fname, dtxt in _doc_texts:
                doc_parts.append(f"📄 {fname}:\n```\n{dtxt[:100000]}\n```")
            doc_content = "\n\n".join(doc_parts)
            # Append to last user message so Claude sees the document content
            if messages and messages[-1]["role"] == "user":
                last = messages[-1]
                if isinstance(last["content"], str):
                    last["content"] += "\n\n" + doc_content
                elif isinstance(last["content"], list):
                    last["content"].append({"type": "text", "text": doc_content})
            else:
                messages.append({"role": "user", "content": doc_content})

        # ── Intent classification → model routing ──
        from src.channels.media import is_image_file
        has_images = bool(_media_paths and any(
            is_image_file(p) for p in _media_paths
        ))
        intent = _classify_intent(text, has_images, chat_id)
        log.info(f"chat: intent={intent} for {chat_id[:16]}")

        # Local model routing (chat / vision / reason)
        if ch_cfg.CHAT_LOCAL_ENABLED and intent != "tools":
            local_reply = ""
            if intent == "vision":
                local_reply = _chat_local_vision(system_prompt, messages, text, _media_paths)
            elif intent == "reason":
                local_reply = _chat_local_reason(system_prompt, messages, text)
            else:  # "chat"
                local_reply = _chat_local(system_prompt, messages, text)

            if local_reply:
                log.info(f"chat: local [{intent}] reply ({len(local_reply)} chars) to {chat_id[:16]}")
                try:
                    reply_fn(chat_id, local_reply)
                except Exception as re:
                    log.error(f"chat: reply_fn failed: {re}")
                save_message(db_path, chat_id, "assistant", local_reply, chat_client=channel_source)
                return

        # ── Fall through to Claude API with tool use ──
        from src.core.config import get_anthropic_client
        client = get_anthropic_client()

        max_rounds = ch_cfg.TOOL_USE_MAX_ROUNDS
        final_reply = ""
        # R49: streaming enabled when on_chunk callback is provided
        use_streaming = on_chunk is not None

        for round_idx in range(max_rounds):
            # R49 steer mode: check cancellation before each round
            if cancelled_fn and cancelled_fn():
                log.info(f"chat: cancelled (steer mode) for {chat_id[:16]}")
                return

            # Tool-use rounds are always non-streaming (need full response to execute tools).
            # Final round (no tool_calls) uses streaming when on_chunk is set.
            # Strategy: try non-streaming first; if no tool_calls AND streaming enabled,
            # redo as streaming for progressive delivery.
            # R52 (VoxCPM): Prompt cache separation — system prompt is static per
            # session, mark it with cache_control so Anthropic caches the prefix.
            # Subsequent tool-use rounds in the same conversation reuse the cache
            # (~90% cost savings on the system prompt portion).
            response = client.messages.create(
                model=ch_cfg.CHAT_MODEL,
                max_tokens=ch_cfg.CHAT_MAX_TOKENS,
                system=[{
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=messages,
                tools=CHAT_TOOLS,
            )

            text_parts = []
            tool_calls = []
            for block in response.content:
                if block.type == "text" and block.text.strip():
                    text_parts.append(block.text.strip())
                elif block.type == "tool_use":
                    tool_calls.append(block)

            if text_parts:
                final_reply = "\n".join(text_parts)
                # Strip hallucinated tool call XML that leaks into text blocks
                import re as _re
                final_reply = _re.sub(
                    r'<(?:function_calls|tool_call|invoke)[^>]*>.*?</(?:function_calls|tool_call|invoke)>',
                    '', final_reply, flags=_re.DOTALL).strip()
                final_reply = _re.sub(
                    r'<(?:function_calls|tool_call|invoke)[^>]*>.*',
                    '', final_reply, flags=_re.DOTALL).strip()

            if not tool_calls:
                # R49: If streaming and we got a final reply, feed it through on_chunk
                # for BlockStreamer progressive delivery. The non-streaming response
                # is already complete, but we simulate chunking for the streamer.
                # Future optimization: use stream=True on the last round.
                if use_streaming and final_reply:
                    _feed_reply_to_streamer(final_reply, on_chunk)
                break

            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for tc in tool_calls:
                # 权限检查
                if permission_check_fn and not permission_check_fn(chat_id, tc.name):
                    result = f"Permission denied: cannot use {tc.name}"
                else:
                    result = execute_tool(
                        tc.name, tc.input, chat_id,
                        reply_fn=reply_fn, channel_source=channel_source,
                        react_fn=react_fn,
                    )
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": result,
                })
            messages.append({"role": "user", "content": tool_results})

        if final_reply:
            if not use_streaming:
                # Non-streaming path: send full reply at once (original behavior)
                log.info(f"chat: sending reply ({len(final_reply)} chars) to {chat_id[:16]}...")
                try:
                    reply_fn(chat_id, final_reply)
                    log.info(f"chat: reply sent successfully")
                except Exception as re:
                    log.error(f"chat: reply_fn failed: {re}", exc_info=True)
            else:
                # Streaming path: BlockStreamer handles delivery via on_chunk,
                # caller is responsible for flush. Just log.
                log.info(f"chat: streamed reply ({len(final_reply)} chars) to {chat_id[:16]}")
            save_message(db_path, chat_id, "assistant", final_reply, chat_client=channel_source)
        else:
            log.warning(f"chat: no final_reply for {chat_id[:16]}...")

        maybe_summarize(db_path, chat_id, client)

    except Exception as e:
        log.error(f"chat: {channel_source} chat failed for {chat_id}: {e}", exc_info=True)
        try:
            reply_fn(chat_id, f"出了点问题: {e}")
        except Exception:
            pass


# ── R49: Streaming helper ────────────────────────────────────────────────────

def _feed_reply_to_streamer(text: str, on_chunk, chunk_size: int = 80):
    """Feed a complete reply through on_chunk in simulated chunks.

    Since Claude API tool-use rounds are non-streaming, we simulate chunking
    for BlockStreamer by splitting at paragraph boundaries. This gives a
    progressive delivery feel even without true streaming.

    Future: use stream=True on the final (no-tool) round for real streaming.
    """
    # Split at paragraph boundaries for natural chunking
    paragraphs = text.split("\n\n")
    for i, para in enumerate(paragraphs):
        if i > 0:
            on_chunk("\n\n")
        # For long paragraphs, further split into smaller chunks
        if len(para) > chunk_size * 3:
            for j in range(0, len(para), chunk_size):
                on_chunk(para[j:j + chunk_size])
        else:
            on_chunk(para)


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def save_to_inbox(text: str) -> tuple[str, int]:
    """长消息存到本地文件，返回 (容器内路径, 字符数)。"""
    inbox_dir = _REPO_ROOT / "tmp" / "chat-inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    short_hash = hashlib.md5(text.encode()).hexdigest()[:6]
    filename = f"{ts}-{short_hash}.txt"
    (inbox_dir / filename).write_text(text, encoding="utf-8")

    return f"/orchestrator/tmp/chat-inbox/{filename}", len(text)


def _handle_broadcast(
    chat_id: str,
    original_text: str,
    broadcast: tuple[list[str], str],
    system_prompt: str,
    reply_fn,
    channel_source: str,
):
    """Handle multi-agent broadcast: @cc @cx message.

    Stolen from WeClaw broadcastToAgents() (R45d):
    parallel dispatch, first-come-first-served, labeled responses.
    """
    import asyncio
    from src.channels.chat.broadcast import broadcast_to_agents, format_broadcast_responses
    from src.channels.chat.db import save_message
    from src.storage.events_db import _DEFAULT_DB

    agent_names, message = broadcast
    db_path = _DEFAULT_DB

    save_message(db_path, chat_id, "user", original_text, chat_client=channel_source)

    log.info("chat: broadcast to %s from %s", agent_names, chat_id[:16])

    async def _run():
        return await broadcast_to_agents(
            user_id=chat_id,
            agent_names=agent_names,
            message=message,
            system_prompt=system_prompt,
        )

    try:
        responses = asyncio.run(_run())
    except RuntimeError:
        # Already in an event loop — use nest_asyncio or thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            responses = pool.submit(lambda: asyncio.run(_run())).result()

    formatted = format_broadcast_responses(responses)
    reply_fn(chat_id, formatted)
    save_message(db_path, chat_id, "assistant", formatted, chat_client=channel_source)
