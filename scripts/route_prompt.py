"""Conversation-level routing hook — classify user prompt and inject dispatch context.

Called by .claude/hooks/routing-hook.sh on every UserPromptSubmit event.
Reads hook input JSON from stdin, uses the existing classifier, outputs
routing decision as JSON to stdout.

Flow:
    stdin (hook JSON) → extract prompt → classify → output additionalContext or empty

Classification tiers:
    CHAT      → pass through (no injection)
    NO_TOKEN  → inject: direct DB query hint
    DIRECT    → pass through (Claude handles)
    AGENT     → inject: route through Governor dispatch pipeline
    DEV       → pass through (orchestrator development, Claude handles directly)
"""
import json
import re
import sys
from pathlib import Path

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.gateway.classifier import classify, RequestTier


# ── CHAT detection (greetings, casual, meta-conversation) ──
_CHAT_PATTERNS = re.compile(
    r'^(?:'
    r'你好|嗨|hi|hello|hey|早|晚安|good\s*(?:morning|night)|'  # greetings
    r'谢谢|thanks?|thx|感谢|辛苦|'                              # gratitude
    r'嗯|ok|好的|收到|了解|明白|知道了|'                           # acknowledgement
    r'怎么样|还好吗|在吗|'                                       # casual check-in
    r'哈哈|lol|笑死|草|'                                        # reactions
    r'是的|对|没错|exactly|right|yeah|yep|'                      # affirmation
    r'不是|不对|no|nope|nah|算了|'                               # negation
    r'\.{1,3}|!{1,3}|\?{1,3}'                                  # punctuation-only
    r')$',
    re.I
)

# ── DEV detection (orchestrator codebase development — Claude handles directly) ──
_DEV_PATTERNS = re.compile(
    r'(?:'
    r'(?:这个|那个|这些)?\s*(?:模块|文件|代码|函数|类|方法)\s*(?:改|重构|接入|wire|refactor)|'
    r'(?:orphan|孤岛|孤儿)\s*(?:模块|module)|'
    r'(?:PR|pull\s*request|commit|branch|分支|提交)|'
    r'(?:CLAUDE\.md|boot\.md|settings\.json|hook|skill)|'
    r'(?:看看|读|read|check)\s*(?:这个|那个|这些)?\s*(?:文件|代码|实现|source)|'
    r'(?:architecture|架构|设计|design)\s*(?:文档|doc|图|diagram)?'
    r')',
    re.I
)

# Short messages: CJK chars carry more info per char than ASCII
_SHORT_THRESHOLD_ASCII = 6
_SHORT_THRESHOLD_CJK = 2

_CJK_RANGE = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')


def _is_too_short(text: str) -> bool:
    """CJK-aware short message detection."""
    if _CJK_RANGE.search(text):
        return len(text) <= _SHORT_THRESHOLD_CJK
    return len(text) <= _SHORT_THRESHOLD_ASCII


def route(prompt: str) -> dict | None:
    """Classify prompt and return routing context, or None for pass-through."""
    text = prompt.strip()

    if not text:
        return None

    # Layer 1: CHAT — short utterances, greetings, reactions
    if _CHAT_PATTERNS.match(text):
        return None

    if _is_too_short(text):
        return None  # too short to be a real task

    # Layer 2: DEV — orchestrator development work (Claude handles directly)
    if _DEV_PATTERNS.search(text):
        return None

    # Layer 3: existing classifier (NO_TOKEN / DIRECT / AGENT)
    result = classify(text)

    if result.tier == RequestTier.NO_TOKEN:
        return {
            "additionalContext": (
                f"[Routing] This is a status/data query (handler: {result.handler}). "
                f"Consider using the DB directly or /status skill. "
                f"No Governor dispatch needed."
            )
        }

    if result.tier == RequestTier.DIRECT:
        return None  # Claude handles single-turn responses naturally

    if result.tier == RequestTier.AGENT:
        return {
            "additionalContext": (
                "[Routing] This looks like a multi-step task. "
                "Route through the Governor pipeline:\n"
                "  python scripts/dispatch.py \"<task>\" --approve --wait\n"
                "This ensures proper Scrutinizer review, department routing, "
                "and execution tracking. Do NOT manually brief agents."
            )
        }

    return None


def main():
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            sys.exit(0)

        hook_input = json.loads(raw)
        prompt = hook_input.get("prompt", "")

        decision = route(prompt)
        if decision:
            print(json.dumps(decision, ensure_ascii=False))

    except Exception:
        # Hook must never crash — silent pass-through on error
        sys.exit(0)


if __name__ == "__main__":
    main()
