# Orchestrator v1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 构建被动数字生活观察系统：自动采集 Claude 会话、Chrome/Edge 历史、Git 仓库、Steam 游戏数据，每日由 Claude API 生成用户画像与洞察报告，本地 Web 面板展示，SQLite+ChromaDB 分层存储，watcher 自愈。

**Architecture:** 四层结构：采集层（collectors）→ 存储层（SQLite热 + ChromaDB向量）→ 分析层（Claude API每日）→ 展示层（Express dashboard）。APScheduler 驱动定时任务，watcher.sh 守护进程。

**Tech Stack:** Python 3.10+, anthropic SDK, SQLite, chromadb, APScheduler, Node.js + Express + WebSocket

---

## 项目结构扩展

```
D:\Agent\orchestrator\
├── src\
│   ├── collectors\
│   │   ├── __init__.py
│   │   ├── claude_collector.py    # .claude 会话采集
│   │   ├── browser_collector.py   # Chrome/Edge 历史
│   │   ├── git_collector.py       # Git commit 记录
│   │   └── steam_collector.py     # Steam 游戏时长
│   ├── storage\
│   │   ├── __init__.py
│   │   ├── events_db.py           # SQLite 事件存储
│   │   └── vector_db.py           # ChromaDB 向量存储
│   ├── analyst.py                 # Claude API 每日分析
│   └── scheduler.py               # APScheduler 任务调度
├── dashboard\
│   ├── server.js                  # Express + WebSocket
│   ├── package.json
│   └── public\
│       └── index.html             # 面板 UI
├── bin\
│   └── watcher.sh                 # 守护进程
└── tests\
    ├── collectors\
    │   ├── test_claude_collector.py
    │   ├── test_browser_collector.py
    │   ├── test_git_collector.py
    │   └── test_steam_collector.py
    └── test_analyst.py
```

---

## Task 6: 扩展 SQLite schema（事件存储）

**Files:**
- Create: `D:\Agent\orchestrator\src\storage\__init__.py`
- Create: `D:\Agent\orchestrator\src\storage\events_db.py`
- Create: `D:\Agent\orchestrator\tests\test_events_db.py`

**Step 1: 写测试**

```python
# tests/test_events_db.py
import pytest
from src.storage.events_db import EventsDB

def test_creates_tables(tmp_path):
    db = EventsDB(str(tmp_path / "events.db"))
    tables = db.get_tables()
    assert "events" in tables
    assert "daily_summaries" in tables
    assert "user_profile" in tables

def test_insert_and_query_event(tmp_path):
    db = EventsDB(str(tmp_path / "events.db"))
    db.insert_event(
        source="claude",
        category="coding",
        title="orchestrator 设计对话",
        duration_minutes=45,
        score=0.8,
        tags=["python", "agent"],
        metadata={"tokens": 3200}
    )
    events = db.get_recent_events(days=1)
    assert len(events) == 1
    assert events[0]["source"] == "claude"
    assert events[0]["score"] == 0.8

def test_dedup_prevents_duplicate(tmp_path):
    db = EventsDB(str(tmp_path / "events.db"))
    db.insert_event("claude", "coding", "同一个对话", 30, 0.5, [], {}, dedup_key="abc123")
    db.insert_event("claude", "coding", "同一个对话", 30, 0.5, [], {}, dedup_key="abc123")
    events = db.get_recent_events(days=1)
    assert len(events) == 1

def test_get_storage_size(tmp_path):
    db = EventsDB(str(tmp_path / "events.db"))
    size = db.get_size_bytes()
    assert isinstance(size, int)
    assert size >= 0
```

**Step 2: 确认测试失败**
```bash
cd D:/Agent/orchestrator && python3 -m pytest tests/test_events_db.py -v
```
预期：`ModuleNotFoundError`

**Step 3: 实现 events_db.py**

```python
# src/storage/events_db.py
import json
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path


class EventsDB:
    def __init__(self, db_path: str = "events.db"):
        self.db_path = db_path
        self._init_tables()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self):
        with self._connect() as conn:
            conn.executescript("""
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
            """)

    def get_tables(self) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            return [row["name"] for row in rows]

    def insert_event(self, source: str, category: str, title: str,
                     duration_minutes: float, score: float, tags: list,
                     metadata: dict, dedup_key: str = None) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self._connect() as conn:
                conn.execute(
                    """INSERT INTO events
                       (source, category, title, duration_minutes, score, tags, metadata, dedup_key, occurred_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (source, category, title, duration_minutes, score,
                     json.dumps(tags, ensure_ascii=False),
                     json.dumps(metadata, ensure_ascii=False, default=str),
                     dedup_key, now)
                )
            return True
        except sqlite3.IntegrityError:
            return False  # 重复 dedup_key，跳过

    def get_recent_events(self, days: int = 7, source: str = None) -> list:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._connect() as conn:
            if source:
                rows = conn.execute(
                    "SELECT * FROM events WHERE occurred_at >= ? AND source = ? ORDER BY occurred_at DESC",
                    (since, source)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM events WHERE occurred_at >= ? ORDER BY occurred_at DESC",
                    (since,)
                ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["tags"] = json.loads(d["tags"])
            d["metadata"] = json.loads(d["metadata"])
            result.append(d)
        return result

    def get_size_bytes(self) -> int:
        path = Path(self.db_path)
        return path.stat().st_size if path.exists() else 0

    def save_daily_summary(self, date: str, summary: str):
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO daily_summaries (date, summary, created_at) VALUES (?, ?, ?)",
                (date, summary, now)
            )

    def save_user_profile(self, profile: dict):
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO user_profile (profile_json, updated_at) VALUES (?, ?)",
                (json.dumps(profile, ensure_ascii=False), now)
            )

    def get_latest_profile(self) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT profile_json FROM user_profile ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
        return json.loads(row["profile_json"]) if row else {}
```

