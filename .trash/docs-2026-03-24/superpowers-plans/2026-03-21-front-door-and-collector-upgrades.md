# Orchestrator 前门 + 采集器升级 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 Orchestrator 装上"前门"（Intent Gateway + Governor 直调 API），同时升级采集器基础设施（ICollector 协议 + 自动发现 + 错误层级 + 并行执行 + 声誉系统 + 可观测性）。

**Architecture:** 分两条独立主线并行推进：
- **主线 A：前门系统**（Intent Gateway + Governor.dispatch_user_intent()）— 让终端对话能直接派单给 Governor，不经过 Dashboard
- **主线 B：采集器升级**（ICollector 协议 → 错误层级 → 自动发现 → 并行执行 → 声誉系统 → 可观测性）— 让后台更强更可靠

两条主线互不依赖，可以分配给不同的 sub-agent 并行开发。

**交互模式：** 用户在 Claude Code 终端对话 → Orchestrator 实例读 boot.md 恢复人格 → 识别用户意图 → 调用 Governor.dispatch_user_intent() → 执行 → 终端直接反馈结果。Dashboard 保持只读橱窗，新增声誉数据 API 但不加命令栏。

**Tech Stack:** Python 3.11+, Claude Agent SDK, Claude API (Haiku for intent parsing), Express.js, SQLite, ThreadPoolExecutor

**Spec:** `docs/superpowers/specs/2026-03-21-opencli-inspired-upgrades-design.md`

---

## 文件结构

### 主线 A：前门系统
```
src/gateway/                          # 新目录
├── __init__.py
├── intent.py                         # Intent Gateway — 自然语言 → TaskSpec
└── dispatcher.py                     # Governor 直调封装 — 终端 → Governor → 执行

tests/gateway/
├── test_intent.py                    # Intent Gateway 单元测试
└── test_dispatcher.py                # Dispatcher 测试
```

### 主线 B：采集器升级
```
src/collectors/
├── base.py                           # 新建：ICollector ABC + CollectorMeta
├── errors.py                         # 新建：CollectorError 层级
├── retry.py                          # 新建：重试 + 熔断
├── registry.py                       # 新建：自动发现 + 注册表
├── reputation.py                     # 新建：声誉系统
├── git_collector.py                  # 修改：继承 ICollector
├── browser_collector.py              # 修改：继承 ICollector
├── claude_collector.py               # 修改：继承 ICollector
├── steam_collector.py                # 修改：继承 ICollector
├── youtube_music_collector.py        # 修改：继承 ICollector
├── qqmusic_collector.py              # 修改：继承 ICollector
├── codebase_collector.py             # 修改：继承 ICollector
├── vscode_collector.py               # 修改：继承 ICollector
└── network_collector.py              # 修改：继承 ICollector

src/scheduler.py                      # 修改：用 registry + ThreadPoolExecutor
src/storage/events_db.py              # 修改：新增 collector_reputation 表

tests/collectors/
├── test_base.py                      # ICollector 协议测试
├── test_registry.py                  # 自动发现测试
├── test_errors_retry.py              # 错误 + 重试测试
└── test_reputation.py                # 声誉系统测试
```

---

## 主线 A：前门系统

### Task A1: Intent Gateway — 自然语言 → 结构化任务

**Files:**
- Create: `src/gateway/__init__.py`
- Create: `src/gateway/intent.py`
- Create: `tests/gateway/test_intent.py`

- [ ] **Step 1: 创建测试文件**

```python
# tests/gateway/test_intent.py
import pytest
from unittest.mock import patch, MagicMock
from src.gateway.intent import IntentGateway, TaskIntent


class TestIntentGateway:
    def setup_method(self):
        self.gw = IntentGateway()

    def test_parse_returns_task_intent(self):
        """parse() 应返回 TaskIntent dataclass。"""
        with patch.object(self.gw, '_call_llm') as mock:
            mock.return_value = {
                "action": "修复 Steam 采集器路径问题",
                "department": "engineering",
                "cognitive_mode": "hypothesis",
                "priority": "medium",
                "problem": "Steam 采集器一直返回 0 数据",
                "expected": "采集器能正确找到 Steam 安装路径并采集数据",
                "needs_clarification": False,
                "clarification_question": None,
            }
            result = self.gw.parse("帮我看看为什么 Steam 采集器一直是 0 数据")
            assert isinstance(result, TaskIntent)
            assert result.department == "engineering"
            assert result.cognitive_mode == "hypothesis"
            assert not result.needs_clarification

    def test_parse_needs_clarification(self):
        """模糊输入应触发澄清。"""
        with patch.object(self.gw, '_call_llm') as mock:
            mock.return_value = {
                "action": "",
                "department": "",
                "cognitive_mode": "react",
                "priority": "medium",
                "problem": "",
                "expected": "",
                "needs_clarification": True,
                "clarification_question": "你说的「那个问题」是指哪个？能具体一点吗？",
            }
            result = self.gw.parse("把那个问题修一下")
            assert result.needs_clarification
            assert "具体" in result.clarification_question

    def test_parse_with_context(self):
        """带上下文的指令应利用上下文。"""
        with patch.object(self.gw, '_call_llm') as mock:
            mock.return_value = {
                "action": "运行 deep_scan 安全审计",
                "department": "security",
                "cognitive_mode": "react",
                "priority": "high",
                "problem": "需要全面安全扫描",
                "expected": "无高危漏洞",
                "needs_clarification": False,
                "clarification_question": None,
            }
            result = self.gw.parse(
                "跑一次安全扫描",
                context={"recent_events": ["dependency update"]},
            )
            assert result.department == "security"

    def test_to_governor_spec(self):
        """TaskIntent 应能转换为 Governor 的 spec 格式。"""
        intent = TaskIntent(
            action="修复 Steam 采集器",
            department="engineering",
            cognitive_mode="hypothesis",
            priority="high",
            problem="路径错误导致 0 数据",
            expected="正常采集",
            needs_clarification=False,
            clarification_question=None,
        )
        spec = intent.to_governor_spec()
        assert spec["department"] == "engineering"
        assert spec["problem"] == "路径错误导致 0 数据"
        assert spec["cognitive_mode"] == "hypothesis"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /d/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/gateway/test_intent.py -v`
