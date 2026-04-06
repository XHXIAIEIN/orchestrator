"""
Production → Test Feedback Loop (R38 — stolen from Braintrust).

"Pull interesting production traces into datasets to improve offline test coverage."

When Governor dispatch fails, automatically captures:
  - task description + spec
  - agent output + failure reason
  - trajectory (tool calls)
  - execution snapshot summary

Stores in data/eval_corpus/ as versioned JSONL files.
Clawvard exam system can pull from this corpus to generate real-world test cases.

Capture criteria (not all failures are worth saving):
  - stuck / doom_loop — agent got confused (high educational value)
  - gate_failed — output violated quality gates
  - scrutiny_failed — task itself was problematic
  - failed with non-trivial output — agent tried but couldn't finish
  - Excluded: timeout (often transient), empty output (nothing to learn from)

Usage:
    # In ReviewManager.finalize_task():
    if status in CAPTURABLE_STATUSES:
        capture_for_corpus(task_id, task, output, status, trajectory=traj)

    # In Clawvard exam runner:
    corpus = load_corpus()
    fresh_questions = corpus.to_exam_questions(max_questions=20)
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Directory for eval corpus data
CORPUS_DIR = Path(__file__).parent.parent.parent.parent / "data" / "eval_corpus"

# Statuses worth capturing (high educational value)
CAPTURABLE_STATUSES = {"failed", "stuck", "doom_loop", "gate_failed", "scrutiny_failed"}

# Statuses excluded (transient or empty)
EXCLUDED_STATUSES = {"timeout", "terminated"}

# Maximum corpus entries per file (rotate at this count)
MAX_ENTRIES_PER_FILE = 500

# Minimum output length to be worth capturing
MIN_OUTPUT_LENGTH = 50


@dataclass
class CorpusEntry:
    """One entry in the eval corpus — a captured production failure."""
    task_id: int
    captured_at: str                          # ISO 8601
    status: str                               # failed / stuck / doom_loop / gate_failed
    action: str                               # task description
    department: str                           # which department handled it
    priority: str                             # low / medium / high
    failure_reason: str                       # why it failed
    agent_output: str                         # what the agent produced (truncated)
    spec: dict = field(default_factory=dict)  # full task spec
    trajectory_summary: dict = field(default_factory=dict)  # tool call summary
    content_hash: str = ""                    # SHA-256 for dedup
    tags: list[str] = field(default_factory=list)  # auto-generated tags

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> CorpusEntry:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ── Capture Logic ─────────────────────────────────────────────


def capture_for_corpus(
    task_id: int,
    task: dict,
    output: str,
    status: str,
    trajectory_summary: dict | None = None,
    corpus_dir: Path | None = None,
) -> Optional[Path]:
    """Capture a failed task as a corpus entry.

    Returns the corpus file path if captured, None if skipped.
    """
    corpus_dir = corpus_dir or CORPUS_DIR

    # Filter: only capture educational failures
    if status not in CAPTURABLE_STATUSES:
        return None

    # Filter: need meaningful output to learn from
    if not output or len(output.strip()) < MIN_OUTPUT_LENGTH:
        log.debug(f"corpus: skipping task #{task_id} — output too short ({len(output)} chars)")
        return None

    spec = task.get("spec", {})
    if isinstance(spec, str):
        try:
            spec = json.loads(spec)
        except (json.JSONDecodeError, TypeError):
            spec = {"raw": spec}

    action = task.get("action", "")
    department = spec.get("department", "unknown")
    priority = task.get("priority", "medium")

    # Extract failure reason from output
    failure_reason = _extract_failure_reason(output, status)

    # Auto-tag based on content
    tags = _auto_tag(action, output, status, department)

    # Content hash for dedup
    content_hash = hashlib.sha256(
        f"{action}:{failure_reason}:{status}".encode("utf-8")
    ).hexdigest()[:16]

    entry = CorpusEntry(
        task_id=task_id,
        captured_at=datetime.now(timezone.utc).isoformat(),
        status=status,
        action=action[:500],
        department=department,
        priority=priority,
        failure_reason=failure_reason[:500],
        agent_output=output[:2000],  # cap output to avoid bloat
        spec={k: v for k, v in spec.items() if k in (
            "summary", "department", "problem", "source", "tier", "mode",
            "expected", "constraints",
        )},
        trajectory_summary=trajectory_summary or {},
        content_hash=content_hash,
        tags=tags,
    )

    # Dedup check: don't capture near-duplicates
    corpus_file = _get_current_corpus_file(corpus_dir)
    if _is_duplicate(entry, corpus_file):
        log.debug(f"corpus: skipping task #{task_id} — duplicate of existing entry")
        return None

    # Write entry
    return _append_entry(entry, corpus_dir)


def _extract_failure_reason(output: str, status: str) -> str:
    """Extract the most informative failure reason from agent output."""
    # Look for explicit failure markers
    markers = [
        "[GATE FAILED]", "[COUNCIL: REJECT]", "[CROSS-REVIEW: DISAGREE]",
        "[WATCHDOG:", "[STUCK]", "[DOOM LOOP]", "Error:", "error:",
        "VERDICT: FAIL",
    ]
    for marker in markers:
        idx = output.find(marker)
        if idx >= 0:
            # Extract up to 200 chars after the marker
            return output[idx:idx + 200].strip()

    # Fallback: last 200 chars (often contain the conclusion)
    return output[-200:].strip() if len(output) > 200 else output.strip()


def _auto_tag(action: str, output: str, status: str, department: str) -> list[str]:
    """Generate tags for corpus search/filtering.

    Two tag dimensions (R38 — stolen from AutoAgent failure classification):
      1. Symptom tags — WHAT went wrong (timeout, permission, import error...)
      2. Root-cause tags — WHY it went wrong (misunderstanding, weak exploration...)
    Both layers coexist so we can answer "what happened" and "how to fix the class".
    """
    tags = [status, department]

    lower_output = output.lower()
    lower_action = action.lower()

    # ── Symptom tags (what went wrong) ──────────────────────
    if "timeout" in lower_output:
        tags.append("timeout_related")
    if "permission" in lower_output or "denied" in lower_output:
        tags.append("permission_error")
    if "import" in lower_output and "error" in lower_output:
        tags.append("import_error")
    if "stuck" in lower_output or "loop" in lower_output:
        tags.append("stuck_loop")
    if "hallucin" in lower_output or "claimed" in lower_output:
        tags.append("hallucination")
    if "token" in lower_output and ("limit" in lower_output or "budget" in lower_output):
        tags.append("token_limit")

    # ── Root-cause tags (why it went wrong) — R38 AutoAgent ─
    # misunderstanding: agent interpreted the task wrong
    if any(kw in lower_output for kw in [
        "误解", "wrong interpretation", "不是要求的", "misunderstood",
        "that's not what", "off-topic", "偏题",
    ]):
        tags.append("rc:misunderstanding")

    # missing_tool: agent needed a capability it didn't have
    if any(kw in lower_output for kw in [
        "no tool", "not available", "不支持", "missing tool",
        "no such command", "command not found", "未安装",
    ]):
        tags.append("rc:missing_tool")

    # weak_exploration: didn't read enough / assumed too much
    if any(kw in lower_output for kw in [
        "didn't read", "没检查", "assumed", "should have checked",
        "没看", "didn't check", "skipped reading",
    ]):
        tags.append("rc:weak_exploration")

    # strategy_error: wrong approach / methodology
    if any(kw in lower_output for kw in [
        "wrong approach", "应该用", "更好的方式", "better approach",
        "should have used", "方法不对",
    ]):
        tags.append("rc:strategy_error")

    # silent_failure: agent claimed success but actually failed
    if any(kw in lower_output for kw in [
        "以为成功", "actually failed", "output mismatch",
        "claimed complete", "but the test", "looks correct but",
    ]):
        tags.append("rc:silent_failure")

    # verification_gap: didn't verify results before declaring done
    if any(kw in lower_output for kw in [
        "没验证", "didn't verify", "claimed complete",
        "should have tested", "没测试", "no verification",
    ]):
        tags.append("rc:verification_gap")

    # ── Task-type tags ──────────────────────────────────────
    if any(kw in lower_action for kw in ["fix", "bug", "修"]):
        tags.append("bugfix")
    if any(kw in lower_action for kw in ["refactor", "重构"]):
        tags.append("refactor")
    if any(kw in lower_action for kw in ["review", "审", "评"]):
        tags.append("review")
    if any(kw in lower_action for kw in ["偷师", "steal", "research"]):
        tags.append("research")

    return sorted(set(tags))


# ── Storage ───────────────────────────────────────────────────


def _get_current_corpus_file(corpus_dir: Path) -> Path:
    """Get the current corpus JSONL file (rotates when full)."""
    corpus_dir.mkdir(parents=True, exist_ok=True)

    # Find latest corpus file
    files = sorted(corpus_dir.glob("corpus_*.jsonl"))
    if files:
        latest = files[-1]
        # Check if it's full
        try:
            line_count = sum(1 for _ in open(latest, "r", encoding="utf-8"))
            if line_count < MAX_ENTRIES_PER_FILE:
                return latest
        except Exception:
            pass

    # Create new file
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    seq = len(files) + 1
    return corpus_dir / f"corpus_{timestamp}_{seq:03d}.jsonl"


def _is_duplicate(entry: CorpusEntry, corpus_file: Path) -> bool:
    """Check if a near-duplicate entry already exists."""
    if not corpus_file.exists():
        return False

    try:
        with open(corpus_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                existing = json.loads(line)
                if existing.get("content_hash") == entry.content_hash:
                    return True
        return False
    except Exception:
        return False


def _append_entry(entry: CorpusEntry, corpus_dir: Path) -> Path:
    """Append entry to the current corpus file."""
    corpus_file = _get_current_corpus_file(corpus_dir)
    corpus_dir.mkdir(parents=True, exist_ok=True)

    with open(corpus_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry.to_dict(), ensure_ascii=False, default=str) + "\n")

    log.info(
        f"corpus: captured task #{entry.task_id} ({entry.status}) → {corpus_file.name} "
        f"[tags: {', '.join(entry.tags[:5])}]"
    )
    return corpus_file


# ── Loading / Query ───────────────────────────────────────────


@dataclass
class EvalCorpus:
    """Loaded eval corpus with query methods."""
    entries: list[CorpusEntry] = field(default_factory=list)

    def filter_by_tag(self, tag: str) -> list[CorpusEntry]:
        return [e for e in self.entries if tag in e.tags]

    def filter_by_status(self, status: str) -> list[CorpusEntry]:
        return [e for e in self.entries if e.status == status]

    def filter_by_department(self, dept: str) -> list[CorpusEntry]:
        return [e for e in self.entries if e.department == dept]

    def to_exam_questions(self, max_questions: int = 20) -> list[dict]:
        """Convert corpus entries to Clawvard-compatible exam questions.

        Each entry becomes a task scenario that the agent must handle correctly.
        """
        questions = []
        for entry in self.entries[:max_questions]:
            questions.append({
                "type": "scenario",
                "prompt": (
                    f"你收到以下任务：\n{entry.action}\n\n"
                    f"上次执行时失败了 ({entry.status})，原因：\n{entry.failure_reason}\n\n"
                    f"请分析失败原因并给出正确的执行策略。"
                ),
                "tags": entry.tags,
                "difficulty": _estimate_difficulty(entry),
                "source_task_id": entry.task_id,
            })
        return questions

    def to_exam_cases(
        self,
        department: str,
        division: str | None = None,
        max_cases: int = 30,
    ) -> list[dict]:
        """Generate exam cases from corpus entries.

        For failures: "here's what went wrong, do better"
        For successes: "here's a golden example, match this quality"

        Returns exam_cases.jsonl compatible dicts.
        """
        entries = self.filter_by_department(department)
        if division:
            entries = [e for e in entries if division in e.tags or not division]

        cases = []
        for entry in entries[:max_cases]:
            is_success = entry.status == "sampled_success"

            if is_success:
                expected = (
                    f"Match the quality of this golden example. "
                    f"Output scored {entry.spec.get('score', 'high')} on eval."
                )
            else:
                expected = (
                    f"Avoid the failure mode: {entry.failure_reason[:200]}. "
                    f"Previous attempt failed with status '{entry.status}'."
                )

            cases.append({
                "id": f"corpus-{entry.task_id}",
                "input": entry.action,
                "expected_behavior": expected,
                "tags": entry.tags,
                "source": f"corpus:{entry.task_id}",
                "difficulty": _estimate_difficulty(entry),
            })

        return cases

    @property
    def stats(self) -> dict:
        """Corpus statistics."""
        from collections import Counter
        status_counts = Counter(e.status for e in self.entries)
        dept_counts = Counter(e.department for e in self.entries)
        tag_counts = Counter(t for e in self.entries for t in e.tags)
        return {
            "total_entries": len(self.entries),
            "by_status": dict(status_counts),
            "by_department": dict(dept_counts),
            "top_tags": dict(tag_counts.most_common(10)),
        }


def _estimate_difficulty(entry: CorpusEntry) -> str:
    """Estimate question difficulty from the failure pattern."""
    if entry.status == "doom_loop":
        return "hard"  # cyclic failures are hardest
    if entry.status == "gate_failed":
        return "medium"
    if "hallucination" in entry.tags:
        return "hard"
    if "stuck_loop" in entry.tags:
        return "hard"
    return "medium"


def capture_success_for_corpus(
    task_id: int,
    task: dict,
    output: str,
    score: float,
    criteria_scores: dict | None = None,
    corpus_dir: Path | None = None,
) -> Optional[Path]:
    """Capture a successful task as a golden example.

    Only called for sampled tasks (5% of successes).
    Stores in sample_*.jsonl alongside failure corpus_*.jsonl.
    """
    corpus_dir = corpus_dir or CORPUS_DIR
    corpus_dir.mkdir(parents=True, exist_ok=True)

    if not output or len(output.strip()) < MIN_OUTPUT_LENGTH:
        return None

    spec = task.get("spec", {})
    if isinstance(spec, str):
        try:
            spec = json.loads(spec)
        except (json.JSONDecodeError, TypeError):
            spec = {"raw": spec}

    action = task.get("action", "")
    department = spec.get("department", "unknown")

    content_hash = hashlib.sha256(
        f"success:{action}:{task_id}".encode("utf-8")
    ).hexdigest()[:16]

    entry = CorpusEntry(
        task_id=task_id,
        captured_at=datetime.now(timezone.utc).isoformat(),
        status="sampled_success",
        action=action[:500],
        department=department,
        priority=task.get("priority", "medium"),
        failure_reason="",  # success, no failure
        agent_output=output[:2000],
        spec={
            **{k: v for k, v in spec.items() if k in (
                "summary", "department", "problem", "source", "tier", "mode",
            )},
            "score": score,
            "criteria_scores": criteria_scores or {},
        },
        trajectory_summary={},
        content_hash=content_hash,
        tags=_auto_tag(action, output, "sampled_success", department),
    )

    # Write to sample file (separate from failure corpus)
    sample_file = _get_sample_file(corpus_dir)
    with open(sample_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry.to_dict(), ensure_ascii=False, default=str) + "\n")

    log.info(
        f"corpus: sampled success task #{task_id} (score={score:.3f}) "
        f"→ {sample_file.name}"
    )
    return sample_file


def _get_sample_file(corpus_dir: Path) -> Path:
    """Get the current sample JSONL file."""
    corpus_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(corpus_dir.glob("sample_*.jsonl"))
    if files:
        latest = files[-1]
        try:
            line_count = sum(1 for _ in open(latest, "r", encoding="utf-8"))
            if line_count < MAX_ENTRIES_PER_FILE:
                return latest
        except Exception:
            pass

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    seq = len(files) + 1
    return corpus_dir / f"sample_{timestamp}_{seq:03d}.jsonl"


def load_corpus(corpus_dir: Path | None = None) -> EvalCorpus:
    """Load all corpus entries from disk (failures + sampled successes)."""
    corpus_dir = corpus_dir or CORPUS_DIR
    if not corpus_dir.exists():
        return EvalCorpus()

    entries = []
    # Load both corpus_*.jsonl (failures) and sample_*.jsonl (successes)
    for pattern in ["corpus_*.jsonl", "sample_*.jsonl"]:
        for f in sorted(corpus_dir.glob(pattern)):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    for line in fh:
                        if not line.strip():
                            continue
                        entries.append(CorpusEntry.from_dict(json.loads(line)))
            except Exception as e:
                log.warning(f"corpus: error reading {f}: {e}")

    log.info(f"corpus: loaded {len(entries)} entries from {corpus_dir}")
    return EvalCorpus(entries=entries)