**Step 4: 运行测试**
```bash
cd D:/Agent/orchestrator && python3 -m pytest tests/test_events_db.py -v
```
预期：4 passed

**Step 5: Commit**
```bash
cd D:/Agent/orchestrator && git add src/storage/ tests/test_events_db.py && git commit -m "feat: add EventsDB with events/daily_summaries/user_profile tables"
```

---

## Task 7: 采集器 — Claude 会话

**Files:**
- Create: `D:\Agent\orchestrator\src\collectors\__init__.py`
- Create: `D:\Agent\orchestrator\src\collectors\claude_collector.py`
- Create: `D:\Agent\orchestrator\tests\collectors\__init__.py`
- Create: `D:\Agent\orchestrator\tests\collectors\test_claude_collector.py`

**Step 1: 写测试**

```python
# tests/collectors/test_claude_collector.py
import json
import pytest
from pathlib import Path
from src.collectors.claude_collector import ClaudeCollector
from src.storage.events_db import EventsDB

def make_fake_session(tmp_path, project="test_project", messages=None):
    """创建伪造的 .claude 会话文件"""
    if messages is None:
        messages = [
            {"role": "user", "content": "帮我写一个 Python 脚本"},
            {"role": "assistant", "content": "好的，这是代码..."},
        ]
    project_dir = tmp_path / ".claude" / "projects" / project
    project_dir.mkdir(parents=True)
    session_file = project_dir / "session_abc123.jsonl"
    with open(session_file, "w", encoding="utf-8") as f:
        for msg in messages:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
    return session_file

def test_collector_finds_sessions(tmp_path):
    make_fake_session(tmp_path)
    db = EventsDB(str(tmp_path / "events.db"))
    collector = ClaudeCollector(db=db, claude_home=str(tmp_path / ".claude"))
    count = collector.collect()
    assert count >= 1

def test_collector_deduplicates(tmp_path):
    make_fake_session(tmp_path)
    db = EventsDB(str(tmp_path / "events.db"))
    collector = ClaudeCollector(db=db, claude_home=str(tmp_path / ".claude"))
    count1 = collector.collect()
    count2 = collector.collect()  # 第二次应该 0 新增
    assert count1 >= 1
    assert count2 == 0

def test_collector_extracts_topics(tmp_path):
    make_fake_session(tmp_path, messages=[
        {"role": "user", "content": "帮我设计一个多 agent 系统"},
        {"role": "assistant", "content": "我建议使用 orchestrator 模式..."},
    ])
    db = EventsDB(str(tmp_path / "events.db"))
    collector = ClaudeCollector(db=db, claude_home=str(tmp_path / ".claude"))
    collector.collect()
    events = db.get_recent_events(days=1, source="claude")
    assert len(events) >= 1
    assert "agent" in " ".join(events[0]["tags"]).lower() or len(events[0]["tags"]) >= 0
```

**Step 2: 确认测试失败**
```bash
cd D:/Agent/orchestrator && python3 -m pytest tests/collectors/test_claude_collector.py -v
```

**Step 3: 实现 claude_collector.py**

```python
# src/collectors/claude_collector.py
import json
import hashlib
import re
from pathlib import Path
from src.storage.events_db import EventsDB

KEYWORD_PATTERNS = [
    r'\b(python|javascript|typescript|rust|go|java)\b',
    r'\b(agent|orchestrator|llm|ai|claude|gpt)\b',
    r'\b(bug|fix|error|debug|test)\b',
    r'\b(设计|架构|系统|功能|实现|优化)\b',
    r'\b(数据|分析|模型|训练|推理)\b',
]


def extract_tags(text: str) -> list:
    text_lower = text.lower()
    found = set()
    for pattern in KEYWORD_PATTERNS:
        matches = re.findall(pattern, text_lower, re.IGNORECASE)
        found.update(matches)
    return list(found)[:10]


class ClaudeCollector:
    def __init__(self, db: EventsDB, claude_home: str = None):
        self.db = db
        if claude_home is None:
            claude_home = str(Path.home() / ".claude")
        self.claude_home = Path(claude_home)

    def collect(self) -> int:
        projects_dir = self.claude_home / "projects"
        if not projects_dir.exists():
            return 0

        new_count = 0
        for project_dir in projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            for session_file in project_dir.glob("*.jsonl"):
                new_count += self._process_session(session_file, project_dir.name)
        return new_count

    def _process_session(self, session_file: Path, project_name: str) -> int:
        dedup_key = f"claude:{session_file.stat().st_mtime}:{session_file.name}"
        dedup_hash = hashlib.md5(dedup_key.encode()).hexdigest()

        messages = []
        try:
            with open(session_file, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        messages.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            return 0

        if not messages:
            return 0

        # 提取文本内容
        all_text = " ".join(
            m.get("content", "") if isinstance(m.get("content"), str)
            else str(m.get("content", ""))
            for m in messages
        )
        tags = extract_tags(all_text)

        # 估算 token 量（简单按字符数）
        approx_tokens = len(all_text) // 4
        score = min(1.0, approx_tokens / 2000)  # token 越多代表越深入
        duration = len(messages) * 1.5  # 估算每条消息约 1.5 分钟

        title = f"[{project_name}] {session_file.stem[:40]}"

        inserted = self.db.insert_event(
            source="claude",
            category="conversation",
            title=title,
            duration_minutes=duration,
            score=score,
            tags=tags,
            metadata={"project": project_name, "messages": len(messages), "approx_tokens": approx_tokens},
            dedup_key=dedup_hash,
        )
        return 1 if inserted else 0
```

