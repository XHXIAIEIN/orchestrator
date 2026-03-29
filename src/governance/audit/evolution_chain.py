"""
四阶段进化审计链 — 偷自 evolver 的 Signal→Hypothesis→Attempt→Outcome 模式。

每次部门 prompt 进化必须记录完整因果链，缺任何一环可追溯。
追加写 JSONL，不可变，可回溯。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class EvolutionPhase:
    SIGNAL = "signal"
    HYPOTHESIS = "hypothesis"
    ATTEMPT = "attempt"
    OUTCOME = "outcome"


DEFAULT_CHAIN_PATH = "data/evolution_events.jsonl"


def _write_event(chain_path, event):
    path = Path(chain_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _now():
    return datetime.now(timezone.utc).isoformat()


def record_signal(department, signals, chain_path=DEFAULT_CHAIN_PATH):
    evo_id = f"evo-{uuid.uuid4().hex[:8]}"
    _write_event(chain_path, {
        "ts": _now(), "evo_id": evo_id,
        "phase": EvolutionPhase.SIGNAL,
        "department": department, "signals": signals,
    })
    return evo_id


def record_hypothesis(evo_id, hypothesis, proposed_change, chain_path=DEFAULT_CHAIN_PATH):
    _write_event(chain_path, {
        "ts": _now(), "evo_id": evo_id,
        "phase": EvolutionPhase.HYPOTHESIS,
        "hypothesis": hypothesis, "proposed_change": proposed_change,
    })


def record_attempt(evo_id, files_changed, diff_summary, chain_path=DEFAULT_CHAIN_PATH):
    _write_event(chain_path, {
        "ts": _now(), "evo_id": evo_id,
        "phase": EvolutionPhase.ATTEMPT,
        "files_changed": files_changed, "diff_summary": diff_summary,
        "blast_radius": len(files_changed),
    })


def record_outcome(evo_id, success, metrics_before, metrics_after, chain_path=DEFAULT_CHAIN_PATH):
    _write_event(chain_path, {
        "ts": _now(), "evo_id": evo_id,
        "phase": EvolutionPhase.OUTCOME,
        "success": success,
        "metrics_before": metrics_before, "metrics_after": metrics_after,
    })


def load_chain(chain_path=DEFAULT_CHAIN_PATH):
    path = Path(chain_path)
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").strip().split("\n"):
        if line.strip():
            events.append(json.loads(line))
    return events


def get_department_history(chain_path, department):
    events = load_chain(chain_path)
    return [e for e in events if e.get("phase") == EvolutionPhase.SIGNAL and e.get("department") == department]
