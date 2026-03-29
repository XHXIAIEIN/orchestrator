# ClawHub P0 偷师落地 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地 ClawHub 偷师 Round 14 的 5 个 P0 模式：WAL 写前日志、三分类错误日志、Pattern-Key 自动晋升、爆炸半径控制、四阶段进化审计链。

**Architecture:** 新增 `.learnings/` 三分类目录和 `SOUL/private/session-state.md` WAL 文件。扩展现有 manifest.yaml schema 加 blast_radius 约束。升级 `evolution_state.json` 为 `evolution_events.jsonl` 追加写审计链。新增 `src/governance/audit/learnings.py` 管理错误分类和 Pattern-Key 晋升。

**Tech Stack:** Python 3.14, pytest, existing SOUL/tools/compiler.py, existing hook infrastructure

**Source:** ClawHub Round 14 偷师 — self-improving-agent / proactive-agent / evolver

---

## File Structure

```
.learnings/LEARNINGS.md                    — NEW: 知识更新/最佳实践
.learnings/ERRORS.md                       — NEW: 工具/API/执行错误分类
.learnings/FEATURES.md                     — NEW: 能力缺口记录
SOUL/private/session-state.md              — NEW: WAL 写前日志
src/governance/audit/learnings.py          — NEW: 三分类管理 + Pattern-Key 晋升
src/governance/audit/evolution_chain.py    — NEW: 四阶段进化审计链
departments/*/manifest.yaml                — MODIFY: 加 blast_radius 约束
src/governance/audit/run_logger.py         — MODIFY: 在 append_run_log 中触发 error 分类
tests/test_learnings.py                    — NEW: learnings 模块测试
tests/test_evolution_chain.py              — NEW: 进化审计链测试
tests/test_blast_radius.py                 — NEW: 爆炸半径约束测试
```

---

### Task 1: 三分类错误日志 — 数据层

**Files:**
- Create: `.learnings/LEARNINGS.md`
- Create: `.learnings/ERRORS.md`
- Create: `.learnings/FEATURES.md`
- Create: `src/governance/audit/learnings.py`
- Create: `tests/test_learnings.py`

偷自 self-improving-agent 的三文件分层模式：LEARNINGS（知识更新）、ERRORS（执行错误）、FEATURES（能力缺口），每条带 Pattern-Key + Occurrences 计数。

- [ ] **Step 1: Create the three classification files**

`.learnings/LEARNINGS.md`:
```markdown
# Learnings

Hard-won knowledge updates and best practices, auto-captured from run history.
Format: `LRN-YYYYMMDD-NNN` with Pattern-Key for dedup and promotion tracking.

<!-- entries below this line are auto-managed -->
```

`.learnings/ERRORS.md`:
```markdown
# Errors

Classified execution errors from tool calls, API failures, and task timeouts.
Format: `ERR-YYYYMMDD-NNN` with Pattern-Key for recurring pattern detection.

<!-- entries below this line are auto-managed -->
```

`.learnings/FEATURES.md`:
```markdown
# Feature Requests

Capability gaps discovered during task execution — things the system couldn't do.
Format: `FTR-YYYYMMDD-NNN` with Pattern-Key for demand tracking.

<!-- entries below this line are auto-managed -->
```

- [ ] **Step 2: Write failing tests for learnings module**

