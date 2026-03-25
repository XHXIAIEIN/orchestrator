"""
On-demand deep insight engine.
Analyses 7 days of cross-source data and generates comprehensive recommendations.
"""
import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from src.storage.events_db import EventsDB
from src.governance.context.prompts import load_prompt
from src.core.agent_client import agent_query_json
from src.core.llm_router import MODEL_SONNET

logger = logging.getLogger(__name__)

MODEL_NAME = MODEL_SONNET

SYSTEM_PROMPT = load_prompt("insights")


def _read_recent_sessions(days: int = 7, limit: int = 30) -> list[dict]:
    """Directly read recent JSONL sessions and extract conversation snippets."""
    import time
    env_home = os.environ.get("CLAUDE_HOME")
    claude_home = (Path(env_home) / "projects") if env_home else Path.home() / ".claude" / "projects"
    if not claude_home.exists():
        return []

    cutoff = time.time() - days * 86400
    files = []
    for f in claude_home.rglob("*.jsonl"):
        try:
            mtime = f.stat().st_mtime
            if mtime > cutoff:
                files.append((mtime, f))
        except OSError:
            continue
    files.sort(reverse=True)

    sessions = []
    for _, fpath in files[:limit]:
        project = fpath.parent.name.replace("D--", "").replace("-", "/")[:50]
        slug = None
        user_msgs = []
        try:
            with open(fpath, encoding="utf-8", errors="ignore") as f:
                for i, line in enumerate(f):
                    if i >= 300:  # cap at 300 lines — files can be 2GB+
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    if not slug and isinstance(obj.get("slug"), str):
                        slug = obj["slug"]
                    if obj.get("type") == "user" and isinstance(obj.get("message"), dict):
                        content = obj["message"].get("content", "")
                        text = _get_text(content).strip()
                        if text and not text.startswith("[Request interrupted"):
                            user_msgs.append(text)
        except OSError:
            continue

        if not user_msgs:
            continue

        sessions.append({
            "project": project,
            "slug": slug or fpath.stem[:16],
            "messages": len(user_msgs),
            "first": user_msgs[0][:120],
            "last": user_msgs[-1][:120] if len(user_msgs) > 1 else "",
        })
    return sessions


def _get_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text":
                parts.append(c.get("text", ""))
        return " ".join(parts)
    return ""


