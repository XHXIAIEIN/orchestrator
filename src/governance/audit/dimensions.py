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