**Step 4: 运行测试**
```bash
cd D:/Agent/orchestrator && python3 -m pytest tests/collectors/test_claude_collector.py -v
```
预期：3 passed

**Step 5: Commit**
```bash
cd D:/Agent/orchestrator && git add src/collectors/ tests/collectors/ && git commit -m "feat: add ClaudeCollector - scans .claude sessions, deduplicates by mtime"
```

---

## Task 8: 采集器 — 浏览器历史

**Files:**
- Create: `D:\Agent\orchestrator\src\collectors\browser_collector.py`
- Create: `D:\Agent\orchestrator\tests\collectors\test_browser_collector.py`

**Step 1: 写测试**

```python
# tests/collectors/test_browser_collector.py
import sqlite3
import pytest
from pathlib import Path
from src.collectors.browser_collector import BrowserCollector, categorize_url
from src.storage.events_db import EventsDB

def make_fake_history_db(path: Path):
    """创建伪造的 Chrome history SQLite 文件"""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("""
        CREATE TABLE urls (
            id INTEGER PRIMARY KEY,
            url TEXT NOT NULL,
            title TEXT,
            visit_count INTEGER DEFAULT 0,
            last_visit_time INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE visits (
            id INTEGER PRIMARY KEY,
            url INTEGER NOT NULL,
            visit_time INTEGER NOT NULL,
            visit_duration INTEGER DEFAULT 0
        )
    """)
    # 插入测试数据（Chrome 时间戳：微秒，从 1601-01-01 起）
    chrome_epoch_offset = 11644473600 * 1000000
    now_chrome = int(__import__('time').time() * 1000000) + chrome_epoch_offset
    conn.execute("INSERT INTO urls VALUES (1, 'https://github.com/test', 'GitHub Test', 5, ?)", (now_chrome,))
    conn.execute("INSERT INTO visits VALUES (1, 1, ?, 120000000)", (now_chrome,))
    conn.commit()
    conn.close()

def test_categorize_url():
    assert categorize_url("https://github.com/test") == "dev"
    assert categorize_url("https://www.youtube.com/watch") == "media"
    assert categorize_url("https://news.ycombinator.com") == "reading"

def test_collector_reads_history(tmp_path):
    history_path = tmp_path / "Chrome" / "History"
    make_fake_history_db(history_path)
    db = EventsDB(str(tmp_path / "events.db"))
    collector = BrowserCollector(db=db, history_paths={"chrome": str(history_path)})
    count = collector.collect()
    assert count >= 1

def test_collector_deduplicates(tmp_path):
    history_path = tmp_path / "Chrome" / "History"
    make_fake_history_db(history_path)
    db = EventsDB(str(tmp_path / "events.db"))
    collector = BrowserCollector(db=db, history_paths={"chrome": str(history_path)})
    collector.collect()
    count2 = collector.collect()
    assert count2 == 0
```

**Step 2: 确认测试失败**
```bash
cd D:/Agent/orchestrator && python3 -m pytest tests/collectors/test_browser_collector.py -v
```

**Step 3: 实现 browser_collector.py**

```python
# src/collectors/browser_collector.py
import hashlib
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from src.storage.events_db import EventsDB

# Chrome 时间戳起点偏移（微秒，从 1601-01-01 到 1970-01-01）
CHROME_EPOCH_OFFSET = 11644473600 * 1_000_000

URL_CATEGORIES = {
    "dev": ["github.com", "gitlab.com", "stackoverflow.com", "docs.", "developer.", "localhost", "127.0.0.1"],
    "reading": ["medium.com", "news.ycombinator.com", "reddit.com", "substack.com", "wikipedia.org", "arxiv.org"],
    "media": ["youtube.com", "bilibili.com", "twitch.tv", "netflix.com", "spotify.com"],
    "ai": ["claude.ai", "chatgpt.com", "openai.com", "anthropic.com", "huggingface.co"],
    "social": ["twitter.com", "x.com", "weibo.com", "linkedin.com", "discord.com"],
}


def categorize_url(url: str) -> str:
    url_lower = url.lower()
    for category, patterns in URL_CATEGORIES.items():
        if any(p in url_lower for p in patterns):
            return category
    return "other"


def chrome_ts_to_iso(chrome_ts: int) -> str:
    if chrome_ts == 0:
        return datetime.now(timezone.utc).isoformat()
    unix_us = chrome_ts - CHROME_EPOCH_OFFSET
    return datetime.fromtimestamp(unix_us / 1_000_000, tz=timezone.utc).isoformat()


class BrowserCollector:
    def __init__(self, db: EventsDB, history_paths: dict = None):
        self.db = db
        if history_paths is None:
            history_paths = self._auto_detect()
        self.history_paths = history_paths

    def _auto_detect(self) -> dict:
        home = Path.home()
        candidates = {
            "chrome": home / "AppData/Local/Google/Chrome/User Data/Default/History",
            "edge": home / "AppData/Local/Microsoft/Edge/User Data/Default/History",
        }
        return {k: str(v) for k, v in candidates.items() if v.exists()}

    def collect(self) -> int:
        total = 0
        for browser, path in self.history_paths.items():
            total += self._collect_from(browser, path)
        return total

    def _collect_from(self, browser: str, history_path: str) -> int:
        # 复制到临时文件（Chrome 可能锁定原文件）
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            shutil.copy2(history_path, tmp_path)
        except (OSError, PermissionError):
            return 0

        new_count = 0
        try:
            conn = sqlite3.connect(tmp_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT u.url, u.title, v.visit_time, v.visit_duration
                FROM visits v JOIN urls u ON v.url = u.id
                WHERE v.visit_time > 0
                ORDER BY v.visit_time DESC
                LIMIT 500
            """).fetchall()
            conn.close()
        except Exception:
            return 0
        finally:
            try:
                Path(tmp_path).unlink()
            except OSError:
                pass

        for row in rows:
            url = row["url"] or ""
            title = row["title"] or url[:80]
            visit_time = row["visit_time"] or 0
            duration_us = row["visit_duration"] or 0
            duration_min = duration_us / 60_000_000

            dedup_key = hashlib.md5(f"{browser}:{url}:{visit_time}".encode()).hexdigest()
            category = categorize_url(url)
            score = min(1.0, duration_min / 10) if duration_min > 0 else 0.1

            inserted = self.db.insert_event(
                source=f"browser_{browser}",
                category=category,
                title=title[:200],
                duration_minutes=duration_min,
                score=score,
                tags=[category, browser],
                metadata={"url": url[:500]},
                dedup_key=dedup_key,
            )
            if inserted:
                new_count += 1

        return new_count
```

