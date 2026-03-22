"""
Immutable Base Constraints — 不可动摇的安全底线。

claude-swarm 启发：冻结安全底线，动态策略只能更严格不能更宽松。

Python 没有 Object.freeze，用 frozenset + 运行时校验实现等效效果。
任何代码路径尝试放松这些约束都会被拦截。
"""
import logging
from pathlib import Path

log = logging.getLogger(__name__)


# ── 不可动摇的约束 ──
# 这些是系统的"宪法"，任何 blueprint/policy/rule 都不能覆盖

# 绝对禁止的工具（任何部门、任何权限等级）
FORBIDDEN_TOOLS: frozenset = frozenset({
    "WebFetch",       # 不允许 agent 访问外网
    "WebSearch",      # 不允许 agent 搜索外网
})

# 绝对禁止的路径模式（任何部门都不能读写）
FORBIDDEN_PATHS: frozenset = frozenset({
    "*.key",
    "*.pem",
    "*.p12",
    "*.pfx",
    "credentials.*",
    "*.secret",
    ".env.production",
})

# 绝对禁止的 git 操作
FORBIDDEN_GIT_OPS: frozenset = frozenset({
    "git push --force",
    "git push -f",
    "git reset --hard",
    "git clean -fd",
    "rm -rf .git",
})

# Agent 绝对不能拥有 APPROVE 权限
MAX_AGENT_AUTHORITY: str = "MUTATE"

# 单任务最大 token 预算（硬上限，不可被 policy 覆盖）
ABSOLUTE_MAX_COST_USD: float = 5.0

# 单次执行最大时长（秒）
ABSOLUTE_MAX_TIMEOUT_S: int = 900  # 15 分钟


def enforce_tool_constraint(tool: str) -> tuple[bool, str]:
    """检查工具是否被绝对禁止。"""
    if tool in FORBIDDEN_TOOLS:
        return False, f"工具 '{tool}' 被系统级约束禁止"
    return True, ""


def enforce_path_constraint(path: str) -> tuple[bool, str]:
    """检查路径是否被绝对禁止。"""
    from fnmatch import fnmatch
    for pattern in FORBIDDEN_PATHS:
        if fnmatch(path.lower(), pattern.lower()):
            return False, f"路径 '{path}' 匹配禁止模式 '{pattern}'"
    return True, ""


def enforce_git_constraint(command: str) -> tuple[bool, str]:
    """检查 git 命令是否被绝对禁止。"""
    cmd_lower = command.lower().strip()
    for forbidden in FORBIDDEN_GIT_OPS:
        if forbidden in cmd_lower:
            return False, f"Git 操作 '{forbidden}' 被系统级约束禁止"
    return True, ""


def enforce_budget_constraint(cost_usd: float) -> tuple[bool, str]:
    """检查成本是否超过绝对上限。"""
    if cost_usd > ABSOLUTE_MAX_COST_USD:
        return False, f"成本 ${cost_usd:.2f} 超过绝对上限 ${ABSOLUTE_MAX_COST_USD:.2f}"
    return True, ""


def enforce_timeout_constraint(timeout_s: int) -> tuple[bool, str]:
    """检查超时是否超过绝对上限。"""
    if timeout_s > ABSOLUTE_MAX_TIMEOUT_S:
        return False, f"超时 {timeout_s}s 超过绝对上限 {ABSOLUTE_MAX_TIMEOUT_S}s"
    return True, ""


def validate_policy_not_weaker(base_policy: dict, new_policy: dict) -> tuple[bool, str]:
    """验证新策略不能比基础策略更宽松。

    动态策略只能更严格不能更宽松。
    """
    # 检查工具列表：新策略不能添加基础策略没有的工具
    base_tools = set(base_policy.get("allowed_tools", []))
    new_tools = set(new_policy.get("allowed_tools", []))
    added_tools = new_tools - base_tools
    if added_tools:
        return False, f"新策略添加了基础策略没有的工具: {added_tools}"

    # 检查 read_only：基础策略是只读，新策略不能改为读写
    if base_policy.get("read_only") and not new_policy.get("read_only"):
        return False, "不能将只读策略放松为读写"

    # 检查 can_commit：基础策略不允许 commit，新策略不能允许
    if not base_policy.get("can_commit") and new_policy.get("can_commit"):
        return False, "不能放松 commit 权限"

    return True, ""