```python
# tests/test_learnings.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from unittest.mock import patch
from src.governance.audit.learnings import (
    LearningEntry, append_learning, append_error, append_feature,
    get_pattern_occurrences, get_promotable_entries,
)


def test_append_error_creates_entry(tmp_path):
    errors_md = tmp_path / "ERRORS.md"
    errors_md.write_text("# Errors\n\n<!-- entries below this line are auto-managed -->\n")

    entry = append_error(
        pattern_key="docker-rebuild-unnecessary",
        summary="Rebuilt Docker image when only config changed",
        detail="Task failed because full rebuild took 5 min; config-only change needs restart not rebuild.",
        area="operations",
        file_path=str(errors_md),
    )

    assert entry.entry_id.startswith("ERR-")
    assert entry.pattern_key == "docker-rebuild-unnecessary"
    assert entry.occurrences == 1
    assert "docker-rebuild-unnecessary" in errors_md.read_text()


def test_append_error_increments_occurrences(tmp_path):
    errors_md = tmp_path / "ERRORS.md"
    errors_md.write_text("# Errors\n\n<!-- entries below this line are auto-managed -->\n")

    append_error("timeout-on-large-query", "Query timed out", "SQL took >30s", "engineering", str(errors_md))
    append_error("timeout-on-large-query", "Query timed out again", "Same pattern", "engineering", str(errors_md))
    entry = append_error("timeout-on-large-query", "Third timeout", "Still happening", "engineering", str(errors_md))

    assert entry.occurrences == 3


def test_append_learning(tmp_path):
    learn_md = tmp_path / "LEARNINGS.md"
    learn_md.write_text("# Learnings\n\n<!-- entries below this line are auto-managed -->\n")

    entry = append_learning(
        pattern_key="pnpm-not-npm",
        summary="Project uses pnpm, not npm",
        detail="Always check lockfile before assuming package manager.",
        area="config",
        file_path=str(learn_md),
    )

    assert entry.entry_id.startswith("LRN-")
    assert entry.status == "active"


def test_get_promotable_entries(tmp_path):
    errors_md = tmp_path / "ERRORS.md"
    errors_md.write_text("# Errors\n\n<!-- entries below this line are auto-managed -->\n")

    for _ in range(3):
        append_error("repeated-mistake", "Same error", "Details", "engineering", str(errors_md))

    promotable = get_promotable_entries(str(errors_md), threshold=3)
    assert len(promotable) == 1
    assert promotable[0].pattern_key == "repeated-mistake"


def test_get_pattern_occurrences(tmp_path):
    errors_md = tmp_path / "ERRORS.md"
    errors_md.write_text("# Errors\n\n<!-- entries below this line are auto-managed -->\n")

    append_error("some-pattern", "Error A", "Detail", "ops", str(errors_md))
    append_error("some-pattern", "Error B", "Detail", "ops", str(errors_md))

    assert get_pattern_occurrences(str(errors_md), "some-pattern") == 2
    assert get_pattern_occurrences(str(errors_md), "nonexistent") == 0
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/test_learnings.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.governance.audit.learnings'`

- [ ] **Step 4: Implement learnings.py**

```python
# src/governance/audit/learnings.py
"""
三分类错误日志 — 偷自 self-improving-agent 的 .learnings/ 模式。

三个文件分类存储：LEARNINGS（知识）、ERRORS（错误）、FEATURES（缺口）。
每条带 Pattern-Key 做去重和出现次数追踪，满阈值触发晋升。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

MARKER = "<!-- entries below this line are auto-managed -->"

# Counters for generating sequential IDs within a session
_counters: dict[str, int] = {}


@dataclass
class LearningEntry:
    entry_id: str           # e.g. ERR-20260330-001
    pattern_key: str        # stable semantic key for dedup
    summary: str
    detail: str
    area: str               # department or domain
    occurrences: int = 1
    status: str = "active"  # active | promoted | archived
    first_seen: str = ""
    last_seen: str = ""


def _next_id(prefix: str) -> str:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    key = f"{prefix}-{today}"
    _counters[key] = _counters.get(key, 0) + 1
    return f"{prefix}-{today}-{_counters[key]:03d}"


def _parse_entries(text: str) -> list[dict]:
    """Parse structured entries from markdown file."""
    entries = []
    current = None
    for line in text.split("\n"):
        m = re.match(r"^## ((?:ERR|LRN|FTR)-\d{8}-\d{3}) — (.+)$", line)
        if m:
            if current:
                entries.append(current)
            current = {"id": m.group(1), "summary": m.group(2), "lines": []}
            continue
        if current is not None:
            current["lines"].append(line)
            pk = re.match(r"^- Pattern-Key: (.+)$", line)
            if pk:
                current["pattern_key"] = pk.group(1)
            occ = re.match(r"^- Occurrences: (\d+)$", line)
            if occ:
                current["occurrences"] = int(occ.group(1))
            st = re.match(r"^- Status: (.+)$", line)
            if st:
                current["status"] = st.group(1)
    if current:
        entries.append(current)
    return entries


def _format_entry(e: LearningEntry) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    return (
        f"\n## {e.entry_id} — {e.summary}\n"
        f"- Pattern-Key: {e.pattern_key}\n"
        f"- Area: {e.area}\n"
        f"- Occurrences: {e.occurrences}\n"
        f"- Status: {e.status}\n"
        f"- First-seen: {e.first_seen}\n"
        f"- Last-seen: {e.last_seen}\n"
        f"- Detail: {e.detail}\n"
    )


def _append_to_file(
    prefix: str,
    pattern_key: str,
    summary: str,
    detail: str,
    area: str,
    file_path: str,
) -> LearningEntry:
    path = Path(file_path)
    text = path.read_text(encoding="utf-8")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    # Check if pattern_key already exists — increment occurrences
    entries = _parse_entries(text)
    for existing in entries:
        if existing.get("pattern_key") == pattern_key:
            old_occ = existing.get("occurrences", 1)
            new_occ = old_occ + 1
            text = text.replace(
                f"- Occurrences: {old_occ}",
                f"- Occurrences: {new_occ}",
                1,
            )
            text = re.sub(
                r"(- Last-seen: ).+",
                f"\\g<1>{now}",
                text,
                count=1,
            )
            path.write_text(text, encoding="utf-8")
            return LearningEntry(
                entry_id=existing["id"],
                pattern_key=pattern_key,
                summary=summary,
                detail=detail,
                area=area,
                occurrences=new_occ,
                status=existing.get("status", "active"),
                first_seen="",
                last_seen=now,
            )

    # New entry
    entry = LearningEntry(
        entry_id=_next_id(prefix),
        pattern_key=pattern_key,
        summary=summary,
        detail=detail,
        area=area,
        occurrences=1,
        status="active",
        first_seen=now,
        last_seen=now,
    )
    formatted = _format_entry(entry)

    if MARKER in text:
        text = text.replace(MARKER, MARKER + formatted)
    else:
        text += formatted

    path.write_text(text, encoding="utf-8")
    return entry


def append_error(pattern_key: str, summary: str, detail: str, area: str, file_path: str) -> LearningEntry:
    return _append_to_file("ERR", pattern_key, summary, detail, area, file_path)


def append_learning(pattern_key: str, summary: str, detail: str, area: str, file_path: str) -> LearningEntry:
    return _append_to_file("LRN", pattern_key, summary, detail, area, file_path)


def append_feature(pattern_key: str, summary: str, detail: str, area: str, file_path: str) -> LearningEntry:
    return _append_to_file("FTR", pattern_key, summary, detail, area, file_path)


def get_pattern_occurrences(file_path: str, pattern_key: str) -> int:
    text = Path(file_path).read_text(encoding="utf-8")
    entries = _parse_entries(text)
    for e in entries:
        if e.get("pattern_key") == pattern_key:
            return e.get("occurrences", 1)
    return 0


def get_promotable_entries(file_path: str, threshold: int = 3) -> list[LearningEntry]:
    """Return entries with occurrences >= threshold that haven't been promoted yet."""
    text = Path(file_path).read_text(encoding="utf-8")
    entries = _parse_entries(text)
    result = []
    for e in entries:
        occ = e.get("occurrences", 1)
        status = e.get("status", "active")
        if occ >= threshold and status == "active":
            result.append(LearningEntry(
                entry_id=e["id"],
                pattern_key=e.get("pattern_key", ""),
                summary=e.get("summary", ""),
                detail="",
                area="",
                occurrences=occ,
                status=status,
            ))
    return result
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/test_learnings.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add .learnings/ src/governance/audit/learnings.py tests/test_learnings.py
git commit -m "feat(learnings): three-category error logging with Pattern-Key tracking — stolen from self-improving-agent"
```