Expected: ImportError — `src.gateway.intent` 不存在

- [ ] **Step 3: 实现 IntentGateway**

```python
# src/gateway/__init__.py
# (空文件)

# src/gateway/intent.py
"""
Intent Gateway — Orchestrator 的前台接待。
把用户的自然语言指令翻译成 Governor 能理解的结构化任务。

灵感：OpenCLI 的 capability routing — 理解用户要什么，路由到对的地方。
"""
import json
import logging
from dataclasses import dataclass, asdict
from typing import Optional

from src.core.llm_router import get_router

log = logging.getLogger(__name__)

# Governor 支持的六部
VALID_DEPARTMENTS = {"engineering", "operations", "protocol", "security", "quality", "personnel"}
VALID_COGNITIVE_MODES = {"direct", "react", "hypothesis", "designer"}
VALID_PRIORITIES = {"low", "medium", "high", "critical"}

INTENT_PROMPT = """你是 Orchestrator 的意图解析器。用户会用自然语言发指令，你需要翻译成结构化任务。

## Orchestrator 六部
- engineering（工部）：代码修改、bug 修复、功能开发、重构
- operations（户部）：运维、部署、配置、系统健康
- protocol（礼部）：注意力审计、时间分析、债务扫描
- security（兵部）：安全扫描、依赖审计、漏洞检测
- quality（刑部）：测试、code review、质量验收
- personnel（吏部）：绩效分析、能力评估、发现层

## 认知模式
- direct: 简单任务（改名、清理、配置调整）
- react: 中等复杂（边做边想）
- hypothesis: 诊断类（先假设后验证 — "为什么X不工作"）
- designer: 大型改动（先设计后实现 — "重构X系统"）

## 输出格式（严格 JSON）
{
  "action": "一句话描述要做什么",
  "department": "目标部门（上面六个之一）",
  "cognitive_mode": "认知模式",
  "priority": "low/medium/high/critical",
  "problem": "问题描述",
  "expected": "期望结果",
  "needs_clarification": false,
  "clarification_question": null
}

如果用户指令太模糊无法确定行动，设置 needs_clarification=true 并在 clarification_question 中用中文提问。

## 上下文
{context}

## 用户指令
{user_input}
"""


@dataclass
class TaskIntent:
    """解析后的用户意图。"""
    action: str
    department: str
    cognitive_mode: str
    priority: str
    problem: str
    expected: str
    needs_clarification: bool
    clarification_question: Optional[str] = None

    def to_governor_spec(self) -> dict:
        """转换为 Governor._dispatch_task() 需要的 spec 格式。"""
        return {
            "department": self.department,
            "problem": self.problem,
            "expected": self.expected,
            "summary": self.action,
            "cognitive_mode": self.cognitive_mode,
            "source": "user_intent",
            "observation": f"用户指令：{self.action}",
            "importance": f"用户直接指派，优先级 {self.priority}",
        }


class IntentGateway:
    """Orchestrator 的前台。理解用户说什么，翻译成 Governor 的语言。"""

    def parse(self, user_input: str, context: dict = None) -> TaskIntent:
        """解析用户自然语言指令。"""
        ctx_str = json.dumps(context or {}, ensure_ascii=False, indent=2)
        prompt = INTENT_PROMPT.format(user_input=user_input, context=ctx_str)

        raw = self._call_llm(prompt)
        return self._validate(raw)

    def _call_llm(self, prompt: str) -> dict:
        """调用 LLM 解析意图。用最便宜的模型。"""
        router = get_router()
        response = router.generate(prompt, task_type="scrutiny", max_tokens=512)

        # 提取 JSON
        text = response.strip()
        # 尝试找 JSON 块
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            log.warning(f"intent: failed to parse LLM response as JSON: {text[:200]}")
            return {
                "action": "", "department": "", "cognitive_mode": "react",
                "priority": "medium", "problem": "", "expected": "",
                "needs_clarification": True,
                "clarification_question": "抱歉，我没理解你的意思。能换个说法吗？",
            }

    def _validate(self, raw: dict) -> TaskIntent:
        """校验并规范化 LLM 输出。"""
        dept = raw.get("department", "").lower()
        if dept not in VALID_DEPARTMENTS:
            dept = "engineering"  # 默认工部

        mode = raw.get("cognitive_mode", "react").lower()
        if mode not in VALID_COGNITIVE_MODES:
            mode = "react"

        priority = raw.get("priority", "medium").lower()
        if priority not in VALID_PRIORITIES:
            priority = "medium"

        return TaskIntent(
            action=raw.get("action", ""),
            department=dept,
            cognitive_mode=mode,
            priority=priority,
            problem=raw.get("problem", ""),
            expected=raw.get("expected", ""),
            needs_clarification=bool(raw.get("needs_clarification", False)),
            clarification_question=raw.get("clarification_question"),
        )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /d/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/gateway/test_intent.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/gateway/ tests/gateway/
git commit -m "feat(gateway): add Intent Gateway for user command parsing"
```

