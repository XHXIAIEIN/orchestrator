"""
6维结构化记忆系统 — Activity / Identity / Context / Preference / Experience / Persona。

偷师来源：LobeHub Agent-as-Unit-of-Work 全栈平台（Round 16 P0 #1）。
原设计用 6 维记忆取代扁平 JSONL，每条记忆带置信度 + 时间衰减 + 语义搜索。

与现有系统的关系：
  - memory_tier.py: hot/extended 两层加载策略，保持不变
  - memory_extractor.py: 6-type 提取器，其分类可映射到本模块的 6 维
  - experiences.jsonl: 扁平存储，本模块提供 migrate_from_jsonl() 迁移到 SQLite
  - StructuredMemoryStore 是新的推荐入口，memory_tier.py 作为兼容层共存
"""
import json
import logging
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from src.storage.pool import get_pool as _get_pool, SQLitePool, _registry_lock, _registry

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent
while _REPO_ROOT != _REPO_ROOT.parent and not ((_REPO_ROOT / "departments").is_dir() and (_REPO_ROOT / "src").is_dir()):
    _REPO_ROOT = _REPO_ROOT.parent

_DEFAULT_DB = str(_REPO_ROOT / "data" / "memory.db")


def _sync_memory_to_qdrant(row_id: int, dimension: str, text: str, metadata: dict):
    import asyncio
    try:
        from src.storage.qdrant_store import QdrantStore
        store = QdrantStore()
        if not store.is_available():
            return
        store.ensure_collection("orch_memory")
        loop = asyncio.new_event_loop()
        loop.run_until_complete(
            store.upsert("orch_memory", f"memory_{dimension}", row_id, text,
                         {"dimension": dimension, **metadata})
        )
        loop.close()
    except Exception:
        pass


# ── Dimensions ──────────────────────────────────────────────────────────

class Dimension(str, Enum):
    """6 维记忆维度。"""
    ACTIVITY   = "activity"
    IDENTITY   = "identity"
    CONTEXT    = "context"
    PREFERENCE = "preference"
    EXPERIENCE = "experience"
    PERSONA    = "persona"


# ── Dataclasses ─────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ActivityMemory:
    """时间事件：叙事 + 情感 + 时间戳 + 关联。"""
    summary: str
    detail: str = ""
    emotion: str = ""                     # 情感标签: bonding, frustration, triumph...
    related_entities: list[str] = field(default_factory=list)
    event_date: str = ""                  # ISO date of the event itself
    confidence: float = 0.8
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    tags: list[str] = field(default_factory=list)


@dataclass
class IdentityMemory:
    """持久事实：角色 + 关系 + 置信度。"""
    fact: str                             # e.g. "我是 Orchestrator 的 AI 管家"
    category: str = ""                    # role / relationship / trait
    subject: str = ""                     # who this fact is about
    confidence: float = 0.9
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    tags: list[str] = field(default_factory=list)


@dataclass
class ContextMemory:
    """进行中状态：项目 + 目标 + 紧急度。"""
    project: str
    goal: str = ""
    status: str = "active"               # active / paused / done
    urgency: float = 0.5                 # 0-1
    notes: str = ""
    confidence: float = 0.7
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    tags: list[str] = field(default_factory=list)


@dataclass
class PreferenceMemory:
    """行为指令：优先级 + 适用条件 + 建议动作。"""
    directive: str                        # e.g. "commit 前不要问，直接提交"
    priority: float = 0.5                # 0-1
    condition: str = ""                   # when this applies
    suggested_action: str = ""
    confidence: float = 0.85
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    tags: list[str] = field(default_factory=list)


@dataclass
class ExperienceMemory:
    """经验教训：情境→推理→行动→结果 + 知识价值评分。"""
    situation: str
    reasoning: str = ""
    action: str = ""
    outcome: str = ""
    knowledge_value: float = 0.5         # 0-1, how broadly applicable
    confidence: float = 0.8
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    tags: list[str] = field(default_factory=list)


@dataclass
class PersonaMemory:
    """用户画像：兴趣 + 背景 + 沟通风格。"""
    aspect: str                           # e.g. "communication_style"
    description: str = ""
    subject: str = "owner"               # whose persona
    confidence: float = 0.85
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    tags: list[str] = field(default_factory=list)


