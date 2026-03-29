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
