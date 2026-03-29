"""
Intent Gateway — Orchestrator 的前台接待。
把用户的自然语言指令翻译成 Governor 能理解的结构化任务。

灵感：OpenCLI 的 capability routing — 理解用户要什么，路由到对的地方。
"""
import json
import logging
from dataclasses import dataclass, asdict
from typing import Optional

from src.core.llm_router import get_router
from src.gateway.intent_rules import try_rule_match

log = logging.getLogger(__name__)

# Governor 支持的部门 (manifest-driven)
from src.governance.registry import VALID_DEPARTMENTS, get_tags_for_prompt, get_intents_for_prompt
VALID_COGNITIVE_MODES = {"direct", "react", "hypothesis", "designer"}
VALID_PRIORITIES = {"low", "medium", "high", "critical"}

def _build_intent_prompt() -> str:
    """Build intent prompt dynamically from manifest-discovered departments."""
    dept_section = get_tags_for_prompt()
    intent_section = get_intents_for_prompt()
    n_depts = len(VALID_DEPARTMENTS)
    return f"""You are Orchestrator's intent parser. Translate natural-language user commands into structured task specifications.

## Departments (matched by semantic tags)
{dept_section}

## Intent types
{intent_section}

## Cognitive modes"""


# Lazy-build on first use to avoid import-time issues
_intent_prompt_cache = None


def _get_intent_prompt():
    global _intent_prompt_cache
    if _intent_prompt_cache is None:
        _intent_prompt_cache = _build_intent_prompt() + _INTENT_PROMPT_SUFFIX
    return _intent_prompt_cache


_INTENT_PROMPT_SUFFIX = """
- direct: trivial tasks (rename, cleanup, config tweak)
- react: moderate complexity (think as you go)
- hypothesis: diagnostic (form hypothesis, then verify — "why does X fail")
- designer: large changes (design first, then implement — "refactor system X")

## Output format (strict JSON)
{{
  "action": "one-line description of what to do",
  "intent": "intent type (one from the list above)",
  "department": "target department (one from the list above)",
  "cognitive_mode": "cognitive mode",
  "priority": "low/medium/high/critical",
  "problem": "problem description",
  "expected": "expected outcome",
  "needs_clarification": false,
  "clarification_question": null
}}

If the user's command is too vague to determine an action, set needs_clarification=true and ask a clarifying question in clarification_question (respond in the user's language).

## Context
{context}

## User command
{user_input}
"""


@dataclass
class TaskIntent:
    """解析后的用户意图。"""
    action: str
    intent: str  # intent type for routing (e.g. "code_fix", "ops_repair")
    department: str
    cognitive_mode: str
    priority: str
    problem: str
    expected: str
    needs_clarification: bool
    clarification_question: Optional[str] = None

    def to_governor_spec(self) -> dict:
        """转换为 Governor._dispatch_task() 需要的 spec 格式。"""
        return {
            "department": self.department,
            "intent": self.intent,
            "problem": self.problem,
            "expected": self.expected,
            "summary": self.action,
            "cognitive_mode": self.cognitive_mode,
            "source": "user_intent",
            "observation": f"用户指令：{self.action}",
            "importance": f"用户直接指派，优先级 {self.priority}",
        }


# ── Model Fallback Chain (stolen from OpenFang) ──
_INTENT_FALLBACK_MODELS = None  # lazy init

def _get_fallback_models() -> list[str]:
    """Build ordered list of models for intent parsing fallback."""
    global _INTENT_FALLBACK_MODELS
    if _INTENT_FALLBACK_MODELS is None:
        from src.core.llm_models import MODEL_HAIKU, MODEL_SONNET
        _INTENT_FALLBACK_MODELS = [MODEL_HAIKU, MODEL_SONNET]
    return _INTENT_FALLBACK_MODELS


class IntentGateway:
    """Orchestrator 的前台。理解用户说什么，翻译成 Governor 的语言。"""

    def parse(self, user_input: str, context: dict = None) -> TaskIntent:
        """Parse user command. Tries rule engine first, falls back to LLM."""
        # Fast path: rule-based matching (no LLM cost)
        rule_result = try_rule_match(user_input)
        if rule_result is not None:
            return rule_result

        # Slow path: LLM-based parsing
        ctx_str = json.dumps(context or {}, ensure_ascii=False, indent=2)
        prompt = _get_intent_prompt().format(user_input=user_input, context=ctx_str)
        raw = self._call_llm(prompt)
        return self._validate(raw)

    def _call_llm(self, prompt: str) -> dict:
        """Call LLM to parse intent, with model fallback chain."""
        from src.gateway.model_fallback import ModelFallbackChain
        from src.core.llm_backends import claude_generate

        chain = ModelFallbackChain(
            models=_get_fallback_models(),
            min_response_len=20,  # valid JSON is at least ~20 chars
        )

        def _call(prompt: str, model: str) -> str:
            return claude_generate(prompt, model, timeout=30, max_tokens=512)

        try:
            response = chain.call(prompt, _call)
        except RuntimeError:
            log.warning("intent: all fallback models failed")
            return {
                "action": "", "department": "", "cognitive_mode": "react",
                "priority": "medium", "problem": "", "expected": "",
                "needs_clarification": True,
                "clarification_question": "LLM 服务暂时不可用，请稍后再试。",
            }

        # Extract JSON
        import re
        text = response.strip()
        m = re.search(r'```(?:json)?\s*(.*?)```', text, re.DOTALL)
        if m:
            text = m.group(1).strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            log.warning(f"intent: failed to parse LLM response as JSON: {text[:200]}")
            return {
                "action": "", "department": "", "cognitive_mode": "react",
                "priority": "medium", "problem": "", "expected": "",
                "needs_clarification": True,
                "clarification_question": "抱歉，我没理解你的意思。能换个说法吗？",
            }

    def _validate(self, raw: dict) -> TaskIntent:
        """校验并规范化 LLM 输出。"""
        dept = raw.get("department", "").lower()
        if dept not in VALID_DEPARTMENTS:
            dept = "engineering"  # 默认工部

        intent = raw.get("intent", "").lower()
        # intent 不做强校验，routing.resolve_route 会 fallback

        mode = raw.get("cognitive_mode", "react").lower()
        if mode not in VALID_COGNITIVE_MODES:
            mode = "react"

        priority = raw.get("priority", "medium").lower()
        if priority not in VALID_PRIORITIES:
            priority = "medium"

        return TaskIntent(
            action=raw.get("action", ""),
            intent=intent,
            department=dept,
            cognitive_mode=mode,
            priority=priority,
            problem=raw.get("problem", ""),
            expected=raw.get("expected", ""),
            needs_clarification=bool(raw.get("needs_clarification", False)),
            clarification_question=raw.get("clarification_question"),
        )