**Step 4: 运行测试**
```bash
cd D:/Agent/orchestrator && python3 -m pytest tests/collectors/test_browser_collector.py -v
```
预期：4 passed

**Step 5: Commit**
```bash
cd D:/Agent/orchestrator && git add src/collectors/browser_collector.py tests/collectors/test_browser_collector.py && git commit -m "feat: add BrowserCollector - reads Chrome/Edge history, categorizes URLs"
```

---

## Task 9: 采集器 — Git + Steam

**Files:**
- Create: `D:\Agent\orchestrator\src\collectors\git_collector.py`
- Create: `D:\Agent\orchestrator\src\collectors\steam_collector.py`
- Create: `D:\Agent\orchestrator\tests\collectors\test_git_collector.py`
- Create: `D:\Agent\orchestrator\tests\collectors\test_steam_collector.py`

**Step 1: 写 Git 测试**

```python
# tests/collectors/test_git_collector.py
import subprocess
import pytest
from src.collectors.git_collector import GitCollector
from src.storage.events_db import EventsDB

def make_fake_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True)
    (repo / "file.py").write_text("print('hello')")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=repo, capture_output=True)
    return repo

def test_collector_finds_commits(tmp_path):
    repo = make_fake_repo(tmp_path)
    db = EventsDB(str(tmp_path / "events.db"))
    collector = GitCollector(db=db, search_paths=[str(tmp_path)])
    count = collector.collect()
    assert count >= 1

def test_collector_deduplicates(tmp_path):
    repo = make_fake_repo(tmp_path)
    db = EventsDB(str(tmp_path / "events.db"))
    collector = GitCollector(db=db, search_paths=[str(tmp_path)])
    collector.collect()
    count2 = collector.collect()
    assert count2 == 0
```

**Step 2: 写 Steam 测试**

```python
# tests/collectors/test_steam_collector.py
import pytest
from pathlib import Path
from src.collectors.steam_collector import SteamCollector, parse_vdf_simple
from src.storage.events_db import EventsDB

def test_parse_vdf():
    vdf = '''
"AppState"
{
    "appid" "570"
    "name" "Dota 2"
    "playtime_forever" "1234"
    "playtime_2weeks" "60"
}
'''
    result = parse_vdf_simple(vdf)
    assert result.get("appid") == "570"
    assert result.get("name") == "Dota 2"
    assert result.get("playtime_forever") == "1234"

def test_collector_no_steam_returns_zero(tmp_path):
    db = EventsDB(str(tmp_path / "events.db"))
    collector = SteamCollector(db=db, steam_path=str(tmp_path / "nonexistent"))
    count = collector.collect()
    assert count == 0
```

**Step 3: 实现 git_collector.py**

```python
# src/collectors/git_collector.py
import hashlib
import subprocess
from pathlib import Path
from src.storage.events_db import EventsDB


def find_git_repos(search_paths: list) -> list:
    repos = []
    for base in search_paths:
        base = Path(base)
        if not base.exists():
            continue
        if (base / ".git").exists():
            repos.append(base)
            continue
        try:
            for item in base.iterdir():
                if item.is_dir() and (item / ".git").exists():
                    repos.append(item)
        except PermissionError:
            continue
    return repos


class GitCollector:
    def __init__(self, db: EventsDB, search_paths: list = None, days_back: int = 30):
        self.db = db
        self.days_back = days_back
        if search_paths is None:
            home = Path.home()
            search_paths = [
                str(home / "Desktop"),
                str(home / "Documents"),
                str(home / "Projects"),
                "D:/",
            ]
        self.search_paths = search_paths

    def collect(self) -> int:
        repos = find_git_repos(self.search_paths)
        total = 0
        for repo in repos:
            total += self._collect_repo(repo)
        return total

    def _collect_repo(self, repo_path: Path) -> int:
        try:
            result = subprocess.run(
                ["git", "log", f"--since={self.days_back} days ago",
                 "--format=%H|%s|%ai|%an", "--shortstat"],
                cwd=repo_path, capture_output=True, text=True, timeout=10
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return 0

        new_count = 0
        lines = result.stdout.strip().split("\n")
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line or "|" not in line:
                i += 1
                continue
            parts = line.split("|", 3)
            if len(parts) < 3:
                i += 1
                continue
            commit_hash, message, timestamp = parts[0], parts[1], parts[2]
            # 下一行可能是 shortstat
            files_changed, insertions = 0, 0
            if i + 1 < len(lines):
                stat_line = lines[i + 1]
                if "changed" in stat_line:
                    import re
                    m = re.search(r"(\d+) insertion", stat_line)
                    if m:
                        insertions = int(m.group(1))
                    i += 1

            dedup_key = f"git:{commit_hash}"
            score = min(1.0, insertions / 200) if insertions > 0 else 0.3

            inserted = self.db.insert_event(
                source="git",
                category="coding",
                title=f"[{repo_path.name}] {message[:100]}",
                duration_minutes=0,
                score=score,
                tags=["git", repo_path.name],
                metadata={"repo": str(repo_path), "hash": commit_hash[:8], "insertions": insertions},
                dedup_key=dedup_key,
            )
            if inserted:
                new_count += 1
            i += 1
        return new_count
```

