# Orchestrator v0 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 构建一个极简问题澄清 agent：收到模糊输入 → Claude 连续追问直到问题清晰 → 将对话和最终问题定义存入 SQLite。

**Architecture:** 三层结构：CLI 作为入口接收用户输入，Claude API agent 执行问题澄清对话循环，SQLite 持久化每次会话的对话记录和最终问题定义。agent 判断问题足够清晰时结束循环并输出结构化定义。

**Tech Stack:** Python 3.10+, anthropic SDK (claude-sonnet-4-6), SQLite (内置), pytest

---

## 项目结构

```
D:\Agent\orchestrator\
├── docs/plans/          # 本文件所在位置
├── src/
│   ├── __init__.py
│   ├── db.py            # SQLite 初始化和操作
│   ├── agent.py         # Claude API 问题澄清 agent
│   └── cli.py           # CLI 入口
├── tests/
│   ├── __init__.py
│   ├── test_db.py
│   └── test_agent.py
├── requirements.txt
└── .env.example         # ANTHROPIC_API_KEY 模板
```

---

## Task 1: 项目脚手架

**Files:**
- Create: `D:\Agent\orchestrator\requirements.txt`
- Create: `D:\Agent\orchestrator\.env.example`
- Create: `D:\Agent\orchestrator\src\__init__.py`
- Create: `D:\Agent\orchestrator\tests\__init__.py`

**Step 1: 创建 requirements.txt**

```
anthropic>=0.40.0
python-dotenv>=1.0.0
pytest>=8.0.0
```

**Step 2: 创建 .env.example**

```
ANTHROPIC_API_KEY=your_key_here
```

**Step 3: 创建空的 __init__.py 文件**

```bash
touch D:/Agent/orchestrator/src/__init__.py
touch D:/Agent/orchestrator/tests/__init__.py
```

**Step 4: 安装依赖**

```bash
cd D:/Agent/orchestrator
pip install -r requirements.txt
```

预期输出：Successfully installed anthropic python-dotenv pytest

**Step 5: 验证安装**

```bash
python -c "import anthropic; print(anthropic.__version__)"
```

预期输出：版本号（如 0.40.x）

---

## Task 2: SQLite 数据库层

**Files:**
- Create: `D:\Agent\orchestrator\tests\test_db.py`
- Create: `D:\Agent\orchestrator\src\db.py`

**Step 1: 写失败的测试**

```python
# tests/test_db.py
import pytest
import tempfile
import os
from src.db import Database

def test_database_creates_tables():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        db = Database(db_path)
        tables = db.get_tables()
        assert "sessions" in tables
        assert "messages" in tables
        assert "problems" in tables
    finally:
        os.unlink(db_path)

def test_create_session_returns_id():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        db = Database(db_path)
        session_id = db.create_session("测试输入")
        assert isinstance(session_id, int)
        assert session_id > 0
    finally:
        os.unlink(db_path)

def test_save_and_retrieve_messages():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        db = Database(db_path)
        session_id = db.create_session("测试输入")
        db.save_message(session_id, "user", "我想做一个网站")
        db.save_message(session_id, "assistant", "你的网站要解决什么问题？")
        messages = db.get_messages(session_id)
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"
    finally:
        os.unlink(db_path)

def test_save_problem_definition():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        db = Database(db_path)
        session_id = db.create_session("测试输入")
        db.save_problem(session_id, "帮助独立开发者追踪项目进度", "中等", ["进度追踪", "独立开发"])
        problems = db.get_problems()
        assert len(problems) == 1
        assert problems[0]["definition"] == "帮助独立开发者追踪项目进度"
    finally:
        os.unlink(db_path)
```

**Step 2: 运行测试，确认失败**

```bash
cd D:/Agent/orchestrator
pytest tests/test_db.py -v
```

预期：FAILED with "ModuleNotFoundError: No module named 'src.db'"

**Step 3: 实现 db.py**

```python
# src/db.py
import sqlite3
import json
from pathlib import Path
from datetime import datetime


class Database:
    def __init__(self, db_path: str = "orchestrator.db"):
        self.db_path = db_path
        self._init_tables()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self):
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    initial_input TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                );

                CREATE TABLE IF NOT EXISTS problems (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    definition TEXT NOT NULL,
                    clarity_level TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                );
            """)

    def get_tables(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            return [row["name"] for row in rows]

    def create_session(self, initial_input: str) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO sessions (initial_input, created_at) VALUES (?, ?)",
                (initial_input, datetime.utcnow().isoformat())
            )
            return cursor.lastrowid

    def save_message(self, session_id: int, role: str, content: str):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (session_id, role, content, datetime.utcnow().isoformat())
            )

    def get_messages(self, session_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT role, content, created_at FROM messages WHERE session_id = ? ORDER BY id",
                (session_id,)
            ).fetchall()
            return [dict(row) for row in rows]

    def save_problem(self, session_id: int, definition: str, clarity_level: str, tags: list[str]):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO problems (session_id, definition, clarity_level, tags, created_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, definition, clarity_level, json.dumps(tags, ensure_ascii=False), datetime.utcnow().isoformat())
            )

    def get_problems(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM problems ORDER BY created_at DESC"
            ).fetchall()
            result = []
            for row in rows:
                d = dict(row)
                d["tags"] = json.loads(d["tags"])
                result.append(d)
            return result
```

