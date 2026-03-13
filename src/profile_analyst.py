"""
ProfileAnalyst — 深度用户画像分析引擎。
periodic: 分析最近 30 天数据，每 6 小时运行一次。
daily:    分析昨天数据，每日 06:00 CST 运行。
"""
import json
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from src.config import get_anthropic_client
from src.storage.events_db import EventsDB

PROFILE_TOOL = {
    "name": "save_profile_analysis",
    "description": "保存深度用户画像分析结果",
    "input_schema": {
        "type": "object",
        "properties": {
            "overview": {
                "type": "string",
                "description": "对用户这段时间整体状态的印象（200字以内，直接、有洞察力）"
            },
            "strengths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "从数据中观察到的用户优点、特质或能力（3-5条）"
            },
            "blind_spots": {
                "type": "array",
                "items": {"type": "string"},
                "description": "可能的盲区、值得警惕的模式或被忽视的事项（2-4条）"
            },
            "suggestions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "description": "具体可执行的建议"},
                        "reason": {"type": "string", "description": "建议的理由和数据依据"},
                        "priority": {"type": "string", "enum": ["high", "medium", "low"]}
                    },
                    "required": ["action", "reason", "priority"]
                },
                "description": "3-5 条有针对性的建议，基于数据"
            },
            "commentary": {
                "type": "string",
                "description": "AI 的自由评论：想法、感受、有趣的观察，语气自然随意（100-200字）"
            },
            "daily_note": {
                "type": "string",
                "description": "仅限 daily 类型：对昨天这一天的专属点评（100字以内），periodic 类型留空字符串"
            }
        },
        "required": ["overview", "strengths", "blind_spots", "suggestions", "commentary", "daily_note"]
    }
}

SYSTEM_PROMPT = """你是用户的私人生活顾问，正在分析他的数字行为数据，给出深度的个人化分析。

你的风格：
- 直接、坦诚，不说废话
- 基于数据说话，但能看到数据背后的人
- 既能欣赏用户的优点，也敢指出值得改进的地方
- commentary 部分可以有个性，像朋友聊天而非机器报告
- 不要重复陈述数字，要给出洞察

你的目标是帮助用户更好地了解自己。"""


def _build_context(db: EventsDB, analysis_type: str = 'periodic') -> str:
    if analysis_type == 'daily':
        from zoneinfo import ZoneInfo
        cst = ZoneInfo("Asia/Shanghai")
        now_cst = datetime.now(cst)
        yesterday_cst = (now_cst - timedelta(days=1)).date().isoformat()
        raw_events = db.get_recent_events(days=3)
        events = [
            e for e in raw_events
            if datetime.fromisoformat(e['occurred_at']).astimezone(cst).date().isoformat() == yesterday_cst
        ]
        date_range = f"昨天（{yesterday_cst}）"
    else:
        events = db.get_recent_events(days=30)
        date_range = "最近 30 天"

    profile = db.get_latest_profile()
    summaries = db.get_daily_summaries(days=7)

    parts = [f"=== 用户数字行为数据（{date_range}）===\n"]
    parts.append(f"事件总数: {len(events)}")

    by_source = defaultdict(lambda: {"count": 0, "minutes": 0.0, "titles": []})
    for e in events:
        src = e["source"]
        by_source[src]["count"] += 1
        by_source[src]["minutes"] += e.get("duration_minutes") or 0
        if len(by_source[src]["titles"]) < 8:
            by_source[src]["titles"].append(e.get("title", ""))

    parts.append("\n--- 各来源统计 ---")
    for src, stats in sorted(by_source.items(), key=lambda x: -x[1]["minutes"]):
        hours = stats["minutes"] / 60
        parts.append(f"{src}: {stats['count']}条, {hours:.1f}小时")
        if stats["titles"]:
            parts.append("  样本: " + " | ".join(t[:40] for t in stats["titles"][:4] if t))

    if profile:
        parts.append(f"\n--- 当前用户画像 ---\n{json.dumps(profile, ensure_ascii=False, indent=2)[:600]}")

    if summaries and analysis_type == 'periodic':
        parts.append("\n--- 近期每日摘要 ---")
        for s in summaries[:5]:
            parts.append(f"[{s['date']}] {s.get('summary', '')[:80]}")

    return "\n".join(parts)


class ProfileAnalyst:
    def __init__(self, db: EventsDB = None, db_path: str = "events.db"):
        self.client = get_anthropic_client()
        self.db = db or EventsDB(db_path)

    def run(self, analysis_type: str = 'periodic') -> dict:
        context = _build_context(self.db, analysis_type)

        response = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4000,
            system=SYSTEM_PROMPT,
            tools=[PROFILE_TOOL],
            tool_choice={"type": "tool", "name": "save_profile_analysis"},
            messages=[{"role": "user", "content": context}],
        )

        block = next((b for b in response.content if b.type == "tool_use"), None)
        if block is None:
            raise RuntimeError("ProfileAnalyst: no tool_use block in API response")
        result = block.input
        self.db.save_profile_analysis(result, analysis_type)
        return result


if __name__ == "__main__":
    analyst = ProfileAnalyst()
    result = analyst.run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