**Step 4: 实现 steam_collector.py**

```python
# src/collectors/steam_collector.py
import hashlib
import re
from pathlib import Path
from src.storage.events_db import EventsDB


def parse_vdf_simple(content: str) -> dict:
    """简单 VDF 解析器，提取 key-value 对"""
    result = {}
    for match in re.finditer(r'"(\w+)"\s+"([^"]*)"', content):
        result[match.group(1)] = match.group(2)
    return result


class SteamCollector:
    def __init__(self, db: EventsDB, steam_path: str = None):
        self.db = db
        if steam_path is None:
            candidates = [
                Path("C:/Program Files (x86)/Steam"),
                Path("C:/Program Files/Steam"),
            ]
            self.steam_path = next((p for p in candidates if p.exists()), None)
        else:
            self.steam_path = Path(steam_path)

    def collect(self) -> int:
        if not self.steam_path or not Path(self.steam_path).exists():
            return 0

        steamapps = Path(self.steam_path) / "steamapps"
        if not steamapps.exists():
            return 0

        new_count = 0
        for acf_file in steamapps.glob("appmanifest_*.acf"):
            try:
                content = acf_file.read_text(encoding="utf-8", errors="ignore")
                data = parse_vdf_simple(content)
                appid = data.get("appid", "")
                name = data.get("name", f"App {appid}")
                playtime_forever = int(data.get("playtime_forever", 0))
                playtime_2weeks = int(data.get("playtime_2weeks", 0))

                if playtime_forever == 0:
                    continue

                dedup_key = hashlib.md5(f"steam:{appid}:{playtime_forever}".encode()).hexdigest()
                score = min(1.0, playtime_2weeks / 600) if playtime_2weeks > 0 else 0.1

                inserted = self.db.insert_event(
                    source="steam",
                    category="gaming",
                    title=name,
                    duration_minutes=playtime_forever,
                    score=score,
                    tags=["gaming", "steam"],
                    metadata={"appid": appid, "playtime_2weeks_min": playtime_2weeks},
                    dedup_key=dedup_key,
                )
                if inserted:
                    new_count += 1
            except (OSError, ValueError):
                continue
        return new_count
```

**Step 5: 运行测试**
```bash
cd D:/Agent/orchestrator && python3 -m pytest tests/collectors/ -v
```
预期：全部通过

**Step 6: Commit**
```bash
cd D:/Agent/orchestrator && git add src/collectors/ tests/collectors/ && git commit -m "feat: add GitCollector and SteamCollector"
```

---

## Task 10: ChromaDB 向量存储

**Files:**
- Create: `D:\Agent\orchestrator\src\storage\vector_db.py`
- Create: `D:\Agent\orchestrator\tests\test_vector_db.py`

**Step 1: 安装 chromadb**
```bash
cd D:/Agent/orchestrator && python3 -m pip install chromadb && echo "chromadb" >> requirements.txt
```

**Step 2: 写测试**

```python
# tests/test_vector_db.py
import pytest
from src.storage.vector_db import VectorDB

def test_add_and_query(tmp_path):
    db = VectorDB(persist_dir=str(tmp_path / "chroma"))
    db.add_document(
        doc_id="test_1",
        text="今天写了很多 Python 代码，实现了一个 agent 系统",
        metadata={"source": "claude", "date": "2026-03-07"}
    )
    results = db.query("agent 系统开发", n_results=1)
    assert len(results) >= 1
    assert results[0]["id"] == "test_1"

def test_deduplicates_by_id(tmp_path):
    db = VectorDB(persist_dir=str(tmp_path / "chroma"))
    db.add_document("dup_1", "第一次添加", {})
    db.add_document("dup_1", "第二次添加", {})  # 应被跳过
    assert db.count() == 1
```

**Step 3: 实现 vector_db.py**

```python
# src/storage/vector_db.py
import chromadb
from chromadb.config import Settings


class VectorDB:
    def __init__(self, persist_dir: str = "chroma_db"):
        self.client = chromadb.PersistentClient(path=persist_dir)
        self.collection = self.client.get_or_create_collection(
            name="life_observations",
            metadata={"hnsw:space": "cosine"},
        )

    def add_document(self, doc_id: str, text: str, metadata: dict) -> bool:
        existing = self.collection.get(ids=[doc_id])
        if existing["ids"]:
            return False
        self.collection.add(
            ids=[doc_id],
            documents=[text],
            metadatas=[metadata or {}],
        )
        return True

    def query(self, text: str, n_results: int = 5) -> list:
        results = self.collection.query(
            query_texts=[text],
            n_results=min(n_results, max(1, self.collection.count())),
        )
        output = []
        for i, doc_id in enumerate(results["ids"][0]):
            output.append({
                "id": doc_id,
                "text": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
                "distance": results["distances"][0][i],
            })
        return output

    def count(self) -> int:
        return self.collection.count()
```