---

### Task A2: Governor 直调封装 — 终端对话直接派单

**Files:**
- Create: `src/gateway/dispatcher.py`
- Create: `tests/gateway/test_dispatcher.py`

- [ ] **Step 1: 创建测试**

```python
# tests/gateway/test_dispatcher.py
import pytest
from unittest.mock import patch, MagicMock
from src.gateway.dispatcher import dispatch_user_intent
from src.gateway.intent import TaskIntent


class TestDispatcher:
    def test_dispatch_creates_task(self):
        """明确意图应创建 Governor 任务并返回 task_id。"""
        intent = TaskIntent(
            action="修复 Steam 采集器", department="engineering",
            cognitive_mode="hypothesis", priority="high",
            problem="Steam 采集器 0 数据", expected="正常采集",
            needs_clarification=False,
        )
        mock_db = MagicMock()
        mock_db.create_task.return_value = 42
        with patch('src.gateway.dispatcher.EventsDB', return_value=mock_db):
            result = dispatch_user_intent(intent, db=mock_db)
            assert result["task_id"] == 42
            assert result["status"] == "created"
            mock_db.create_task.assert_called_once()

    def test_dispatch_clarification_returns_question(self):
        """需要澄清的意图不创建任务，返回问题。"""
        intent = TaskIntent(
            action="", department="",
            cognitive_mode="react", priority="medium",
            problem="", expected="",
            needs_clarification=True,
            clarification_question="你说的「那个」是哪个？",
        )
        result = dispatch_user_intent(intent)
        assert result["status"] == "needs_clarification"
        assert "那个" in result["question"]

    def test_full_pipeline_from_text(self):
        """从自然语言到派单的完整流程。"""
        with patch('src.gateway.dispatcher.IntentGateway') as MockGW:
            MockGW.return_value.parse.return_value = TaskIntent(
                action="运行安全扫描", department="security",
                cognitive_mode="react", priority="high",
                problem="需要安全检查", expected="无高危漏洞",
                needs_clarification=False,
            )
            mock_db = MagicMock()
            mock_db.create_task.return_value = 99
            with patch('src.gateway.dispatcher.EventsDB', return_value=mock_db):
                result = dispatch_from_text("跑一次安全扫描", db=mock_db)
                assert result["task_id"] == 99
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/gateway/test_dispatcher.py -v`
Expected: ImportError

- [ ] **Step 3: 实现 dispatcher.py**

```python
# src/gateway/dispatcher.py
"""
Dispatcher — 终端对话直接调用 Governor 的桥梁。

使用场景：在 Claude Code 终端里，Orchestrator 实例识别到用户想派活，
直接调这个模块创建 Governor 任务。不走 Dashboard，不走 HTTP。

用法：
    from src.gateway.dispatcher import dispatch_from_text
    result = dispatch_from_text("帮我看看为什么 Steam 采集器是 0 数据")
    # → {"task_id": 42, "status": "created", "action": "...", "department": "..."}
"""
import logging
from pathlib import Path

from src.gateway.intent import IntentGateway, TaskIntent
from src.storage.events_db import EventsDB

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent
DB_PATH = str(BASE_DIR / "data" / "events.db")


def dispatch_user_intent(intent: TaskIntent, db: EventsDB = None) -> dict:
    """把解析好的 TaskIntent 变成 Governor 任务。

    返回:
    - {"task_id": int, "status": "created", "action": ..., "department": ...}
    - {"status": "needs_clarification", "question": ...}
    """
    if intent.needs_clarification:
        return {
            "status": "needs_clarification",
            "question": intent.clarification_question or "能再说具体一点吗？",
        }

    db = db or EventsDB(DB_PATH)
    spec = intent.to_governor_spec()

    task_id = db.create_task(
        action=intent.action,
        reason=f"用户指令（终端）",
        priority=intent.priority,
        spec=spec,
        source="user_intent",
    )

    db.write_log(
        f"前门派单: #{task_id} → {intent.department}: {intent.action}",
        "INFO", "gateway",
    )

    log.info(f"dispatcher: created task #{task_id} [{intent.department}] {intent.action}")

    return {
        "task_id": task_id,
        "status": "created",
        "action": intent.action,
        "department": intent.department,
        "priority": intent.priority,
        "cognitive_mode": intent.cognitive_mode,
    }


def dispatch_from_text(text: str, context: dict = None, db: EventsDB = None) -> dict:
    """一步到位：自然语言 → 解析 → 派单。

    终端对话里直接调用这个。
    """
    gateway = IntentGateway()
    intent = gateway.parse(text, context=context)
    return dispatch_user_intent(intent, db=db)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/gateway/test_dispatcher.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/gateway/dispatcher.py tests/gateway/test_dispatcher.py
git commit -m "feat(gateway): add dispatcher for terminal-to-Governor pipeline"
```

