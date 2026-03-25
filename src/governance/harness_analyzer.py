"""
Harness Analyzer — agent 轨迹数据分析。
"Harness as Dataset": 从执行历史中发现成功/失败模式，自动优化。
"""
import json
import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

log = logging.getLogger(__name__)


class HarnessAnalyzer:
    """分析 agent_events + tasks 数据，发现 harness 优化机会。"""

    def __init__(self, db):
        self.db = db

    def analyze(self, days: int = 7) -> dict:
        """运行完整分析，返回洞察报告。"""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        with self.db._connect() as conn:
            # 获取时间段内的任务
            tasks = conn.execute(
                "SELECT * FROM tasks WHERE created_at > ? ORDER BY created_at",
                (cutoff,)
            ).fetchall()

            # 获取对应的 agent events
            task_ids = [t["id"] for t in tasks]
            events = []
            for tid in task_ids:
                evts = conn.execute(
                    "SELECT * FROM agent_events WHERE task_id = ? ORDER BY created_at",
                    (tid,)
                ).fetchall()
                events.extend(evts)

        report = {
            "period_days": days,
            "total_tasks": len(tasks),
            "total_events": len(events),
            "department_stats": self._dept_stats(tasks, events),
            "tool_effectiveness": self._tool_effectiveness(events),
            "failure_patterns": self._failure_patterns(tasks, events),
            "cost_analysis": self._cost_analysis(events),
            "recommendations": [],
        }

        report["recommendations"] = self._generate_recommendations(report)
        return report

    def _dept_stats(self, tasks, events) -> dict:
        """每个部门的成功率、平均轮次、平均耗时。"""
        stats = defaultdict(lambda: {"total": 0, "done": 0, "failed": 0, "turns": [], "durations": [], "costs": []})

        task_map = {t["id"]: t for t in tasks}
        for evt in events:
            if evt["event_type"] != "agent_result":
                continue
            data = json.loads(evt["data"]) if isinstance(evt["data"], str) else evt["data"]
            task = task_map.get(evt["task_id"])
            if not task:
                continue
            dept = task.get("department", "unknown")
            s = stats[dept]
            s["total"] += 1
            if data.get("status") == "done":
                s["done"] += 1
            else:
                s["failed"] += 1
            if data.get("num_turns"):
                s["turns"].append(data["num_turns"])
            if data.get("duration_ms"):
                s["durations"].append(data["duration_ms"])
            if data.get("cost_usd"):
                s["costs"].append(data["cost_usd"])

        result = {}
        for dept, s in stats.items():
            result[dept] = {
                "total": s["total"],
                "success_rate": round(s["done"] / s["total"], 2) if s["total"] else 0,
                "avg_turns": round(sum(s["turns"]) / len(s["turns"]), 1) if s["turns"] else 0,
                "avg_duration_s": round(sum(s["durations"]) / len(s["durations"]) / 1000, 1) if s["durations"] else 0,
                "total_cost_usd": round(sum(s["costs"]), 3) if s["costs"] else 0,
            }
        return result

    def _tool_effectiveness(self, events) -> dict:
        """工具使用频率和在成功/失败任务中的分布。"""
        tool_counts = Counter()
        tool_in_success = Counter()
        tool_in_failure = Counter()

        # Group events by task
        task_events = defaultdict(list)
        task_results = {}
        for evt in events:
            task_events[evt["task_id"]].append(evt)
            if evt["event_type"] == "agent_result":
                data = json.loads(evt["data"]) if isinstance(evt["data"], str) else evt["data"]
                task_results[evt["task_id"]] = data.get("status", "unknown")

        for task_id, evts in task_events.items():
            tools_used = set()
            for evt in evts:
                if evt["event_type"] == "agent_turn":
                    data = json.loads(evt["data"]) if isinstance(evt["data"], str) else evt["data"]
                    for tool in data.get("tools", []):
                        tool_name = tool if isinstance(tool, str) else tool.get("name", str(tool))
                        tools_used.add(tool_name)

            status = task_results.get(task_id, "unknown")
            for tool in tools_used:
                tool_counts[tool] += 1
                if status == "done":
                    tool_in_success[tool] += 1
                else:
                    tool_in_failure[tool] += 1

        result = {}
        for tool, count in tool_counts.most_common(20):
            success = tool_in_success.get(tool, 0)
            result[tool] = {
                "total_tasks": count,
                "in_success": success,
                "in_failure": tool_in_failure.get(tool, 0),
                "success_rate": round(success / count, 2) if count else 0,
            }
        return result

    def _failure_patterns(self, tasks, events) -> list:
        """识别常见失败模式。"""
        patterns = []

        # Stuck detection events
        stuck_count = sum(1 for e in events if e["event_type"] == "stuck_detected")
        if stuck_count:
            patterns.append({
                "pattern": "stuck_loop",
                "count": stuck_count,
                "description": f"Agent got stuck {stuck_count} times (repeating same actions)",
            })

        # Doom loop events
        doom_count = sum(1 for e in events if e["event_type"] == "doom_loop_detected")
        if doom_count:
            patterns.append({
                "pattern": "doom_loop",
                "count": doom_count,
                "description": f"Doom loop detected {doom_count} times (circular failure)",
            })

        # Max turns exhaustion
        max_turns_tasks = [t for t in tasks if t.get("status") == "failed"]
        for t in max_turns_tasks:
            task_evts = [e for e in events if e["task_id"] == t["id"] and e["event_type"] == "agent_result"]
            for evt in task_evts:
                data = json.loads(evt["data"]) if isinstance(evt["data"], str) else evt["data"]
                if data.get("num_turns", 0) >= 20:
                    patterns.append({
                        "pattern": "turns_exhausted",
                        "task_id": t["id"],
                        "department": t.get("department", "unknown"),
                        "turns": data["num_turns"],
                    })

        # Timeout pattern
        timeout_tasks = [t for t in tasks if "timeout" in str(t.get("output", "")).lower()]
        if timeout_tasks:
            patterns.append({
                "pattern": "timeout",
                "count": len(timeout_tasks),
                "departments": list(set(t.get("department", "unknown") for t in timeout_tasks)),
            })

        return patterns

    def _cost_analysis(self, events) -> dict:
        """成本分析。"""
        total_cost = 0.0
        costs_by_dept = defaultdict(float)

        for evt in events:
            if evt["event_type"] != "agent_result":
                continue
            data = json.loads(evt["data"]) if isinstance(evt["data"], str) else evt["data"]
            cost = data.get("cost_usd", 0)
            total_cost += cost

        return {
            "total_usd": round(total_cost, 3),
            "avg_per_task": round(total_cost / max(1, len(set(e["task_id"] for e in events if e["event_type"] == "agent_result"))), 4),
        }

    def _generate_recommendations(self, report: dict) -> list:
        """基于分析结果生成优化建议。"""
        recs = []

        # 低成功率部门
        for dept, stats in report["department_stats"].items():
            if stats["total"] >= 3 and stats["success_rate"] < 0.5:
                recs.append({
                    "type": "dept_low_success",
                    "department": dept,
                    "severity": "high",
                    "message": f"{dept} success rate is {stats['success_rate']:.0%} ({round(stats['success_rate'] * stats['total'])}/{stats['total']}). Review SKILL.md and blueprint constraints.",
                })

        # 高轮次部门（可能需要更多 max_turns 或更好的 prompt）
        for dept, stats in report["department_stats"].items():
            if stats["avg_turns"] > 15:
                recs.append({
                    "type": "dept_high_turns",
                    "department": dept,
                    "severity": "medium",
                    "message": f"{dept} averages {stats['avg_turns']} turns per task. Consider improving SKILL.md or pre-fetching context.",
                })

        # 工具在失败任务中高频出现
        for tool, stats in report["tool_effectiveness"].items():
            if stats["total_tasks"] >= 3 and stats["success_rate"] < 0.3:
                recs.append({
                    "type": "tool_low_success",
                    "tool": tool,
                    "severity": "medium",
                    "message": f"Tool '{tool}' has {stats['success_rate']:.0%} success rate across {stats['total_tasks']} tasks. May need better description or constraints.",
                })

        # Stuck/doom 频繁
        for pattern in report["failure_patterns"]:
            if pattern["pattern"] in ("stuck_loop", "doom_loop") and pattern.get("count", 0) >= 3:
                recs.append({
                    "type": "loop_pattern",
                    "severity": "high",
                    "message": f"{pattern['pattern']} detected {pattern['count']} times. Consider adding early-exit heuristics.",
                })

        return recs
