import json
from datetime import date
from src.config import get_anthropic_client
from src.storage.events_db import EventsDB

ANALYST_TOOL = {
    "name": "save_analysis",
    "description": "保存今日分析结果和用户画像更新",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "今日活动一句话摘要"},
            "time_breakdown": {
                "type": "object",
                "description": "各类别活动时间（分钟），如 {coding: 120, reading: 30}"
            },
            "top_topics": {
                "type": "array",
                "items": {"type": "string"},
                "description": "今日最高频出现的主题关键词"
            },
            "behavioral_insights": {"type": "string", "description": "行为模式洞察（一段话）"},
            "profile_update": {
                "type": "object",
                "description": "需要更新到用户画像的字段"
            }
        },
        "required": ["summary", "top_topics", "behavioral_insights", "profile_update"]
    }
}

ANALYST_PROMPT = """你是 Orchestrator 管家，正在记今天的工作日志。

基于数据说话，不猜测。记清楚这几件事：
1. 今天实际做了什么——哪些项目、什么内容
2. 时间怎么分的——量化到小时（"RAG 3.2h, 浏览 1.5h, 音乐 0.8h"）
3. 今天反复出现的主题——反映真实兴趣和焦点
4. 值得注意的模式——凌晨活跃、长时间深度专注、突然冒出的新兴趣
5. 画像需要更新什么——只写真正变了的，别每天重写一遍

简洁、有洞察力。这是管家日志，不是年终总结。"""


class DailyAnalyst:
    def __init__(self, db: EventsDB = None, db_path: str = "events.db"):
        self.client = get_anthropic_client()
        self.db = db or EventsDB(db_path)

    def run(self) -> dict:
        events = self.db.get_recent_events(days=1)
        profile = self.db.get_latest_profile()

        events_text = json.dumps(events[:50], ensure_ascii=False, indent=2, default=str)
        profile_text = json.dumps(profile, ensure_ascii=False, indent=2) if profile else "（暂无历史画像）"

        response = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=ANALYST_PROMPT,
            tools=[ANALYST_TOOL],
            tool_choice={"type": "tool", "name": "save_analysis"},
            messages=[{
                "role": "user",
                "content": f"今日活动数据：\n{events_text}\n\n当前用户画像：\n{profile_text}"
            }],
        )

        block = next(b for b in response.content if b.type == "tool_use")
        result = block.input

        today = date.today().isoformat()
        self.db.save_daily_summary(today, json.dumps(result, ensure_ascii=False))
        if result.get("profile_update"):
            updated = {**(profile or {}), **result["profile_update"]}
            self.db.save_user_profile(updated)

        return result
