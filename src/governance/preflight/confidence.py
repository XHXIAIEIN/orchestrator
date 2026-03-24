# src/governance/preflight/confidence.py
"""5-Dimension Confidence Scoring — preflight risk quantification.

Stolen from pro-workflow's 5-dimension confidence model. Scores each task
on 5 axes before dispatch, producing a 0-100 composite score that gates
execution strategy: high confidence → fast path, low → extra scrutiny or
human confirmation.

Dimensions:
  1. complexity    — how many moving parts (files, dependencies, steps)
  2. dependency    — reliance on external systems (APIs, DBs, network)
  3. side_effect   — blast radius if something goes wrong
  4. ambiguity     — how clear/specific is the task description
  5. cost          — estimated token/time cost
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class DimensionScore:
    """Score for a single dimension, 0-100 (100 = most confident/least risky)."""
    name: str
    score: int  # 0 = very risky, 100 = very safe
    reason: str = ""


@dataclass
class ConfidenceReport:
    """Composite confidence assessment."""
    dimensions: list[DimensionScore] = field(default_factory=list)
    task_id: int = 0

    @property
    def composite(self) -> int:
        """Weighted composite score, 0-100."""
        if not self.dimensions:
            return 50  # neutral default
        weights = {
            "complexity": 0.25,
            "dependency": 0.15,
            "side_effect": 0.30,  # highest weight — blast radius matters most
            "ambiguity": 0.20,
            "cost": 0.10,
        }
        total_w = 0
        total_s = 0
        for d in self.dimensions:
            w = weights.get(d.name, 0.2)
            total_w += w
            total_s += d.score * w
        return int(total_s / total_w) if total_w > 0 else 50

    @property
    def tier(self) -> str:
        """Confidence tier for routing decisions."""
        c = self.composite
        if c >= 80:
            return "HIGH"      # fast path, minimal scrutiny
        if c >= 50:
            return "MEDIUM"    # normal scrutiny
        if c >= 30:
            return "LOW"       # extra scrutiny, conservative model
        return "CRITICAL"      # human confirmation required

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "composite": self.composite,
            "tier": self.tier,
            "dimensions": {d.name: {"score": d.score, "reason": d.reason} for d in self.dimensions},
        }


# ── Scoring Functions ──

def _score_complexity(spec: dict) -> DimensionScore:
    """Estimate task complexity from description and metadata."""
    action = (spec.get("action") or "").lower()
    problem = (spec.get("problem") or "").lower()
    combined = f"{action} {problem}"

    score = 80  # default: fairly simple

    # Multi-file signals
    multi_file_signals = ["多个文件", "multiple files", "重构", "refactor", "迁移", "migrate",
                          "子系统", "subsystem", "架构", "architecture"]
    for s in multi_file_signals:
        if s in combined:
            score -= 20
            break

    # Complex operation signals
    complex_signals = ["并发", "concurrent", "分布式", "distributed", "性能优化",
                       "performance", "安全", "security", "加密", "encrypt"]
    for s in complex_signals:
        if s in combined:
            score -= 15
            break

    # Simple operation signals boost
    simple_signals = ["typo", "rename", "改名", "注释", "comment", "格式", "format",
                      "版本号", "bump", "配置", "config"]
    for s in simple_signals:
        if s in combined:
            score = min(score + 15, 95)
            break

    return DimensionScore("complexity", max(5, min(95, score)), f"task: {combined[:60]}")


def _score_dependency(spec: dict) -> DimensionScore:
    """Estimate external dependency risk."""
    action = (spec.get("action") or "").lower()
    problem = (spec.get("problem") or "").lower()
    combined = f"{action} {problem}"

    score = 85

    external_signals = ["api", "网络", "network", "http", "外部", "external",
                        "third-party", "第三方", "数据库", "database", "docker"]
    for s in external_signals:
        if s in combined:
            score -= 25
            break

    # Local-only signals boost
    local_signals = ["本地", "local", "纯代码", "code-only", "文件", "file"]
    for s in local_signals:
        if s in combined:
            score = min(score + 10, 95)
            break

    return DimensionScore("dependency", max(5, min(95, score)))


def _score_side_effect(spec: dict) -> DimensionScore:
    """Estimate blast radius — what breaks if this goes wrong."""
    action = (spec.get("action") or "").lower()
    problem = (spec.get("problem") or "").lower()
    combined = f"{action} {problem}"

    score = 75

    high_risk = ["schema", "migration", "数据库", "database", "events.db",
                 "docker", "重启", "restart", "删除", "delete", "生产", "production",
                 "credentials", "密钥", "key", ".env", "push", "部署", "deploy"]
    for s in high_risk:
        if s in combined:
            score -= 30
            break

    medium_risk = ["重构", "refactor", "多文件", "接口", "api", "配置", "config",
                   "全局", "global", "共享", "shared"]
    if score > 50:
        for s in medium_risk:
            if s in combined:
                score -= 15
                break

    # Read-only department boost
    dept = spec.get("department", "")
    if dept in ("quality", "protocol", "security", "personnel"):
        score = min(score + 20, 95)

    return DimensionScore("side_effect", max(5, min(95, score)))


def _score_ambiguity(spec: dict) -> DimensionScore:
    """Score how clear and actionable the task description is."""
    action = spec.get("action") or ""
    problem = spec.get("problem") or ""
    combined = f"{action} {problem}"

    score = 70

    # Specificity signals: file paths, line numbers, function names
    has_path = bool(re.search(r'[\w/]+\.\w+', combined))
    has_line = bool(re.search(r':\d+', combined))
    has_function = bool(re.search(r'[\w_]+\(\)', combined))
    has_error = bool(re.search(r'error|exception|traceback', combined, re.I))

    if has_path:
        score += 10
    if has_line:
        score += 5
    if has_function:
        score += 5
    if has_error:
        score += 5

    # Vagueness signals
    vague_signals = ["看看", "研究", "了解", "explore", "investigate", "看一下",
                     "想想", "think about", "或许", "maybe", "可能", "might"]
    for s in vague_signals:
        if s in combined.lower():
            score -= 15
            break

    # Very short description = probably vague
    if len(combined) < 20:
        score -= 20
    elif len(combined) > 100:
        score += 5

    return DimensionScore("ambiguity", max(5, min(95, score)))


def _score_cost(spec: dict, blueprint=None) -> DimensionScore:
    """Estimate token/time cost."""
    score = 80

    max_turns = 25
    if blueprint:
        max_turns = getattr(blueprint, "max_turns", 25)

    # High turn count = higher cost risk
    if max_turns > 30:
        score -= 15
    elif max_turns <= 10:
        score += 10

    # Model cost
    model = ""
    if blueprint:
        model = getattr(blueprint, "model", "")
    if "opus" in model:
        score -= 20
    elif "haiku" in model:
        score += 15

    return DimensionScore("cost", max(5, min(95, score)))


# ── Public API ──

def assess_confidence(task: dict, blueprint=None) -> ConfidenceReport:
    """Run full 5-dimension confidence assessment on a task.

    Args:
        task: Task dict with at least 'spec' containing action/problem/department
        blueprint: Optional Blueprint for model/turn info

    Returns:
        ConfidenceReport with composite score and per-dimension breakdown
    """
    spec = task.get("spec", {})
    task_id = task.get("id", 0)

    report = ConfidenceReport(
        task_id=task_id,
        dimensions=[
            _score_complexity(spec),
            _score_dependency(spec),
            _score_side_effect(spec),
            _score_ambiguity(spec),
            _score_cost(spec, blueprint),
        ],
    )

    log.info(
        f"Confidence: task #{task_id} → {report.composite}/100 ({report.tier}) "
        f"[{', '.join(f'{d.name}={d.score}' for d in report.dimensions)}]"
    )

    return report
