"""
Intent-based Routing — 意图到部门的声明式映射 + Policy Profiles。

每个意图类型绑定一个 policy profile（决定模型选择、超时、token 预算），
取代硬编码的部门路由。

Ferment-inspired: intent → capability → policy profile
"""
from dataclasses import dataclass, field
from enum import Enum


class PolicyProfile(Enum):
    """执行策略档位。决定模型选择、超时和 token 预算。"""
    LOW_LATENCY = "low_latency"      # haiku, 短超时, 低 token
    BALANCED = "balanced"            # sonnet, 中等超时
    HIGH_QUALITY = "high_quality"    # sonnet/opus, 长超时, 高 token


@dataclass
class PolicyConfig:
    """每个 profile 的具体参数。"""
    model: str
    max_turns: int
    timeout_s: int
    max_output_tokens: int  # agent 输出上限

    @classmethod
    def from_profile(cls, profile: PolicyProfile) -> "PolicyConfig":
        return _PROFILE_CONFIGS[profile]


_PROFILE_CONFIGS: dict[PolicyProfile, "PolicyConfig"] = {
    PolicyProfile.LOW_LATENCY: PolicyConfig(
        model="claude-haiku-4-5",
        max_turns=10,
        timeout_s=120,
        max_output_tokens=1024,
    ),
    PolicyProfile.BALANCED: PolicyConfig(
        model="claude-sonnet-4-6",
        max_turns=25,
        timeout_s=300,
        max_output_tokens=4096,
    ),
    PolicyProfile.HIGH_QUALITY: PolicyConfig(
        model="claude-sonnet-4-6",
        max_turns=40,
        timeout_s=600,
        max_output_tokens=8192,
    ),
}


@dataclass
class IntentRoute:
    """意图到部门的路由规则。"""
    intent: str              # 意图标识
    department: str          # 目标部门
    profile: PolicyProfile   # 执行策略
    description: str = ""    # 人类可读描述
    requires_approval: bool = False  # 是否需要人工批准


# ── Intent Route Table ──
# 声明式路由：intent → department + policy profile
INTENT_ROUTES: dict[str, IntentRoute] = {
    # 工部 — 代码变更
    "code_fix": IntentRoute("code_fix", "engineering", PolicyProfile.BALANCED,
                            "Bug 修复、错误处理"),
    "code_feature": IntentRoute("code_feature", "engineering", PolicyProfile.HIGH_QUALITY,
                                "新功能开发"),
    "code_refactor": IntentRoute("code_refactor", "engineering", PolicyProfile.HIGH_QUALITY,
                                 "代码重构"),
    "code_config": IntentRoute("code_config", "engineering", PolicyProfile.LOW_LATENCY,
                               "配置调整、改名、清理"),

    # 户部 — 运维
    "ops_repair": IntentRoute("ops_repair", "operations", PolicyProfile.BALANCED,
                              "采集器/服务修复"),
    "ops_deploy": IntentRoute("ops_deploy", "operations", PolicyProfile.BALANCED,
                              "部署、配置更新", requires_approval=True),
    "ops_health": IntentRoute("ops_health", "operations", PolicyProfile.LOW_LATENCY,
                              "健康检查、状态查询"),

    # 礼部 — 审计
    "audit_attention": IntentRoute("audit_attention", "protocol", PolicyProfile.LOW_LATENCY,
                                   "注意力审计、TODO 扫描"),
    "audit_debt": IntentRoute("audit_debt", "protocol", PolicyProfile.LOW_LATENCY,
                              "技术债扫描"),

    # 兵部 — 安全
    "security_scan": IntentRoute("security_scan", "security", PolicyProfile.LOW_LATENCY,
                                 "安全扫描、依赖审计"),
    "security_incident": IntentRoute("security_incident", "security", PolicyProfile.HIGH_QUALITY,
                                     "安全事件响应", requires_approval=True),

    # 刑部 — 质量
    "quality_review": IntentRoute("quality_review", "quality", PolicyProfile.BALANCED,
                                  "Code review、测试执行"),
    "quality_regression": IntentRoute("quality_regression", "quality", PolicyProfile.HIGH_QUALITY,
                                      "回归测试、完整验收"),

    # 吏部 — 绩效
    "perf_report": IntentRoute("perf_report", "personnel", PolicyProfile.LOW_LATENCY,
                               "绩效报告、趋势分析"),
    "perf_deep": IntentRoute("perf_deep", "personnel", PolicyProfile.BALANCED,
                             "深度能力评估"),
}

# 部门默认 intent（当 LLM 只返回部门名时的 fallback）
_DEPT_DEFAULT_INTENT: dict[str, str] = {
    "engineering": "code_fix",
    "operations": "ops_repair",
    "protocol": "audit_attention",
    "security": "security_scan",
    "quality": "quality_review",
    "personnel": "perf_report",
}


def resolve_route(intent: str = "", department: str = "") -> IntentRoute:
    """Resolve an intent to a route. Falls back by department if intent unknown."""
    if intent and intent in INTENT_ROUTES:
        return INTENT_ROUTES[intent]

    # Fallback: department → default intent
    if department:
        default_intent = _DEPT_DEFAULT_INTENT.get(department, "code_fix")
        return INTENT_ROUTES.get(default_intent, INTENT_ROUTES["code_fix"])

    return INTENT_ROUTES["code_fix"]


def get_policy_config(route: IntentRoute) -> PolicyConfig:
    """Get the execution policy config for a route."""
    return PolicyConfig.from_profile(route.profile)