**Step 4: 运行测试**
```bash
cd D:/Agent/orchestrator && python3 -m pytest tests/test_vector_db.py -v
```
预期：2 passed

**Step 5: Commit**
```bash
cd D:/Agent/orchestrator && git add src/storage/vector_db.py tests/test_vector_db.py requirements.txt && git commit -m "feat: add ChromaDB vector storage layer"
```

---

## Task 11: 分析 Agent（每日画像）

**Files:**
- Create: `D:\Agent\orchestrator\src\analyst.py`
- Create: `D:\Agent\orchestrator\tests\test_analyst.py`

**Step 1: 写测试**

```python
# tests/test_analyst.py
import pytest
from unittest.mock import MagicMock, patch
from src.analyst import DailyAnalyst
from src.storage.events_db import EventsDB

def make_analyst_response(definition):
    block = MagicMock()
    block.type = "tool_use"
    block.name = "save_analysis"
    block.id = "tu_analysis"
    block.input = {
        "summary": "今天主要在做 Python 开发",
        "time_breakdown": {"coding": 120, "reading": 30},
        "top_topics": ["python", "agent", "orchestrator"],
        "behavioral_insights": "下午最活跃，偏向深度工作",
        "profile_update": {"interests": ["AI", "编程"], "work_style": "夜猫子"}
    }
    response = MagicMock()
    response.content = [block]
    return response

def test_analyst_runs(tmp_path):
    db = EventsDB(str(tmp_path / "events.db"))
    db.insert_event("claude", "coding", "写代码", 60, 0.8, ["python"], {})
    db.insert_event("browser_chrome", "dev", "看文档", 30, 0.6, ["docs"], {})

    with patch("src.analyst.anthropic.Anthropic") as MockAnthropic:
        mock_client = MagicMock()
        MockAnthropic.return_value = mock_client
        mock_client.messages.create.return_value = make_analyst_response("test")

        analyst = DailyAnalyst(api_key="test-key", db=db)
        result = analyst.run()

        assert "summary" in result
        assert "top_topics" in result
```

**Step 2: 实现 analyst.py**

```python
# src/analyst.py
import os
import json
from datetime import date
import anthropic
from src.storage.events_db import EventsDB

ANALYST_TOOL = {
    "name": "save_analysis",
    "description": "保存今日分析结果和用户画像更新",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "今日活动一句话摘要"},
            "time_breakdown": {
                "type": "object",
                "description": "各类别活动时间（分钟），如 {coding: 120, reading: 30}"
            },
            "top_topics": {
                "type": "array",
                "items": {"type": "string"},
                "description": "今日最高频出现的主题关键词"
            },
            "behavioral_insights": {"type": "string", "description": "行为模式洞察（一段话）"},
            "profile_update": {
                "type": "object",
                "description": "需要更新到用户画像的字段"
            }
        },
        "required": ["summary", "top_topics", "behavioral_insights", "profile_update"]
    }
}

ANALYST_PROMPT = """你是一个生活分析专家，根据用户的数字活动数据，生成有深度的每日洞察。

分析要点：
1. 今天实际做了什么（基于数据，不要猜测）
2. 时间如何分配（量化）
3. 反复出现的主题（反映真实兴趣）
4. 行为规律（活跃时段、专注深度）
5. 对用户画像的更新建议

风格：简洁、有洞察力、基于数据说话。"""


class DailyAnalyst:
    def __init__(self, api_key: str = None, db: EventsDB = None, db_path: str = "events.db"):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.db = db or EventsDB(db_path)

    def run(self) -> dict:
        events = self.db.get_recent_events(days=1)
        profile = self.db.get_latest_profile()

        events_text = json.dumps(events[:50], ensure_ascii=False, indent=2, default=str)
        profile_text = json.dumps(profile, ensure_ascii=False, indent=2) if profile else "（暂无历史画像）"

        response = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=ANALYST_PROMPT,
            tools=[ANALYST_TOOL],
            tool_choice={"type": "tool", "name": "save_analysis"},
            messages=[{
                "role": "user",
                "content": f"今日活动数据：\n{events_text}\n\n当前用户画像：\n{profile_text}"
            }],
        )

        block = next(b for b in response.content if b.type == "tool_use")
        result = block.input

        today = date.today().isoformat()
        self.db.save_daily_summary(today, json.dumps(result, ensure_ascii=False))
        if result.get("profile_update"):
            updated = {**profile, **result["profile_update"]}
            self.db.save_user_profile(updated)

        return result
```

**Step 3: 运行测试**
```bash
cd D:/Agent/orchestrator && python3 -m pytest tests/test_analyst.py -v
```
预期：1 passed

**Step 4: Commit**
```bash
cd D:/Agent/orchestrator && git add src/analyst.py tests/test_analyst.py && git commit -m "feat: add DailyAnalyst - Claude API daily user portrait and insights"
```

---

## Task 12: 调度器 + Watcher

**Files:**
- Create: `D:\Agent\orchestrator\src\scheduler.py`
- Create: `D:\Agent\orchestrator\bin\watcher.sh`

**Step 1: 安装 APScheduler**
```bash
cd D:/Agent/orchestrator && python3 -m pip install apscheduler && echo "apscheduler" >> requirements.txt
```

**Step 2: 实现 scheduler.py**

