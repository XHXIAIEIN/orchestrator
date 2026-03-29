# Clawvard 偷师落地 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Clawvard 的 4 个可偷模式落地到 Orchestrator：多维度评估体系、自诊断闭环、技能维度映射、审批链 hash 完整性。

**Architecture:** 扩展吏部从单一健康分数到 6 维度雷达评估（对齐六部）。新增 `diagnostician.py` 分析 run-log 数据自动识别薄弱维度并生成改进建议。manifest.yaml 加 `dimensions` 字段标注技能影响维度。审批链 `approval.py` 加 step-hash 保证多步流程不可篡改。

**Tech Stack:** Python 3.14, SQLite (events.db), existing run_logger hash-chain infra

**Source:** [Clawvard](https://clawvard.school) 偷师 — 多维评估 + 诊断闭环 + 技能市场分维度

---

## File Structure

```
src/governance/audit/diagnostician.py    — NEW: 自诊断引擎（评估→诊断→处方）
src/governance/audit/dimensions.py       — NEW: 维度定义 + 评分逻辑
departments/personnel/SKILL.md           — MODIFY: 扩展为多维度评估输出
departments/*/manifest.yaml              — MODIFY: 加 dimensions 字段
src/governance/approval.py               — MODIFY: 加 step-hash chain
tests/test_dimensions.py                 — NEW: 维度评分测试
tests/test_diagnostician.py             — NEW: 自诊断测试
```

---

### Task 1: 维度定义模块

**Files:**
- Create: `src/governance/audit/dimensions.py`
- Create: `tests/test_dimensions.py`

六部天然映射六个评估维度，不需要生造 Clawvard 的 8 维度：

| 维度 | 对应部 | 指标来源 |
|------|--------|----------|
| execution (执行力) | 工部 | success rate, completion rate |
| operations (运维力) | 户部 | uptime, repair speed |
| evaluation (评估力) | 吏部 | report accuracy, anomaly catch rate |
| attention (注意力) | 礼部 | debt resolution rate, stale item count |
| quality (品控力) | 刑部 | review finding rate, regression count |
| security (防御力) | 兵部 | vuln response time, exposure count |

- [ ] **Step 1: Write failing test for dimension scoring**

```python
# tests/test_dimensions.py
from src.governance.audit.dimensions import score_dimension, DimensionScore

def test_score_execution_healthy():
    """success_rate >= 90% and avg_duration trend stable → A grade."""
    runs = [
        {"status": "done", "duration_s": 60, "department": "engineering"},
        {"status": "done", "duration_s": 55, "department": "engineering"},
        {"status": "done", "duration_s": 70, "department": "engineering"},
        {"status": "failed", "duration_s": 10, "department": "engineering"},
    ] * 3  # 12 runs, 9/12 = 75% → B range
    score = score_dimension("execution", runs)
    assert isinstance(score, DimensionScore)
    assert score.dimension == "execution"
    assert 70 <= score.score <= 89  # B range
    assert score.grade in ("B+", "B", "B-")

def test_score_execution_perfect():
    runs = [{"status": "done", "duration_s": 50, "department": "engineering"}] * 20
    score = score_dimension("execution", runs)
    assert score.score >= 90
    assert score.grade in ("S", "A+", "A")

def test_score_with_no_data():
    score = score_dimension("execution", [])
    assert score.score == 0
    assert score.grade == "N/A"
    assert "insufficient" in score.note.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/test_dimensions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.governance.audit.dimensions'`

- [ ] **Step 3: Implement dimensions.py**

```python
# src/governance/audit/dimensions.py
"""
六维度评估体系 — 偷自 Clawvard 多维雷达图模式。

每个维度对应一个部，从 run-log 数据中计算得分（0-100）。
"""
from dataclasses import dataclass

DIMENSIONS = {
    "execution":  {"department": "engineering", "name_zh": "执行力"},
    "operations": {"department": "operations",  "name_zh": "运维力"},
    "evaluation": {"department": "personnel",   "name_zh": "评估力"},
    "attention":  {"department": "protocol",    "name_zh": "注意力"},
    "quality":    {"department": "quality",      "name_zh": "品控力"},
    "security":   {"department": "security",    "name_zh": "防御力"},
}

GRADE_TABLE = [
    (95, "S"), (90, "A+"), (85, "A"), (80, "A-"),
    (75, "B+"), (70, "B"), (65, "B-"),
    (60, "C+"), (55, "C"), (50, "C-"),
    (40, "D+"), (30, "D"), (0, "F"),
]


@dataclass
class DimensionScore:
    dimension: str
    department: str
    score: float       # 0-100
    grade: str         # S / A+ / A / ... / F / N/A
    name_zh: str
    note: str = ""


def _to_grade(score: float) -> str:
    for threshold, grade in GRADE_TABLE:
        if score >= threshold:
            return grade
    return "F"


def score_dimension(dimension: str, runs: list[dict]) -> DimensionScore:
    """Score a dimension from run-log entries."""
    meta = DIMENSIONS.get(dimension, {"department": dimension, "name_zh": dimension})
    dept = meta["department"]

    # Filter runs for this department
    dept_runs = [r for r in runs if r.get("department", dept) == dept]

    if len(dept_runs) < 3:
        return DimensionScore(
            dimension=dimension, department=dept, score=0,
            grade="N/A", name_zh=meta["name_zh"],
            note="Insufficient data (< 3 runs)",
        )

    total = len(dept_runs)
    success = sum(1 for r in dept_runs if r.get("status") == "done")
    success_rate = (success / total) * 100

    # Duration trend: compare first half vs second half
    durations = [r.get("duration_s", 0) for r in dept_runs if r.get("duration_s", 0) > 0]
    duration_penalty = 0
    if len(durations) >= 4:
        mid = len(durations) // 2
        first_avg = sum(durations[:mid]) / mid
        second_avg = sum(durations[mid:]) / (len(durations) - mid)
        if first_avg > 0:
            increase = (second_avg - first_avg) / first_avg
            if increase > 1.0:
                duration_penalty = 15
            elif increase > 0.2:
                duration_penalty = 5

    score = max(0, min(100, success_rate - duration_penalty))
    grade = _to_grade(score)

    return DimensionScore(
        dimension=dimension, department=dept, score=round(score, 1),
        grade=grade, name_zh=meta["name_zh"],
    )


def score_all(runs: list[dict]) -> list[DimensionScore]:
    """Score all 6 dimensions from a combined run-log."""
    return [score_dimension(dim, runs) for dim in DIMENSIONS]


def format_radar(scores: list[DimensionScore]) -> str:
    """Format scores as a text radar / report card."""
    lines = ["## 六维度成绩单\n"]
    lines.append("| 维度 | 部门 | 得分 | 等级 | 备注 |")
    lines.append("|------|------|------|------|------|")
    for s in scores:
        lines.append(f"| {s.name_zh} | {s.department} | {s.score}/100 | {s.grade} | {s.note} |")

    valid = [s for s in scores if s.grade != "N/A"]
    if valid:
        avg = sum(s.score for s in valid) / len(valid)
        overall_grade = _to_grade(avg)
        lines.append(f"\n**综合: {avg:.1f}/100 ({overall_grade})**")

    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/test_dimensions.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/governance/audit/dimensions.py tests/test_dimensions.py
git commit -m "feat(吏部): six-dimension evaluation system — stolen from Clawvard radar model"
```

---

### Task 2: 自诊断引擎

**Files:**
- Create: `src/governance/audit/diagnostician.py`
- Create: `tests/test_diagnostician.py`

核心逻辑：分析 run-log → 用 dimensions.py 评分 → 找最弱维度 → 生成改进处方。

- [ ] **Step 1: Write failing test**

```python
# tests/test_diagnostician.py
from src.governance.audit.diagnostician import diagnose

def test_diagnose_finds_weakest():
    """Diagnose should identify the weakest dimension and suggest improvement."""
    runs = [
        # Engineering: 10 runs, 9 success = 90%
        *[{"department": "engineering", "status": "done", "duration_s": 50}] * 9,
        {"department": "engineering", "status": "failed", "duration_s": 10},
        # Security: 10 runs, 5 success = 50%
        *[{"department": "security", "status": "done", "duration_s": 30}] * 5,
        *[{"department": "security", "status": "failed", "duration_s": 5}] * 5,
    ]
    result = diagnose(runs)
    assert result.weakest.dimension == "security"
    assert result.weakest.score < 60
    assert len(result.prescriptions) > 0
    assert any("security" in p.lower() or "兵部" in p for p in result.prescriptions)

def test_diagnose_empty_data():
    result = diagnose([])
    assert result.weakest is None
    assert "insufficient" in result.summary.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/test_diagnostician.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement diagnostician.py**

```python
# src/governance/audit/diagnostician.py
"""
自诊断引擎 — 偷自 Clawvard 的 评估→诊断→处方 闭环。

分析 run-log 数据 → 六维度评分 → 找薄弱点 → 生成改进建议。
"""
from dataclasses import dataclass, field

from src.governance.audit.dimensions import (
    DimensionScore, score_all, format_radar, DIMENSIONS,
)

# 每个维度的改进处方模板
PRESCRIPTIONS = {
    "execution": [
        "工部成功率偏低 — 检查近期 failed 任务的 notes 字段，排查共性错误模式",
        "建议：缩小单次任务粒度，增加 preflight check 覆盖",
    ],
    "operations": [
        "户部运维响应慢 — 检查 collector 健康状态和 Docker 资源占用",
        "建议：增加自动重启策略，缩短 health check 间隔",
    ],
    "evaluation": [
        "吏部评估能力弱 — 可能是数据不足导致，增加定时评估频率",
        "建议：扩展 metrics 采集维度，增加异常检测灵敏度",
    ],
    "attention": [
        "礼部注意力债务积压 — 运行 debt_scanner 清理过期 TODO",
        "建议：缩短 debt 扫描周期，对反复出现的债务升级处理",
    ],
    "quality": [
        "刑部品控薄弱 — 检查 review 覆盖率和回归测试命中率",
        "建议：对高风险变更强制双重 review，增加自动化测试",
    ],
    "security": [
        "兵部防御告警 — 检查依赖漏洞扫描和 secret 泄露检测",
        "建议：提高扫描频率，对 HIGH 级别漏洞设置自动阻断",
    ],
}


@dataclass
class Diagnosis:
    scores: list[DimensionScore]
    weakest: DimensionScore | None
    strongest: DimensionScore | None
    prescriptions: list[str] = field(default_factory=list)
    summary: str = ""


def diagnose(runs: list[dict]) -> Diagnosis:
    """Run full diagnostic: score → find weakness → prescribe."""
    scores = score_all(runs)
    valid = [s for s in scores if s.grade != "N/A"]

    if not valid:
        return Diagnosis(
            scores=scores, weakest=None, strongest=None,
            summary="Insufficient data for diagnosis.",
        )

    sorted_scores = sorted(valid, key=lambda s: s.score)
    weakest = sorted_scores[0]
    strongest = sorted_scores[-1]

    prescriptions = PRESCRIPTIONS.get(weakest.dimension, [])

    avg = sum(s.score for s in valid) / len(valid)
    summary = (
        f"综合 {avg:.1f}/100 | "
        f"最强: {strongest.name_zh}({strongest.grade}) | "
        f"最弱: {weakest.name_zh}({weakest.grade})"
    )

    return Diagnosis(
        scores=scores,
        weakest=weakest,
        strongest=strongest,
        prescriptions=list(prescriptions),
        summary=summary,
    )


def format_diagnosis(d: Diagnosis) -> str:
    """Format full diagnostic report."""
    if d.weakest is None:
        return "## 自诊断报告\n\n数据不足，无法诊断。"

    parts = [
        format_radar(d.scores),
        "",
        f"## 诊断: {d.summary}",
        "",
        "## 处方 (针对最弱维度)",
        "",
    ]
    for rx in d.prescriptions:
        parts.append(f"- {rx}")

    return "\n".join(parts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/test_diagnostician.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/governance/audit/diagnostician.py tests/test_diagnostician.py
git commit -m "feat(吏部): self-diagnostic engine — evaluate→diagnose→prescribe loop from Clawvard"
```

---

### Task 3: Manifest 维度标注

**Files:**
- Modify: `departments/engineering/manifest.yaml`
- Modify: `departments/operations/manifest.yaml`
- Modify: `departments/personnel/manifest.yaml`
- Modify: `departments/protocol/manifest.yaml`
- Modify: `departments/quality/manifest.yaml`
- Modify: `departments/security/manifest.yaml`

每个 manifest 加一个 `dimensions` 字段，标注该部门影响哪些评估维度（主维度 + 辅助维度）。偷自 Clawvard 的 skill-dimension 映射模式。

- [ ] **Step 1: Add dimensions to engineering manifest**

在 `departments/engineering/manifest.yaml` 的 tags 块后面加：

```yaml
# ── Dimension Mapping (偷自 Clawvard skill-dimension 模式) ──
dimensions:
  primary: execution      # 主影响维度
  secondary: [quality]     # 辅助影响维度
  boost: "+9"              # 自评估提升分（参考值）
```

- [ ] **Step 2: Add dimensions to all other manifests**

operations:
```yaml
dimensions:
  primary: operations
  secondary: [execution]
  boost: "+8"
```

personnel:
```yaml
dimensions:
  primary: evaluation
  secondary: [attention]
  boost: "+7"
```

protocol:
```yaml
dimensions:
  primary: attention
  secondary: [quality]
  boost: "+6"
```

quality:
```yaml
dimensions:
  primary: quality
  secondary: [execution, security]
  boost: "+10"
```

security:
```yaml
dimensions:
  primary: security
  secondary: [quality]
  boost: "+8"
```

- [ ] **Step 3: Commit**

```bash
git add departments/*/manifest.yaml
git commit -m "feat(manifests): add dimension mapping to all departments — skill-dimension model from Clawvard"
```

---

### Task 4: 审批链 Step-Hash

**Files:**
- Modify: `src/governance/approval.py`

在多步审批流中加 step hash。偷自 Clawvard 的 hash-chain 考试模式。run_logger.py 已有 `_compute_hash`，直接复用。

- [ ] **Step 1: Read current approval.py**

Read `src/governance/approval.py` to find `ApprovalRequest` dataclass and the approval flow.

- [ ] **Step 2: Add step_hash field to ApprovalRequest**

在 `ApprovalRequest` dataclass 中增加：

```python
step_hash: str = ""        # 哈希链: SHA-256(prev_step_hash + canonical request)
prev_step_hash: str = ""   # 上一步的 hash，空串 = 链首
```

- [ ] **Step 3: Add hash computation to approval creation**

在创建 `ApprovalRequest` 的地方，计算 hash：

```python
from src.governance.audit.run_logger import _compute_hash

def _hash_approval(request: ApprovalRequest, prev_hash: str = "") -> str:
    """Compute step hash for approval chain integrity."""
    entry = {
        "task_id": request.task_id,
        "description": request.description,
        "authority_level": request.authority_level,
        "requested_at": request.requested_at,
    }
    return _compute_hash(entry, prev_hash)
```

- [ ] **Step 4: Wire hash into approval flow**

在 `request_approval()` 或等效方法中：
1. 从 DB/内存获取 `prev_step_hash`（最后一次审批的 hash）
2. 计算当前 `step_hash`
3. 存入 `ApprovalRequest`
4. 写入 DB 时一并保存

- [ ] **Step 5: Commit**

```bash
git add src/governance/approval.py
git commit -m "feat(approval): add step-hash chain to approval flow — integrity pattern from Clawvard"
```

---

### Task 5: 吏部 SKILL.md 更新 + 集成

**Files:**
- Modify: `departments/personnel/SKILL.md`

扩展吏部的输出格式，从单一表格变为多维度成绩单。

- [ ] **Step 1: Update SKILL.md output format**

在 `## Output` 部分增加六维度成绩单模板：

```markdown
## Output (Extended — 六维度模式)

When performing full evaluation, output BOTH the per-component table AND the dimension radar:

```
PERFORMANCE REPORT — <date> (window: <N> days)

## 六维度成绩单

| 维度 | 部门 | 得分 | 等级 | 备注 |
|------|------|------|------|------|

综合: XX.X/100 (Grade)

## 诊断

最强: XX(Grade) | 最弱: XX(Grade)

## 处方

- [针对最弱维度的改进建议]

RESULT: DONE
```
```

- [ ] **Step 2: Add dimension evaluation scope**

在 `## Scope` 下的 DO 列表加：

```
DO: run six-dimension evaluation using src/governance/audit/diagnostician.py, output radar report with prescriptions
```

- [ ] **Step 3: Commit**

```bash
git add departments/personnel/SKILL.md
git commit -m "feat(吏部): upgrade SKILL.md to six-dimension evaluation output — Clawvard radar model"
```

---

### Task 6: 最终验证

- [ ] **Step 1: Run all tests**

```bash
cd D:/Users/Administrator/Documents/GitHub/orchestrator
python -m pytest tests/test_dimensions.py tests/test_diagnostician.py -v
```
Expected: 5 passed

- [ ] **Step 2: Verify hash chain still works**

```bash
python -c "from src.governance.audit.run_logger import verify_chain; print(verify_chain())"
```
Expected: `{"valid": True, ...}`

- [ ] **Step 3: Test diagnostic on real data**

```bash
python -c "
from src.governance.audit.run_logger import load_recent_runs
from src.governance.audit.diagnostician import diagnose, format_diagnosis

runs = []
for dept in ['engineering', 'operations', 'personnel', 'protocol', 'quality', 'security']:
    for r in load_recent_runs(dept, 50):
        r['department'] = dept
        runs.append(r)

print(format_diagnosis(diagnose(runs)))
"
```

- [ ] **Step 4: Final commit (if any fixups)**

```bash
git add -A
git commit -m "chore: integration verification for Clawvard steal patterns"
```
