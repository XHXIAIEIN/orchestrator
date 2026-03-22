"""
Complexity Classifier — 加权关键词判断任务复杂度。

codingbuddy 启发：简单任务跳过完整编排流程。
与 Gateway 三路分流互补：三路分流看请求类型，复杂度分类看任务深度。

复杂度等级：
  TRIVIAL — 改名、改配置、加注释（直接执行，跳过门下省）
  SIMPLE  — 小 bug 修复、单文件改动（快速审查）
  MODERATE — 多文件改动、新功能（标准流程）
  COMPLEX — 重构、架构变更、跨项目（深度审查 + 设计模式）
"""
import re
from enum import IntEnum


class Complexity(IntEnum):
    TRIVIAL = 0
    SIMPLE = 1
    MODERATE = 2
    COMPLEX = 3


# 关键词 → 权重
_COMPLEXITY_SIGNALS: list[tuple[list[str], int]] = [
    # 高复杂度信号 (+3)
    (["重构", "refactor", "架构", "architecture", "迁移", "migrate",
      "redesign", "重新设计", "系统", "framework"], 3),

    # 中复杂度信号 (+2)
    (["新功能", "feature", "implement", "实现", "集成", "integrate",
      "多个文件", "multiple files", "跨项目", "cross-project",
      "数据库", "database", "schema"], 2),

    # 低复杂度信号 (+1)
    (["修复", "fix", "bug", "错误", "error", "更新", "update",
      "添加", "add", "调整", "adjust"], 1),

    # 简单信号 (-1)
    (["改名", "rename", "配置", "config", "注释", "comment",
      "清理", "cleanup", "格式", "format", "typo", "拼写"], -1),
]

# 文件数量权重
_FILE_COUNT_WEIGHT = {
    1: 0,       # 单文件 → 不加分
    3: 1,       # 2-3 文件 → +1
    5: 2,       # 4-5 文件 → +2
    999: 3,     # 6+ 文件 → +3
}


def classify_complexity(action: str, spec: dict = None) -> Complexity:
    """根据任务描述和 spec 判断复杂度。"""
    text = action.lower()
    if spec:
        text += " " + (spec.get("problem", "") + " " + spec.get("summary", "")).lower()

    score = 0

    # 关键词加权
    for keywords, weight in _COMPLEXITY_SIGNALS:
        for kw in keywords:
            if kw in text:
                score += weight
                break  # 每组只匹配一次

    # 文件数量（如果 spec 里有 files_changed）
    if spec:
        files = spec.get("files_changed", [])
        n = len(files) if isinstance(files, list) else 0
        for threshold, weight in sorted(_FILE_COUNT_WEIGHT.items()):
            if n <= threshold:
                score += weight
                break

    # 映射到等级
    if score <= 0:
        return Complexity.TRIVIAL
    elif score <= 2:
        return Complexity.SIMPLE
    elif score <= 4:
        return Complexity.MODERATE
    else:
        return Complexity.COMPLEX


def should_skip_scrutiny(complexity: Complexity) -> bool:
    """TRIVIAL 任务跳过门下省审查。"""
    return complexity <= Complexity.TRIVIAL


def get_recommended_turns(complexity: Complexity) -> int:
    """根据复杂度推荐 agent 最大轮数。"""
    return {
        Complexity.TRIVIAL: 8,
        Complexity.SIMPLE: 15,
        Complexity.MODERATE: 25,
        Complexity.COMPLEX: 40,
    }[complexity]