```python
# src/scheduler.py
import logging
import os
from pathlib import Path
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from src.config import load_api_key
from src.storage.events_db import EventsDB
from src.collectors.claude_collector import ClaudeCollector
from src.collectors.browser_collector import BrowserCollector
from src.collectors.git_collector import GitCollector
from src.collectors.steam_collector import SteamCollector
from src.analyst import DailyAnalyst

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent
DB_PATH = str(BASE_DIR / "events.db")
CHROMA_DIR = str(BASE_DIR / "chroma_db")


def run_collectors():
    db = EventsDB(DB_PATH)
    results = {}
    for name, collector in [
        ("claude", ClaudeCollector(db=db)),
        ("browser", BrowserCollector(db=db)),
        ("git", GitCollector(db=db)),
        ("steam", SteamCollector(db=db)),
    ]:
        try:
            count = collector.collect()
            results[name] = count
        except Exception as e:
            log.error(f"Collector [{name}] failed: {e}")
            results[name] = -1

    log.info(f"Collection done: {results}")
    return results


def run_analysis():
    api_key = load_api_key()
    if not api_key:
        log.warning("No API key, skipping analysis")
        return
    db = EventsDB(DB_PATH)
    analyst = DailyAnalyst(api_key=api_key, db=db)
    try:
        result = analyst.run()
        log.info(f"Analysis done: {result.get('summary', '')[:80]}")
    except Exception as e:
        log.error(f"Analysis failed: {e}")


def start():
    scheduler = BlockingScheduler()
    # 每小时采集一次
    scheduler.add_job(run_collectors, "interval", hours=1, id="collectors")
    # 每天 22:00 分析
    scheduler.add_job(run_analysis, CronTrigger(hour=22, minute=0), id="analysis")

    log.info("Scheduler started. Collectors: hourly. Analysis: 22:00 daily.")
    log.info("Running initial collection...")
    run_collectors()

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped.")


if __name__ == "__main__":
    start()
```

**Step 3: 实现 watcher.sh**

```bash
#!/bin/bash
# watcher.sh — 守护 scheduler 进程，挂掉自动重启

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="$SCRIPT_DIR/scheduler.pid"
LOG_FILE="$SCRIPT_DIR/scheduler.log"

start_scheduler() {
    echo "[$(date)] Starting scheduler..." >> "$LOG_FILE"
    cd "$SCRIPT_DIR"
    python3 -m src.scheduler >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    echo "[$(date)] Scheduler started with PID $(cat $PID_FILE)" >> "$LOG_FILE"
}

echo "[$(date)] Watcher started." >> "$LOG_FILE"

while true; do
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ! kill -0 "$PID" 2>/dev/null; then
            echo "[$(date)] Scheduler (PID $PID) is dead, restarting..." >> "$LOG_FILE"
            start_scheduler
        fi
    else
        start_scheduler
    fi
    sleep 30
done
```

**Step 4: 运行测试（冒烟）**
```bash
cd D:/Agent/orchestrator && python3 -c "from src.scheduler import run_collectors; r = run_collectors(); print(r)"
```
预期：打印各采集器的结果数量

**Step 5: Commit**
```bash
cd D:/Agent/orchestrator && git add src/scheduler.py bin/watcher.sh requirements.txt && git commit -m "feat: add APScheduler (hourly collect, daily analyze) and watcher self-healing"
```

---

## Task 13: Web Dashboard

**Files:**
- Create: `D:\Agent\orchestrator\dashboard\package.json`
- Create: `D:\Agent\orchestrator\dashboard\server.js`
- Create: `D:\Agent\orchestrator\dashboard\public\index.html`

**Step 1: 初始化 Node.js 项目**
```bash
cd D:/Agent/orchestrator/dashboard && npm init -y && npm install express ws better-sqlite3
```

**Step 2: 实现 server.js**

```javascript
// dashboard/server.js
const express = require('express');
const { WebSocketServer } = require('ws');
const Database = require('better-sqlite3');
const path = require('path');
const http = require('http');

const PORT = 3030;
const DB_PATH = path.join(__dirname, '..', 'events.db');

const app = express();
const server = http.createServer(app);
const wss = new WebSocketServer({ server });

app.use(express.static(path.join(__dirname, 'public')));

function getDb() {
  try { return new Database(DB_PATH, { readonly: true }); }
  catch { return null; }
}

app.get('/api/summary', (req, res) => {
  const db = getDb();
  if (!db) return res.json({ error: 'DB not ready' });
  const summary = db.prepare(
    "SELECT * FROM daily_summaries ORDER BY date DESC LIMIT 7"
  ).all();
  const profile = db.prepare(
    "SELECT profile_json FROM user_profile ORDER BY updated_at DESC LIMIT 1"
  ).get();
  db.close();
  res.json({
    summaries: summary,
    profile: profile ? JSON.parse(profile.profile_json) : {}
  });
});

app.get('/api/events', (req, res) => {
  const db = getDb();
  if (!db) return res.json([]);
  const days = parseInt(req.query.days) || 7;
  const since = new Date(Date.now() - days * 86400000).toISOString();
  const events = db.prepare(
    "SELECT source, category, title, duration_minutes, score, tags, occurred_at FROM events WHERE occurred_at >= ? ORDER BY occurred_at DESC LIMIT 200"
  ).all(since);
  db.close();
  res.json(events.map(e => ({ ...e, tags: JSON.parse(e.tags) })));
});

app.get('/api/stats', (req, res) => {
  const db = getDb();
  if (!db) return res.json({});
  const bySource = db.prepare(
    "SELECT source, COUNT(*) as count, SUM(duration_minutes) as total_min FROM events GROUP BY source"
  ).all();
  const total = db.prepare("SELECT COUNT(*) as count FROM events").get();
  db.close();
  res.json({ bySource, total: total.count });
});

// WebSocket 推送实时更新
wss.on('connection', (ws) => {
  ws.send(JSON.stringify({ type: 'connected', message: 'Orchestrator Dashboard' }));
});

function broadcast(data) {
  wss.clients.forEach(client => {
    if (client.readyState === 1) client.send(JSON.stringify(data));
  });
}

server.listen(PORT, () => {
  console.log(`Dashboard running at http://localhost:${PORT}`);
});