---

## 主线 B：采集器升级

### Task B1: ICollector 协议 + 错误层级

**Files:**
- Create: `src/collectors/base.py`
- Create: `src/collectors/errors.py`
- Create: `src/collectors/retry.py`
- Create: `tests/collectors/test_base.py`
- Create: `tests/collectors/test_errors_retry.py`

- [ ] **Step 1: 创建测试文件**

```python
# tests/collectors/test_base.py
import pytest
from src.collectors.base import ICollector, CollectorMeta
from src.storage.events_db import EventsDB
from unittest.mock import MagicMock


class DummyCollector(ICollector):
    @classmethod
    def metadata(cls) -> CollectorMeta:
        return CollectorMeta(
            name="dummy", display_name="Dummy", category="core",
            env_vars=["DUMMY_PATH"], requires=["dummy_bin"],
            event_sources=["dummy"], default_enabled=True,
        )

    def collect(self) -> int:
        return 42


class TestICollector:
    def test_metadata(self):
        meta = DummyCollector.metadata()
        assert meta.name == "dummy"
        assert meta.category == "core"
        assert meta.default_enabled is True

    def test_collect(self):
        db = MagicMock(spec=EventsDB)
        c = DummyCollector(db=db)
        assert c.collect() == 42

    def test_collect_with_metrics(self):
        db = MagicMock(spec=EventsDB)
        c = DummyCollector(db=db)
        result = c.collect_with_metrics()
        assert result == 42
        assert db.write_log.called

    def test_preflight_default(self):
        db = MagicMock(spec=EventsDB)
        c = DummyCollector(db=db)
        ok, reason = c.preflight()
        assert ok is True


# tests/collectors/test_errors_retry.py
import pytest
from src.collectors.errors import TransientError, PermanentError
from src.collectors.retry import with_retry


class TestErrors:
    def test_transient_is_retryable(self):
        e = TransientError("TIMEOUT", "网络超时")
        assert e.retryable is True

    def test_permanent_not_retryable(self):
        e = PermanentError("NOT_FOUND", "路径不存在")
        assert e.retryable is False


class TestRetry:
    def test_success_no_retry(self):
        calls = []
        def fn():
            calls.append(1)
            return "ok"
        result = with_retry(fn, max_retries=3)
        assert result == "ok"
        assert len(calls) == 1

    def test_transient_retry_then_success(self):
        attempts = []
        def fn():
            attempts.append(1)
            if len(attempts) < 3:
                raise TransientError("TIMEOUT", "timeout")
            return "ok"
        result = with_retry(fn, max_retries=3, base_delay=0.01)
        assert result == "ok"
        assert len(attempts) == 3

    def test_permanent_no_retry(self):
        def fn():
            raise PermanentError("NOT_FOUND", "/bad/path")
        with pytest.raises(PermanentError):
            with_retry(fn, max_retries=3, base_delay=0.01)

    def test_transient_exhausted(self):
        def fn():
            raise TransientError("LOCK", "file locked")
        with pytest.raises(TransientError):
            with_retry(fn, max_retries=2, base_delay=0.01)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/collectors/test_base.py tests/collectors/test_errors_retry.py -v`
Expected: ImportError

- [ ] **Step 3: 实现 base.py, errors.py, retry.py**

```python
# src/collectors/base.py
"""
ICollector 协议 — 所有采集器的统一基类。
灵感：OpenCLI 的 adapter interface + metadata 声明。
"""
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from src.storage.events_db import EventsDB


COLLECTOR_TIMEOUTS = {
    "subprocess": int(os.environ.get("COLLECTOR_TIMEOUT_SUBPROCESS", "30")),
    "http": int(os.environ.get("COLLECTOR_TIMEOUT_HTTP", "10")),
    "file_io": int(os.environ.get("COLLECTOR_TIMEOUT_FILE", "5")),
}


@dataclass
class CollectorMeta:
    """采集器自我描述。"""
    name: str
    display_name: str
    category: str                      # "core" | "optional" | "experimental"
    env_vars: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    event_sources: list[str] = field(default_factory=list)
    default_enabled: bool = True


class ICollector(ABC):
    """采集器统一协议。"""

    def __init__(self, db: EventsDB, **kwargs):
        self.db = db
        self.log = logging.getLogger(f"collector.{self.metadata().name}")

    @classmethod
    @abstractmethod
    def metadata(cls) -> CollectorMeta:
        ...

    @abstractmethod
    def collect(self) -> int:
        ...

    def preflight(self) -> tuple[bool, str]:
        return True, "ok"

    def collect_with_metrics(self) -> int:
        """带日志和计时的采集包装器。"""
        meta = self.metadata()
        self.log.info("starting collection")
        t0 = time.time()

        try:
            count = self.collect()
            elapsed = time.time() - t0
            self.log.info(f"done: {count} events in {elapsed:.1f}s")
            self.db.write_log(
                f"[{meta.name}] {count} events, {elapsed:.1f}s",
                "INFO", f"collector.{meta.name}",
            )
            return count
        except Exception as e:
            elapsed = time.time() - t0
            self.log.error(f"failed after {elapsed:.1f}s: {e}")
            self.db.write_log(
                f"[{meta.name}] FAILED: {e}",
                "ERROR", f"collector.{meta.name}",
            )
            return -1
```

