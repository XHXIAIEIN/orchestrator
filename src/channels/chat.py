"""
Channel 对话公共层 — Claude API 对话、DB 持久化、摘要记忆、工具执行。

Telegram 和 WeChat 共享这套逻辑，各自只实现传输层。
使用方式：Channel 子类继承 ChatMixin，实现 _reply_text() 和 _platform_rules()。
"""
import hashlib
import json
import logging
import sqlite3
import threading
from abc import abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.channels import config as ch_cfg

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# ── Tool 定义 ────────────────────────────────────────────────────────────────

CHAT_TOOLS = [
    {
        "name": "dispatch_task",
        "description": (
            "Send a task to Governor for execution. Predefined scenarios "
            "(full_audit, system_health, deep_scan) or free-form tasks. "
            "Results auto-push back to the channel."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "Task description or scenario name"},
                "department": {"type": "string", "description": "Target department. Empty = auto-route.", "default": ""},
                "priority": {"type": "string", "enum": ["low", "medium", "high"], "default": "medium"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "query_status",
        "description": "Query system status: health checks, recent tasks, collector stats, or channel status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query_type": {"type": "string", "enum": ["health", "tasks", "collectors", "channels"]},
            },
            "required": ["query_type"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a local file. Paths start with /orchestrator/. Also reads long user messages saved to tmp/chat-inbox/.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute file path"},
                "max_chars": {"type": "integer", "description": "Max chars to read", "default": 8000},
            },
            "required": ["path"],
        },
    },
    {
        "name": "wake_claude",
        "description": (
            "Wake up Claude Code on the host machine. Use for ANYTHING that "
            "needs the local computer: open apps (QQ Music, browsers, etc.), "
            "write/modify code, run shell commands, git operations, complex "
            "debugging, file management. Claude Code has full access to the host."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "What Claude Code should do"},
                "context": {"type": "string", "description": "Relevant context from our conversation", "default": ""},
            },
            "required": ["task"],
        },
    },
]


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


# ── DB 持久化 ─────────────────────────────────────────────────────────────────

def db_conn(db_path: str) -> sqlite3.Connection:
    """Connect with WAL mode if possible."""
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        pass
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _ensure_chat_client_column(conn: sqlite3.Connection):
    """确保 chat_messages 表有 chat_client 字段（兼容旧表）。"""
    try:
        conn.execute("SELECT chat_client FROM chat_messages LIMIT 0")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE chat_messages ADD COLUMN chat_client TEXT DEFAULT ''")
        conn.commit()


def _ensure_media_paths_column(conn: sqlite3.Connection):
    """确保 chat_messages 表有 media_paths 字段（JSON 数组）。"""
    try:
        conn.execute("SELECT media_paths FROM chat_messages LIMIT 0")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE chat_messages ADD COLUMN media_paths TEXT DEFAULT ''")
        conn.commit()


def save_message(db_path: str, chat_id: str, role: str, content: str,
                 chat_client: str = "", media_paths: list[str] | None = None):
    """存一条消息。含硬上限保护。media_paths: 关联的媒体文件路径列表。"""
    conn = db_conn(db_path)
    _ensure_chat_client_column(conn)
    _ensure_media_paths_column(conn)
    count = conn.execute(
        "SELECT COUNT(*) FROM chat_messages WHERE chat_id = ?", (chat_id,)
    ).fetchone()[0]
    if count >= ch_cfg.MAX_DB_MESSAGES:
        excess = count - ch_cfg.MAX_DB_MESSAGES + ch_cfg.DB_PRUNE_EXTRA
        conn.execute(
            "DELETE FROM chat_messages WHERE id IN "
            "(SELECT id FROM chat_messages WHERE chat_id = ? ORDER BY id ASC LIMIT ?)",
            (chat_id, excess),
        )
    media_json = json.dumps(media_paths) if media_paths else ""
    conn.execute(
        "INSERT INTO chat_messages (chat_id, role, content, created_at, chat_client, media_paths) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (chat_id, role, content, datetime.now(timezone.utc).isoformat(), chat_client, media_json),
    )
    conn.commit()
    conn.close()