module.exports = { broadcast };
```

**Step 3: 实现 index.html（极简面板）**

```html
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>Orchestrator — 生活观察者</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, sans-serif; background: #0f0f0f; color: #e0e0e0; padding: 20px; }
h1 { font-size: 1.2rem; color: #888; margin-bottom: 20px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; }
.card { background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 8px; padding: 16px; }
.card h2 { font-size: 0.75rem; text-transform: uppercase; color: #555; margin-bottom: 12px; letter-spacing: 1px; }
.stat { font-size: 2rem; font-weight: bold; color: #fff; }
.stat-label { font-size: 0.8rem; color: #666; margin-top: 4px; }
.event-list { list-style: none; }
.event-list li { padding: 6px 0; border-bottom: 1px solid #222; font-size: 0.85rem; display: flex; justify-content: space-between; }
.event-list li .src { color: #555; font-size: 0.75rem; }
.event-list li .title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin: 0 8px; }
.tag { background: #2a2a2a; color: #888; font-size: 0.7rem; padding: 2px 6px; border-radius: 3px; margin-right: 4px; }
.summary-text { font-size: 0.9rem; line-height: 1.6; color: #ccc; }
#status { position: fixed; bottom: 10px; right: 10px; font-size: 0.7rem; color: #444; }
</style>
</head>
<body>
<h1>Orchestrator · 生活观察者</h1>
<div class="grid" id="grid">
  <div class="card" id="card-stats">
    <h2>采集统计</h2>
    <div id="stats-content"><div class="stat">—</div></div>
  </div>
  <div class="card" id="card-summary">
    <h2>今日洞察</h2>
    <div id="summary-content" class="summary-text">加载中...</div>
  </div>
  <div class="card" id="card-events">
    <h2>最近活动</h2>
    <ul class="event-list" id="events-list"></ul>
  </div>
</div>
<div id="status">● 连接中...</div>

<script>
async function load() {
  const [stats, events, summary] = await Promise.all([
    fetch('/api/stats').then(r => r.json()),
    fetch('/api/events?days=1').then(r => r.json()),
    fetch('/api/summary').then(r => r.json()),
  ]);

  // 统计
  document.getElementById('stats-content').innerHTML =
    `<div class="stat">${stats.total ?? 0}</div><div class="stat-label">总事件数</div>` +
    (stats.bySource || []).map(s =>
      `<div style="margin-top:8px;font-size:0.8rem;color:#888">${s.source}: ${s.count} 条 / ${Math.round(s.total_min||0)} 分钟</div>`
    ).join('');

  // 洞察
  const latest = summary.summaries?.[0];
  if (latest) {
    const data = JSON.parse(latest.summary || '{}');
    document.getElementById('summary-content').innerHTML =
      `<p>${data.summary || '暂无摘要'}</p>` +
      (data.top_topics?.length ? `<p style="margin-top:8px">${data.top_topics.map(t => `<span class="tag">${t}</span>`).join('')}</p>` : '') +
      (data.behavioral_insights ? `<p style="margin-top:8px;color:#888;font-size:0.8rem">${data.behavioral_insights}</p>` : '');
  } else {
    document.getElementById('summary-content').innerHTML = '<p style="color:#555">暂无分析数据，等待今日 22:00 首次分析。</p>';
  }

  // 事件列表
  const list = document.getElementById('events-list');
  list.innerHTML = events.slice(0, 30).map(e =>
    `<li>
      <span class="src">${e.source}</span>
      <span class="title" title="${e.title}">${e.title}</span>
      <span style="color:#555;font-size:0.75rem">${Math.round(e.duration_minutes||0)}m</span>
    </li>`
  ).join('') || '<li style="color:#555">暂无数据</li>';
}

// WebSocket
const ws = new WebSocket(`ws://${location.host}`);
ws.onopen = () => document.getElementById('status').textContent = '● 已连接';
ws.onmessage = () => load();
ws.onclose = () => document.getElementById('status').textContent = '● 已断开';

load();
setInterval(load, 30000);
</script>
</body>
</html>
```

**Step 4: 测试面板**
```bash
cd D:/Agent/orchestrator/dashboard && node server.js
```
浏览器访问 http://localhost:3030 验证面板显示正常。

**Step 5: Commit**
```bash
cd D:/Agent/orchestrator && git add dashboard/ && git commit -m "feat: add Express+WebSocket dashboard at port 3030"
```

---

## Task 14: 端到端集成验证

**Step 1: 运行全部测试**
```bash
cd D:/Agent/orchestrator && python3 -m pytest tests/ -v
```
预期：全部通过

**Step 2: 实际采集一次**
```bash
cd D:/Agent/orchestrator && python3 -c "from src.scheduler import run_collectors; print(run_collectors())"
```

**Step 3: 启动面板验证数据**
```bash
cd D:/Agent/orchestrator/dashboard && node server.js &
start http://localhost:3030
```

**Step 4: 最终 Commit**
```bash
cd D:/Agent/orchestrator && git add . && git commit -m "feat: orchestrator v1 complete - passive life observer"
```

---

## 完成标准
- [ ] 全部测试通过
- [ ] 四个采集器实际能采到数据
- [ ] 面板 http://localhost:3030 正常展示
- [ ] 调度器可以启动并运行
