"""Schema DDL and migration statements for EventsDB."""

TABLE_DDL = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    duration_minutes REAL DEFAULT 0,
    score REAL DEFAULT 0.5,
    tags TEXT NOT NULL DEFAULT '[]',
    metadata TEXT NOT NULL DEFAULT '{}',
    dedup_key TEXT UNIQUE,
    occurred_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_source ON events(source);
CREATE INDEX IF NOT EXISTS idx_events_occurred ON events(occurred_at);

CREATE TABLE IF NOT EXISTS daily_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT UNIQUE NOT NULL,
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_profile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS insights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data_json TEXT NOT NULL,
    generated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spec TEXT NOT NULL DEFAULT '{}',
    action TEXT NOT NULL,
    reason TEXT,
    priority TEXT DEFAULT 'medium',
    source TEXT DEFAULT 'auto',
    status TEXT DEFAULT 'pending',
    output TEXT,
    scrutiny_note TEXT,
    created_at TEXT NOT NULL,
    approved_at TEXT,
    started_at TEXT,
    finished_at TEXT,
    parent_task_id INTEGER,
    depends_on TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level TEXT NOT NULL DEFAULT 'INFO',
    source TEXT NOT NULL DEFAULT 'system',
    message TEXT NOT NULL,
    run_id TEXT,
    step TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scheduler_status (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profile_analysis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data_json TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'periodic',
    generated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attention_debts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    project TEXT NOT NULL,
    summary TEXT NOT NULL,
    severity TEXT DEFAULT 'medium',
    status TEXT DEFAULT 'open',
    context TEXT,
    resolved_by TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    UNIQUE(session_id, summary)
);
CREATE INDEX IF NOT EXISTS idx_debts_status ON attention_debts(status);

CREATE TABLE IF NOT EXISTS experiences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    type TEXT NOT NULL,
    summary TEXT NOT NULL,
    detail TEXT NOT NULL,
    instance TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(date, summary)
);
CREATE INDEX IF NOT EXISTS idx_experiences_date ON experiences(date);

CREATE TABLE IF NOT EXISTS agent_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    data TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_events_task ON agent_events(task_id);

CREATE TABLE IF NOT EXISTS collector_reputation (
    name TEXT PRIMARY KEY,
    data TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    department TEXT NOT NULL,
    task_id INTEGER,
    mode TEXT NOT NULL DEFAULT 'auto',
    summary TEXT NOT NULL,
    files_changed TEXT NOT NULL DEFAULT '[]',
    commit_hash TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'done',
    duration_s INTEGER DEFAULT 0,
    notes TEXT DEFAULT '',
    hash TEXT NOT NULL,
    prev_hash TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_run_logs_dept ON run_logs(department);
CREATE INDEX IF NOT EXISTS idx_run_logs_created ON run_logs(created_at);

CREATE TABLE IF NOT EXISTS sub_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    stage_name TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    started_at TEXT,
    finished_at TEXT,
    duration_ms INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0,
    output_preview TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sub_runs_task ON sub_runs(task_id);

CREATE TABLE IF NOT EXISTS task_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    agent_id TEXT NOT NULL DEFAULT '',
    session_data TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(task_id, agent_id)
);
CREATE INDEX IF NOT EXISTS idx_sessions_task ON task_sessions(task_id);

CREATE TABLE IF NOT EXISTS heartbeats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    agent_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'alive',
    progress_pct INTEGER DEFAULT 0,
    message TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_heartbeats_task ON heartbeats(task_id);

CREATE TABLE IF NOT EXISTS file_index (
    path TEXT PRIMARY KEY,
    routing_hint TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]',
    embedding TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_msg_chat ON chat_messages(chat_id, created_at);

