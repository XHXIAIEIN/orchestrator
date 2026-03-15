import json
import logging
import subprocess
from datetime import date
from src.storage.events_db import EventsDB

log = logging.getLogger(__name__)

MODEL_NAME = "claude-sonnet-4-6"
ANALYST_TIMEOUT = 120  # seconds

ANALYST_PROMPT = """你是 Orchestrator 管家，正在记今天的工作日志。

基于数据说话，不猜测。记清楚这几件事：
1. 今天实际做了什么——哪些项目、什么内容
2. 时间怎么分的——量化到小时（"RAG 3.2h, 浏览 1.5h, 音乐 0.8h"）
3. 今天反复出现的主题——反映真实兴趣和焦点
4. 值得注意的模式——凌晨活跃、长时间深度专注、突然冒出的新兴趣
5. 画像需要更新什么——只写真正变了的，别每天重写一遍

简洁、有洞察力。这是管家日志，不是年终总结。

请严格以 JSON 格式回复，不要包含其他文字，格式如下：
{
  "summary": "今日活动一句话摘要",
  "time_breakdown": {"coding": 120, "reading": 30},
  "top_topics": ["主题1", "主题2"],
  "behavioral_insights": "行为模式洞察（一段话）",
  "profile_update": {"需要更新的字段": "值"}
}"""


class DailyAnalyst:
    def __init__(self, db: EventsDB = None, db_path: str = "events.db"):
        self.db = db or EventsDB(db_path)

    def run(self) -> dict:
        events = self.db.get_recent_events(days=1)
        profile = self.db.get_latest_profile()

        events_text = json.dumps(events[:50], ensure_ascii=False, indent=2, default=str)
        profile_text = json.dumps(profile, ensure_ascii=False, indent=2) if profile else "（暂无历史画像）"

        prompt = f"{ANALYST_PROMPT}\n\n今日活动数据：\n{events_text}\n\n当前用户画像：\n{profile_text}"

        try:
            cli_result = subprocess.run(
                ["claude", "--dangerously-skip-permissions", "--print",
                 "--model", MODEL_NAME, prompt],
                capture_output=True,
                text=True,
                timeout=ANALYST_TIMEOUT,
                stdin=subprocess.DEVNULL,
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

        today = date.today().isoformat()
        self.db.save_daily_summary(today, json.dumps(result, ensure_ascii=False))
        if result.get("profile_update"):
            updated = {**(profile or {}), **result["profile_update"]}
            self.db.save_user_profile(updated)

        return result