```python
# src/collectors/errors.py
"""采集器统一错误层级。灵感：OpenCLI 的 CliError (code + hint)。"""


class CollectorError(Exception):
    code: str = "UNKNOWN"
    hint: str = ""
    retryable: bool = False

    def __init__(self, code: str = None, hint: str = None):
        self.code = code or self.__class__.code
        self.hint = hint or self.__class__.hint
        super().__init__(f"[{self.code}] {self.hint}")


class TransientError(CollectorError):
    retryable = True


class PermanentError(CollectorError):
    retryable = False
```

```python
# src/collectors/retry.py
"""重试策略。灵感：OpenCLI 的 daemon-client 3 次重试。"""
import logging
import random
import time

from src.collectors.errors import TransientError, PermanentError

log = logging.getLogger(__name__)


def with_retry(fn, max_retries=3, base_delay=0.5, max_delay=10.0):
    """指数退避重试。仅对 TransientError 重试。"""
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except TransientError as e:
            last_error = e
            if attempt == max_retries:
                raise
            delay = min(base_delay * (2 ** attempt), max_delay)
            delay *= 0.8 + random.random() * 0.4
            log.warning(f"retry: attempt {attempt+1}/{max_retries}, "
                        f"retrying in {delay:.1f}s: {e.code}")
            time.sleep(delay)
        except PermanentError:
            raise
    raise last_error
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/collectors/test_base.py tests/collectors/test_errors_retry.py -v`
Expected: All passed

- [ ] **Step 5: Commit**

```bash
git add src/collectors/base.py src/collectors/errors.py src/collectors/retry.py tests/collectors/test_base.py tests/collectors/test_errors_retry.py
git commit -m "feat(collectors): add ICollector protocol, error hierarchy, and retry"
```

---

### Task B2: 采集器注册表 + 自动发现

**Files:**
- Create: `src/collectors/registry.py`
- Create: `tests/collectors/test_registry.py`

- [ ] **Step 1: 创建测试**

```python
# tests/collectors/test_registry.py
import pytest
from unittest.mock import MagicMock, patch
from src.collectors.registry import discover_collectors, build_enabled_collectors
from src.collectors.base import ICollector, CollectorMeta


class TestDiscovery:
    def test_discover_finds_collectors(self):
        """应能发现 src/collectors/ 下的 ICollector 子类。"""
        registry = discover_collectors()
        # 在迁移完成后，应该至少发现 9 个
        assert isinstance(registry, dict)
        # 至少 base.py 里的 ICollector 不应被发现（它是 ABC）
        assert "ICollector" not in str(registry.values())

    def test_build_enabled_respects_env(self):
        """COLLECTOR_XXX=false 应禁用对应采集器。"""
        db = MagicMock()
        with patch.dict('os.environ', {'COLLECTOR_STEAM': 'false'}):
            enabled = build_enabled_collectors(db)
            names = [name for name, _ in enabled]
            assert "steam" not in names

    def test_build_enabled_default(self):
        """default_enabled=True 的 core 采集器应默认启用。"""
        db = MagicMock()
        enabled = build_enabled_collectors(db)
        names = [name for name, _ in enabled]
        # 迁移完成后 git 应该在列表中
        # 目前可能还没有迁移的采集器，所以只测 enabled 是个 list
        assert isinstance(enabled, list)
```

- [ ] **Step 2: 运行测试确认失败**

- [ ] **Step 3: 实现 registry.py**