---

### Task 2: 爆炸半径控制

**Files:**
- Modify: `departments/engineering/manifest.yaml`
- Modify: `departments/operations/manifest.yaml`
- Modify: `departments/quality/manifest.yaml`
- Modify: `departments/personnel/manifest.yaml`
- Modify: `departments/security/manifest.yaml`
- Modify: `departments/protocol/manifest.yaml`
- Create: `tests/test_blast_radius.py`

偷自 evolver 的 blast radius constraint：每次执行有文件数上限，防止单次改动影响过广。

- [ ] **Step 1: Write failing test for blast radius validation**

```python
# tests/test_blast_radius.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml
import pytest


def load_manifest(dept: str) -> dict:
    manifest_path = Path(__file__).parent.parent / "departments" / dept / "manifest.yaml"
    return yaml.safe_load(manifest_path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("dept", [
    "engineering", "operations", "quality", "personnel", "security", "protocol"
])
def test_manifest_has_blast_radius(dept):
    """Every department manifest must have blast_radius constraints."""
    manifest = load_manifest(dept)
    assert "blast_radius" in manifest, f"{dept} manifest missing blast_radius"
    br = manifest["blast_radius"]
    assert "max_files_per_run" in br
    assert isinstance(br["max_files_per_run"], int)
    assert br["max_files_per_run"] > 0


@pytest.mark.parametrize("dept,expected_max", [
    ("engineering", 15),
    ("operations", 8),
    ("quality", 5),
    ("personnel", 5),
    ("security", 8),
    ("protocol", 5),
])
def test_blast_radius_values(dept, expected_max):
    """Verify sensible blast radius limits per department."""
    manifest = load_manifest(dept)
    br = manifest["blast_radius"]
    assert br["max_files_per_run"] == expected_max


def test_blast_radius_check_function():
    """Test the blast radius check utility."""
    from src.governance.audit.learnings import check_blast_radius

    assert check_blast_radius(5, 10) is True   # under limit
    assert check_blast_radius(10, 10) is True   # at limit
    assert check_blast_radius(11, 10) is False  # over limit
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/test_blast_radius.py -v`
Expected: FAIL — `blast_radius` not in manifest

- [ ] **Step 3: Add blast_radius to all manifests**

Add this block to each department manifest.yaml after the `policy:` section:

**engineering** (MUTATE, broadest scope):
```yaml
# ── Blast Radius (偷自 evolver GEP constraint) ──
blast_radius:
  max_files_per_run: 15      # engineering needs more room for features
  forbidden_paths: [".env", "*.key", "*.pem", "data/events.db", "SOUL/private/identity.md"]
```

**operations** (infra, moderate):
```yaml
blast_radius:
  max_files_per_run: 8
  forbidden_paths: [".env", "*.key", "*.pem", "data/events.db", "SOUL/private/identity.md"]
```

**quality** (READ + review, narrow):
```yaml
blast_radius:
  max_files_per_run: 5
  forbidden_paths: [".env", "*.key", "*.pem", "data/events.db", "SOUL/private/identity.md"]
```

**personnel** (READ + evaluation, narrow):
```yaml
blast_radius:
  max_files_per_run: 5
  forbidden_paths: [".env", "*.key", "*.pem", "data/events.db", "SOUL/private/identity.md"]
```

**security** (audit scope, moderate):
```yaml
blast_radius:
  max_files_per_run: 8
  forbidden_paths: [".env", "*.key", "*.pem", "data/events.db", "SOUL/private/identity.md"]
```

**protocol** (debt tracking, narrow):
```yaml
blast_radius:
  max_files_per_run: 5
  forbidden_paths: [".env", "*.key", "*.pem", "data/events.db", "SOUL/private/identity.md"]
```

- [ ] **Step 4: Add check_blast_radius to learnings.py**

Append to `src/governance/audit/learnings.py`:

```python
def check_blast_radius(file_count: int, max_files: int) -> bool:
    """Check if a run's file change count is within blast radius.

    Returns True if within limit, False if exceeded.
    """
    return file_count <= max_files
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/test_blast_radius.py -v`
Expected: 13 passed (6 has_blast_radius + 6 values + 1 function)

- [ ] **Step 6: Commit**

```bash
git add departments/*/manifest.yaml src/governance/audit/learnings.py tests/test_blast_radius.py
git commit -m "feat(manifests): add blast_radius constraints to all departments — stolen from evolver GEP"
```

---

### Task 3: 四阶段进化审计链

**Files:**
- Create: `src/governance/audit/evolution_chain.py`
- Create: `tests/test_evolution_chain.py`

偷自 evolver 的 Signal → Hypothesis → Attempt → Outcome 四阶段审计链，每次进化必须写完整因果记录。

- [ ] **Step 1: Write failing tests**

```python
# tests/test_evolution_chain.py
import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from src.governance.audit.evolution_chain import (
    EvolutionChain, EvolutionPhase,
    record_signal, record_hypothesis, record_attempt, record_outcome,
    load_chain, get_department_history,
)


def test_full_four_stage_chain(tmp_path):
    """A complete evolution must have all 4 stages."""
    chain_path = str(tmp_path / "evolution_events.jsonl")

    evo_id = record_signal(
        department="engineering",
        signals=["success_rate dropped to 0.6", "3 timeouts in last 10 runs"],
        chain_path=chain_path,
    )
    assert evo_id.startswith("evo-")

    record_hypothesis(
        evo_id=evo_id,
        hypothesis="Timeout threshold too low for large codebases",
        proposed_change="Increase timeout_s from 300 to 600",
        chain_path=chain_path,
    )

    record_attempt(
        evo_id=evo_id,
        files_changed=["departments/engineering/manifest.yaml"],
        diff_summary="timeout_s: 300 → 600",
        chain_path=chain_path,
    )

    record_outcome(
        evo_id=evo_id,
        success=True,
        metrics_before={"success_rate": 0.6},
        metrics_after={"success_rate": 0.85},
        chain_path=chain_path,
    )

    events = load_chain(chain_path)
    evo_events = [e for e in events if e["evo_id"] == evo_id]
    assert len(evo_events) == 4
    phases = [e["phase"] for e in evo_events]
    assert phases == ["signal", "hypothesis", "attempt", "outcome"]


def test_incomplete_chain_detected(tmp_path):
    """An evolution with missing stages should be detectable."""
    chain_path = str(tmp_path / "evolution_events.jsonl")

    evo_id = record_signal(
        department="quality",
        signals=["review findings dropped"],
        chain_path=chain_path,
    )
    # Only signal, no hypothesis/attempt/outcome
    events = load_chain(chain_path)
    evo_events = [e for e in events if e["evo_id"] == evo_id]
    assert len(evo_events) == 1
    assert evo_events[0]["phase"] == "signal"


def test_get_department_history(tmp_path):
    chain_path = str(tmp_path / "evolution_events.jsonl")

    evo1 = record_signal("engineering", ["signal A"], chain_path)
    record_outcome(evo1, True, {}, {}, chain_path)

    evo2 = record_signal("quality", ["signal B"], chain_path)
    record_outcome(evo2, False, {}, {}, chain_path)

    eng_history = get_department_history(chain_path, "engineering")
    assert len(eng_history) == 1
    assert eng_history[0]["evo_id"] == evo1

    qual_history = get_department_history(chain_path, "quality")
    assert len(qual_history) == 1
    assert qual_history[0]["evo_id"] == evo2


def test_chain_is_append_only(tmp_path):
    chain_path = str(tmp_path / "evolution_events.jsonl")
    record_signal("engineering", ["test"], chain_path)
    record_signal("operations", ["test2"], chain_path)

    lines = Path(chain_path).read_text().strip().split("\n")
    assert len(lines) == 2
    for line in lines:
        event = json.loads(line)
        assert "ts" in event
        assert "evo_id" in event
        assert "phase" in event
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/test_evolution_chain.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement evolution_chain.py**

```python
# src/governance/audit/evolution_chain.py
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


