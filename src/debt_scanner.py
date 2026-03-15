"""
注意力债务扫描器 — 礼部

扫描 Claude 对话历史，找出被提到但从未解决的问题。

流水线设计（防止上下文遗忘）：
  1. extract_sessions()  — Python 提取每个 session 的关键消息，写入临时摘要
  2. analyze_batch()     — Claude sub-agent 按批次分析，发现的 debt 立即写 DB
  3. cross_check()       — 对比已知 debt 和最近活动，标记已解决的

每一步都持久化到 DB，不依赖 LLM 上下文记忆。
"""
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from src.storage.events_db import EventsDB
from src.llm_router import get_router

log = logging.getLogger(__name__)

# 触发词：暗示有问题但可能没解决
DEBT_SIGNALS = re.compile(
    r'(bug|error|fix|todo|hack|workaround|临时|后面再|下次|待办|没修|没解决|先跳过|'
    r'broken|failed|crash|issue|问题|报错|不工作|卡住|超时|失败|待改|遗留)',
    re.IGNORECASE
)

BATCH_SIZE = 4
TIMEOUT = 120


def _get_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
    return ""


class DebtScanner:
    def __init__(self, db: EventsDB, claude_home: str = None):
        self.db = db
        env = os.environ.get("CLAUDE_HOME")
        self.claude_home = Path(claude_home or env or (str(Path.home() / ".claude")))

    def extract_sessions(self, full_scan: bool = False) -> list[dict]:
        """Phase 1: 提取每个 session 的关键消息（纯 Python，不用 LLM）。"""
        from src.project_registry import _claude_dir_to_project

        projects_dir = self.claude_home / "projects"
        if not projects_dir.exists():
            return []

        # 如果不是全量扫描，只看最近修改的文件
        scanned = self._get_scanned_sessions()
        results = []

        for proj in projects_dir.iterdir():
            if not proj.is_dir():
                continue
            project_name = _claude_dir_to_project(proj.name)
            for sf in proj.glob("*.jsonl"):
                sid = sf.stem
                if not full_scan and sid in scanned:
                    continue

                summary = self._extract_one(sf, project_name)
                if summary and summary["signals"]:
                    results.append(summary)

        log.info(f"DebtScanner: extracted {len(results)} sessions with debt signals")
        return results

    def _extract_one(self, session_file: Path, project: str) -> dict | None:
        """从单个 session 提取：前3条 + 最后3条用户消息 + 所有含触发词的消息。"""
        user_msgs = []
        assistant_last = ""
        session_id = session_file.stem
        slug = ""
        timestamp = ""

        try:
            with open(session_file, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if not slug and isinstance(obj.get("slug"), str):
                        slug = obj["slug"]
                    if not timestamp and isinstance(obj.get("timestamp"), str):
                        timestamp = obj["timestamp"]

                    if obj.get("type") == "user" and isinstance(obj.get("message"), dict):
                        text = _get_text(obj["message"].get("content", ""))
                        if text and len(text) > 10:
                            user_msgs.append(text[:500])
                    elif obj.get("type") == "assistant" and isinstance(obj.get("message"), dict):
                        text = _get_text(obj["message"].get("content", ""))
                        if text:
                            assistant_last = text[:500]
        except OSError:
            return None

        if not user_msgs:
            return None

        # 提取关键消息
        first3 = user_msgs[:3]
        last3 = user_msgs[-3:] if len(user_msgs) > 3 else []
        signal_msgs = [m for m in user_msgs if DEBT_SIGNALS.search(m)]

        # 去重
        key_msgs = list(dict.fromkeys(first3 + last3 + signal_msgs))

        return {
            "session_id": session_id,
            "project": project,
            "slug": slug,
            "timestamp": timestamp,
            "total_messages": len(user_msgs),
            "signals": signal_msgs[:10],
            "key_messages": key_msgs[:15],
            "last_assistant": assistant_last[:300],
        }

    def analyze_batch(self, sessions: list[dict]) -> list[dict]:
        """Phase 2: 用 Claude 按批次分析，返回 debt 列表。"""
        all_debts = []

        for i in range(0, len(sessions), BATCH_SIZE):
            batch = sessions[i:i + BATCH_SIZE]
            debts = self._analyze_one_batch(batch)
            all_debts.extend(debts)
            # 立即写 DB — 不等全部分析完
            for d in debts:
                self._save_debt(d)
            log.info(f"DebtScanner: batch {i // BATCH_SIZE + 1}, found {len(debts)} debts")

        return all_debts

    def _analyze_one_batch(self, batch: list[dict]) -> list[dict]:
        """单批次分析。"""
        summaries = []
        for s in batch:
            msgs = "\n".join(f"  - {m[:200]}" for m in s["key_messages"][:10])
            summaries.append(
                f"Session: {s['slug'] or s['session_id'][:8]} ({s['project']}, {s['total_messages']}条消息)\n"
                f"关键消息:\n{msgs}\n"
                f"最后助手回复: {s['last_assistant'][:150]}"
            )

        prompt = f"""你是 Orchestrator 礼部——负责审计注意力债务。

分析以下 {len(batch)} 个 Claude 对话会话，找出被提到但从未解决的问题。

判断标准：
- 用户提到了 bug/error/问题，但对话结束时没有修复确认
- 用户说了"后面再做"/"先跳过"/"下次"但没有后续
- 对话中途用户切换话题，前面的问题被遗忘
- 助手最后的回复暗示工作未完成

对于每个发现的遗留问题，输出 JSON 数组，每项包含：
- session_id: 来源会话的 slug 或 ID
- project: 项目名称（从会话数据的括号中提取）
- summary: 一句话描述遗留问题（中文）
- severity: high/medium/low
- context: 相关消息的简短引用

如果没有发现遗留问题，返回空数组 []。
只输出 JSON 数组，不要其他内容。

=== 会话数据 ===

{chr(10).join(summaries)}"""

        try:
            text = get_router().generate(prompt, task_type="debt_scan")
            # Strip markdown fences
            if text.startswith("```"):
                text = re.sub(r'^```\w*\n?', '', text)
                text = re.sub(r'\n?```$', '', text)
            return json.loads(text)
        except (json.JSONDecodeError, Exception) as e:
            log.warning(f"DebtScanner: batch analysis failed: {e}")
            return []

    def _save_debt(self, debt: dict):
        """写入单条 debt 到 DB。"""
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self.db._connect() as conn:
                conn.execute(
                    """INSERT OR IGNORE INTO attention_debts
                       (session_id, project, summary, severity, context, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        debt.get("session_id", ""),
                        debt.get("project", ""),
                        debt.get("summary", ""),
                        debt.get("severity", "medium"),
                        debt.get("context", ""),
                        now,
                    )
                )
        except Exception as e:
            log.warning(f"DebtScanner: failed to save debt: {e}")

    def _get_scanned_sessions(self) -> set:
        """获取已扫描过的 session ID。"""
        try:
            with self.db._connect() as conn:
                rows = conn.execute("SELECT DISTINCT session_id FROM attention_debts").fetchall()
            return {r[0] for r in rows}
        except Exception:
            return set()

    def run(self, full_scan: bool = False) -> list[dict]:
        """完整流水线。"""
        log.info(f"DebtScanner: starting {'full' if full_scan else 'incremental'} scan")
        self.db.write_log(
            f"礼部开始{'全量' if full_scan else '增量'}注意力债务扫描",
            "INFO", "debt_scanner"
        )

        # Phase 1: Extract
        sessions = self.extract_sessions(full_scan=full_scan)
        if not sessions:
            log.info("DebtScanner: no sessions with debt signals found")
            self.db.write_log("礼部扫描完成：未发现新的注意力债务信号", "INFO", "debt_scanner")
            return []

        # Phase 2: Analyze in batches (results saved to DB per batch)
        debts = self.analyze_batch(sessions)

        self.db.write_log(
            f"礼部扫描完成：扫描 {len(sessions)} 个会话，发现 {len(debts)} 个遗留问题",
            "INFO", "debt_scanner"
        )
        log.info(f"DebtScanner: done. {len(sessions)} sessions scanned, {len(debts)} debts found")
        return debts