```python
# src/collectors/registry.py
"""
采集器注册表 — 动态扫描 + 自动发现。
灵感：OpenCLI 的 Manifest 预编译 + discovery.ts。
"""
import importlib
import logging
import os
from pathlib import Path

from src.collectors.base import ICollector, CollectorMeta

log = logging.getLogger(__name__)
_COLLECTORS_DIR = Path(__file__).parent


def discover_collectors() -> dict[str, type[ICollector]]:
    """扫描 src/collectors/*_collector.py，找到 ICollector 子类。"""
    registry = {}
    for py_file in sorted(_COLLECTORS_DIR.glob("*_collector.py")):
        module_name = f"src.collectors.{py_file.stem}"
        try:
            module = importlib.import_module(module_name)
        except Exception as e:
            log.warning(f"registry: failed to import {module_name}: {e}")
            continue

        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (isinstance(attr, type)
                    and issubclass(attr, ICollector)
                    and attr is not ICollector
                    and hasattr(attr, 'metadata')):
                try:
                    meta = attr.metadata()
                    registry[meta.name] = attr
                    log.debug(f"registry: discovered {meta.name}")
                except Exception as e:
                    log.warning(f"registry: {attr_name}.metadata() failed: {e}")
    return registry


def build_enabled_collectors(db, **kwargs) -> list[tuple[str, ICollector]]:
    """构建启用的采集器实例列表。替代 scheduler._build_collectors()。"""
    registry = discover_collectors()
    enabled = []

    for name, cls in registry.items():
        meta = cls.metadata()

        env_key = f"COLLECTOR_{name.upper()}"
        env_val = os.environ.get(env_key)
        if env_val is not None:
            is_on = env_val.lower() in ("true", "1", "yes")
        else:
            is_on = meta.default_enabled

        if not is_on:
            continue

        try:
            instance = cls(db=db)
            enabled.append((name, instance))
        except Exception as e:
            log.error(f"registry: {name} init failed: {e}")

    log.info(f"registry: {len(enabled)}/{len(registry)} collectors enabled")
    return enabled
```

- [ ] **Step 4: 运行测试确认通过**

- [ ] **Step 5: Commit**

```bash
git add src/collectors/registry.py tests/collectors/test_registry.py
git commit -m "feat(collectors): add auto-discovery registry"
```

---

### Task B3: 迁移全部 9 个采集器到 ICollector 协议

**Files:**
- Modify: `src/collectors/git_collector.py`
- Modify: `src/collectors/browser_collector.py`
- Modify: `src/collectors/claude_collector.py`
- Modify: `src/collectors/steam_collector.py`
- Modify: `src/collectors/youtube_music_collector.py`
- Modify: `src/collectors/qqmusic_collector.py`
- Modify: `src/collectors/codebase_collector.py`
- Modify: `src/collectors/vscode_collector.py`
- Modify: `src/collectors/network_collector.py`

每个采集器的改动模式完全相同：
1. 加 `from src.collectors.base import ICollector, CollectorMeta`
2. 类声明改为 `class XxxCollector(ICollector):`
3. 加 `@classmethod def metadata(cls) -> CollectorMeta:` 返回对应元数据
4. `__init__` 加 `super().__init__(db)`
5. **不改动 collect() 内部逻辑**

- [ ] **Step 1: 迁移全部 9 个采集器**

每个采集器需要添加的 metadata：

| Collector | name | category | default_enabled | env_vars | requires |
|-----------|------|----------|----------------|----------|----------|
| GitCollector | git | core | True | GIT_REPOS_ROOT, GIT_PATHS | git |
| BrowserCollector | browser | core | True | CHROME_HISTORY_ROOT | - |
| ClaudeCollector | claude | core | True | CLAUDE_HOME | - |
| SteamCollector | steam | optional | False | STEAM_PATH | steam |
| YouTubeMusicCollector | youtube_music | optional | False | CHROME_HISTORY_ROOT | - |
| QQMusicCollector | qqmusic | optional | False | QQMUSIC_DATA_PATH | - |
| CodebaseCollector | codebase | core | True | ORCHESTRATOR_ROOT | git |
| VSCodeCollector | vscode | core | True | VSCODE_DATA_PATH | - |
| NetworkCollector | network | core | True | - | - |

- [ ] **Step 2: 运行现有测试确认不破坏**

Run: `python -m pytest tests/collectors/ -v`
Expected: 所有现有测试仍然通过

- [ ] **Step 3: 运行 registry 发现测试确认 9 个采集器都能被发现**

Run: `python -m pytest tests/collectors/test_registry.py -v`

- [ ] **Step 4: Commit**

```bash
git add src/collectors/
git commit -m "refactor(collectors): migrate all 9 collectors to ICollector protocol"
```

---

### Task B4: 声誉系统

**Files:**
- Create: `src/collectors/reputation.py`
- Create: `tests/collectors/test_reputation.py`
- Modify: `src/storage/events_db.py` (新表)

- [ ] **Step 1: events_db.py 添加 collector_reputation 表**

在 `_init_tables()` 的 `executescript` 中添加：

```sql
CREATE TABLE IF NOT EXISTS collector_reputation (
    name TEXT PRIMARY KEY,
    data TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);
```

- [ ] **Step 2: 创建测试**

```python
# tests/collectors/test_reputation.py
import pytest
from unittest.mock import MagicMock
from src.collectors.reputation import ReputationTracker


class TestReputation:
    def setup_method(self):
        self.db = MagicMock()
        self.db.execute_sql = MagicMock(return_value=[])
        self.tracker = ReputationTracker(self.db)

    def test_update_success(self):
        self.tracker.update("git", event_count=15)
        rep = self.tracker._cache["git"]
        assert rep["total_runs"] == 1
        assert rep["successful_runs"] == 1
        assert rep["streak"] == 1

    def test_update_failure(self):
        self.tracker.update("steam", event_count=-1, error="path not found")
        rep = self.tracker._cache["steam"]
        assert rep["streak"] == -1
        assert rep["last_failure_reason"] == "path not found"

    def test_health_score_good(self):
        for _ in range(10):
            self.tracker.update("git", event_count=20)
        rep = self.tracker._cache["git"]
        assert rep["health_score"] > 0.8

    def test_should_skip_after_5_failures(self):
        for _ in range(5):
            self.tracker.update("steam", event_count=-1, error="broken")
        skip, reason = self.tracker.should_skip("steam")
        assert skip is True
        assert "circuit" in reason.lower() or "consecutive" in reason.lower()

    def test_should_not_skip_healthy(self):
        self.tracker.update("git", event_count=10)
        skip, _ = self.tracker.should_skip("git")
        assert skip is False
```

