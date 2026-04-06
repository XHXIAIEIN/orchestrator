"""Chat tool definitions and execution."""
import json
import logging
import threading
from pathlib import Path

from src.channels import config as ch_cfg

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent
while _REPO_ROOT != _REPO_ROOT.parent and not ((_REPO_ROOT / "departments").is_dir() and (_REPO_ROOT / "src").is_dir()):
    _REPO_ROOT = _REPO_ROOT.parent

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
                "mode": {
                    "type": "string",
                    "enum": ["quick", "deep", "compare", "fix"],
                    "description": (
                        "Operation mode. quick=fast scan 2min; deep=full audit chain; "
                        "compare=diff against last run; fix=auto-repair issues found. "
                        "Default: auto (inferred from action)."
                    ),
                },
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
            "Wake up Claude Code on the host machine to do real work "
            "(code changes, file ops, git). Provide a spotlight: one-line summary + keywords."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "spotlight": {
                    "type": "string",
                    "description": "One-line task summary with keywords, e.g. '修复 TG bot 轮询崩溃 [telegram, polling, fix]'",
                },
            },
            "required": ["spotlight"],
        },
    },
    {
        "name": "wake_interact",
        "description": (
            "Send a message to a running wake session — add instructions, "
            "ask for progress, or nudge the running Claude Code."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Message to inject into the running wake session",
                },
            },
            "required": ["message"],
        },
    },
    {
        "name": "wake_remote",
        "description": (
            "Launch a new Claude Code remote session on the host machine. "
            "This creates an isolated session via Remote Trigger with /persona loaded."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Why waking up, e.g. '帮我看看 TG bot 日志'",
                },
            },
            "required": [],
        },
    },
    {
        "name": "react",
        "description": (
            "Add an emoji reaction to the user's message. Use this to express "
            "your feeling about what the user said — surprise, love, laughter, "
            "agreement, thinking, sadness, etc. Totally optional; use your instinct."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "emoji": {
                    "type": "string",
                    "description": (
                        "A single Telegram reaction emoji. MUST be one of: "
                        "👍 👎 ❤ 🔥 🥰 👏 😁 🤔 🤯 😱 🤬 😢 🎉 🤩 🤮 💩 🙏 "
                        "👌 🕊 🤡 🥱 🥴 😍 🐳 🌚 🌭 💯 🤣 ⚡ 🍌 🏆 💔 🤨 😐 "
                        "🍓 🍾 💋 🖕 😈 😴 😭 🤓 👻 👨\u200d💻 👀 🎃 🙈 😇 😨 🤝 "
                        "✍ 🤗 🫡 🎅 🎄 ☃ 💅 🤪 🗿 🆒 💘 🙉 🦄 😘 💊 🙊 😎 👾 🤷\u200d♂ 🤷\u200d♀ 😡"
                    ),
                },
            },
            "required": ["emoji"],
        },
    },
]


# ── Operation Modes (stolen from AI Designer MCP, Round 37) ──
# Maps mode name → tier override + behavioral instructions.
# Tier controls resources (tokens/model/turns), instructions control behavior.
_OPERATION_MODES: dict[str, dict] = {
    "quick": {
        "tier": "light",
        "extra_instructions": (
            "[Mode: Quick Scan] Deliver results within 2 minutes. Check key metrics only, "
            "skip deep analysis. Output: one-paragraph summary + issues found (if any). No long reports."
        ),
    },
    "deep": {
        "tier": "heavy",
        "extra_instructions": (
            "[Mode: Deep Audit] Full analysis chain, leave nothing unchecked. Examine all dimensions, "
            "cross-validate findings. Output: structured report + evidence + recommendations. Take your time."
        ),
    },
    "compare": {
        "tier": "standard",
        "extra_instructions": (
            "[Mode: Compare] Find the previous run result for this department/domain (via ctx_read --list), "
            "and diff against current analysis. Output: diff summary — what improved, what degraded, what unchanged."
        ),
    },
    "fix": {
        "tier": "standard",
        "extra_instructions": (
            "[Mode: Auto-Fix] When issues are found, fix them directly instead of just reporting. "
            "For each fix: describe the problem → execute repair command → verify success. "
            "Output: fix summary (N issues found, M fixed, K require manual intervention)."
        ),
    },
}


