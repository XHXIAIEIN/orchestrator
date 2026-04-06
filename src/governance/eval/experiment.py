"""
Experiment Ledger — Score-Driven Keep/Discard Loop (R38 — stolen from AutoAgent).

"If `passed` improved → keep. Same score but simpler → keep. Otherwise → discard."

Tracks configuration experiments with versioned snapshots:
  - Each experiment records: config snapshot, eval score, cost, decision
  - Keep/Discard logic is automatic based on score comparison
  - Ledger is append-only JSONL for full auditability
  - "Simplicity as tiebreaker": same score + fewer tokens = keep

Integrates with:
  - scoring.py  → ScoringResult for eval scores
  - corpus.py   → failed experiments feed into eval corpus
  - Clawvard    → exam scores as the primary improvement signal

Usage:
    ledger = ExperimentLedger()

    # Before modifying config, snapshot the current state
    baseline = ledger.current_best()

    # After modification, evaluate and decide
    result = ledger.record_experiment(
        name="prompt_v3_shorter_system",
        config_snapshot={"system_prompt": "...", "tools": [...]},
        score=0.87,
        cost_usd=0.12,
        metadata={"trigger": "clawvard_exam", "exam_id": 42},
    )
    # ExperimentResult(decision="keep", reason="score improved 0.82 → 0.87")

    # If score dropped, auto-discard:
    result = ledger.record_experiment(
        name="prompt_v4_aggressive",
        config_snapshot={...},
        score=0.79,
        cost_usd=0.15,
    )
    # ExperimentResult(decision="discard", reason="score regressed 0.87 → 0.79")
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

log = logging.getLogger(__name__)

# Default ledger location
LEDGER_DIR = Path(__file__).parent.parent.parent.parent / "data" / "experiments"

# Decision types
Decision = Literal["keep", "discard", "baseline"]


@dataclass
class ConfigSnapshot:
    """Frozen snapshot of an agent configuration at a point in time.

    Not a diff — the full state, so rollback doesn't depend on history chain.
    """
    prompt_hash: str = ""             # SHA-256[:16] of system prompt text
    prompt_length: int = 0            # token proxy: char count of system prompt
    tool_count: int = 0               # number of tools registered
    model: str = ""                   # model identifier
    extra: dict = field(default_factory=dict)  # anything else worth tracking

    @property
    def complexity_score(self) -> int:
        """Simple complexity metric: prompt length + tool count × 100.

        Used for "simplicity as tiebreaker" — same eval score, pick the simpler one.
        """
        return self.prompt_length + self.tool_count * 100

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> ConfigSnapshot:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ExperimentEntry:
    """One row in the experiment ledger."""
    name: str                         # human-readable experiment name
    timestamp: str                    # ISO 8601
    config: ConfigSnapshot            # full config at this point
    score: float                      # primary eval score (0-1)
    cost_usd: float = 0.0            # cost of running this evaluation
    decision: Decision = "baseline"   # keep / discard / baseline
    reason: str = ""                  # why this decision was made
    metadata: dict = field(default_factory=dict)  # trigger, exam_id, etc.
    commit_hash: str = ""             # git commit if available

    def to_dict(self) -> dict:
        d = asdict(self)
        d["config"] = self.config.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> ExperimentEntry:
        d = dict(d)
        if isinstance(d.get("config"), dict):
            d["config"] = ConfigSnapshot.from_dict(d["config"])
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ExperimentResult:
    """Return value from record_experiment()."""
    decision: Decision
    reason: str
    entry: ExperimentEntry
    baseline_score: float | None = None  # what we compared against


class ExperimentLedger:
    """Append-only experiment ledger with keep/discard logic.

    Core rule (from AutoAgent program.md):
      1. score improved → keep
      2. score same + config simpler → keep
      3. otherwise → discard

    Anti-overfitting test: "If this exact task disappeared, would this still
    be a worthwhile config improvement?" — enforced by caller, not ledger.
    """

    def __init__(self, ledger_dir: Path | None = None, department: str | None = None):
        self._dir = ledger_dir or LEDGER_DIR
        if department:
            self._dir = self._dir / department  # data/experiments/engineering/
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file = self._dir / "ledger.jsonl"
        self._entries: list[ExperimentEntry] | None = None  # lazy load

    @property
    def entries(self) -> list[ExperimentEntry]:
        """All experiment entries, loaded lazily."""
        if self._entries is None:
            self._entries = self._load()
        return self._entries

    def current_best(self) -> ExperimentEntry | None:
        """The most recent 'keep' or 'baseline' entry = current active config."""
        for entry in reversed(self.entries):
            if entry.decision in ("keep", "baseline"):
                return entry
        return None

    def record_baseline(
        self,
        name: str,
        config: ConfigSnapshot | dict,
        score: float,
        cost_usd: float = 0.0,
        metadata: dict | None = None,
        commit_hash: str = "",
    ) -> ExperimentEntry:
        """Record the initial baseline (first entry, or hard reset)."""
        if isinstance(config, dict):
            config = ConfigSnapshot.from_dict(config)

        entry = ExperimentEntry(
            name=name,
            timestamp=datetime.now(timezone.utc).isoformat(),
            config=config,
            score=score,
            cost_usd=cost_usd,
            decision="baseline",
            reason="initial baseline",
            metadata=metadata or {},
            commit_hash=commit_hash,
        )
        self._append(entry)
        log.info(f"experiment: baseline recorded — {name} (score={score:.3f})")
        return entry

    def record_experiment(
        self,
        name: str,
        config: ConfigSnapshot | dict,
        score: float,
        cost_usd: float = 0.0,
        metadata: dict | None = None,
        commit_hash: str = "",
    ) -> ExperimentResult:
        """Record an experiment and auto-decide keep/discard.

        Decision logic (stolen from AutoAgent program.md):
          1. No baseline exists → this becomes baseline
          2. Score improved → keep
          3. Score same + simpler config → keep (simplicity tiebreaker)
          4. Otherwise → discard
        """
        if isinstance(config, dict):
            config = ConfigSnapshot.from_dict(config)

        baseline = self.current_best()

        # No baseline → this is the baseline
        if baseline is None:
            entry = self.record_baseline(name, config, score, cost_usd, metadata, commit_hash)
            return ExperimentResult(
                decision="baseline",
                reason="no prior baseline, establishing this as baseline",
                entry=entry,
                baseline_score=None,
            )

        baseline_score = baseline.score
        decision: Decision
        reason: str

        if score > baseline_score:
            # Rule 1: score improved → keep
            decision = "keep"
            reason = f"score improved {baseline_score:.3f} → {score:.3f} (+{score - baseline_score:.3f})"

        elif score == baseline_score:
            # Rule 2: same score, check simplicity
            if config.complexity_score < baseline.config.complexity_score:
                decision = "keep"
                delta = baseline.config.complexity_score - config.complexity_score
                reason = f"score tied at {score:.3f}, but config is simpler (complexity -{delta})"
            else:
                decision = "discard"
                reason = f"score tied at {score:.3f} and config is not simpler"

        else:
            # Rule 3: score regressed → discard
            decision = "discard"
            reason = f"score regressed {baseline_score:.3f} → {score:.3f} ({score - baseline_score:+.3f})"

        entry = ExperimentEntry(
            name=name,
            timestamp=datetime.now(timezone.utc).isoformat(),
            config=config,
            score=score,
            cost_usd=cost_usd,
            decision=decision,
            reason=reason,
            metadata=metadata or {},
            commit_hash=commit_hash,
        )
        self._append(entry)

        emoji = "✓" if decision == "keep" else "✗"
        log.info(f"experiment: {emoji} {decision} — {name} ({reason})")

        return ExperimentResult(
            decision=decision,
            reason=reason,
            entry=entry,
            baseline_score=baseline_score,
        )

    def history(self, limit: int = 50) -> list[ExperimentEntry]:
        """Recent experiment history, newest first."""
        return list(reversed(self.entries[-limit:]))

    def stats(self) -> dict:
        """Summary statistics for the ledger."""
        entries = self.entries
        if not entries:
            return {"total": 0}

        kept = [e for e in entries if e.decision == "keep"]
        discarded = [e for e in entries if e.decision == "discard"]
        best = self.current_best()

        return {
            "total": len(entries),
            "kept": len(kept),
            "discarded": len(discarded),
            "keep_rate": len(kept) / max(len(kept) + len(discarded), 1),
            "current_best_score": best.score if best else None,
            "current_best_name": best.name if best else None,
            "total_cost_usd": sum(e.cost_usd for e in entries),
        }

    # ── Persistence ─────────────────────────────────────────

    def _append(self, entry: ExperimentEntry):
        """Append entry to ledger file and in-memory cache."""
        with open(self._file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry.to_dict(), ensure_ascii=False, default=str) + "\n")
        if self._entries is not None:
            self._entries.append(entry)

    def _load(self) -> list[ExperimentEntry]:
        """Load all entries from ledger file."""
        if not self._file.exists():
            return []

        entries = []
        try:
            with open(self._file, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    entries.append(ExperimentEntry.from_dict(json.loads(line)))
        except Exception as e:
            log.warning(f"experiment: error loading ledger: {e}")

        log.info(f"experiment: loaded {len(entries)} entries from ledger")
        return entries