- [ ] **Step 3: 实现 reputation.py**

```python
# src/collectors/reputation.py
"""
采集器声誉系统 — 追踪每个采集器的长期健康状况。
灵感：OpenCLI 的 AI 自助闭环评估 + Strategy Cascade 的信心度。
"""
import json
import logging
from datetime import datetime, timezone, timedelta

from src.storage.events_db import EventsDB

log = logging.getLogger(__name__)

CIRCUIT_OPEN_THRESHOLD = 5   # 连续失败次数
CIRCUIT_OPEN_DURATION = 3600  # 熔断时间（秒）


class ReputationTracker:
    def __init__(self, db: EventsDB):
        self.db = db
        self._cache: dict[str, dict] = {}

    def _default_rep(self, name: str) -> dict:
        return {
            "name": name,
            "total_runs": 0,
            "successful_runs": 0,
            "total_events": 0,
            "avg_events_per_run": 0.0,
            "last_success": "",
            "last_failure": "",
            "last_failure_reason": "",
            "streak": 0,
            "health_score": 1.0,
        }

    def _load(self, name: str) -> dict:
        if name in self._cache:
            return self._cache[name]
        try:
            with self.db._connect() as conn:
                row = conn.execute(
                    "SELECT data FROM collector_reputation WHERE name = ?", (name,)
                ).fetchone()
                if row:
                    self._cache[name] = json.loads(row["data"])
                    return self._cache[name]
        except Exception:
            pass
        self._cache[name] = self._default_rep(name)
        return self._cache[name]

    def _save(self, name: str):
        rep = self._cache.get(name, self._default_rep(name))
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self.db._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO collector_reputation (name, data, updated_at) VALUES (?, ?, ?)",
                    (name, json.dumps(rep, ensure_ascii=False), now),
                )
        except Exception as e:
            log.warning(f"reputation: failed to save {name}: {e}")

    def update(self, name: str, event_count: int, error: str = None):
        rep = self._load(name)
        now = datetime.now(timezone.utc).isoformat()
        rep["total_runs"] += 1

        if event_count >= 0:
            rep["successful_runs"] += 1
            rep["total_events"] += event_count
            rep["avg_events_per_run"] = rep["total_events"] / rep["successful_runs"]
            rep["last_success"] = now
            rep["streak"] = max(rep["streak"] + 1, 1)
        else:
            rep["last_failure"] = now
            rep["last_failure_reason"] = error or "unknown"
            rep["streak"] = min(rep["streak"] - 1, -1)

        rep["health_score"] = self._calc_health(rep)
        self._cache[name] = rep
        self._save(name)

    def _calc_health(self, rep: dict) -> float:
        rate = rep["successful_runs"] / max(rep["total_runs"], 1)
        volume = min(rep["avg_events_per_run"] / 10.0, 1.0)
        trend = 1.0 if rep["streak"] > 0 else max(0.0, 1.0 + rep["streak"] * 0.1)
        return round(rate * 0.6 + volume * 0.2 + trend * 0.2, 3)

    def should_skip(self, name: str) -> tuple[bool, str]:
        rep = self._load(name)
        if rep["streak"] <= -CIRCUIT_OPEN_THRESHOLD:
            if rep["last_failure"]:
                try:
                    last = datetime.fromisoformat(rep["last_failure"])
                    if (datetime.now(timezone.utc) - last).total_seconds() < CIRCUIT_OPEN_DURATION:
                        return True, f"circuit open: {-rep['streak']} consecutive failures"
                except (ValueError, TypeError):
                    pass
        return False, ""

    def get_all(self) -> list[dict]:
        try:
            with self.db._connect() as conn:
                rows = conn.execute("SELECT data FROM collector_reputation ORDER BY name").fetchall()
                return [json.loads(r["data"]) for r in rows]
        except Exception:
            return list(self._cache.values())
```

- [ ] **Step 4: 运行测试确认通过**

- [ ] **Step 5: Commit**

```bash
git add src/collectors/reputation.py tests/collectors/test_reputation.py src/storage/events_db.py
git commit -m "feat(collectors): add reputation tracker with circuit breaker"
```

---

### Task B5: scheduler.py 改造 — 并行执行 + 集成

**Files:**
- Modify: `src/scheduler.py`

- [ ] **Step 1: 改造 run_collectors()**

替换现有的 `_build_collectors()` + 顺序 for 循环为 registry + ThreadPoolExecutor：

