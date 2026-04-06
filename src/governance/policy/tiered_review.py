"""
三层 Review — 快速扫描 → 风险驱动深检 → 全量审核。

偷师来源: OpenClaw 多 Agent 协同系统 (P4)
原始设计 (orc-spencer): 两层 bead/goal
升级: 三层漏斗 + token 预算，low risk 直接过，省掉 80% 审核 token。

集成: ReviewManager.finalize_task() 根据 risk_level 决定跑哪些 gate。
"""
import logging
import re

from src.core.llm_router import MODEL_SONNET, MODEL_HAIKU

log = logging.getLogger(__name__)

# ── High blast-radius departments (matches review.py _HIGH_BLAST_DEPARTMENTS) ──
_HIGH_BLAST_DEPARTMENTS = {"security", "operations"}


class ReviewTier:
    SCAN = "scan"       # Layer 1: 快速扫描 (~0 LLM tokens)
    FOCUSED = "focused"  # Layer 2: 风险驱动深检 (~2000-5000 tokens)
    FULL = "full"       # Layer 3: 全量审核 (~10000+ tokens)

    # Backward compat aliases
    QUICK = SCAN
    DEEP = FULL


class RiskLevel:
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


def classify_risk(task: dict, dept_key: str, status: str) -> str:
    """Classify task risk level based on department, output, and task metadata.

    Returns RiskLevel.LOW / MEDIUM / HIGH.
    """
    if status != "done":
        return RiskLevel.LOW  # Failed tasks don't need deep review

    spec = task.get("spec", {})
    action = task.get("action", "").lower()
    output = task.get("output", "")

    # ── HIGH: non-negotiable deep review ──
    high_signals = [
        dept_key in _HIGH_BLAST_DEPARTMENTS,
        spec.get("requires_approval"),
        spec.get("priority") == "critical",
        spec.get("rework_count", 0) >= 2,
    ]
    if any(high_signals):
        return RiskLevel.HIGH

    # ── MEDIUM: worth a second look ──
    medium_signals = [
        len(output) > 2000,
        spec.get("cognitive_mode") == "designer",
        "refactor" in action or "重构" in action,
        "architect" in action or "架构" in action,
        "delete" in action or "删除" in action,
        "migration" in action or "迁移" in action,
        _count_files_in_output(output) > 5,
    ]
    if any(medium_signals):
        return RiskLevel.MEDIUM

    return RiskLevel.LOW


def determine_review_tier(task: dict, dept_key: str = "", status: str = "done") -> str:
    """Map risk level to review tier.

    Backward-compatible: accepts old call signature (task only).
    """
    risk = classify_risk(task, dept_key, status)
    if risk == RiskLevel.HIGH:
        return ReviewTier.FULL
    elif risk == RiskLevel.MEDIUM:
        return ReviewTier.FOCUSED
    return ReviewTier.SCAN


# ── Gate Sets per Tier ──
# Each tier defines which expensive gates to run.
# Cheap gates (schema validation, file ratchet, run log, dependency chain)
# always run regardless of tier.

TIER_GATES = {
    ReviewTier.SCAN: {
        # Layer 1: only cheap local checks, zero LLM calls
        "council": False,
        "cross_review": False,
        "eval_harness": False,
        "visual_verify": False,
        "quality_dispatch": False,
        "deslop": True,          # file scan, no LLM
        "file_ratchet": True,    # file scan, no LLM
    },
    ReviewTier.FOCUSED: {
        # Layer 2: add eval + trajectory, skip council
        "council": False,
        "cross_review": False,
        "eval_harness": True,
        "visual_verify": False,
        "quality_dispatch": True,
        "deslop": True,
        "file_ratchet": True,
    },
    ReviewTier.FULL: {
        # Layer 3: everything
        "council": True,
        "cross_review": True,
        "eval_harness": True,
        "visual_verify": True,
        "quality_dispatch": True,
        "deslop": True,
        "file_ratchet": True,
    },
}


def should_run_gate(tier: str, gate_name: str) -> bool:
    """Check if a specific gate should run for the given tier."""
    gates = TIER_GATES.get(tier, TIER_GATES[ReviewTier.FULL])
    return gates.get(gate_name, True)


def get_review_config(tier: str) -> dict:
    """Get review dispatch configuration per tier."""
    if tier == ReviewTier.FULL:
        return {
            "max_turns": 30,
            "timeout_s": 300,
            "model": MODEL_SONNET,
            "instructions": (
                "这是一个高风险改动的全量审查。请：\n"
                "1. 逐文件检查每个改动\n"
                "2. 运行所有相关测试\n"
                "3. 检查边界条件和错误处理\n"
                "4. 评估架构影响\n"
                "5. 检查是否引入技术债\n"
            ),
        }
    elif tier == ReviewTier.FOCUSED:
        return {
            "max_turns": 20,
            "timeout_s": 180,
            "model": MODEL_SONNET,
            "instructions": (
                "中等风险改动审查。重点：\n"
                "1. git diff 检查关键改动\n"
                "2. 运行受影响的测试\n"
                "3. 检查逻辑正确性\n"
            ),
        }
    else:
        return {
            "max_turns": 15,
            "timeout_s": 120,
            "model": MODEL_HAIKU,
            "instructions": (
                "快速审查小改动。重点：\n"
                "1. git diff 检查实际改动\n"
                "2. 逻辑是否正确\n"
                "3. 是否引入明显 bug\n"
            ),
        }


def _count_files_in_output(output: str) -> int:
    """估算输出中提到了多少个文件路径。"""
    paths = re.findall(r'(?:src|departments|SOUL|dashboard|tests)/[\w/.-]+\.\w+', output)
    return len(set(paths))