**Step 4: 运行测试，确认通过**

```bash
pytest tests/test_db.py -v
```

预期：4 passed

**Step 5: Commit**

```bash
cd D:/Agent/orchestrator
git init
git add src/db.py tests/test_db.py src/__init__.py tests/__init__.py requirements.txt .env.example
git commit -m "feat: add SQLite database layer with sessions, messages, problems tables"
```

---

## Task 3: Claude API 问题澄清 Agent

**Files:**
- Create: `D:\Agent\orchestrator\tests\test_agent.py`
- Create: `D:\Agent\orchestrator\src\agent.py`

**Step 1: 写失败的测试**

```python
# tests/test_agent.py
import pytest
from unittest.mock import MagicMock, patch
from src.agent import ClarificationAgent

def make_mock_response(content: str, stop_reason: str = "end_turn"):
    msg = MagicMock()
    msg.content = [MagicMock(text=content)]
    msg.stop_reason = stop_reason
    return msg

def test_agent_initializes():
    agent = ClarificationAgent(api_key="test-key")
    assert agent is not None

def test_agent_detects_clear_problem():
    agent = ClarificationAgent(api_key="test-key")
    response = '{"is_clear": true, "question": null, "definition": "帮助用户追踪待办事项", "clarity_level": "高", "tags": ["任务管理"]}'
    result = agent._parse_response(response)
    assert result["is_clear"] is True
    assert result["definition"] == "帮助用户追踪待办事项"

def test_agent_detects_unclear_problem():
    agent = ClarificationAgent(api_key="test-key")
    response = '{"is_clear": false, "question": "你想解决什么具体问题？", "definition": null, "clarity_level": "低", "tags": []}'
    result = agent._parse_response(response)
    assert result["is_clear"] is False
    assert "question" in result
    assert result["question"] is not None

def test_agent_runs_clarification_loop(tmp_path):
    db_path = str(tmp_path / "test.db")

    with patch("anthropic.Anthropic") as MockAnthropic:
        mock_client = MagicMock()
        MockAnthropic.return_value = mock_client

        # 第一轮：不清晰，追问
        mock_client.messages.create.side_effect = [
            make_mock_response('{"is_clear": false, "question": "你的目标用户是谁？", "definition": null, "clarity_level": "低", "tags": []}'),
            # 第二轮：清晰了
            make_mock_response('{"is_clear": true, "question": null, "definition": "帮助独立开发者追踪项目进度", "clarity_level": "高", "tags": ["开发者", "项目管理"]}'),
        ]

        agent = ClarificationAgent(api_key="test-key", db_path=db_path)
        result = agent.run("我想做一个工具", user_replies=["给独立开发者用"])

        assert result["definition"] == "帮助独立开发者追踪项目进度"
        assert result["session_id"] is not None
```

**Step 2: 运行测试，确认失败**

```bash
cd D:/Agent/orchestrator
pytest tests/test_agent.py -v
```

预期：FAILED with "ModuleNotFoundError: No module named 'src.agent'"

**Step 3: 实现 agent.py**

