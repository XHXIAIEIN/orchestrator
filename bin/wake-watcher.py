"""Wake Watcher — monitor tmp/wake/ for task files, dispatch via Agent SDK."""

import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

# Ensure project root is on sys.path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.core.agent_client import agent_query  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="[wake-watcher] %(asctime)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

WAKE_DIR = _root / "tmp" / "wake"
POLL_INTERVAL = 5  # seconds
MAX_WORKERS = 2


def _build_prompt(task: str, context: str, chat_id: str) -> str:
    return f"""[Wake from Telegram] chat_id={chat_id}

Task: {task}

Context: {context}

Instructions:
- You were woken up by the Telegram bot because it needs help with something it can't do alone.
- Complete the task, commit if needed, then write a brief summary.
- The summary will be sent back to the user on Telegram.
- Work in the orchestrator repo: {_root}"""


def _dispatch(file_path: Path):
    """Process a single wake request file."""
    try:
        content = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception as e:
        log.error("Failed to read %s: %s", file_path.name, e)
        return

    if content.get("status") != "pending":
        return

    task = content.get("task", "")
    context = content.get("context", "")
    chat_id = content.get("chat_id", "")
    log.info("Wake request: %s", task[:80])

    # Mark as processing
    content["status"] = "processing"
    file_path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")

    prompt = _build_prompt(task, context, chat_id)
    output_file = file_path.with_suffix(".output.txt")

    try:
        result = agent_query(
            prompt=prompt,
            max_turns=25,
            cwd=str(_root),
        )
        output_file.write_text(result, encoding="utf-8")
        content["status"] = "done"
        log.info("Wake task completed: %s", task[:60])
    except Exception as e:
        error_msg = f"Agent SDK error: {e}"
        output_file.write_text(error_msg, encoding="utf-8")
        content["status"] = "failed"
        content["error"] = str(e)[:500]
        log.error("Wake task failed: %s — %s", task[:60], e)

    content["completed_at"] = datetime.now().isoformat()
    file_path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    WAKE_DIR.mkdir(parents=True, exist_ok=True)
    log.info("Monitoring %s (every %ds)", WAKE_DIR, POLL_INTERVAL)

    pool = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="wake")

    try:
        while True:
            for f in WAKE_DIR.glob("*.json"):
                if f.name.endswith(".response.json"):
                    continue
                try:
                    content = json.loads(f.read_text(encoding="utf-8"))
                    if content.get("status") == "pending":
                        pool.submit(_dispatch, f)
                except Exception:
                    continue
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        log.info("Shutting down")
        pool.shutdown(wait=False)


if __name__ == "__main__":
    main()
