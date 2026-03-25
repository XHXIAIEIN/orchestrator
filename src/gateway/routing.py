"""
Intent-based Routing — 意图到部门的声明式映射 + Policy Profiles。

每个意图类型绑定一个 policy profile（决定模型选择、超时、token 预算），
取代硬编码的部门路由。

Ferment-inspired: intent → capability → policy profile
"""
from dataclasses import dataclass, field
from enum import Enum

from src.core.llm_router import MODEL_SONNET, MODEL_HAIKU


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
        model=MODEL_HAIKU,
        max_turns=10,
        timeout_s=120,
        max_output_tokens=1024,
    ),
    PolicyProfile.BALANCED: PolicyConfig(
        model=MODEL_SONNET,
        max_turns=25,
        timeout_s=300,
        max_output_tokens=4096,
    ),
    PolicyProfile.HIGH_QUALITY: PolicyConfig(
        model=MODEL_SONNET,
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


# ── Intent Route Table (manifest-driven auto-discovery) ──
# Built from departments/*/manifest.yaml by registry.py.
# Bridges IntentEntry → IntentRoute with proper PolicyProfile enums.

from src.governance.registry import INTENT_ENTRIES, DEPT_DEFAULT_INTENTS

_PROFILE_MAP = {
    "LOW_LATENCY": PolicyProfile.LOW_LATENCY,
    "BALANCED": PolicyProfile.BALANCED,
    "HIGH_QUALITY": PolicyProfile.HIGH_QUALITY,
}


def _build_routes() -> dict[str, IntentRoute]:
    """Convert registry IntentEntries to IntentRoutes."""
    routes = {}
    for name, entry in INTENT_ENTRIES.items():
        profile = _PROFILE_MAP.get(entry.profile, PolicyProfile.BALANCED)
        routes[name] = IntentRoute(
            intent=name,
            department=entry.department,
            profile=profile,
            description=entry.description,
            requires_approval=entry.requires_approval,
        )
    return routes


INTENT_ROUTES: dict[str, IntentRoute] = _build_routes()

# 部门默认 intent（当 LLM 只返回部门名时的 fallback）
_DEPT_DEFAULT_INTENT: dict[str, str] = dict(DEPT_DEFAULT_INTENTS)


def _fallback_route() -> IntentRoute:
    """Return the first available route as ultimate fallback (no hardcoded keys)."""
    if INTENT_ROUTES:
        return next(iter(INTENT_ROUTES.values()))
    # Absolute last resort — should never happen if any manifest exists
    return IntentRoute("unknown", "engineering", PolicyProfile.BALANCED, "fallback")


def resolve_route(intent: str = "", department: str = "") -> IntentRoute:
    """Resolve an intent to a route. Falls back by department if intent unknown."""
    if intent and intent in INTENT_ROUTES:
        return INTENT_ROUTES[intent]

    # Fallback: department → default intent
    if department:
        default_intent = _DEPT_DEFAULT_INTENT.get(department)
        if default_intent and default_intent in INTENT_ROUTES:
            return INTENT_ROUTES[default_intent]

    return _fallback_route()


def get_policy_config(route: IntentRoute) -> PolicyConfig:
    """Get the execution policy config for a route."""
    return PolicyConfig.from_profile(route.profile)