# Type alias for any memory entry
MemoryItem = ActivityMemory | IdentityMemory | ContextMemory | PreferenceMemory | ExperienceMemory | PersonaMemory

_DIMENSION_CLASS: dict[Dimension, type] = {
    Dimension.ACTIVITY:   ActivityMemory,
    Dimension.IDENTITY:   IdentityMemory,
    Dimension.CONTEXT:    ContextMemory,
    Dimension.PREFERENCE: PreferenceMemory,
    Dimension.EXPERIENCE: ExperienceMemory,
    Dimension.PERSONA:    PersonaMemory,
}


# ── SQLite Schema ───────────────────────────────────────────────────────

_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    summary TEXT NOT NULL,
    detail TEXT DEFAULT '',
    emotion TEXT DEFAULT '',
    related_entities TEXT DEFAULT '[]',
    event_date TEXT DEFAULT '',
    confidence REAL DEFAULT 0.8,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    tags TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS identity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fact TEXT NOT NULL,
    category TEXT DEFAULT '',
    subject TEXT DEFAULT '',
    confidence REAL DEFAULT 0.9,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    tags TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS context (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    goal TEXT DEFAULT '',
    status TEXT DEFAULT 'active',
    urgency REAL DEFAULT 0.5,
    notes TEXT DEFAULT '',
    confidence REAL DEFAULT 0.7,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    tags TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS preference (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    directive TEXT NOT NULL,
    priority REAL DEFAULT 0.5,
    condition TEXT DEFAULT '',
    suggested_action TEXT DEFAULT '',
    confidence REAL DEFAULT 0.85,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    tags TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS experience (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    situation TEXT NOT NULL,
    reasoning TEXT DEFAULT '',
    action TEXT DEFAULT '',
    outcome TEXT DEFAULT '',
    knowledge_value REAL DEFAULT 0.5,
    confidence REAL DEFAULT 0.8,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    tags TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS persona (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    aspect TEXT NOT NULL,
    description TEXT DEFAULT '',
    subject TEXT DEFAULT 'owner',
    confidence REAL DEFAULT 0.85,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    tags TEXT DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_activity_confidence ON activity(confidence);
CREATE INDEX IF NOT EXISTS idx_activity_updated ON activity(updated_at);
CREATE INDEX IF NOT EXISTS idx_identity_confidence ON identity(confidence);
CREATE INDEX IF NOT EXISTS idx_context_status ON context(status);
CREATE INDEX IF NOT EXISTS idx_experience_knowledge_value ON experience(knowledge_value);
CREATE INDEX IF NOT EXISTS idx_persona_subject ON persona(subject);
"""


# ── Connection Pool (delegates to src.storage.pool) ──────────────────

# Backward-compat aliases for tests that import _pools / _pool_lock
_pool_lock = _registry_lock
_pools = _registry


# ── Store ───────────────────────────────────────────────────────────────

class StructuredMemoryStore:
    """6维结构化记忆存储。SQLite 后端，每个维度一张表。"""

    def __init__(self, db_path: str = _DEFAULT_DB):
        self.db_path = db_path
        self._pool = _get_pool(
            db_path,
            row_factory=sqlite3.Row,
            ensure_parent=True,
            log_prefix="memory_db",
        )
        self._init_tables()

    def _connect(self):
        return self._pool.connect()

    def _init_tables(self):
        with self._connect() as conn:
            conn.executescript(_TABLE_DDL)

    # ── add ──

    def add(self, dimension: Dimension | str, entry: MemoryItem) -> int:
        """添加一条记忆，返回 row id。"""
        dim = Dimension(dimension) if isinstance(dimension, str) else dimension
        table = dim.value
        data = self._entry_to_row(entry)
        cols = ", ".join(data.keys())
        placeholders = ", ".join("?" for _ in data)
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT INTO {table} ({cols}) VALUES ({placeholders})",
                list(data.values()),
            )
            row_id = cur.lastrowid
        log.debug(f"structured_memory: added {dim.value} entry (id={row_id})")
        # Sync to Qdrant (fire-and-forget)
        import threading
        text_for_embed = " ".join(str(v) for v in data.values() if isinstance(v, str))
        threading.Thread(
            target=_sync_memory_to_qdrant,
            args=(row_id, dim.value, text_for_embed,
                  {"confidence": getattr(entry, 'confidence', 0.8)}),
            daemon=True,
        ).start()
        return row_id

    def add_batch(self, dimension: Dimension | str, entries: list[MemoryItem]) -> list[int]:
        """批量添加记忆条目。"""
        if not entries:
            return []
        dim = Dimension(dimension) if isinstance(dimension, str) else dimension
        table = dim.value
        ids = []
        with self._connect() as conn:
            for entry in entries:
                data = self._entry_to_row(entry)
                cols = ", ".join(data.keys())
                placeholders = ", ".join("?" for _ in data)
                cur = conn.execute(
                    f"INSERT INTO {table} ({cols}) VALUES ({placeholders})",
                    list(data.values()),
                )
                ids.append(cur.lastrowid)
        log.info(f"structured_memory: batch added {len(ids)} {dim.value} entries")
        return ids

    # ── search ──

    def search(self, dimension: Dimension | str, query: str, top_k: int = 5) -> list[dict]:
        """按维度关键词搜索。先用 LIKE 匹配，预留 embedding 接口。

        返回 list[dict]，按 confidence DESC + updated_at DESC 排序。
        """
        dim = Dimension(dimension) if isinstance(dimension, str) else dimension
        table = dim.value

        # 搜索所有 TEXT 列
        text_cols = self._get_text_columns(dim)
        where_parts = []
        params = []
        for kw in query.split():
            col_matches = " OR ".join(f"{col} LIKE ?" for col in text_cols)
            where_parts.append(f"({col_matches})")
            params.extend([f"%{kw}%"] * len(text_cols))

        where_clause = " AND ".join(where_parts) if where_parts else "1=1"

        sql = (
            f"SELECT * FROM {table} WHERE {where_clause} "
            f"ORDER BY confidence DESC, updated_at DESC LIMIT ?"
        )
        params.append(top_k)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def search_embedding(self, dimension: Dimension | str, embedding: list[float],
                         top_k: int = 5) -> list[dict]:
        """预留的 embedding 向量搜索接口。

        当前实现：fallback 到全量扫描 + 余弦相似度。
        未来：接入 sqlite-vss 或外部向量数据库。
        """
        # TODO: 接入 embedding 搜索后端
        log.warning("structured_memory: embedding search not yet implemented, returning empty")
        return []

    # ── get_hot ──

    def get_hot(self, budget_chars: int = 8000) -> list[dict]:
        """获取 hot memory：高置信度 + 近期更新，跨所有维度。

        用于编入 boot prompt。按 confidence * recency_score 排序，
        在 budget_chars 字符预算内尽可能多地返回。
        """
        all_entries = []
        for dim in Dimension:
            with self._connect() as conn:
                rows = conn.execute(
                    f"SELECT *, '{dim.value}' as dimension FROM {dim.value} "
                    f"WHERE confidence >= 0.6 "
                    f"ORDER BY confidence DESC, updated_at DESC LIMIT 20"
                ).fetchall()
                all_entries.extend(dict(r) for r in rows)

        # 按 confidence 降序排
        all_entries.sort(key=lambda e: (e.get("confidence", 0), e.get("updated_at", "")), reverse=True)

        # 按预算截断
        result = []
        total_chars = 0
        for entry in all_entries:
            entry_text = self._entry_text_length(entry)
            if total_chars + entry_text > budget_chars:
                break
            result.append(entry)
            total_chars += entry_text

        log.debug(f"structured_memory: get_hot returned {len(result)} entries ({total_chars} chars)")
        return result

    # ── expire ──

    def expire(self, min_confidence: float = 0.3, max_age_days: int = 90) -> int:
        """过期低置信度旧记忆。返回删除数。"""
        cutoff = datetime.now(timezone.utc).isoformat()
        # 简化：直接按 confidence < min_confidence AND updated_at older than max_age_days
        total_deleted = 0
        for dim in Dimension:
            with self._connect() as conn:
                cur = conn.execute(
                    f"DELETE FROM {dim.value} WHERE confidence < ? "
                    f"AND julianday(?) - julianday(updated_at) > ?",
                    (min_confidence, cutoff, max_age_days),
                )
                total_deleted += cur.rowcount
        if total_deleted > 0:
            log.info(f"structured_memory: expired {total_deleted} entries "
                     f"(confidence < {min_confidence}, age > {max_age_days}d)")
        return total_deleted

    # ── count ──

    def count(self, dimension: Optional[Dimension | str] = None) -> dict[str, int]:
        """返回各维度记忆条数。dimension=None 时返回全部。"""
        dims = [Dimension(dimension)] if dimension else list(Dimension)
        result = {}
        for dim in dims:
            with self._connect() as conn:
                row = conn.execute(f"SELECT COUNT(*) as cnt FROM {dim.value}").fetchone()
                result[dim.value] = row["cnt"]
        return result

    # ── get_all ──

    def get_all(self, dimension: Dimension | str, limit: int = 100, offset: int = 0) -> list[dict]:
        """获取某维度全部记忆。"""
        dim = Dimension(dimension) if isinstance(dimension, str) else dimension
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM {dim.value} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── migrate_from_jsonl ──

    def migrate_from_jsonl(self, jsonl_path: str | Path) -> dict[str, int]:
        """从 experiences.jsonl 迁移到 6 维结构化存储。

        分类逻辑基于 entry 的 type 字段：
          bonding, conflict, trust, milestone → Activity
          discovery, revelation              → Experience
          preference, rule                   → Preference
          profile, background                → Persona
          relationship, role                 → Identity
          project, goal, task                → Context
          其他                                → Experience (default)
        """
        path = Path(jsonl_path)
        if not path.exists():
            log.warning(f"structured_memory: JSONL not found: {path}")
            return {}

        type_to_dim: dict[str, Dimension] = {
            # Activity
            "bonding": Dimension.ACTIVITY,
            "conflict": Dimension.ACTIVITY,
            "trust": Dimension.ACTIVITY,
            "milestone": Dimension.ACTIVITY,
            "event": Dimension.ACTIVITY,
            "growth": Dimension.ACTIVITY,
            "correction": Dimension.ACTIVITY,
            # Experience
            "discovery": Dimension.EXPERIENCE,
            "revelation": Dimension.EXPERIENCE,
            "lesson": Dimension.EXPERIENCE,
            "case": Dimension.EXPERIENCE,
            "pattern": Dimension.EXPERIENCE,
            "insight": Dimension.EXPERIENCE,
            # Preference
            "preference": Dimension.PREFERENCE,
            "rule": Dimension.PREFERENCE,
            "directive": Dimension.PREFERENCE,
            # Persona
            "profile": Dimension.PERSONA,
            "background": Dimension.PERSONA,
            "interest": Dimension.PERSONA,
            "communication": Dimension.PERSONA,
            # Identity
            "relationship": Dimension.IDENTITY,
            "role": Dimension.IDENTITY,
            "identity": Dimension.IDENTITY,
            # Context
            "project": Dimension.CONTEXT,
            "goal": Dimension.CONTEXT,
            "task": Dimension.CONTEXT,
        }

        counts: dict[str, int] = {d.value: 0 for d in Dimension}
        entries_by_dim: dict[Dimension, list[MemoryItem]] = {d: [] for d in Dimension}

        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                log.warning(f"structured_memory: skipping malformed line {line_no}")
                continue

            entry_type = raw.get("type", "").lower()
            dim = type_to_dim.get(entry_type, Dimension.EXPERIENCE)
            tags = raw.get("tags", [])
            if entry_type:
                tags = list(set(tags + [entry_type]))
            date_str = raw.get("date", "")
            summary = raw.get("summary", "")
            detail = raw.get("detail", "")
            now = _now()

            if dim == Dimension.ACTIVITY:
                entries_by_dim[dim].append(ActivityMemory(
                    summary=summary,
                    detail=detail,
                    emotion=entry_type,
                    event_date=date_str,
                    tags=tags,
                    created_at=now,
                    updated_at=now,
                ))
            elif dim == Dimension.EXPERIENCE:
                entries_by_dim[dim].append(ExperienceMemory(
                    situation=summary,
                    reasoning=detail,
                    outcome=raw.get("outcome", ""),
                    tags=tags,
                    created_at=now,
                    updated_at=now,
                ))
            elif dim == Dimension.PREFERENCE:
                entries_by_dim[dim].append(PreferenceMemory(
                    directive=summary,
                    suggested_action=detail,
                    tags=tags,
                    created_at=now,
                    updated_at=now,
                ))
            elif dim == Dimension.PERSONA:
                entries_by_dim[dim].append(PersonaMemory(
                    aspect=entry_type or "general",
                    description=f"{summary}: {detail}" if detail else summary,
                    tags=tags,
                    created_at=now,
                    updated_at=now,
                ))
            elif dim == Dimension.IDENTITY:
                entries_by_dim[dim].append(IdentityMemory(
                    fact=f"{summary}: {detail}" if detail else summary,
                    category=entry_type,
                    tags=tags,
                    created_at=now,
                    updated_at=now,
                ))
            elif dim == Dimension.CONTEXT:
                entries_by_dim[dim].append(ContextMemory(
                    project=summary,
                    goal=detail,
                    tags=tags,
                    created_at=now,
                    updated_at=now,
                ))

        # Batch insert
        for dim, entries in entries_by_dim.items():
            if entries:
                self.add_batch(dim, entries)
                counts[dim.value] = len(entries)

        total = sum(counts.values())
        log.info(f"structured_memory: migrated {total} entries from JSONL → {counts}")
        return counts

    def migrate_from_db(self, events_db) -> dict[str, int]:
        """从 EventsDB 的 experiences 表迁移到 6 维结构化存储。

        events_db: src.storage.events_db.EventsDB 实例
        DB schema: (date, type, summary, detail, instance)
        """
        type_to_dim: dict[str, Dimension] = {
            "bonding": Dimension.ACTIVITY, "conflict": Dimension.ACTIVITY,
            "trust": Dimension.ACTIVITY, "milestone": Dimension.ACTIVITY,
            "event": Dimension.ACTIVITY, "growth": Dimension.ACTIVITY,
            "correction": Dimension.ACTIVITY, "humor": Dimension.ACTIVITY,
            "discovery": Dimension.EXPERIENCE, "revelation": Dimension.EXPERIENCE,
            "lesson": Dimension.EXPERIENCE, "case": Dimension.EXPERIENCE,
            "pattern": Dimension.EXPERIENCE, "insight": Dimension.EXPERIENCE,
            "limitation": Dimension.EXPERIENCE, "philosophy": Dimension.EXPERIENCE,
            "resolution": Dimension.EXPERIENCE,
            "preference": Dimension.PREFERENCE, "rule": Dimension.PREFERENCE,
            "directive": Dimension.PREFERENCE,
            "profile": Dimension.PERSONA, "background": Dimension.PERSONA,
            "interest": Dimension.PERSONA, "communication": Dimension.PERSONA,
            "relationship": Dimension.IDENTITY, "role": Dimension.IDENTITY,
            "identity": Dimension.IDENTITY,
            "project": Dimension.CONTEXT, "goal": Dimension.CONTEXT,
            "task": Dimension.CONTEXT,
        }

        # Pull all experiences from DB (get a large batch)
        rows = events_db.get_recent_experiences(n=9999)
        if not rows:
            log.info("structured_memory: no experiences in DB to migrate")
            return {}

        counts: dict[str, int] = {d.value: 0 for d in Dimension}
        entries_by_dim: dict[Dimension, list] = {d: [] for d in Dimension}
        now = _now()

        for raw in rows:
            entry_type = (raw.get("type") or "").lower()
            dim = type_to_dim.get(entry_type, Dimension.EXPERIENCE)
            summary = raw.get("summary", "")
            detail = raw.get("detail", "")
            date_str = raw.get("date", "")
            tags = [entry_type] if entry_type else []

            if dim == Dimension.ACTIVITY:
                entries_by_dim[dim].append(ActivityMemory(
                    summary=summary, detail=detail, emotion=entry_type,
                    event_date=date_str, tags=tags, created_at=now, updated_at=now,
                ))
            elif dim == Dimension.EXPERIENCE:
                entries_by_dim[dim].append(ExperienceMemory(
                    situation=summary, reasoning=detail, outcome="",
                    tags=tags, created_at=now, updated_at=now,
                ))
            elif dim == Dimension.PREFERENCE:
                entries_by_dim[dim].append(PreferenceMemory(
                    directive=summary, suggested_action=detail,
                    tags=tags, created_at=now, updated_at=now,
                ))
            elif dim == Dimension.PERSONA:
                entries_by_dim[dim].append(PersonaMemory(
                    aspect=entry_type or "general",
                    description=f"{summary}: {detail}" if detail else summary,
                    tags=tags, created_at=now, updated_at=now,
                ))
            elif dim == Dimension.IDENTITY:
                entries_by_dim[dim].append(IdentityMemory(
                    fact=f"{summary}: {detail}" if detail else summary,
                    category=entry_type, tags=tags, created_at=now, updated_at=now,
                ))
            elif dim == Dimension.CONTEXT:
                entries_by_dim[dim].append(ContextMemory(
                    project=summary, goal=detail,
                    tags=tags, created_at=now, updated_at=now,
                ))

        for dim, entries in entries_by_dim.items():
            if entries:
                self.add_batch(dim, entries)
                counts[dim.value] = len(entries)

        total = sum(counts.values())
        log.info(f"structured_memory: migrated {total} entries from EventsDB → {counts}")
        return counts

    # ── Internal helpers ────────────────────────────────────────────────

    @staticmethod
    def _entry_to_row(entry: MemoryItem) -> dict:
        """Convert dataclass to dict suitable for SQLite INSERT."""
        data = asdict(entry)
        # Serialize complex types
        for key, val in data.items():
            if isinstance(val, list):
                data[key] = json.dumps(val, ensure_ascii=False)
            elif isinstance(val, datetime):
                data[key] = val.isoformat()
        return data

    @staticmethod
    def _get_text_columns(dim: Dimension) -> list[str]:
        """Return TEXT column names for a dimension (for keyword search)."""
        text_cols_map = {
            Dimension.ACTIVITY:   ["summary", "detail", "emotion", "tags"],
            Dimension.IDENTITY:   ["fact", "category", "subject", "tags"],
            Dimension.CONTEXT:    ["project", "goal", "notes", "status", "tags"],
            Dimension.PREFERENCE: ["directive", "condition", "suggested_action", "tags"],
            Dimension.EXPERIENCE: ["situation", "reasoning", "action", "outcome", "tags"],
            Dimension.PERSONA:    ["aspect", "description", "subject", "tags"],
        }
        return text_cols_map.get(dim, ["tags"])

    @staticmethod
    def _entry_text_length(entry: dict) -> int:
        """Estimate character length of an entry for budget tracking."""
        total = 0
        for key, val in entry.items():
            if key in ("id", "confidence", "urgency", "priority", "knowledge_value", "dimension"):
                continue
            total += len(str(val))
        return total


# ── Memory Effort Level (Round 16 LobeHub P2) ─────────────────────────

class MemoryEffortLevel(str, Enum):
    """记忆系统努力等级。根据场景动态调整，避免永远全力运转。

    LOW    — 日常闲聊/简单问答，最少记忆操作
    MEDIUM — 有明确 action 但非正式任务，常规记忆
    HIGH   — 正式任务/考试/dispatch，主动去重和精炼
    """
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# ── Effort Level 配置 ──

_EFFORT_CONFIG: dict[MemoryEffortLevel, dict] = {
    MemoryEffortLevel.LOW: {
        "search_top_k": 3,
        "expire_enabled": False,
        "dedup_enabled": False,
    },
    MemoryEffortLevel.MEDIUM: {
        "search_top_k": 8,
        "expire_enabled": True,
        "dedup_enabled": False,
    },
    MemoryEffortLevel.HIGH: {
        "search_top_k": 15,
        "expire_enabled": True,
        "dedup_enabled": True,
    },
}

# 用于判断 HIGH effort 的关键字段
_HIGH_EFFORT_SIGNALS = {"department", "spec", "exam", "exam_mode", "dispatch", "dispatch_id"}
# 用于判断 MEDIUM effort 的关键字段
_MEDIUM_EFFORT_SIGNALS = {"action", "command", "task", "goal", "intent"}


def infer_effort_level(task_context: dict) -> MemoryEffortLevel:
    """根据任务上下文推断记忆努力等级。

    判断逻辑（优先级从高到低）：
      HIGH:   有 department/spec/exam_mode/dispatch 来源
      MEDIUM: 有明确 action/command/task 但不是正式任务
      LOW:    闲聊、问答、无 spec（默认）

    Args:
        task_context: 任务上下文字典，可包含 department, spec, action,
                      exam_mode, dispatch_id, source 等字段。

    Returns:
        MemoryEffortLevel 枚举值。
    """
    if not task_context:
        return MemoryEffortLevel.LOW

    ctx_keys = set(task_context.keys())

    # HIGH: 正式任务信号
    for signal in _HIGH_EFFORT_SIGNALS:
        if signal in ctx_keys and task_context[signal]:
            return MemoryEffortLevel.HIGH

    # HIGH: source 字段包含 dispatch
    source = str(task_context.get("source", "")).lower()
    if "dispatch" in source:
        return MemoryEffortLevel.HIGH

    # MEDIUM: 有明确动作意图
    for signal in _MEDIUM_EFFORT_SIGNALS:
        if signal in ctx_keys and task_context[signal]:
            return MemoryEffortLevel.MEDIUM

    return MemoryEffortLevel.LOW


def apply_effort_level(store: StructuredMemoryStore, level: MemoryEffortLevel) -> dict:
    """根据努力等级调整记忆系统行为。

    作为外部调节器，不修改 StructuredMemoryStore 的内部状态，
    而是执行相应的维护操作并返回配置参数供调用方使用。

    行为：
      LOW:    search top_k=3, 不触发 expire
      MEDIUM: search top_k=8, 正常 expire
      HIGH:   search top_k=15, 主动去重（搜索相似条目，合并重复）

    Args:
        store: StructuredMemoryStore 实例。
        level: 目标努力等级。

    Returns:
        dict 包含:
          - search_top_k: int, 建议的搜索结果数
          - expired_count: int, 本次过期清理的条目数（LOW 时为 0）
          - dedup_merged: int, 本次去重合并的条目数（仅 HIGH 时 > 0）
    """
    config = _EFFORT_CONFIG[level]
    result = {
        "level": level.value,
        "search_top_k": config["search_top_k"],
        "expired_count": 0,
        "dedup_merged": 0,
    }

    # Expire
    if config["expire_enabled"]:
        result["expired_count"] = store.expire()

    # Dedup (HIGH only): 逐维度搜索相似条目，合并重复
    if config["dedup_enabled"]:
        result["dedup_merged"] = _dedup_all_dimensions(store)

    log.info(f"memory_effort: applied level={level.value} → {result}")
    return result


def _dedup_all_dimensions(store: StructuredMemoryStore) -> int:
    """跨所有维度执行去重。

    策略：同一维度内，如果两条记忆的主文本字段完全相同，
    保留 confidence 更高（或更新）的那条，删除另一条。
    """
    total_merged = 0
    # 每个维度的主文本字段（用于判断重复）
    primary_field: dict[Dimension, str] = {
        Dimension.ACTIVITY:   "summary",
        Dimension.IDENTITY:   "fact",
        Dimension.CONTEXT:    "project",
        Dimension.PREFERENCE: "directive",
        Dimension.EXPERIENCE: "situation",
        Dimension.PERSONA:    "aspect",
    }

    for dim in Dimension:
        pf = primary_field.get(dim)
        if not pf:
            continue

        entries = store.get_all(dim, limit=9999)
        if len(entries) < 2:
            continue

        # Group by primary field value
        groups: dict[str, list[dict]] = {}
        for entry in entries:
            key = str(entry.get(pf, "")).strip().lower()
            if key:
                groups.setdefault(key, []).append(entry)

        # Find duplicates and remove lower-confidence ones
        ids_to_delete: list[int] = []
        for key, group in groups.items():
            if len(group) < 2:
                continue
            # Sort: highest confidence first, then newest updated_at
            group.sort(
                key=lambda e: (e.get("confidence", 0), e.get("updated_at", "")),
                reverse=True,
            )
            # Keep first, mark rest for deletion
            for dup in group[1:]:
                if dup.get("id"):
                    ids_to_delete.append(dup["id"])

        if ids_to_delete:
            with store._connect() as conn:
                placeholders = ",".join("?" for _ in ids_to_delete)
                conn.execute(
                    f"DELETE FROM {dim.value} WHERE id IN ({placeholders})",
                    ids_to_delete,
                )
            total_merged += len(ids_to_delete)
            log.debug(f"memory_effort: dedup {dim.value} removed {len(ids_to_delete)} duplicates")

    return total_merged
