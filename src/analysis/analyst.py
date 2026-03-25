import json
import logging
import subprocess
from datetime import datetime, timezone, timedelta
from src.storage.events_db import EventsDB
from src.governance.context.prompts import load_prompt

# Orchestrator serves a UTC+8 user — all daily boundaries use this offset
_LOCAL_TZ = timezone(timedelta(hours=8))

log = logging.getLogger(__name__)

MODEL_NAME = "claude-sonnet-4-6"
ANALYST_TIMEOUT = 120  # seconds

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
            cli_result = subprocess.run(
                ["claude", "--dangerously-skip-permissions", "--print",
                 "--model", MODEL_NAME, "-"],
                capture_output=True,
                text=True,
                timeout=ANALYST_TIMEOUT,
                input=prompt,
            )
            text = cli_result.stdout.strip()
            if not text:
                text = cli_result.stderr.strip()
                log.error(f"DailyAnalyst: claude CLI returned no stdout, stderr: {text[:200]}")
                return {}

            # Extract JSON from response (handle possible markdown fences)
            json_text = text
            if "```json" in json_text:
                json_text = json_text.split("```json", 1)[1].split("```", 1)[0]
            elif "```" in json_text:
                json_text = json_text.split("```", 1)[1].split("```", 1)[0]
            result = json.loads(json_text.strip())

        except subprocess.TimeoutExpired:
            log.error(f"DailyAnalyst: claude CLI timed out after {ANALYST_TIMEOUT}s")
            return {}
        except FileNotFoundError:
            log.error("DailyAnalyst: claude CLI not found in PATH")
            return {}
        except json.JSONDecodeError as e:
            log.error(f"DailyAnalyst: failed to parse JSON from claude response: {e}")
            log.debug(f"DailyAnalyst: raw response: {text[:500]}")
            return {}
        except Exception as e:
            log.error(f"DailyAnalyst: unexpected error: {e}")
            return {}

        report_date = yesterday_start.date().isoformat()
        self.db.save_daily_summary(report_date, json.dumps(result, ensure_ascii=False))
        if result.get("profile_update"):
            updated = {**(profile or {}), **result["profile_update"]}
            self.db.save_user_profile(updated)

        return result