def execute_tool(tool_name: str, tool_input: dict, chat_id: str = "",
                 reply_fn=None, channel_source: str = "channel",
                 react_fn=None) -> str:
    """执行工具调用。reply_fn 用于任务完成后回调通知。react_fn 用于表情回应。"""
    if tool_name == "dispatch_task":
        return _tool_dispatch_task(tool_input, chat_id, reply_fn, channel_source)
    elif tool_name == "query_status":
        return _tool_query_status(tool_input)
    elif tool_name == "read_file":
        return _tool_read_file(tool_input)
    elif tool_name == "wake_claude":
        return _tool_wake_claude(tool_input, chat_id, channel_source)
    elif tool_name == "wake_interact":
        return _tool_wake_interact(tool_input, chat_id)
    elif tool_name == "wake_remote":
        return _tool_wake_remote(tool_input, chat_id)
    elif tool_name == "react":
        emoji = tool_input.get("emoji", "")
        if react_fn and emoji:
            react_fn(emoji)
            return f"Reacted with {emoji}"
        return "No reaction target (not a direct message)"
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
    mode = params.get("mode", "")  # Operation Mode (R37 AI Designer steal)
    if not action:
        return "action 不能为空"

    try:
        from src.core.event_bus import get_event_bus, Event, Priority as EvPriority

        predefined = set(ch_cfg.PREDEFINED_SCENARIOS)
        if action in predefined:
            bus = get_event_bus()
            bus.publish(Event(
                event_type="channel.command.run",
                payload={"scenario": action, "source": f"{channel_source}_chat", "mode": mode},
                priority=EvPriority.HIGH,
                source=f"channel:{channel_source}:chat",
            ))
            return f"已提交预定义场景: {action}" + (f" (mode={mode})" if mode else "")

        from src.storage.events_db import EventsDB
        db = EventsDB()

        # ── Operation Mode → tier + extra_instructions mapping ──
        # quick → light tier, "2 分钟内出结果，只看关键指标"
        # deep  → heavy tier, "完整分析链，不遗漏"
        # compare → standard tier, "和上次 run 结果对比，输出 diff"
        # fix   → standard tier, "发现问题直接修复，输出修复摘要"
        mode_config = _OPERATION_MODES.get(mode, {})
        spec = {
            "summary": action,
            "department": params.get("department", ""),
            "problem": action,
            "source": f"{channel_source}_chat",
        }
        if mode_config:
            if mode_config.get("tier"):
                spec["tier"] = mode_config["tier"]
            if mode_config.get("extra_instructions"):
                spec["extra_instructions"] = mode_config["extra_instructions"]
            spec["mode"] = mode

        task_id = db.create_task(
            action=action,
            reason=f"{channel_source} 对话触发",
            priority=priority,
            spec=spec,
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


def _tool_wake_claude(params: dict, chat_id: str, channel_source: str = "channel") -> str:
    from src.channels.wake import create_session
    from src.channels.channel_config import ALLOWED_USERS
    spotlight = params.get("spotlight", "")
    if not spotlight:
        return "Error: spotlight is required"
    is_admin = ALLOWED_USERS.get(chat_id) == "admin"
    result = create_session(
        chat_id=chat_id, spotlight=spotlight, channel=channel_source,
        auto_approve=is_admin,
    )
    status_msg = "直接执行" if is_admin else "等待审批"
    return (
        f"Wake session #{result['session_id']} created (task #{result['task_id']}). "
        f"{status_msg}"
    )


def _tool_wake_remote(params: dict, chat_id: str) -> str:
    """Open a Windows Terminal tab with Wake Remote profile.

    Dual-mode:
      - Host (Claude Code): wt.exe directly opens a tab.
      - Container (TG bot): writes queue file → host watcher opens tab.
    """
    import json, os, subprocess, time

    reason = params.get("reason", "")
    in_container = os.path.exists("/.dockerenv")

    if in_container:
        # ── Container path: queue for host-side watcher ──
        queue_dir = _REPO_ROOT / "tmp" / "wake" / "queue"
        queue_dir.mkdir(parents=True, exist_ok=True)
        request = {
            "chat_id": chat_id,
            "reason": reason,
            "ts": time.time(),
            "profile": "Wake Remote",
        }
        fname = f"{int(time.time() * 1000)}.json"
        (queue_dir / fname).write_text(
            json.dumps(request, ensure_ascii=False), encoding="utf-8",
        )
        log.info(f"wake_remote: queued {fname} reason={reason[:80]}")
        label = f" ({reason[:60]})" if reason else ""
        return f"Wake request queued{label}. Host watcher will open terminal tab."

    # ── Host path: open WT tab directly ──
    try:
        project_root = str(_REPO_ROOT).replace("/", "\\")
        if reason:
            # Write a temp .ps1 launcher to dodge quoting hell
            launcher_dir = _REPO_ROOT / "tmp" / "wake" / "launchers"
            launcher_dir.mkdir(parents=True, exist_ok=True)
            ts = int(time.time() * 1000)
            script = launcher_dir / f"wake-{ts}.ps1"
            git_bash = r"D:\Program Files\Git\bin\bash.exe"
            lines = [
                f'Set-Location "{project_root}"',
                f'$gitBash = "{git_bash}"',
                'if ((Test-Path $gitBash) -and -not $env:CLAUDE_CODE_GIT_BASH_PATH) {',
                '    $env:CLAUDE_CODE_GIT_BASH_PATH = $gitBash',
                '}',
                'Write-Host "=== Wake Remote ===" -ForegroundColor Cyan',
                f'Write-Host "Task: {reason[:100]}"',
                'Write-Host ""',
                f'claude --dangerously-skip-permissions "{reason}"',
            ]
            script.write_text("\n".join(lines) + "\n", encoding="utf-8")
            script_path = str(script).replace("/", "\\")
            cmd = [
                "wt.exe", "-w", "0", "new-tab",
                "-d", project_root,
                "--title", f"Wake: {reason[:30]}",
                "--", "pwsh", "-NoExit", "-File", script_path,
            ]
        else:
            cmd = ["wt.exe", "-w", "0", "new-tab", "--profile", "Wake Remote"]
        subprocess.Popen(cmd)
        log.info(f"wake_remote: opened WT tab, reason={reason[:80]}")
        label = f" Task: {reason[:100]}" if reason else " Generic remote session."
        return f"Terminal tab opened.{label}"
    except FileNotFoundError:
        return "wt.exe not found — is Windows Terminal installed?"
    except Exception as e:
        log.warning(f"wake_remote: failed: {e}")
        return f"Failed to open terminal tab: {e}"


def _tool_wake_interact(params: dict, chat_id: str) -> str:
    from src.storage.events_db import EventsDB
    db = EventsDB()
    session = db.get_active_wake_session(chat_id)
    if not session:
        return "No active wake session for this chat"
    if session["status"] != "running":
        return f"Wake session #{session['id']} is {session['status']}, not running"
    message = params.get("message", "")
    if not message:
        return "Error: message is required"
    db.add_agent_event(
        task_id=session["task_id"],
        event_type="wake.inject",
        data={"message": message, "chat_id": chat_id},
    )
    return f"Message injected into wake session #{session['id']}"
