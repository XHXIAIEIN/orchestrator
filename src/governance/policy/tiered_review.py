"""
两层 Review — 小任务快审 + 大功能深审。

orc-spencer 启发：bead 级快审 + goal 级独立 sub-agent 深审。

集成：Governor._dispatch_quality_review 根据任务复杂度选择审查深度。
"""
import logging

from src.core.llm_router import MODEL_SONNET, MODEL_HAIKU

log = logging.getLogger(__name__)


class ReviewTier:
    QUICK = "quick"     # 小改动：检查 diff，5 分钟内
    DEEP = "deep"       # 大改动：独立 sub-agent，完整测试


def determine_review_tier(task: dict) -> str:
    """根据任务特征决定审查深度。"""
    spec = task.get("spec", {})
    action = task.get("action", "").lower()
    output = task.get("output", "")

    # 深审条件
    deep_signals = [
        len(output) > 2000,                           # 大量输出
        spec.get("cognitive_mode") == "designer",     # 设计模式任务
        "refactor" in action or "重构" in action,      # 重构
        "architect" in action or "架构" in action,      # 架构变更
        spec.get("rework_count", 0) >= 2,             # 多次返工
        _count_files_in_output(output) > 5,            # 改了很多文件
    ]

    if any(deep_signals):
        return ReviewTier.DEEP

    return ReviewTier.QUICK


def get_review_config(tier: str) -> dict:
    """获取审查配置。"""
    if tier == ReviewTier.DEEP:
        return {
            "max_turns": 30,
            "timeout_s": 300,
            "model": MODEL_SONNET,
            "instructions": (
                "这是一个大型改动的深度审查。请：\n"
                "1. 逐文件检查每个改动\n"
                "2. 运行所有相关测试\n"
                "3. 检查边界条件和错误处理\n"
                "4. 评估架构影响\n"
                "5. 检查是否引入技术债\n"
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
    import re
    paths = re.findall(r'(?:src|departments|SOUL|dashboard|tests)/[\w/.-]+\.\w+', output)
    return len(set(paths))
