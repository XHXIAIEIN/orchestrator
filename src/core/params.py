"""
参数清洗工具 — 偷自 Tavily MCP Server 的参数预处理模式。

核心思路：API 调用前统一清洗参数，移除无效值、解决互斥冲突，
避免下游 API 因为 None / 空字符串 / 矛盾参数而报错。

用法:
    from src.core.params import sanitize_params

    params = sanitize_params(
        {"query": "test", "max_results": None, "filter": "", "tags": []},
        mutex_groups=[["time_range", "start_date"]],
    )
    # → {"query": "test"}
"""
from typing import Any


def sanitize_params(
    params: dict[str, Any],
    mutex_groups: list[list[str]] | None = None,
) -> dict[str, Any]:
    """清洗参数字典。

    1. 移除值为 None / 空字符串 / 空列表 / 空字典 的键
    2. 处理互斥参数组：同组内如果有多个键存在，保留第一个有值的，移除其余

    Args:
        params: 原始参数字典（不会被修改）
        mutex_groups: 互斥参数组列表。例如 [["time_range", "start_date", "end_date"]]
                      表示这三个参数互斥，只保留第一个有值的。

    Returns:
        清洗后的新字典
    """
    # Step 1: 移除空值
    cleaned = {
        k: v for k, v in params.items()
        if v is not None and v != "" and v != [] and v != {}
    }

    # Step 2: 互斥参数解冲突
    if mutex_groups:
        for group in mutex_groups:
            # 找出组内所有存在且有值的键
            present = [k for k in group if k in cleaned]
            if len(present) > 1:
                # 保留第一个，移除其余
                for k in present[1:]:
                    del cleaned[k]

    return cleaned


def merge_defaults(
    params: dict[str, Any],
    defaults: dict[str, Any],
    locked: frozenset[str] | None = None,
) -> dict[str, Any]:
    """将默认值与用户参数合并。locked 参数强制使用默认值。

    偷自 Tavily 的 DEFAULT_PARAMETERS 环境变量模式：
    预设默认值，请求时可覆盖，但 locked 参数不可覆盖。

    Args:
        params: 用户提供的参数
        defaults: 预设默认值
        locked: 锁死的参数名集合（强制使用 defaults 中的值）

    Returns:
        合并后的新字典
    """
    result = {**defaults}
    locked = locked or frozenset()

    for k, v in params.items():
        if k in locked:
            continue  # 锁死参数不可覆盖
        result[k] = v

    return result