def load_recent(db_path: str, chat_id: str, limit: int = 20) -> list[dict]:
    """从 DB 加载最近 N 轮对话。包含 media_paths（如果有）。"""
    conn = db_conn(db_path)
    _ensure_media_paths_column(conn)
    rows = conn.execute(
        "SELECT role, content, media_paths FROM chat_messages "
        "WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
        (chat_id, limit),
    ).fetchall()
    conn.close()
    results = []
    for r in reversed(rows):
        msg = {"role": r[0], "content": r[1]}
        if r[2]:
            try:
                msg["media_paths"] = json.loads(r[2])
            except (json.JSONDecodeError, TypeError):
                pass
        results.append(msg)
    return results


def load_memory(db_path: str, chat_id: str) -> str:
    """加载摘要记忆。"""
    conn = db_conn(db_path)
    row = conn.execute(
        "SELECT summary FROM chat_memory WHERE chat_id = ?", (chat_id,)
    ).fetchone()
    conn.close()
    return row[0] if row else ""


def save_memory(db_path: str, chat_id: str, summary: str):
    """保存摘要记忆。"""
    conn = db_conn(db_path)
    conn.execute(
        "INSERT INTO chat_memory (chat_id, summary, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(chat_id) DO UPDATE SET summary = ?, updated_at = ?",
        (chat_id, summary, datetime.now(timezone.utc).isoformat(),
         summary, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def count_messages(db_path: str, chat_id: str) -> int:
    conn = db_conn(db_path)
    count = conn.execute(
        "SELECT COUNT(*) FROM chat_messages WHERE chat_id = ?", (chat_id,)
    ).fetchone()[0]
    conn.close()
    return count


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
            content_parts = []
            for p in paths:
                try:
                    from pathlib import Path
                    pp = Path(p)
                    if pp.exists() and pp.stat().st_size < 5 * 1024 * 1024:  # <5MB
                        b64 = b64mod.b64encode(pp.read_bytes()).decode()
                        mime = "image/jpeg"
                        if p.endswith(".png"): mime = "image/png"
                        elif p.endswith(".webp"): mime = "image/webp"
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
    return messages


def maybe_summarize(db_path: str, chat_id: str, client):
    """消息数超过阈值时，压缩旧消息为摘要记忆。"""
    total = count_messages(db_path, chat_id)
    if total <= ch_cfg.SUMMARIZE_THRESHOLD:
        return

    conn = db_conn(db_path)
    rows = conn.execute(
        "SELECT role, content FROM chat_messages "
        "WHERE chat_id = ? ORDER BY id ASC",
        (chat_id,),
    ).fetchall()
    conn.close()

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
            conn = db_conn(db_path)
            conn.execute(
                "DELETE FROM chat_messages WHERE chat_id = ? AND id NOT IN "
                "(SELECT id FROM chat_messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?)",
                (chat_id, chat_id, ch_cfg.RECENT_TURNS),
            )
            conn.commit()
            conn.close()
            log.info(f"chat: summarized {len(old_messages)} messages for {chat_id}")

    except Exception as e:
        log.warning(f"chat: summarize failed: {e}")


# ── 工具执行 ──────────────────────────────────────────────────────────────────

def execute_tool(tool_name: str, tool_input: dict, chat_id: str = "",
                 reply_fn=None, channel_source: str = "channel") -> str:
    """执行工具调用。reply_fn 用于任务完成后回调通知。"""
    if tool_name == "dispatch_task":
        return _tool_dispatch_task(tool_input, chat_id, reply_fn, channel_source)
    elif tool_name == "query_status":
        return _tool_query_status(tool_input)
    elif tool_name == "read_file":
        return _tool_read_file(tool_input)
    elif tool_name == "wake_claude":
        return _tool_wake_claude(tool_input, chat_id)
    return f"Unknown tool: {tool_name}"


def _tool_read_file(params: dict) -> str:
    file_path = params.get("path", "")
    max_chars = params.get("max_chars", ch_cfg.MAX_FILE_READ_CHARS)

    if not file_path:
        return "path 不能为空"

    allowed_prefixes = [p.replace("\\", "/") for p in ch_cfg.READ_ALLOW_PATHS]
    clean_path = file_path.replace("\\", "/")
    if not any(clean_path.startswith(p) for p in allowed_prefixes):
        return "安全限制：路径不在白名单中"

    if clean_path.startswith("/orchestrator"):
        local_path = _REPO_ROOT / clean_path[len("/orchestrator/"):]
    elif clean_path.startswith("/git-repos"):
        local_path = Path("D:/Users/Administrator/Documents/GitHub") / clean_path[len("/git-repos/"):]
    else:
        local_path = Path(file_path)

    try:
        if not local_path.exists():
            return f"文件不存在: {file_path}"
        if local_path.stat().st_size > ch_cfg.MAX_FILE_READ_BYTES:
            return f"文件过大 ({local_path.stat().st_size} bytes)，拒绝读取"
        content = local_path.read_text(encoding="utf-8", errors="replace")
        if len(content) > max_chars:
            return content[:max_chars] + f"\n\n[...已截取前 {max_chars} 字符，共 {len(content)} 字符]"
        return content
    except Exception as e:
        return f"读取失败: {e}"


def _tool_dispatch_task(params: dict, chat_id: str, reply_fn, channel_source: str) -> str:
    action = params.get("action", "")
    priority = params.get("priority", "medium")
    if not action:
        return "action 不能为空"

    try:
        from src.core.event_bus import get_event_bus, Event, Priority as EvPriority

        predefined = set(ch_cfg.PREDEFINED_SCENARIOS)
        if action in predefined:
            bus = get_event_bus()
            bus.publish(Event(
                event_type="channel.command.run",
                payload={"scenario": action, "source": f"{channel_source}_chat"},
                priority=EvPriority.HIGH,
                source=f"channel:{channel_source}:chat",
            ))
            return f"已提交预定义场景: {action}"

        from src.storage.events_db import EventsDB
        db = EventsDB()
        task_id = db.create_task(
            action=action,
            reason=f"{channel_source} 对话触发",
            priority=priority,
            spec={
                "summary": action,
                "department": params.get("department", ""),
                "problem": action,
                "source": f"{channel_source}_chat",
            },
            source="channel",
        )

        def _run():
            try:
                from src.governance.governor import Governor
                gov = Governor(db=EventsDB())
                gov.execute_task(task_id)

                result_db = EventsDB()
                row = result_db.query(
                    f"SELECT status, output FROM tasks WHERE id={task_id}"
                )
                if row and reply_fn:
                    status, output = row[0][0], (row[0][1] or "")[:300]
                    if status == "done":
                        reply_fn(chat_id, f"任务 #{task_id} 完成: {output}")
                    elif status == "failed":
                        reply_fn(chat_id, f"任务 #{task_id} 失败: {output}")
            except Exception as e:
                log.error(f"chat: task {task_id} execution failed: {e}")
                if reply_fn:
                    reply_fn(chat_id, f"任务 #{task_id} 执行出错: {e}")

        threading.Thread(target=_run, name=f"chat-task-{task_id}", daemon=True).start()
        return f"任务 #{task_id} 已提交（{action[:50]}）"

    except Exception as e:
        return f"派发失败: {e}"


def _tool_query_status(params: dict) -> str:
    query_type = params.get("query_type", "health")
    try:
        if query_type == "health":
            from src.core.health import HealthCheck
            hc = HealthCheck()
            report = hc.run()
            lines = [f"整体: {'正常' if report.get('healthy') else '异常'}"]
            for name, data in report.get("checks", {}).items():
                tag = "OK" if data.get("ok") else "ERR"
                lines.append(f"  [{tag}] {name}")
            return "\n".join(lines)

        elif query_type == "tasks":
            from src.storage.events_db import EventsDB
            db = EventsDB()
            tasks = db.query(
                "SELECT task_id, department, status, summary "
                f"FROM tasks ORDER BY created_at DESC LIMIT {ch_cfg.TASKS_DISPLAY_LIMIT}"
            )
            if not tasks:
                return "暂无任务记录"
            return "\n".join(
                f"[{t[2]}] #{t[0][:8]} [{t[1] or '?'}] {(t[3] or '')[:50]}"
                for t in tasks
            )

        elif query_type == "collectors":
            from src.storage.events_db import EventsDB
            db = EventsDB()
            rows = db.query("SELECT name, data FROM collector_reputation ORDER BY name")
            if not rows:
                return "无采集器数据"
            lines = []
            for r in rows:
                try:
                    d = json.loads(r[1])
                    lines.append(f"[{d.get('status','?')}] {d.get('name','?')}: {d.get('last_count',0)} events")
                except Exception:
                    lines.append(f"{r[0]}: parse error")
            return "\n".join(lines)

        elif query_type == "channels":
            from src.channels.registry import get_channel_registry
            reg = get_channel_registry()
            status = reg.get_status()
            if not status:
                return "无 channel 配置"
            return "\n".join(
                f"{'[ON]' if info['enabled'] else '[OFF]'} {name} ({info['type']})"
                for name, info in status.items()
            )

        return f"未知查询类型: {query_type}"
    except Exception as e:
        return f"查询失败: {e}"


def _tool_wake_claude(params: dict, chat_id: str) -> str:
    task = params.get("task", "")
    context = params.get("context", "")
    if not task:
        return "task is required"
    try:
        from src.channels.wake import write_wake_request
        filename = write_wake_request(
            task=task, context=context, chat_id=chat_id,
        )
        return f"Claude Code wake request sent ({filename}). A terminal will open on the host machine."
    except Exception as e:
        return f"Wake failed: {e}"


# ── Intent 分类 — 偷师 kevinzhj/model-router-hook 的信号检测 ──────────────────

_TOOL_SIGNALS = {
    # 系统查询 → query_status
    "查状态", "看状态", "系统状态", "health", "collectors", "采集器",
    # 主机操作 → wake_claude (multi-char phrases to avoid false positives)
    "打开", "运行一下", "执行一下", "跑一下", "帮我改", "帮我修", "帮我写",
    "改代码", "写代码", "改文件", "写文件", "修一下", "修复",
    "呼叫外援", "wake claude", "叫claude",
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
        "vision"  — has images, route to gemma3:27b
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
    """Call Ollama vision model (gemma3:27b) for image understanding."""
    try:
        from src.core.llm_router import get_router
        router = get_router()
        if not router._ollama_available:
            return ""

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


# ── 对话主循环 ────────────────────────────────────────────────────────────────

def do_chat(chat_id: str, text: str, original_text: str,
            system_prompt: str, reply_fn, channel_source: str = "channel",
            permission_check_fn=None, media: list = None):
    """对话主循环 — 闲聊走本地模型，需要工具时走 Claude API。

    Args:
        chat_id: 用户标识（Telegram chat_id / WeChat user_id）
        text: 给 LLM 看的内容
        original_text: 存 DB 的原文（长消息时与 text 不同）
        system_prompt: 系统提示词
        reply_fn: 回复函数 reply_fn(chat_id, text)
        channel_source: 来源标识（"telegram" / "wechat"）
        permission_check_fn: 权限检查 fn(chat_id, tool_name) -> bool，None=全放行
    """
    try:
        from src.storage.events_db import _DEFAULT_DB

        db_path = _DEFAULT_DB
        db_content = original_text if original_text else text
        # Collect media paths for DB storage
        _media_paths = []
        if media:
            from src.channels.media import MediaType
            for att in media:
                if att.local_path:
                    _media_paths.append(att.local_path)
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

        # ── Intent classification → model routing ──
        has_images = bool(_media_paths and any(
            p.endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif'))
            for p in _media_paths
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

        for _ in range(max_rounds):
            response = client.messages.create(
                model=ch_cfg.CHAT_MODEL,
                max_tokens=ch_cfg.CHAT_MAX_TOKENS,
                system=system_prompt,
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
                    )
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": result,
                })
            messages.append({"role": "user", "content": tool_results})

        if final_reply:
            log.info(f"chat: sending reply ({len(final_reply)} chars) to {chat_id[:16]}...")
            try:
                reply_fn(chat_id, final_reply)
                log.info(f"chat: reply sent successfully")
            except Exception as re:
                log.error(f"chat: reply_fn failed: {re}", exc_info=True)
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


# ── 命令处理 ──────────────────────────────────────────────────────────────────

def handle_command(text: str, chat_id: str, reply_fn, channel_source: str = "channel"):
    """解析并执行 /command。"""
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower().split("@")[0]  # 去掉 @bot_name
    args = parts[1] if len(parts) > 1 else ""

    if cmd == "/help":
        _cmd_help(reply_fn, chat_id)
    elif cmd == "/status":
        _cmd_status(reply_fn, chat_id)
    elif cmd == "/tasks":
        _cmd_tasks(reply_fn, chat_id)
    elif cmd == "/run":
        _cmd_run(reply_fn, chat_id, args, channel_source)
    elif cmd == "/channels":
        _cmd_channels(reply_fn, chat_id)
    else:
        reply_fn(chat_id, f"未知命令: {cmd}\n发送 /help 查看可用命令")


COMMANDS = {
    "/status": "查看系统状态",
    "/tasks": "最近任务列表",
    "/run": "触发场景执行 (用法: /run <scenario>)",
    "/channels": "查看 channel 状态",
    "/help": "显示帮助",
}


def _cmd_help(reply_fn, chat_id: str):
    lines = ["Orchestrator 命令\n"]
    for cmd, desc in COMMANDS.items():
        lines.append(f"{cmd} — {desc}")
    reply_fn(chat_id, "\n".join(lines))


def _cmd_status(reply_fn, chat_id: str):
    try:
        from src.core.health import HealthCheck
        hc = HealthCheck()
        report = hc.run()
        lines = ["系统状态\n"]
        lines.append(f"整体: {'正常' if report.get('healthy') else '异常'}")
        for name, data in report.get("checks", {}).items():
            mark = "ok" if data.get("ok") else "异常"
            lines.append(f"  {name}: {mark}")
        reply_fn(chat_id, "\n".join(lines))
    except Exception as e:
        reply_fn(chat_id, f"获取状态失败: {e}")


def _cmd_tasks(reply_fn, chat_id: str):
    try:
        from src.storage.events_db import EventsDB
        db = EventsDB()
        tasks = db.query(
            "SELECT task_id, department, status, summary "
            f"FROM tasks ORDER BY created_at DESC LIMIT {ch_cfg.TASKS_DISPLAY_LIMIT}"
        )
        if not tasks:
            reply_fn(chat_id, "暂无任务记录")
            return
        lines = ["最近任务\n"]
        status_labels = {
            "done": "完成", "failed": "失败", "running": "执行中",
            "pending": "等待", "scrutiny_failed": "审查未通过",
        }
        for t in tasks:
            label = status_labels.get(t[2], t[2])
            dept = t[1] or "?"
            summary = (t[3] or "")[:60]
            lines.append(f"  {t[0][:8]} {dept} — {summary} ({label})")
        reply_fn(chat_id, "\n".join(lines))
    except Exception as e:
        reply_fn(chat_id, f"获取任务失败: {e}")


def _cmd_run(reply_fn, chat_id: str, scenario: str, channel_source: str):
    if not scenario.strip():
        reply_fn(chat_id, "用法: /run <scenario_name>")
        return
    try:
        from src.core.event_bus import get_event_bus, Event, Priority
        bus = get_event_bus()
        bus.publish(Event(
            event_type="channel.command.run",
            payload={"scenario": scenario.strip(), "source": channel_source},
            priority=Priority.HIGH,
            source=f"channel:{channel_source}",
        ))
        reply_fn(chat_id, f"已提交: {scenario.strip()}")
    except Exception as e:
        reply_fn(chat_id, f"提交失败: {e}")


def _cmd_channels(reply_fn, chat_id: str):
    try:
        from src.channels.registry import get_channel_registry
        reg = get_channel_registry()
        status = reg.get_status()
        lines = ["Channel 状态\n"]
        for name, info in status.items():
            state = "在线" if info["enabled"] else "离线"
            lines.append(f"  {name} ({info['type']}): {state}")
        reply_fn(chat_id, "\n".join(lines))
    except Exception as e:
        reply_fn(chat_id, f"获取 channel 状态失败: {e}")


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
