"""
Agent 推理链落盘 — 完整保真 JSONL 日志。

偷师来源: OpenClaw 多 Agent 协同系统 (P8)
- 现有 agent_turn 事件截断到 300 字符，用于实时监控
- 本模块写入完整推理链，用于事后审计、Governor 决策回溯、训练数据积累

文件: data/reasoning-trace.jsonl
格式: 每行一条 JSON，按 task_id + turn 排序
"""
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_TRACE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "reasoning-trace.jsonl"
# Cap individual fields to prevent runaway logs (e.g. base64 blobs)
_MAX_FIELD_CHARS = 50_000


def append_reasoning_trace(
    task_id: int,
    turn: int,
    thinking: list[str] | None = None,
    tool_calls: list[dict] | None = None,
    text: list[str] | None = None,
    error: str | None = None,
) -> None:
    """Append one reasoning trace entry to the JSONL log.

    All fields are stored at full fidelity (up to _MAX_FIELD_CHARS per item).
    This is separate from agent_events DB to keep the hot path fast —
    JSONL append is O(1) with no DB overhead.
    """
    try:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "task_id": task_id,
            "turn": turn,
        }
        if thinking:
            entry["thinking"] = [t[:_MAX_FIELD_CHARS] for t in thinking]
        if tool_calls:
            # Truncate tool input values but keep structure
            safe_calls = []
            for tc in tool_calls:
                safe = {"tool": tc.get("tool", "")}
                inp = tc.get("input", {})
                if isinstance(inp, dict):
                    safe["input"] = {
                        k: (str(v)[:_MAX_FIELD_CHARS] if len(str(v)) > _MAX_FIELD_CHARS else v)
                        for k, v in inp.items()
                    }
                else:
                    safe["input"] = str(inp)[:_MAX_FIELD_CHARS]
                safe_calls.append(safe)
            entry["tool_calls"] = safe_calls
        if text:
            entry["text"] = [t[:_MAX_FIELD_CHARS] for t in text]
        if error:
            entry["error"] = error[:_MAX_FIELD_CHARS]

        _TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_TRACE_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    except Exception as e:
        # Never break agent execution for logging failures
        log.debug(f"reasoning_trace: write failed ({e})")
