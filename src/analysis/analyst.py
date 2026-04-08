import json
import logging
from datetime import datetime, timezone, timedelta
from src.storage.events_db import EventsDB
from src.governance.context.prompts import load_prompt
from src.core.llm_backends import claude_generate
from src.core.llm_models import MODEL_OPUS

# Orchestrator serves a UTC+8 user — all daily boundaries use this offset
_LOCAL_TZ = timezone(timedelta(hours=8))

log = logging.getLogger(__name__)

MODEL_NAME = MODEL_OPUS

ANALYST_PROMPT = load_prompt("analyst")


class DailyAnalyst:
    def __init__(self, db: EventsDB = None, db_path: str = None):
        self.db = db or (EventsDB(db_path) if db_path else EventsDB())

    def run(self) -> dict:
        # Pull events for "yesterday" in local timezone (UTC+8), not last-24h-UTC
        now_local = datetime.now(_LOCAL_TZ)
        yesterday_start = (now_local.replace(hour=0, minute=0, second=0, microsecond=0)
                           - timedelta(days=1))
        since_utc = yesterday_start.astimezone(timezone.utc).isoformat()
        events = self.db.get_recent_events(since=since_utc)
        profile = self.db.get_latest_profile()

        events_text = json.dumps(events[:50], ensure_ascii=False, indent=2, default=str)
        profile_text = json.dumps(profile, ensure_ascii=False, indent=2) if profile else "（暂无历史画像）"

        prompt = f"{ANALYST_PROMPT}\n\n今日活动数据：\n{events_text}\n\n当前用户画像：\n{profile_text}"

        try:
            raw = claude_generate(prompt, model=MODEL_NAME, timeout=120, max_tokens=4096)
            text = raw.strip()
            if text.startswith("```"):
                first_nl = text.find("\n")
                if first_nl >= 0:
                    text = text[first_nl + 1:]
                if text.endswith("```"):
                    text = text[:-3]
            result = json.loads(text)
        except json.JSONDecodeError as e:
            log.error(f"DailyAnalyst: JSON parse error: {e}, raw: {raw[:200] if raw else 'EMPTY'}")
            return {}
        except Exception as e:
            log.error(f"DailyAnalyst: API error: {e}")
            return {}

        report_date = yesterday_start.date().isoformat()
        self.db.save_daily_summary(report_date, json.dumps(result, ensure_ascii=False))
        if result.get("profile_update"):
            updated = {**(profile or {}), **result["profile_update"]}
            self.db.save_user_profile(updated)

        return result
