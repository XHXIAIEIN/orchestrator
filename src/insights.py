"""
On-demand deep insight engine.
Analyses 7 days of cross-source data and generates comprehensive recommendations.
"""
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from src.config import get_anthropic_client
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
                        "action":         {"type": "string", "description": "执行计划或变通方案"},
                        "reason":         {"type": "string", "description": "执行原因"},
                        "priority":       {"type": "string", "enum": ["high", "medium", "low"]},
                        "problem":        {"type": "string", "description": "这个建议要解决什么问题"},
                        "behavior_chain": {"type": "string", "description": "观察到的数字行为链，支撑问题存在的证据"},
                        "observation":    {"type": "string", "description": "目前看到了什么现象"},
                        "expected":       {"type": "string", "description": "执行后应该变成什么样"},
                        "summary":        {"type": "string", "description": "一句话计划概要"},
                        "importance":     {"type": "string", "description": "为什么这个重要"},
                        "department":     {"type": "string", "enum": ["engineering", "operations", "quality"], "description": "交给哪个部门：engineering=代码工程, operations=系统运维, quality=质量验收"}
                    },
                    "required": ["action", "reason", "priority", "problem", "behavior_chain", "observation", "expected", "summary", "importance", "department"]
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

SYSTEM_PROMPT = """你是 Orchestrator——一个 24 小时运行的 AI 管家，正在分析主人过去 7 天的数字足迹。

你了解这个人：Construct 3 中文社区的核心建设者，从 RPG Maker 教程整理者一路走到现在用 AI 打造游戏引擎智能辅助生态。不是职业程序员，是"用代码解决问题的创作者"——看到重复劳动就想自动化，看到知识孤岛就想建图书馆。主力项目是 Construct 3 RAG + Copilot + LoRA，副线有直播互动工具、游戏工具、各种自动化脚本。经常凌晨还在写代码，偶尔会在一个技术死胡同里死磕十几种方案。

你的工作是从数据里挖出真正值得关注的信号——动机、模式、趋势，不是复读数字。基于数据说话，不无中生有，但敢于大胆推断他的目标和方向。

建议必须具体可执行。"建议注意休息"是废话，"把 Steam collector 的路径从 C 盘改到 D 盘"才是建议。recommendations 里的任务必须是 Orchestrator 自己在 /orchestrator 目录下能动手做的。

语气像一个真正关心你但嘴上不饶人的损友——"你又凌晨 3 点在调蓝牙了"，然后紧跟一条真正有用的行动建议。你是管家，不是报告生成器。"""


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

    return "\n".join(parts)


class InsightEngine:
    def __init__(self, db: EventsDB = None, db_path: str = "events.db"):
        self.client = get_anthropic_client()
        self.db = db or EventsDB(db_path)

    def run(self, days: int = 7) -> dict:
        context = _build_context(self.db)

        response = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=6000,
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
