#!/usr/bin/env python3
"""
Wake Watcher — DB 轮询执行器。

在宿主机运行（不在 Docker 内）。
轮询 wake_sessions 表中 status='approved' 的记录，拉起 Claude Code 执行。
每 turn 检查取消信号和交互注入。
"""
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))

from src.core.agent_client import agent_query
from src.storage.events_db import EventsDB

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("wake-watcher")

POLL_INTERVAL = 5   # seconds
MAX_WORKERS = 2
WORK_DIR = _root / "tmp" / "wake"
QUEUE_DIR = _root / "tmp" / "wake" / "queue"
QUEUE_DONE = _root / "tmp" / "wake" / "queue" / "done"

# Track which sessions are currently being executed
_active: set[int] = set()


def _load_env():
    """Load .env file, strip ANTHROPIC_API_KEY so Claude CLI uses OAuth."""
    env_file = _root / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key == "ANTHROPIC_API_KEY":
            os.environ.pop(key, None)
            continue
        os.environ.setdefault(key, val)


def _build_prompt(session: dict) -> str:
    """Build the prompt for Claude Code from a wake session."""
    return f"""[Wake Session #{session['id']}] chat_id={session['chat_id']}

Task: {session['spotlight']}

Instructions:
- You were woken up by the orchestrator because it needs Claude Code to do real work.
- Use the /bot-tg or /bot-wx skill to check recent chat messages for full context (chat_id={session['chat_id']}).
- Complete the task, commit if needed, then write a brief result summary.
- Work in the orchestrator repo: {_root}
"""


def _write_milestone(db: EventsDB, task_id: int, step: str, message: str):
    """Write a milestone event."""
    db.add_agent_event(
        task_id=task_id,
        event_type="wake.milestone",
        data={"step": step, "msg": message, "ts": datetime.now(timezone.utc).isoformat()},
    )


def _dispatch(session: dict):
    """Execute a single wake session."""
    db = EventsDB()
    sid = session["id"]
    task_id = session["task_id"]

    log.info("Starting wake session #%d: %s", sid, session["spotlight"])

    # Mark running
    db.update_wake_session(sid, status="running")
    db.update_task(task_id, status="running",
                   started_at=datetime.now(timezone.utc).isoformat())

    _write_milestone(db, task_id, "start", f"开始执行: {session['spotlight']}")

    # Notify channels
    try:
        from src.channels.wake import _notify
        _notify(session, "started")
    except Exception:
        pass

    prompt = _build_prompt(session)

    try:
        result = agent_query(
            prompt=prompt,
            max_turns=25,
            cwd=str(_root),
        )

        # Check cancel
        s = db.get_wake_session(sid)
        if s and s["status"] == "cancelled":
            log.info("Wake #%d cancelled during execution", sid)
            db.finish_wake_session(sid, status="cancelled", result="执行中被取消")
            _write_milestone(db, task_id, "cancelled", "任务被用户取消")
            return

        # Store result
        result_text = result.strip()[-2000:] if len(result) > 2000 else result.strip()
        db.finish_wake_session(sid, status="done", result=result_text)
        db.update_task(task_id, status="done", output=result_text[:500],
                       finished_at=datetime.now(timezone.utc).isoformat())

        _write_milestone(db, task_id, "done", "任务完成")
        log.info("Wake #%d completed", sid)

        # Notify
        try:
            updated = db.get_wake_session(sid)
            from src.channels.wake import _notify
            _notify(updated, "done")
        except Exception:
            pass

    except Exception as e:
        error_msg = f"Agent SDK error: {str(e)[:500]}"
        log.error("Wake #%d failed: %s", sid, e)
        db.finish_wake_session(sid, status="failed", result=error_msg)
        db.update_task(task_id, status="failed", output=error_msg,
                       finished_at=datetime.now(timezone.utc).isoformat())
        _write_milestone(db, task_id, "failed", error_msg)

        try:
            updated = db.get_wake_session(sid)
            from src.channels.wake import _notify
            _notify(updated, "failed")
        except Exception:
            pass

    finally:
        _active.discard(sid)


def _process_queue():
    """Process queue files from container → open WT tabs on host."""
    import json
    import shutil
    import subprocess

    if not QUEUE_DIR.exists():
        return

    QUEUE_DONE.mkdir(parents=True, exist_ok=True)
    launcher_dir = _root / "tmp" / "wake" / "launchers"
    launcher_dir.mkdir(parents=True, exist_ok=True)
    project_root = str(_root).replace("/", "\\")

    for f in sorted(QUEUE_DIR.glob("*.json")):
        try:
            req = json.loads(f.read_text(encoding="utf-8"))
            profile = req.get("profile", "Wake Remote")
            reason = req.get("reason", "")

            if reason:
                # Write .ps1 launcher to avoid quoting/truncation
                script = launcher_dir / f"wake-{f.stem}.ps1"
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
                cmd = ["wt.exe", "-w", "0", "new-tab", "--profile", profile]

            subprocess.Popen(cmd)
            log.info("Opened WT tab from queue: %s (reason=%s)", f.name, reason[:60])

            shutil.move(str(f), str(QUEUE_DONE / f.name))

        except Exception as e:
            log.error("Failed to process queue file %s: %s", f.name, e)
            try:
                shutil.move(str(f), str(QUEUE_DONE / f.name))
            except Exception:
                pass


def main():
    _load_env()
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    db = EventsDB()
    log.info("Wake watcher started (polling every %ds, max %d workers)", POLL_INTERVAL, MAX_WORKERS)

    pool = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="wake")

    try:
        while True:
            # DB-based sessions (headless execution via Agent SDK)
            sessions = db.get_wake_sessions(status="approved")
            for s in sessions:
                if s["id"] not in _active:
                    _active.add(s["id"])
                    pool.submit(_dispatch, s)

            # Queue-based requests (visual WT tab execution)
            _process_queue()

            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        log.info("Shutting down")
        pool.shutdown(wait=False)


if __name__ == "__main__":
    main()
