"""
Execution Snapshot — 增量快照追踪，支持回放与摘要渲染。

偷师来源: LobeHub Round 16 — Agent-as-Unit-of-Work 模式。
每步执行记录为 StepSnapshot (JSONL 序列化)，可重建消息历史、
渲染摘要表、replay 整个执行过程。
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)

EventType = Literal[
    "turn_start", "tool_call", "tool_result",
    "assistant_message", "progress", "error",
]

# ── StepSnapshot ──────────────────────────────────────────────

@dataclass
class StepSnapshot:
    """单步执行快照。"""
    step_num: int
    timestamp: str                      # ISO 8601
    event_type: EventType
    data: dict = field(default_factory=dict)
    cumulative_tokens: int = 0
    cumulative_cost_usd: float = 0.0
    duration_ms: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> StepSnapshot:
        return cls(
            step_num=d["step_num"],
            timestamp=d["timestamp"],
            event_type=d["event_type"],
            data=d.get("data", {}),
            cumulative_tokens=d.get("cumulative_tokens", 0),
            cumulative_cost_usd=d.get("cumulative_cost_usd", 0.0),
            duration_ms=d.get("duration_ms", 0),
        )


# ── ExecutionSnapshot ─────────────────────────────────────────

class ExecutionSnapshot:
    """一次任务执行的完整快照序列。"""

    def __init__(self, task_id: int, department: str):
        self.task_id = task_id
        self.department = department
        self._steps: list[StepSnapshot] = []
        self._cumulative_tokens: int = 0
        self._cumulative_cost: float = 0.0
        self._last_ts: float = time.monotonic()
        self._start_ts: float = self._last_ts

    def record(
        self,
        event_type: EventType,
        data: dict,
        tokens: int = 0,
        cost: float = 0.0,
    ) -> StepSnapshot:
        """记录一步快照，自动计算累计值和耗时。"""
        now = time.monotonic()
        duration_ms = int((now - self._last_ts) * 1000)
        self._last_ts = now

        self._cumulative_tokens += tokens
        self._cumulative_cost += cost

        step = StepSnapshot(
            step_num=len(self._steps) + 1,
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_type=event_type,
            data=data,
            cumulative_tokens=self._cumulative_tokens,
            cumulative_cost_usd=round(self._cumulative_cost, 6),
            duration_ms=duration_ms,
        )
        self._steps.append(step)
        return step

    def get_steps(self) -> list[StepSnapshot]:
        return list(self._steps)

    def get_summary(self) -> dict:
        """摘要统计。"""
        total_ms = int((time.monotonic() - self._start_ts) * 1000) if self._steps else 0
        tool_calls = sum(1 for s in self._steps if s.event_type == "tool_call")
        errors = sum(1 for s in self._steps if s.event_type == "error")
        return {
            "task_id": self.task_id,
            "department": self.department,
            "total_steps": len(self._steps),
            "total_tokens": self._cumulative_tokens,
            "total_cost_usd": round(self._cumulative_cost, 6),
            "total_duration_ms": total_ms,
            "tool_calls": tool_calls,
            "errors": errors,
        }

    def render_table(self) -> str:
        """渲染 markdown 风格文本表格。"""
        if not self._steps:
            return "(no steps recorded)"

        header = "| Step | Event            | Tokens | Cost($)  | Δms   |"
        sep    = "|------|------------------|--------|----------|-------|"
        rows = [header, sep]
        for s in self._steps:
            rows.append(
                f"| {s.step_num:<4} "
                f"| {s.event_type:<16} "
                f"| {s.cumulative_tokens:<6} "
                f"| {s.cumulative_cost_usd:<8.4f} "
                f"| {s.duration_ms:<5} |"
            )
        summary = self.get_summary()
        rows.append(sep)
        rows.append(
            f"| {'SUM':<4} "
            f"| {'—':<16} "
            f"| {summary['total_tokens']:<6} "
            f"| {summary['total_cost_usd']:<8.4f} "
            f"| {summary['total_duration_ms']:<5} |"
        )
        return "\n".join(rows)

    # ── 序列化 ──

    def save(self, path: str | Path) -> None:
        """保存为 JSONL，一行一步。首行写 meta。"""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            meta = {"_meta": True, "task_id": self.task_id, "department": self.department}
            f.write(json.dumps(meta, ensure_ascii=False) + "\n")
            for step in self._steps:
                f.write(json.dumps(step.to_dict(), ensure_ascii=False) + "\n")
        log.debug("Snapshot saved: %s (%d steps)", path, len(self._steps))

    @classmethod
    def load(cls, path: str | Path) -> ExecutionSnapshot:
        """从 JSONL 文件加载快照。"""
        path = Path(path)
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        if not lines:
            raise ValueError(f"Empty snapshot file: {path}")

        first = json.loads(lines[0])
        if first.get("_meta"):
            task_id = first["task_id"]
            department = first["department"]
            step_lines = lines[1:]
        else:
            # 兼容：无 meta 行
            task_id = 0
            department = "unknown"
            step_lines = lines

        snap = cls(task_id=task_id, department=department)
        for line in step_lines:
            if not line.strip():
                continue
            d = json.loads(line)
            step = StepSnapshot.from_dict(d)
            snap._steps.append(step)

        # 恢复累计值
        if snap._steps:
            last = snap._steps[-1]
            snap._cumulative_tokens = last.cumulative_tokens
            snap._cumulative_cost = last.cumulative_cost_usd

        return snap

    # ── 回放 ──

    def reconstruct_messages(self) -> list[dict]:
        """从快照重建消息历史（用于回放/调试）。"""
        messages: list[dict] = []
        for step in self._steps:
            if step.event_type == "turn_start":
                messages.append({
                    "role": "system",
                    "type": "turn_start",
                    "turn": step.data.get("turn", 0),
                    "timestamp": step.timestamp,
                })
            elif step.event_type == "assistant_message":
                messages.append({
                    "role": "assistant",
                    "content": step.data.get("text", ""),
                    "timestamp": step.timestamp,
                })
            elif step.event_type == "tool_call":
                messages.append({
                    "role": "assistant",
                    "type": "tool_call",
                    "tool": step.data.get("tool", ""),
                    "input": step.data.get("input", {}),
                    "timestamp": step.timestamp,
                })
            elif step.event_type == "tool_result":
                messages.append({
                    "role": "tool",
                    "tool": step.data.get("tool", ""),
                    "output": step.data.get("output", ""),
                    "timestamp": step.timestamp,
                })
            elif step.event_type == "error":
                messages.append({
                    "role": "system",
                    "type": "error",
                    "error": step.data.get("error", ""),
                    "timestamp": step.timestamp,
                })
            elif step.event_type == "progress":
                messages.append({
                    "role": "system",
                    "type": "progress",
                    "message": step.data.get("message", ""),
                    "timestamp": step.timestamp,
                })
        return messages


# ── SnapshotStore ─────────────────────────────────────────────

class SnapshotStore:
    """简单文件存储：data/snapshots/{task_id}.jsonl。"""

    def __init__(self, base_dir: str | Path | None = None):
        if base_dir is None:
            base_dir = Path(__file__).parent.parent.parent / "data" / "snapshots"
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, task_id: int) -> Path:
        return self.base_dir / f"{task_id}.jsonl"

    def save_snapshot(self, snapshot: ExecutionSnapshot) -> Path:
        """保存快照，返回文件路径。"""
        path = self._path_for(snapshot.task_id)
        snapshot.save(path)
        return path

    def load_snapshot(self, task_id: int) -> ExecutionSnapshot:
        """加载指定任务的快照。"""
        path = self._path_for(task_id)
        if not path.exists():
            raise FileNotFoundError(f"No snapshot for task_id={task_id}: {path}")
        return ExecutionSnapshot.load(path)

    def list_snapshots(self) -> list[int]:
        """列出所有已保存快照的 task_id。"""
        ids = []
        for f in sorted(self.base_dir.glob("*.jsonl")):
            try:
                ids.append(int(f.stem))
            except ValueError:
                continue
        return ids
