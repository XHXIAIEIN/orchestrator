"""
On-demand deep insight engine.
Analyses 7 days of cross-source data and generates comprehensive recommendations.
"""
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import anthropic
from src.config import load_api_key
from src.storage.events_db import EventsDB

INSIGHTS_TOOL = {
    "name": "save_insights",
    "description": "保存深度洞察分析结果",
    "input_schema": {
        "type": "object",
        "properties": {
            "overview": {
                "type": "string",
                "description": "这7天你在做什么 — 2-3句话的整体概述"
            },
            "time_distribution": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "source": {"type": "string"},
                        "hours": {"type": "number"},
                        "pct": {"type": "number"},
                        "label": {"type": "string"}
                    },
                    "required": ["source", "hours", "pct", "label"]
                },
                "description": "各来源时间分布"
            },
            "top_interests": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string"},
                        "evidence": {"type": "string"},
                        "strength": {"type": "string", "enum": ["strong", "moderate", "emerging"]}
                    },
                    "required": ["topic", "evidence", "strength"]
                },
                "description": "前5个兴趣领域，附数据证据"
            },
            "patterns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "观察到的行为规律，每条一句话，3-5条"
            },
            "anomalies": {
                "type": "array",
                "items": {"type": "string"},
                "description": "值得注意的异常或特别事项"
            },
            "recommendations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string"},
                        "reason": {"type": "string"},
                        "priority": {"type": "string", "enum": ["high", "medium", "low"]}
                    },
                    "required": ["action", "reason", "priority"]
                },
                "description": "可执行的建议，3-5条，带原因和优先级"
            },
            "goal_hypothesis": {
                "type": "string",
                "description": "根据你的数字行为，推断你正在追求或应该追求的长期目标"
            }
        },
        "required": ["overview", "top_interests", "patterns", "recommendations", "goal_hypothesis"]
    }
}

SYSTEM_PROMPT = """你是一个洞察力极强的生活分析师。你能从数字行为数据中发现真正有价值的规律。

你的分析原则：
- 基于数据说话，不要无中生有
- 发现数据背后的动机和模式，而不是只重复数字
- 建议要具体可执行，不要废话
- 对目标的推断要大胆但有依据
- 找到数据中真正值得关注的信号

你不是在写报告，你是在帮助用户更好地了解自己。"""


def _read_recent_sessions(days: int = 7, limit: int = 30) -> list[dict]:
    """Directly read recent JSONL sessions and extract conversation snippets."""
    import time
    claude_home = Path.home() / ".claude" / "projects"
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
                for line in f:
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

    # Daily summaries
    summaries_raw = []
    try:
        import sqlite3
        conn = sqlite3.connect(db.db_path)
        conn.row_factory = sqlite3.Row
        seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
        rows = conn.execute(
            "SELECT date, summary FROM daily_summaries WHERE date >= ? ORDER BY date DESC",
            (seven_days_ago,)
        ).fetchall()
        conn.close()
        for r in rows:
            try:
                summaries_raw.append({"date": r["date"], **json.loads(r["summary"])})
            except Exception:
                pass
    except Exception:
        pass

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

    return "\n".join(parts)


class InsightEngine:
    def __init__(self, api_key: str = None, db: EventsDB = None, db_path: str = "events.db"):
        self.api_key = api_key or load_api_key()
        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.db = db or EventsDB(db_path)

    def run(self, days: int = 7) -> dict:
        context = _build_context(self.db)

        response = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=[INSIGHTS_TOOL],
            tool_choice={"type": "tool", "name": "save_insights"},
            messages=[{"role": "user", "content": context}],
        )

        block = next(b for b in response.content if b.type == "tool_use")
        result = block.input
        result["generated_at"] = datetime.now(timezone.utc).isoformat()
        self.db.save_insights(result)
        return result


if __name__ == "__main__":
    engine = InsightEngine()
    result = engine.run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