def _write_event(chain_path: str, event: dict) -> None:
    path = Path(chain_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_signal(
    department: str,
    signals: list[str],
    chain_path: str = DEFAULT_CHAIN_PATH,
) -> str:
    """Record the signal phase — what triggered the evolution consideration.

    Returns the evo_id for linking subsequent phases.
    """
    evo_id = f"evo-{uuid.uuid4().hex[:8]}"
    _write_event(chain_path, {
        "ts": _now(),
        "evo_id": evo_id,
        "phase": EvolutionPhase.SIGNAL,
        "department": department,
        "signals": signals,
    })
    return evo_id


def record_hypothesis(
    evo_id: str,
    hypothesis: str,
    proposed_change: str,
    chain_path: str = DEFAULT_CHAIN_PATH,
) -> None:
    """Record the hypothesis phase — why we think this change will help."""
    _write_event(chain_path, {
        "ts": _now(),
        "evo_id": evo_id,
        "phase": EvolutionPhase.HYPOTHESIS,
        "hypothesis": hypothesis,
        "proposed_change": proposed_change,
    })


def record_attempt(
    evo_id: str,
    files_changed: list[str],
    diff_summary: str,
    chain_path: str = DEFAULT_CHAIN_PATH,
) -> None:
    """Record the attempt phase — what was actually changed."""
    _write_event(chain_path, {
        "ts": _now(),
        "evo_id": evo_id,
        "phase": EvolutionPhase.ATTEMPT,
        "files_changed": files_changed,
        "diff_summary": diff_summary,
        "blast_radius": len(files_changed),
    })


def record_outcome(
    evo_id: str,
    success: bool,
    metrics_before: dict[str, Any],
    metrics_after: dict[str, Any],
    chain_path: str = DEFAULT_CHAIN_PATH,
) -> None:
    """Record the outcome phase — did it work?"""
    _write_event(chain_path, {
        "ts": _now(),
        "evo_id": evo_id,
        "phase": EvolutionPhase.OUTCOME,
        "success": success,
        "metrics_before": metrics_before,
        "metrics_after": metrics_after,
    })


def load_chain(chain_path: str = DEFAULT_CHAIN_PATH) -> list[dict]:
    """Load all events from the chain."""
    path = Path(chain_path)
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").strip().split("\n"):
        if line.strip():
            events.append(json.loads(line))
    return events


def get_department_history(
    chain_path: str,
    department: str,
) -> list[dict]:
    """Get all signal events for a department (entry point for each evolution)."""
    events = load_chain(chain_path)
    return [
        e for e in events
        if e.get("phase") == EvolutionPhase.SIGNAL
        and e.get("department") == department
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/test_evolution_chain.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/governance/audit/evolution_chain.py tests/test_evolution_chain.py
git commit -m "feat(evolution): four-stage audit chain (Signal→Hypothesis→Attempt→Outcome) — stolen from evolver GEP"
```

---

### Task 4: WAL-Before-Reply（SESSION-STATE.md）

**Files:**
- Create: `SOUL/private/session-state.md`
- Create: `src/governance/audit/wal.py`
- Create: `tests/test_wal.py`

偷自 proactive-agent 的 WAL Protocol：关键信息写盘在响应之前。

- [ ] **Step 1: Create initial session-state file**

`SOUL/private/session-state.md`:
```markdown
# Session State (WAL)

Write-Ahead Log for critical context that must survive compaction.
Updated BEFORE responding, not after. If it's not here, it didn't happen.

## Active Decisions

<!-- Decisions, preferences, corrections captured during conversation -->

## Active Tasks

<!-- Current work items with status -->

## Critical Context

<!-- Names, dates, URLs, precise values that would be lost on compaction -->
```

- [ ] **Step 2: Write failing tests for WAL module**

```python
# tests/test_wal.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from src.governance.audit.wal import (
    WALSignal, scan_for_signals, write_wal_entry, load_session_state,
    SIGNAL_TYPES,
)


def test_scan_detects_correction():
    signals = scan_for_signals("Actually, we should use PostgreSQL not MySQL")
    assert any(s.signal_type == "correction" for s in signals)


def test_scan_detects_decision():
    signals = scan_for_signals("Let's go with option A, use React for the frontend")
    assert any(s.signal_type == "decision" for s in signals)


def test_scan_detects_preference():
    signals = scan_for_signals("I prefer 2-space indentation and single quotes")
    assert any(s.signal_type == "preference" for s in signals)


def test_scan_detects_precise_value():
    signals = scan_for_signals("The API key is sk-abc123 and the deadline is 2026-04-15")
    assert any(s.signal_type == "precise_value" for s in signals)


def test_scan_returns_empty_for_generic():
    signals = scan_for_signals("ok sounds good")
    assert len(signals) == 0


def test_write_wal_entry(tmp_path):
    state_path = tmp_path / "session-state.md"
    state_path.write_text(
        "# Session State (WAL)\n\n"
        "## Active Decisions\n\n"
        "## Active Tasks\n\n"
        "## Critical Context\n\n"
    )

    write_wal_entry(
        str(state_path),
        section="Active Decisions",
        content="Use PostgreSQL for the new service (corrected from MySQL)",
    )

    text = state_path.read_text()
    assert "PostgreSQL" in text
    assert "Active Decisions" in text


def test_load_session_state(tmp_path):
    state_path = tmp_path / "session-state.md"
    state_path.write_text(
        "# Session State (WAL)\n\n"
        "## Active Decisions\n\n"
        "- Use React\n\n"
        "## Active Tasks\n\n"
        "- Build login page\n\n"
        "## Critical Context\n\n"
        "- Deadline: April 15\n"
    )

    state = load_session_state(str(state_path))
    assert "Use React" in state["Active Decisions"]
    assert "Build login page" in state["Active Tasks"]
    assert "April 15" in state["Critical Context"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/test_wal.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 4: Implement wal.py**

```python
# src/governance/audit/wal.py
"""
WAL (Write-Ahead Log) Protocol — 偷自 proactive-agent。

关键原则：想回复的冲动是敌人。细节在上下文里看起来很显然，
不写也记得住——这个直觉在 context compaction 后必然崩溃。

扫描每条用户输入的 6 类信号，命中则先写 SESSION-STATE.md 再回复。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SIGNAL_TYPES = [
    "correction",      # "actually...", "no, it should be...", "not X, Y"
    "proper_noun",     # names, product names, company names
    "preference",      # "I prefer...", "I like...", "use X style"
    "decision",        # "let's go with...", "we'll use...", "option A"
    "draft_change",    # modifications to in-progress content
    "precise_value",   # numbers, dates, IDs, URLs, API keys
]

# Pattern matchers for each signal type
_PATTERNS: dict[str, list[re.Pattern]] = {
    "correction": [
        re.compile(r"\b(actually|不对|其实应该|纠正|correction)\b", re.IGNORECASE),
        re.compile(r"\bnot\s+\w+[,;]\s*(but|rather|instead)\b", re.IGNORECASE),
        re.compile(r"\bshould\s+be\s+\w+\s+not\b", re.IGNORECASE),
    ],
    "decision": [
        re.compile(r"\b(let'?s\s+(go\s+with|use)|we'?ll\s+use|决定用|就用)\b", re.IGNORECASE),
        re.compile(r"\b(option\s+[A-D]|方案\s*[A-D一二三四])\b", re.IGNORECASE),
        re.compile(r"\b(go\s+with|choose|pick|选)\s+\w+", re.IGNORECASE),
    ],
    "preference": [
        re.compile(r"\b(I\s+prefer|我(喜欢|偏好)|偏好)\b", re.IGNORECASE),
        re.compile(r"\b(use\s+\w+\s+(style|format|indent))", re.IGNORECASE),
        re.compile(r"\b(single\s+quotes|double\s+quotes|tabs|spaces)\b", re.IGNORECASE),
    ],
    "precise_value": [
        re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),  # dates
        re.compile(r"\b(sk-|pk-|api[_-]?key)[a-zA-Z0-9]+", re.IGNORECASE),  # API keys
        re.compile(r"https?://\S+"),  # URLs
        re.compile(r"\b\d+\.\d+\.\d+\b"),  # version numbers
    ],
}


@dataclass
class WALSignal:
    signal_type: str
    matched_text: str
    confidence: float  # 0-1


def scan_for_signals(user_input: str) -> list[WALSignal]:
    """Scan user input for WAL-worthy signals."""
    signals = []
    for signal_type, patterns in _PATTERNS.items():
        for pattern in patterns:
            match = pattern.search(user_input)
            if match:
                signals.append(WALSignal(
                    signal_type=signal_type,
                    matched_text=match.group(0),
                    confidence=0.8,
                ))
                break  # one match per signal type is enough
    return signals


def write_wal_entry(
    state_path: str,
    section: str,
    content: str,
) -> None:
    """Write an entry to a specific section of SESSION-STATE.md.

    This is the WRITE in WAL — happens BEFORE responding.
    """
    path = Path(state_path)
    text = path.read_text(encoding="utf-8")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    entry = f"- [{now}] {content}"
    section_header = f"## {section}"

    if section_header in text:
        # Insert after section header
        parts = text.split(section_header)
        if len(parts) >= 2:
            rest = parts[1]
            # Find the next section or end
            next_section = re.search(r"\n## ", rest)
            if next_section:
                insert_pos = next_section.start()
                new_rest = rest[:insert_pos].rstrip() + "\n" + entry + "\n" + rest[insert_pos:]
            else:
                new_rest = rest.rstrip() + "\n" + entry + "\n"
            text = parts[0] + section_header + new_rest
    else:
        text += f"\n{section_header}\n\n{entry}\n"

    path.write_text(text, encoding="utf-8")


def load_session_state(state_path: str) -> dict[str, str]:
    """Load SESSION-STATE.md into sections."""
    path = Path(state_path)
    if not path.exists():
        return {}

    text = path.read_text(encoding="utf-8")
    sections: dict[str, str] = {}
    current_section = None
    current_lines: list[str] = []

    for line in text.split("\n"):
        m = re.match(r"^## (.+)$", line)
        if m:
            if current_section:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = m.group(1)
            current_lines = []
        elif current_section:
            current_lines.append(line)

    if current_section:
        sections[current_section] = "\n".join(current_lines).strip()

    return sections
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/test_wal.py -v`
Expected: 7 passed

- [ ] **Step 6: Commit**

```bash
git add SOUL/private/session-state.md src/governance/audit/wal.py tests/test_wal.py
git commit -m "feat(wal): Write-Ahead Log protocol for session state — stolen from proactive-agent"
```

---

### Task 5: Pattern-Key 自动晋升到 boot.md

**Files:**
- Create: `src/governance/audit/promoter.py`
- Create: `tests/test_promoter.py`

偷自 self-improving-agent 的 Pattern-Key 晋升机制：同一错误出现 ≥3 次自动写入 boot.md Learnings 区块。

- [ ] **Step 1: Write failing tests**

```python
# tests/test_promoter.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from src.governance.audit.learnings import append_error
from src.governance.audit.promoter import (
    promote_to_boot, scan_and_promote, mark_as_promoted,
)


def _setup_errors_with_repeats(tmp_path, pattern_key, count):
    errors_md = tmp_path / "ERRORS.md"
    errors_md.write_text("# Errors\n\n<!-- entries below this line are auto-managed -->\n")
    for i in range(count):
        append_error(pattern_key, f"Error #{i+1}", "Same issue repeating", "engineering", str(errors_md))
    return str(errors_md)


def test_promote_to_boot(tmp_path):
    """Promoting an entry appends a learning line to boot.md Learnings section."""
    boot_md = tmp_path / "boot.md"
    boot_md.write_text(
        "# Boot\n\n## Learnings\n\n"
        "Hard-won rules from past mistakes.\n\n"
        "- Existing learning [engineering]\n"
    )

    promote_to_boot(
        boot_path=str(boot_md),
        pattern_key="docker-rebuild-unnecessary",
        summary="Don't rebuild Docker image for config-only changes; restart is enough",
        area="operations",
    )

    text = boot_md.read_text()
    assert "docker-rebuild-unnecessary" in text or "Don't rebuild Docker" in text
    assert "Existing learning" in text  # original content preserved
    assert text.count("## Learnings") == 1  # didn't duplicate the section


def test_scan_and_promote(tmp_path):
    """Entries with >= threshold occurrences get promoted."""
    errors_md = _setup_errors_with_repeats(tmp_path, "repeated-timeout", 4)

    boot_md = tmp_path / "boot.md"
    boot_md.write_text("# Boot\n\n## Learnings\n\n- Old learning [misc]\n")

    promoted = scan_and_promote(
        learnings_path=errors_md,
        boot_path=str(boot_md),
        threshold=3,
    )

    assert len(promoted) == 1
    assert promoted[0] == "repeated-timeout"
    assert "repeated-timeout" in boot_md.read_text() or "Error #" in boot_md.read_text()


def test_mark_as_promoted(tmp_path):
    errors_md = _setup_errors_with_repeats(tmp_path, "mark-test", 3)

    mark_as_promoted(errors_md, "mark-test")

    text = Path(errors_md).read_text()
    assert "Status: promoted" in text


def test_no_double_promotion(tmp_path):
    """Already-promoted entries are not promoted again."""
    errors_md = _setup_errors_with_repeats(tmp_path, "already-done", 5)
    boot_md = tmp_path / "boot.md"
    boot_md.write_text("# Boot\n\n## Learnings\n\n")

    scan_and_promote(errors_md, str(boot_md), threshold=3)
    first_text = boot_md.read_text()

    # Second run should not add again
    promoted = scan_and_promote(errors_md, str(boot_md), threshold=3)
    assert len(promoted) == 0
    assert boot_md.read_text() == first_text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/test_promoter.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement promoter.py**

```python
# src/governance/audit/promoter.py
"""
Pattern-Key 自动晋升 — 偷自 self-improving-agent 的 promotion 机制。

同一 Pattern-Key 出现 ≥ threshold 次 → 自动追加到 boot.md Learnings 区块。
晋升后标记为 promoted 防止重复。
"""
from __future__ import annotations

import re
from pathlib import Path

from src.governance.audit.learnings import get_promotable_entries, _parse_entries

LEARNINGS_SECTION = "## Learnings"


def promote_to_boot(
    boot_path: str,
    pattern_key: str,
    summary: str,
    area: str,
) -> None:
    """Append a promoted learning to boot.md's Learnings section."""
    path = Path(boot_path)
    text = path.read_text(encoding="utf-8")

    # Don't duplicate
    if pattern_key in text:
        return

    entry_line = f"- {summary} [{area}] (auto-promoted: {pattern_key})"

    if LEARNINGS_SECTION in text:
        # Find the Learnings section and append at the end of its content
        parts = text.split(LEARNINGS_SECTION, 1)
        after = parts[1]
        # Find next section header
        next_section = re.search(r"\n## ", after)
        if next_section:
            insert_pos = next_section.start()
            new_after = after[:insert_pos].rstrip() + "\n" + entry_line + "\n" + after[insert_pos:]
        else:
            new_after = after.rstrip() + "\n" + entry_line + "\n"
        text = parts[0] + LEARNINGS_SECTION + new_after
    else:
        text += f"\n{LEARNINGS_SECTION}\n\n{entry_line}\n"

    path.write_text(text, encoding="utf-8")


def mark_as_promoted(learnings_path: str, pattern_key: str) -> None:
    """Mark a pattern_key as promoted in its learnings file."""
    path = Path(learnings_path)
    text = path.read_text(encoding="utf-8")

    # Find the entry block with this pattern key and update status
    lines = text.split("\n")
    found_key = False
    for i, line in enumerate(lines):
        if f"- Pattern-Key: {pattern_key}" in line:
            found_key = True
        if found_key and "- Status: active" in line:
            lines[i] = "- Status: promoted"
            break

    path.write_text("\n".join(lines), encoding="utf-8")


def scan_and_promote(
    learnings_path: str,
    boot_path: str,
    threshold: int = 3,
) -> list[str]:
    """Scan a learnings file and promote entries that hit the threshold.

    Returns list of promoted pattern_keys.
    """
    promotable = get_promotable_entries(learnings_path, threshold)
    promoted = []

    for entry in promotable:
        promote_to_boot(
            boot_path=boot_path,
            pattern_key=entry.pattern_key,
            summary=entry.summary,
            area=entry.area or "general",
        )
        mark_as_promoted(learnings_path, entry.pattern_key)
        promoted.append(entry.pattern_key)

    return promoted
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/test_promoter.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/governance/audit/promoter.py tests/test_promoter.py
git commit -m "feat(promoter): Pattern-Key auto-promotion to boot.md Learnings — stolen from self-improving-agent"
```

---

### Task 6: 集成验证

- [ ] **Step 1: Run all new tests together**

```bash
cd D:/Users/Administrator/Documents/GitHub/orchestrator
python -m pytest tests/test_learnings.py tests/test_blast_radius.py tests/test_evolution_chain.py tests/test_wal.py tests/test_promoter.py -v
```
Expected: All passed (5 + 13 + 4 + 7 + 4 = 33 tests)

- [ ] **Step 2: Run existing tests to verify no regressions**

```bash
python -m pytest tests/test_dimensions.py tests/test_diagnostician.py -v
```
Expected: All existing tests still pass

- [ ] **Step 3: Verify file structure**

```bash
ls -la .learnings/
ls -la SOUL/private/session-state.md
ls -la src/governance/audit/learnings.py
ls -la src/governance/audit/evolution_chain.py
ls -la src/governance/audit/wal.py
ls -la src/governance/audit/promoter.py
```

- [ ] **Step 4: Final commit if any fixups needed**

```bash
git add -A
git commit -m "chore: ClawHub P0 steal integration verification — 5 patterns from Round 14"
```
