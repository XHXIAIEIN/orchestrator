import json
import os
from datetime import date
import anthropic
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

ANALYST_PROMPT = """你是一个生活分析专家，根据用户的数字活动数据，生成有深度的每日洞察。

分析要点：
1. 今天实际做了什么（基于数据，不要猜测）
2. 时间如何分配（量化）
3. 反复出现的主题（反映真实兴趣）
4. 行为规律（活跃时段、专注深度）
5. 对用户画像的更新建议

风格：简洁、有洞察力、基于数据说话。"""


class DailyAnalyst:
    def __init__(self, api_key: str = None, db: EventsDB = None, db_path: str = "events.db"):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.client = anthropic.Anthropic(api_key=self.api_key)
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
            updated = {**profile, **result["profile_update"]}
            self.db.save_user_profile(updated)

        return result