def _build_context(db: EventsDB) -> str:
    events = db.get_recent_events(days=7)

    # Per-source stats
    by_source: dict[str, dict] = defaultdict(lambda: {"count": 0, "minutes": 0.0, "titles": []})
    for e in events:
        src = e["source"]
        by_source[src]["count"] += 1
        by_source[src]["minutes"] += e.get("duration_minutes") or 0
        if len(by_source[src]["titles"]) < 10:
            by_source[src]["titles"].append(e.get("title", ""))

    summaries_raw = db.get_daily_summaries(days=7)

    profile = db.get_latest_profile()

    # Top music
    music_events = [e for e in events if e["source"] == "youtube_music"]
    top_music = sorted(music_events, key=lambda e: e.get("duration_minutes", 0), reverse=True)[:10]

    # Top browser URLs (by duration)
    browser_events = [e for e in events if "browser" in e["source"]]
    top_browser = sorted(browser_events, key=lambda e: e.get("duration_minutes", 0), reverse=True)[:15]

    # Claude conversations
    claude_events = [e for e in events if e["source"] == "claude"]

    parts = [
        "=== 过去7天数据摘要 ===\n",
        f"总事件数: {len(events)}\n",
        "\n--- 各来源统计 ---",
    ]
    for src, stats in sorted(by_source.items(), key=lambda x: -x[1]["minutes"]):
        hours = stats["minutes"] / 60
        parts.append(f"{src}: {stats['count']}条, {hours:.1f}小时")
        if stats["titles"]:
            parts.append("  样本: " + " | ".join(t[:40] for t in stats["titles"][:5] if t))

    if top_browser:
        parts.append("\n--- Top 浏览内容（按时长）---")
        for e in top_browser[:10]:
            parts.append(f"  [{e['category']}] {e['title'][:60]} — {e.get('duration_minutes', 0):.0f}min")

    if top_music:
        parts.append("\n--- 最近听的音乐 ---")
        for e in top_music[:8]:
            parts.append(f"  {e['title'][:50]} — {e.get('duration_minutes', 0):.0f}min")

    if claude_events:
        parts.append("\n--- Claude 对话（最近10条）---")
        for e in claude_events[:10]:
            m = e.get("metadata", {})
            parts.append(f"  {e['title'][:70]} ({m.get('messages', '?')}条消息)")

    if summaries_raw:
        parts.append("\n--- 已有每日摘要 ---")
        for s in summaries_raw[:5]:
            parts.append(f"[{s['date']}] {s.get('summary', '')[:100]}")
            if s.get("behavioral_insights"):
                parts.append(f"  → {s['behavioral_insights'][:80]}")

    if profile:
        parts.append(f"\n--- 用户画像 ---\n{json.dumps(profile, ensure_ascii=False, indent=2)[:800]}")

    # Actual Claude conversation content from JSONL files
    sessions = _read_recent_sessions(days=7, limit=30)
    if sessions:
        parts.append("\n--- Claude 对话实际内容（最近30个会话）---")
        for s in sessions:
            parts.append(f"[{s['project']}] {s['slug']} ({s['messages']}条用户消息)")
            parts.append(f"  首条: {s['first']}")
            if s["last"] and s["last"] != s["first"]:
                parts.append(f"  末条: {s['last']}")

    # 可调度项目清单
    try:
        from src.core.project_registry import load_registry
        registry = load_registry()
        if registry:
            parts.append("\n--- 可调度项目清单 ---")
            for name, info in sorted(registry.items()):
                marker = " [有CLAUDE.md]" if info.get("has_claude_md") else ""
                parts.append(f"  {name}: {info['path']}{marker}")
    except Exception:
        pass

    return "\n".join(parts)


JSON_SCHEMA_PROMPT = """

请严格按照以下 JSON schema 输出结果，不要输出任何其他内容（不要 markdown code fence，不要解释，只输出纯 JSON）：

{
  "overview": "这7天你在做什么 — 2-3句话的整体概述",
  "time_distribution": [{"source": "来源", "hours": 0, "pct": 0, "label": "标签"}],
  "top_interests": [{"topic": "主题", "evidence": "数据证据", "strength": "strong|moderate|emerging"}],
  "patterns": ["观察到的行为规律，每条一句话，3-5条"],
  "anomalies": ["值得注意的异常或特别事项"],
  "recommendations": [{
    "action": "执行计划或变通方案",
    "reason": "执行原因",
    "priority": "high|medium|low",
    "project": "目标项目名（必须是可调度项目清单中的项目名，默认 orchestrator）",
    "department": "engineering|operations|protocol|security|quality|personnel",
    "problem": "这个建议要解决什么问题",
    "behavior_chain": "观察到的数字行为链，支撑问题存在的证据",
    "observation": "目前看到了什么现象",
    "expected": "执行后应该变成什么样",
    "summary": "一句话计划概要",
    "importance": "为什么这个重要"
  }],
  "goal_hypothesis": "根据你的数字行为，推断你正在追求或应该追求的长期目标"
}

必填字段: overview, top_interests, patterns, recommendations, goal_hypothesis
recommendations.project 必须是可调度项目清单中的项目名。如果建议针对 Orchestrator 自身，填 orchestrator。"""


class InsightEngine:
    def __init__(self, db: EventsDB = None, db_path: str = None):
        self.db = db or (EventsDB(db_path) if db_path else EventsDB())

    def run(self, days: int = 7) -> dict:
        context = _build_context(self.db)
        prompt = SYSTEM_PROMPT + "\n\n" + context + JSON_SCHEMA_PROMPT

        result = agent_query_json(prompt, model=MODEL_NAME)

        result["generated_at"] = datetime.now(timezone.utc).isoformat()
        self.db.save_insights(result)
        return result


if __name__ == "__main__":
    engine = InsightEngine()
    result = engine.run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