```python
# src/agent.py
import json
import os
import anthropic
from src.db import Database

SYSTEM_PROMPT = """你是一个问题澄清专家。你的唯一工作是帮助用户把模糊的想法变成清晰、可执行的问题定义。

每次回复必须是严格的 JSON 格式，不能有任何其他文字：

{
  "is_clear": true/false,
  "question": "如果不清晰，问用户的下一个问题（只问一个）",
  "definition": "如果清晰了，给出简洁的问题定义（一句话）",
  "clarity_level": "低/中/高",
  "tags": ["关键词1", "关键词2"]
}

判断标准：
- 低：意图完全模糊，不知道要做什么
- 中：大方向有了，但缺少关键细节（目标用户、具体场景、成功标准）
- 高：问题清晰，知道是什么、为谁、解决什么

追问策略：
- 每次只问一个最关键的问题
- 最多追问 5 次，超过则强制输出当前最佳理解
- 问题要具体，不要泛泛而谈"""


class ClarificationAgent:
    def __init__(self, api_key: str = None, db_path: str = "orchestrator.db"):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.db = Database(db_path)
        self.max_rounds = 5

    def _parse_response(self, content: str) -> dict:
        # 提取 JSON，兼容模型偶尔包裹在 ```json ``` 的情况
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1])
        return json.loads(content)

    def run(self, initial_input: str, user_replies: list[str] = None) -> dict:
        """
        运行问题澄清循环。
        user_replies 仅用于测试时注入预设回答，生产环境为 None（从 stdin 读取）。
        """
        session_id = self.db.create_session(initial_input)
        messages = [{"role": "user", "content": initial_input}]
        self.db.save_message(session_id, "user", initial_input)

        reply_queue = list(user_replies) if user_replies else []

        for round_num in range(self.max_rounds):
            response = self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=512,
                system=SYSTEM_PROMPT,
                messages=messages,
            )

            raw = response.content[0].text
            result = self._parse_response(raw)
            self.db.save_message(session_id, "assistant", raw)

            messages.append({"role": "assistant", "content": raw})

            if result.get("is_clear") or round_num == self.max_rounds - 1:
                self.db.save_problem(
                    session_id,
                    result.get("definition", "（未能完全澄清）"),
                    result.get("clarity_level", "低"),
                    result.get("tags", []),
                )
                return {
                    "session_id": session_id,
                    "definition": result.get("definition"),
                    "clarity_level": result.get("clarity_level"),
                    "tags": result.get("tags", []),
                    "rounds": round_num + 1,
                }

            # 不清晰，需要用户回答追问
            question = result["question"]
            if reply_queue:
                user_reply = reply_queue.pop(0)
            else:
                print(f"\nAgent: {question}")
                user_reply = input("你: ").strip()

            self.db.save_message(session_id, "user", user_reply)
            messages.append({"role": "user", "content": user_reply})

        # 不应该到这里，但保险起见
        return {"session_id": session_id, "definition": None, "rounds": self.max_rounds}
```

**Step 4: 运行测试，确认通过**

```bash
pytest tests/test_agent.py -v
```

预期：4 passed

**Step 5: Commit**

```bash
git add src/agent.py tests/test_agent.py
git commit -m "feat: add Claude API clarification agent with 5-round dialogue loop"
```

---

## Task 4: CLI 入口

**Files:**
- Create: `D:\Agent\orchestrator\src\cli.py`

**Step 1: 实现 cli.py**

```python
# src/cli.py
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from src.agent import ClarificationAgent
from src.db import Database

load_dotenv()

DB_PATH = str(Path(__file__).parent.parent / "orchestrator.db")


def run():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("错误：请设置 ANTHROPIC_API_KEY 环境变量")
        print("复制 .env.example 为 .env 并填入你的 key")
        sys.exit(1)

    agent = ClarificationAgent(api_key=api_key, db_path=DB_PATH)

    print("=== Orchestrator v0 ===")
    print("输入你的想法或问题（Ctrl+C 退出）\n")

    try:
        while True:
            initial_input = input("你: ").strip()
            if not initial_input:
                continue

            print("\n[开始澄清...]\n")
            result = agent.run(initial_input)

            print("\n" + "="*40)
            print(f"问题定义: {result['definition']}")
            print(f"清晰度:   {result['clarity_level']}")
            print(f"标签:     {', '.join(result['tags'])}")
            print(f"用时轮数: {result['rounds']}")
            print(f"会话 ID:  {result['session_id']}")
            print("="*40 + "\n")

    except KeyboardInterrupt:
        print("\n\n已退出。")
        db = Database(DB_PATH)
        problems = db.get_problems()
        if problems:
            print(f"\n本次共定义了 {len(problems)} 个问题，已存入数据库。")


def main():
    run()


if __name__ == "__main__":
    main()
```

**Step 2: 手动冒烟测试**

确保 `.env` 中有有效的 `ANTHROPIC_API_KEY`，然后：

```bash
cd D:/Agent/orchestrator
python -m src.cli
```

输入"我想做一个 orchestrator"，验证 agent 开始追问。

**Step 3: Commit**

```bash
git add src/cli.py
git commit -m "feat: add CLI entry point for clarification agent"
```

---

## Task 5: 端到端验证

**Step 1: 运行全部测试**

```bash
cd D:/Agent/orchestrator
pytest tests/ -v
```

预期：全部 PASS

**Step 2: 验证数据库内容**

```bash
python -c "
from src.db import Database
db = Database('orchestrator.db')
problems = db.get_problems()
for p in problems:
    print(p)
"
```

预期：打印出冒烟测试时存入的问题定义记录

**Step 3: 最终 Commit**

```bash
git add .
git commit -m "feat: orchestrator v0 complete - clarification agent with SQLite persistence"
```

---

## 完成标准

- [ ] 所有测试通过（`pytest tests/ -v`）
- [ ] CLI 可以正常启动并与 Claude 对话
- [ ] 对话记录和问题定义正确存入 SQLite
- [ ] `.env.example` 存在，`.env` 不进入 git