```python
# 删除旧的 9 个 collector import 和 _build_collectors()
# 替换为：
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from src.collectors.registry import build_enabled_collectors
from src.collectors.reputation import ReputationTracker

MAX_COLLECTOR_WORKERS = int(os.environ.get("COLLECTOR_PARALLEL_WORKERS", "4"))
COLLECTOR_RUN_TIMEOUT = int(os.environ.get("COLLECTOR_RUN_TIMEOUT", "60"))


def run_collectors():
    db = EventsDB(DB_PATH)
    db.write_log("开始采集数据", "INFO", "collector")
    enabled = build_enabled_collectors(db)
    results = {}
    reputation = ReputationTracker(db)

    def _run_one(name, collector):
        skip, reason = reputation.should_skip(name)
        if skip:
            log.info(f"collector [{name}] skipped: {reason}")
            return name, 0, reason
        t0 = time.time()
        try:
            count = collector.collect_with_metrics()
            return name, count, None
        except Exception as e:
            elapsed = time.time() - t0
            log.error(f"collector [{name}] failed after {elapsed:.1f}s: {e}")
            return name, -1, str(e)

    with ThreadPoolExecutor(max_workers=MAX_COLLECTOR_WORKERS) as pool:
        futures = {
            pool.submit(_run_one, name, collector): name
            for name, collector in enabled
        }
        for future in as_completed(futures, timeout=COLLECTOR_RUN_TIMEOUT):
            fname = futures[future]
            try:
                name, count, error = future.result()
                results[name] = count
                reputation.update(name, count, error)
            except Exception as e:
                results[fname] = -1
                reputation.update(fname, -1, str(e))

    # 日志汇总
    ok = [k for k, v in results.items() if v >= 0]
    fail = [k for k, v in results.items() if v < 0]
    msg = f"采集完成：{', '.join(ok)} 各 {[results[k] for k in ok]} 条"
    if fail:
        msg += f"；失败：{', '.join(fail)}"
    db.write_log(msg, "INFO", "collector")
    log.info(f"Collection done: {results}")

    # burst detection + health check（保持原有逻辑）
    # ...（不变）
```

- [ ] **Step 2: 保留 `_is_collector_enabled()` 作为向后兼容（标记 deprecated）**

```python
def _is_collector_enabled(name):
    """DEPRECATED: 由 registry.build_enabled_collectors() 替代。保留以防外部调用。"""
    # ... 保持原有逻辑不变
```

- [ ] **Step 3: 运行完整测试套件**

Run: `python -m pytest tests/ -v --timeout=60`
Expected: 全部通过

- [ ] **Step 4: Commit**

```bash
git add src/scheduler.py
git commit -m "feat(scheduler): parallel collectors via registry + reputation"
```

---

### Task B6: Dashboard API — 声誉数据 + 采集器控制

**Files:**
- Modify: `dashboard/server.js`

- [ ] **Step 1: 添加声誉 API**

```javascript
// GET /api/collectors/reputation — 所有采集器的健康状况
app.get('/api/collectors/reputation', (req, res) => {
  const db = getDb();
  if (!db) return res.status(503).json({ error: 'db not available' });
  try {
    const rows = dbAll(db, 'SELECT name, data, updated_at FROM collector_reputation ORDER BY name');
    const result = rows.map(r => {
      try { return { ...JSON.parse(r.data), updated_at: r.updated_at }; }
      catch { return { name: r.name, error: 'parse failed' }; }
    });
    res.json(result);
  } catch (e) {
    res.status(500).json({ error: e.message });
  } finally { db.close(); }
});

// POST /api/collectors/:name/trigger — 手动触发单个采集器
app.post('/api/collectors/:name/trigger', (req, res) => {
  const name = req.params.name;
  const proc = spawn('python3', ['-c', `
import sys, json
sys.path.insert(0, '/orchestrator')
from src.storage.events_db import EventsDB
from src.collectors.registry import discover_collectors

db = EventsDB('/orchestrator/data/events.db')
registry = discover_collectors()
name = '${name}'
if name not in registry:
    print(json.dumps({'error': f'collector {name} not found'}))
    sys.exit(0)

cls = registry[name]
collector = cls(db=db)
count = collector.collect_with_metrics()
print(json.dumps({'name': name, 'count': count}))
  `]);

  let out = '';
  proc.stdout.on('data', d => { out += d; });
  proc.on('close', () => {
    try { res.json(JSON.parse(out)); }
    catch { res.status(500).json({ error: out }); }
  });
});
```

- [ ] **Step 2: Commit**

```bash
git add dashboard/server.js
git commit -m "feat(dashboard): add collector reputation API and manual trigger"
```

---

## 验证清单

- [ ] **主线 A 集成测试**: 在 Python REPL 中执行 `from src.gateway.dispatcher import dispatch_from_text; print(dispatch_from_text("帮我看看为什么 Steam 采集器是 0 数据"))`，验证任务被创建
- [ ] **主线 B 集成测试**: 运行 `run_collectors()`，验证并行执行 + 声誉数据写入 DB
- [ ] **全量回归**: `python -m pytest tests/ -v`
- [ ] **Docker 构建**: `docker compose build && docker compose up -d` 确认容器正常启动
