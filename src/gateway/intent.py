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

log = logging.getLogger(__name__)

# Governor 支持的六部
VALID_DEPARTMENTS = {"engineering", "operations", "protocol", "security", "quality", "personnel"}
VALID_COGNITIVE_MODES = {"direct", "react", "hypothesis", "designer"}
VALID_PRIORITIES = {"low", "medium", "high", "critical"}

INTENT_PROMPT = """你是 Orchestrator 的意图解析器。用户会用自然语言发指令，你需要翻译成结构化任务。

## Orchestrator 六部
- engineering（工部）：代码修改、bug 修复、功能开发、重构
- operations（户部）：运维、部署、配置、系统健康
- protocol（礼部）：注意力审计、时间分析、债务扫描
- security（兵部）：安全扫描、依赖审计、漏洞检测
- quality（刑部）：测试、code review、质量验收
- personnel（吏部）：绩效分析、能力评估、发现层

## 认知模式
- direct: 简单任务（改名、清理、配置调整）
- react: 中等复杂（边做边想）
- hypothesis: 诊断类（先假设后验证 — "为什么X不工作"）
- designer: 大型改动（先设计后实现 — "重构X系统"）

## 输出格式（严格 JSON）
{{
  "action": "一句话描述要做什么",
  "department": "目标部门（上面六个之一）",
  "cognitive_mode": "认知模式",
  "priority": "low/medium/high/critical",
  "problem": "问题描述",
  "expected": "期望结果",
  "needs_clarification": false,
  "clarification_question": null
}}

如果用户指令太模糊无法确定行动，设置 needs_clarification=true 并在 clarification_question 中用中文提问。

## 上下文
{context}

## 用户指令
{user_input}
"""


@dataclass
class TaskIntent:
    """解析后的用户意图。"""
    action: str
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
            "problem": self.problem,
            "expected": self.expected,
            "summary": self.action,
            "cognitive_mode": self.cognitive_mode,
            "source": "user_intent",
            "observation": f"用户指令：{self.action}",
            "importance": f"用户直接指派，优先级 {self.priority}",
        }


class IntentGateway:
    """Orchestrator 的前台。理解用户说什么，翻译成 Governor 的语言。"""

    def parse(self, user_input: str, context: dict = None) -> TaskIntent:
        """解析用户自然语言指令。"""
        ctx_str = json.dumps(context or {}, ensure_ascii=False, indent=2)
        prompt = INTENT_PROMPT.format(user_input=user_input, context=ctx_str)

        raw = self._call_llm(prompt)
        return self._validate(raw)

    def _call_llm(self, prompt: str) -> dict:
        """调用 LLM 解析意图。用最便宜的模型。"""
        router = get_router()
        response = router.generate(prompt, task_type="scrutiny", max_tokens=512)

        # 提取 JSON（用正则避免多 code block 截断）
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

        mode = raw.get("cognitive_mode", "react").lower()
        if mode not in VALID_COGNITIVE_MODES:
            mode = "react"

        priority = raw.get("priority", "medium").lower()
        if priority not in VALID_PRIORITIES:
            priority = "medium"

        return TaskIntent(
            action=raw.get("action", ""),
            department=dept,
            cognitive_mode=mode,
            priority=priority,
            problem=raw.get("problem", ""),
            expected=raw.get("expected", ""),
            needs_clarification=bool(raw.get("needs_clarification", False)),
            clarification_question=raw.get("clarification_question"),
        )