CREATE TABLE IF NOT EXISTS chat_memory (
    chat_id TEXT PRIMARY KEY,
    summary TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    summary TEXT DEFAULT '',
    topics TEXT NOT NULL DEFAULT '[]',
    experience_ids TEXT NOT NULL DEFAULT '[]',
    source TEXT NOT NULL DEFAULT 'cli',
    created_at TEXT NOT NULL,
    UNIQUE(session_id)
);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at);

CREATE TABLE IF NOT EXISTS memory_entries (
    path TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    type TEXT NOT NULL DEFAULT 'project',
    content_hash TEXT NOT NULL DEFAULT '',
    last_modified TEXT NOT NULL,
    synced_at TEXT NOT NULL,
    l0 TEXT NOT NULL DEFAULT '',
    l1 TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_memory_type ON memory_entries(type);

CREATE TABLE IF NOT EXISTS learnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_key TEXT NOT NULL,
    area TEXT NOT NULL DEFAULT 'general',
    rule TEXT NOT NULL,
    context TEXT NOT NULL DEFAULT '',
    source_type TEXT NOT NULL DEFAULT 'error',
    status TEXT NOT NULL DEFAULT 'pending',
    recurrence INTEGER NOT NULL DEFAULT 1,
    department TEXT,
    task_id INTEGER,
    created_at TEXT NOT NULL,
    promoted_at TEXT,
    retired_at TEXT,
    UNIQUE(pattern_key)
);
CREATE INDEX IF NOT EXISTS idx_learnings_status ON learnings(status);
CREATE INDEX IF NOT EXISTS idx_learnings_area ON learnings(area);
CREATE INDEX IF NOT EXISTS idx_learnings_dept ON learnings(department);

CREATE TABLE IF NOT EXISTS wake_sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     INTEGER NOT NULL,
    chat_id     TEXT NOT NULL,
    spotlight   TEXT NOT NULL,
    mode        TEXT NOT NULL DEFAULT 'silent',
    status      TEXT NOT NULL DEFAULT 'pending',
    result      TEXT,
    created_at  TEXT NOT NULL,
    started_at  TEXT,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_wake_status ON wake_sessions(status);
CREATE INDEX IF NOT EXISTS idx_wake_task ON wake_sessions(task_id);
"""

# Migrations: (table, column, type)
MIGRATIONS_TASKS = [
    ("tasks", "scrutiny_note", "TEXT"),
    ("tasks", "parent_task_id", "INTEGER"),
    ("tasks", "depends_on", "TEXT DEFAULT '[]'"),
]

MIGRATIONS_LOGS = [
    ("logs", "run_id", "TEXT"),
    ("logs", "step", "TEXT"),
]

MIGRATIONS_LEARNINGS = [
    ("learnings", "hit_count", "INTEGER DEFAULT 0"),
    ("learnings", "last_hit_at", "TEXT"),
    ("learnings", "ttl_days", "INTEGER DEFAULT 0"),
    ("learnings", "expires_at", "TEXT"),
    # DB-unification: detail, related_keys, entry_type, first_seen, last_seen
    ("learnings", "detail", "TEXT DEFAULT ''"),
    ("learnings", "related_keys", "TEXT DEFAULT '[]'"),
    ("learnings", "entry_type", "TEXT DEFAULT 'learning'"),
    ("learnings", "first_seen", "TEXT DEFAULT ''"),
    ("learnings", "last_seen", "TEXT DEFAULT ''"),
]

DEFERRED_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_logs_run_id ON logs(run_id)",
]


def get_table_ddl() -> list[str]:
    """Return the DDL as a single-element list (one executescript block)."""
    return [TABLE_DDL]


def get_migrations() -> list[tuple[str, str, str]]:
    """Return all ALTER TABLE migrations as (table, column, type) tuples."""
    return MIGRATIONS_TASKS + MIGRATIONS_LOGS + MIGRATIONS_LEARNINGS


def get_deferred_indexes() -> list[str]:
    """Return SQL statements for indexes that depend on migration columns."""
    return DEFERRED_INDEXES
