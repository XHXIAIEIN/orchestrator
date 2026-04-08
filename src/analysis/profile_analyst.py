"""
ProfileAnalyst — 深度用户画像分析引擎。
periodic: 分析最近 30 天数据，每 6 小时运行一次。
daily:    分析昨天数据，每日 06:00 CST 运行。
"""
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta

log = logging.getLogger(__name__)

from src.storage.events_db import EventsDB
from src.governance.context.prompts import load_prompt
from src.core.agent_client import agent_query_json
from src.core.llm_router import MODEL_OPUS

PROFILE_TOOL = {
    "name": "save_profile_analysis",
    "description": "Save deep user profile analysis result",
    "input_schema": {
        "type": "object",
        "properties": {
            "overview": {
                "type": "string",
                "description": "Overall impression of user's state this period (under 200 Chinese chars, direct, insightful)"
            },
            "strengths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "User strengths, traits, or abilities observed from data (3-5 items)"
            },
            "blind_spots": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Possible blind spots, concerning patterns, or overlooked issues (2-4 items)"
            },
            "suggestions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "description": "Specific actionable suggestion"},
                        "reason": {"type": "string", "description": "Reason and data evidence for the suggestion"},
                        "priority": {"type": "string", "enum": ["high", "medium", "low"]}
                    },
                    "required": ["action", "reason", "priority"]
                },
                "description": "3-5 targeted suggestions based on data"
            },
            "commentary": {
                "type": "string",
                "description": "Frenemy roast: data-driven trash talk, late-night text vibe not weekly report (200-350 Chinese chars)"
            },
            "daily_note": {
                "type": "string",
                "description": "Daily type only: yesterday's dedicated roast (under 100 Chinese chars). Empty string for periodic type."
            }
        },
        "required": ["overview", "strengths", "blind_spots", "suggestions", "commentary", "daily_note"]
    }
}

SYSTEM_PROMPT = load_prompt("profile")


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


JSON_INSTRUCTION = """

CRITICAL: All data is already provided below. Do NOT use any tools. Output ONLY a valid JSON object directly. No markdown fences, no planning, no extra text.

{
  "overview": "overall impression (50-100 Chinese chars)",
  "strengths": ["strength with data evidence", "strength 2", "strength 3"],
  "blind_spots": ["blind spot with data evidence", "blind spot 2"],
  "suggestions": [
    {"action": "specific actionable suggestion", "reason": "data-backed reason", "priority": "high|medium|low"}
  ],
  "commentary": "frenemy roast, 200-350 Chinese chars, data-driven, late-night text vibe not weekly report",
  "daily_note": "daily type only (under 100 Chinese chars), empty string for periodic"
}"""

MODEL_NAME = MODEL_OPUS


class ProfileAnalyst:
    def __init__(self, db: EventsDB = None, db_path: str = None):
        self.db = db or (EventsDB(db_path) if db_path else EventsDB())

    def run(self, analysis_type: str = 'periodic') -> dict | None:
        context = _build_context(self.db, analysis_type)
        prompt = SYSTEM_PROMPT + JSON_INSTRUCTION + "\n\n" + context

        try:
            parsed = agent_query_json(prompt, model=MODEL_NAME)
        except RuntimeError:
            log.error("ProfileAnalyst: agent_query_json failed, skipping this run")
            return None

        self.db.save_profile_analysis(parsed, analysis_type)
        return parsed


if __name__ == "__main__":
    analyst = ProfileAnalyst()
    result = analyst.run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
