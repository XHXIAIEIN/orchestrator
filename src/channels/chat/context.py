"""Chat context building — conversation history + memory assembly."""
import logging

from src.channels import config as ch_cfg
from src.channels.chat.db import load_memory, load_recent, count_messages, save_memory, load_all_messages, prune_old_messages

log = logging.getLogger(__name__)


def build_context(db_path: str, chat_id: str) -> list[dict]:
    """构建对话上下文：摘要记忆 + 最近消息。"""
    messages = []
    memory = load_memory(db_path, chat_id)
    if memory:
        messages.append({
            "role": "user",
            "content": f"[系统：以下是之前对话的摘要记忆，帮你回忆上下文]\n{memory}",
        })
        messages.append({
            "role": "assistant",
            "content": "明白，我记得这些。继续。",
        })
    recent = load_recent(db_path, chat_id, ch_cfg.RECENT_TURNS)
    # Filter out messages with empty content (Claude API rejects them)
    # For recent messages with media_paths, inline images as multimodal content
    import base64 as b64mod
    media_msg_count = 0
    MAX_INLINE_MEDIA_MSGS = 3  # only inline images from last N media messages

    # Count media messages from the end to decide which ones to inline
    media_indices = set()
    for i in range(len(recent) - 1, -1, -1):
        if recent[i].get("media_paths") and recent[i]["role"] == "user":
            media_msg_count += 1
            if media_msg_count <= MAX_INLINE_MEDIA_MSGS:
                media_indices.add(i)

    for i, m in enumerate(recent):
        if not m.get("content"):
            continue
        paths = m.pop("media_paths", None)
        if paths and i in media_indices and m["role"] == "user":
            # Build multimodal content with inlined images
            from src.channels.media import is_image_file, detect_image_mime
            content_parts = []
            for p in paths:
                try:
                    from pathlib import Path
                    pp = Path(p)
                    if pp.exists() and pp.stat().st_size < 5 * 1024 * 1024:  # <5MB
                        if is_image_file(p):
                            b64 = b64mod.b64encode(pp.read_bytes()).decode()
                            # Detect MIME from magic bytes first, fall back to extension
                            mime = detect_image_mime(p)
                            if not mime:
                                suffix = pp.suffix.lower()
                                mime = "image/jpeg"
                                if suffix == ".png": mime = "image/png"
                                elif suffix == ".webp": mime = "image/webp"
                                elif suffix == ".gif": mime = "image/gif"
                            content_parts.append({
                                "type": "image",
                                "source": {"type": "base64", "media_type": mime, "data": b64},
                            })
                except Exception:
                    pass
            content_parts.append({"type": "text", "text": m["content"]})
            messages.append({"role": m["role"], "content": content_parts})
        else:
            # Older media messages: just text with path references
            if paths:
                m["content"] += f"\n[附带 {len(paths)} 个媒体文件]"
            messages.append(m)

    # ── Token budget guard: prevent 200K+ prompts ──
    MAX_CONTEXT_CHARS = 400_000  # ~100K tokens, safe under 200K with system prompt
    total = sum(_msg_chars(m) for m in messages)
    while total > MAX_CONTEXT_CHARS and len(messages) > 2:
        removed = messages.pop(0)  # drop oldest message
        total -= _msg_chars(removed)

    return messages


def _msg_chars(msg: dict) -> int:
    """Estimate character count of a message (including base64 images)."""
    content = msg.get("content", "")
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        total = 0
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text":
                    total += len(part.get("text", ""))
                elif part.get("type") == "image":
                    total += len(part.get("source", {}).get("data", ""))
            elif isinstance(part, str):
                total += len(part)
        return total
    return 0


def maybe_summarize(db_path: str, chat_id: str, client):
    """消息数超过阈值时，压缩旧消息为摘要记忆。"""
    total = count_messages(db_path, chat_id)
    if total <= ch_cfg.SUMMARIZE_THRESHOLD:
        return

    rows = load_all_messages(db_path, chat_id)

    old_messages = rows[:-ch_cfg.RECENT_TURNS]
    if len(old_messages) < ch_cfg.SUMMARIZE_MIN_MESSAGES:
        return

    existing_memory = load_memory(db_path, chat_id)
    conversation_text = "\n".join(
        f"[{r[0]}] {r[1][:200]}" for r in old_messages
    )

    compress_prompt = (
        "你是 Orchestrator 的记忆管理器。把以下对话历史压缩成简洁的摘要记忆，"
        "保留关键信息：主人的偏好、做过的决定、提到的项目/问题、重要上下文。"
        f"丢弃闲聊和重复内容。用中文，不超过 {ch_cfg.SUMMARIZE_MAX_CHARS} 字。\n\n"
    )
    if existing_memory:
        compress_prompt += f"现有记忆：\n{existing_memory}\n\n请将以下新对话合并进现有记忆：\n\n"
    compress_prompt += conversation_text

    try:
        response = client.messages.create(
            model=ch_cfg.CHAT_MODEL,
            max_tokens=ch_cfg.SUMMARIZE_MAX_TOKENS,
            messages=[{"role": "user", "content": compress_prompt}],
        )
        new_memory = next(
            (b.text for b in response.content if b.type == "text"), ""
        ).strip()

        if new_memory:
            save_memory(db_path, chat_id, new_memory)
            prune_old_messages(db_path, chat_id, ch_cfg.RECENT_TURNS)
            log.info(f"chat: summarized {len(old_messages)} messages for {chat_id}")

    except Exception as e:
        log.warning(f"chat: summarize failed: {e}")
