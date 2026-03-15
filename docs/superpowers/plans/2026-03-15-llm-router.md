# LLM Router Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Orchestrator 的 Governor 审查和 DebtScanner 分析走本地 Ollama（qwen3:32b），保留深度分析在 Claude，实现混合推理。

**Architecture:** 新增 `src/llm_router.py` 作为统一路由层，所有 LLM 调用通过它决定走 Ollama 还是 Claude CLI。失败自动 fallback。环境变量可手动覆盖。

**Tech Stack:** Python 3.14+, urllib (stdlib), Ollama REST API, Claude CLI

**Spec:** `docs/superpowers/specs/2026-03-15-llm-router-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `src/llm_router.py` | Create | 路由表、Ollama HTTP 客户端、Claude CLI 封装、fallback、日志 |
| `tests/test_llm_router.py` | Create | Router 单元测试（mock HTTP/subprocess） |
| `src/governor.py` | Modify L107-143 | scrutinize() 改用 router |
| `src/debt_scanner.py` | Modify L151-201 | _analyze_one_batch() 改用 router |
| `docker-compose.yml` | Modify | 加 extra_hosts + OLLAMA_HOST |

---

## Chunk 1: LLM Router 核心模块

### Task 1: 创建 llm_router.py — 路由表和 Ollama 客户端

**Files:**
- Create: `src/llm_router.py`
- Create: `tests/test_llm_router.py`

- [ ] **Step 1: 写 Ollama 调用的 failing test**

```python
# tests/test_llm_router.py
import json
from unittest.mock import patch, MagicMock
from src.llm_router import LLMRouter, ROUTES

def test_ollama_generate_success():
    """Ollama 正常返回时，generate() 应返回模型输出文本。"""
    router = LLMRouter()
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = json.dumps({"response": "VERDICT: APPROVE\nREASON: looks good"}).encode()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
        result = router.generate("test prompt", task_type="scrutiny")

    assert "VERDICT: APPROVE" in result
    mock_urlopen.assert_called_once()

def test_ollama_generate_fallback_on_timeout():
    """Ollama 超时时，应 fallback 到 Claude CLI。"""
    import urllib.error
    router = LLMRouter()

    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
        with patch.object(router, "_claude_generate", return_value="VERDICT: APPROVE\nREASON: fallback") as mock_claude:
            result = router.generate("test prompt", task_type="scrutiny")

    assert "VERDICT: APPROVE" in result
    mock_claude.assert_called_once()

def test_ollama_generate_fallback_on_garbage():
    """Ollama 返回少于 10 字符时，应 fallback 到 Claude。"""
    router = LLMRouter()
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = json.dumps({"response": ""}).encode()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_response):
        with patch.object(router, "_claude_generate", return_value="VERDICT: REJECT\nREASON: fallback") as mock_claude:
            result = router.generate("test prompt", task_type="scrutiny")

    assert "fallback" in result
    mock_claude.assert_called_once()

def test_force_claude_override():
    """LLM_FORCE_CLAUDE 环境变量应强制指定任务类型走 Claude。"""
    router = LLMRouter()

    with patch.dict("os.environ", {"LLM_FORCE_CLAUDE": "scrutiny,debt_scan"}):
        with patch.object(router, "_claude_generate", return_value="forced claude") as mock_claude:
            result = router.generate("test", task_type="scrutiny")

    assert result == "forced claude"
    mock_claude.assert_called_once()

def test_claude_task_types_always_use_claude():
    """deep_analysis 和 profile 类型应始终走 Claude，不走 Ollama。"""
    router = LLMRouter()

    with patch.object(router, "_claude_generate", return_value="claude result") as mock_claude:
        result = router.generate("test", task_type="deep_analysis")

    assert result == "claude result"
    mock_claude.assert_called_once()

def test_routes_have_required_keys():
    """每条路由必须有 backend, model, timeout。"""
    for task_type, route in ROUTES.items():
        assert "backend" in route, f"{task_type} missing backend"
        assert "model" in route, f"{task_type} missing model"
        assert "timeout" in route, f"{task_type} missing timeout"

def test_unknown_task_type_raises():
    """未知的 task_type 应抛出 ValueError。"""
    import pytest
    router = LLMRouter()
    with pytest.raises(ValueError, match="Unknown task_type"):
        router.generate("test", task_type="nonexistent")

def test_ollama_unavailable_skips_to_claude():
    """启动探测 Ollama 不可达时，应直接走 Claude 不再尝试 HTTP。"""
    router = LLMRouter()
    router._ollama_available = False  # 模拟探测失败

    with patch.object(router, "_claude_generate", return_value="VERDICT: APPROVE\nREASON: skipped") as mock_claude:
        with patch("urllib.request.urlopen") as mock_urlopen:
            result = router.generate("test", task_type="scrutiny")

    mock_urlopen.assert_not_called()  # 不应尝试 Ollama
    mock_claude.assert_called_once()
    assert "APPROVE" in result
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd D:\Users\Administrator\Documents\GitHub\orchestrator && python -m pytest tests/test_llm_router.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.llm_router'`

- [ ] **Step 3: 实现 llm_router.py**

```python
# src/llm_router.py
"""
LLM Router — 统一路由层。
按 task_type 决定走 Ollama（本地）还是 Claude CLI（云端）。
Ollama 失败自动 fallback 到 Claude。
"""
import json
import logging
import os
import subprocess
import time
import urllib.request
import urllib.error

log = logging.getLogger(__name__)

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

ROUTES = {
    "scrutiny":      {"backend": "ollama", "model": "qwen3:32b", "timeout": 20,  "fallback": "claude", "fallback_model": "claude-haiku-4-5-20251001"},
    "debt_scan":     {"backend": "ollama", "model": "qwen3:32b", "timeout": 60,  "fallback": "claude", "fallback_model": "claude-haiku-4-5-20251001"},
    "summary":       {"backend": "claude", "model": "claude-haiku-4-5-20251001",  "timeout": 120},
    "deep_analysis": {"backend": "claude", "model": "claude-sonnet-4-6",          "timeout": 120},
    "profile":       {"backend": "claude", "model": "claude-sonnet-4-6",          "timeout": 120},
}

MIN_RESPONSE_LEN = 10  # 少于这个字符数视为垃圾输出


class LLMRouter:
    def __init__(self):
        self._ollama_available = None  # lazy probe

    def generate(self, prompt: str, task_type: str,
                 max_tokens: int = 1024, temperature: float = 0.3) -> str:
        """统一入口。根据 task_type 查路由表决定后端。"""
        route = ROUTES.get(task_type)
        if not route:
            raise ValueError(f"Unknown task_type: {task_type}")

        backend = route["backend"]

        # 环境变量强制覆盖
        force_claude = os.environ.get("LLM_FORCE_CLAUDE", "")
        if force_claude and task_type in [t.strip() for t in force_claude.split(",")]:
            backend = "claude"
            log.info(f"router: [force_claude] {task_type} overridden to claude")

        if backend == "ollama":
            return self._ollama_with_fallback(
                prompt, task_type, route, max_tokens, temperature
            )
        else:
            return self._claude_generate(
                prompt, route["model"], route["timeout"], max_tokens
            )

    def _ollama_with_fallback(self, prompt: str, task_type: str, route: dict,
                               max_tokens: int, temperature: float) -> str:
        """尝试 Ollama，失败则 fallback 到 Claude。"""
        # 启动探测发现 Ollama 不可达 → 直接走 Claude
        if self._ollama_available is False:
            log.info(f"router: [skip_ollama] {task_type} -> claude (ollama unavailable)")
            return self._claude_fallback(prompt, task_type, route, max_tokens)

        t0 = time.time()
        try:
            result = self._ollama_generate(
                prompt, route["model"], route["timeout"], max_tokens, temperature
            )
            elapsed = time.time() - t0

            if len(result.strip()) < MIN_RESPONSE_LEN:
                log.warning(f"router: [fallback] {task_type} ollama_garbage ({len(result.strip())} chars) -> claude")
                return self._claude_fallback(prompt, task_type, route, max_tokens)

            log.info(f"router: [ollama] {task_type} {elapsed:.1f}s ok ({len(result)} chars)")
            return result

        except Exception as e:
            elapsed = time.time() - t0
            reason = type(e).__name__
            log.warning(f"router: [fallback] {task_type} ollama_{reason} ({elapsed:.1f}s) -> claude")
            return self._claude_fallback(prompt, task_type, route, max_tokens)

    def _claude_fallback(self, prompt: str, task_type: str, route: dict,
                          max_tokens: int) -> str:
        """Fallback 到 Claude CLI。"""
        fallback_model = route.get("fallback_model", "claude-haiku-4-5-20251001")
        t0 = time.time()
        result = self._claude_generate(prompt, fallback_model, route["timeout"], max_tokens)
        elapsed = time.time() - t0
        log.info(f"router: [claude_fallback] {task_type} {elapsed:.1f}s ok")
        return result

    def _ollama_generate(self, prompt: str, model: str, timeout: int,
                          max_tokens: int, temperature: float) -> str:
        """调 Ollama REST API。"""
        url = f"{OLLAMA_HOST}/api/generate"
        payload = json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }).encode()

        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        return data.get("response", "")

    def _claude_generate(self, prompt: str, model: str, timeout: int,
                          max_tokens: int) -> str:
        """调 Claude CLI（stdin 传 prompt，避免命令行长度限制）。"""
        result = subprocess.run(
            ["claude", "--dangerously-skip-permissions", "--print",
             "--model", model, "-"],
            capture_output=True, text=True,
            timeout=timeout, input=prompt,
        )
        return result.stdout.strip() or result.stderr.strip() or ""

    def check_ollama(self) -> bool:
        """探测 Ollama 是否可达 + 检查所需模型。启动时调用一次。"""
        try:
            url = f"{OLLAMA_HOST}/api/tags"
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read().decode())
            models = [m.get("name", "") for m in data.get("models", [])]
            log.info(f"router: Ollama reachable, models: {models}")
            # 检查路由表中需要的模型是否存在
            needed = {r["model"] for r in ROUTES.values() if r["backend"] == "ollama"}
            for m in needed:
                if not any(m in avail for avail in models):
                    log.warning(f"router: Ollama model '{m}' not found, run: ollama pull {m}")
            self._ollama_available = True
            return True
        except Exception as e:
            log.warning(f"router: Ollama unreachable ({e}), all tasks will use Claude")
            self._ollama_available = False
            return False


# 模块级单例
_router = None

def get_router() -> LLMRouter:
    global _router
    if _router is None:
        _router = LLMRouter()
        _router.check_ollama()
    return _router
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd D:\Users\Administrator\Documents\GitHub\orchestrator && python -m pytest tests/test_llm_router.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/llm_router.py tests/test_llm_router.py
git commit -m "feat: add LLM router with Ollama backend and Claude fallback"
```

---

## Chunk 2: 接入 Governor 和 DebtScanner

### Task 2: Governor.scrutinize() 改用 router

**Files:**
- Modify: `src/governor.py:107-143`

- [ ] **Step 1: 写 Governor 使用 router 的 test**

```python
# tests/test_governor_router.py
from unittest.mock import patch, MagicMock
from src.governor import Governor

def test_scrutinize_uses_router():
    """scrutinize() 应通过 LLMRouter 而不是直接调 subprocess。"""
    mock_db = MagicMock()
    gov = Governor(db=mock_db)

    task = {
        "action": "test action",
        "reason": "test reason",
        "spec": {
            "project": "orchestrator",
            "cwd": "/orchestrator",
            "summary": "test summary",
            "problem": "test problem",
            "observation": "test obs",
            "expected": "test expected",
        }
    }

    with patch("src.governor.get_router") as mock_get_router:
        mock_router = MagicMock()
        mock_router.generate.return_value = "VERDICT: APPROVE\nREASON: looks good"
        mock_get_router.return_value = mock_router

        approved, reason = gov.scrutinize(1, task)

    assert approved is True
    assert "looks good" in reason
    mock_router.generate.assert_called_once()
    call_kwargs = mock_router.generate.call_args
    assert call_kwargs[1]["task_type"] == "scrutiny" or call_kwargs[0][1] == "scrutiny"

def test_scrutinize_reject():
    """scrutinize() 应能正确解析 REJECT 响应。"""
    mock_db = MagicMock()
    gov = Governor(db=mock_db)
    task = {"action": "delete everything", "reason": "yolo", "spec": {"project": "orchestrator", "cwd": "/orchestrator", "summary": "bad", "problem": "", "observation": "", "expected": ""}}

    with patch("src.governor.get_router") as mock_get_router:
        mock_router = MagicMock()
        mock_router.generate.return_value = "VERDICT: REJECT\nREASON: too dangerous"
        mock_get_router.return_value = mock_router

        approved, reason = gov.scrutinize(1, task)

    assert approved is False
    assert "dangerous" in reason
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_governor_router.py -v`
Expected: FAIL — `ImportError` (get_router not imported in governor.py)

- [ ] **Step 3: 修改 governor.py — scrutinize() 改用 router**

在 `src/governor.py` 中：

1. 添加 import：`from src.llm_router import get_router`
2. 删除死代码：`SCRUTINY_MODEL = "claude-haiku-4-5-20251001"`（L77，已移入路由表）
3. 替换 `scrutinize()` 方法中 L127-135 的 subprocess 调用：

```python
# 旧代码（删除）:
#   result = subprocess.run(
#       ["claude", "--dangerously-skip-permissions", "--print",
#        "--model", SCRUTINY_MODEL, prompt],
#       capture_output=True, text=True, timeout=30,
#       stdin=subprocess.DEVNULL,
#   )
#   text = (result.stdout.strip() or result.stderr.strip() or "")

# 新代码:
    text = get_router().generate(prompt, task_type="scrutiny")
```

完整替换后的 `scrutinize()` 方法：

```python
def scrutinize(self, task_id: int, task: dict) -> tuple[bool, str]:
    """门下省审查：快速判断任务是否值得执行。返回 (approved, reason)。"""
    spec = task.get("spec", {})
    project_name = spec.get("project", "orchestrator")
    task_cwd = spec.get("cwd", "")
    if not task_cwd:
        from src.project_registry import resolve_project
        task_cwd = resolve_project(project_name) or os.environ.get("ORCHESTRATOR_ROOT", "/orchestrator")

    prompt = SCRUTINY_PROMPT.format(
        summary=spec.get("summary", task.get("action", "")),
        project=project_name,
        cwd=task_cwd,
        problem=spec.get("problem", ""),
        observation=spec.get("observation", ""),
        expected=spec.get("expected", ""),
        action=task.get("action", ""),
        reason=task.get("reason", ""),
    )
    try:
        text = get_router().generate(prompt, task_type="scrutiny")
        approved = "VERDICT: APPROVE" in text
        reason_line = next((l for l in text.splitlines() if l.startswith("REASON:")), "")
        reason = reason_line.replace("REASON:", "").strip() or text[:80]
        log.info(f"Governor: scrutiny task #{task_id} → {'APPROVE' if approved else 'REJECT'}: {reason}")
        return approved, reason
    except Exception as e:
        log.warning(f"Governor: scrutiny failed ({e}), defaulting to APPROVE")
        return True, f"审查异常，默认放行：{e}"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_governor_router.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/governor.py tests/test_governor_router.py
git commit -m "feat: Governor scrutiny uses LLM router (Ollama with Claude fallback)"
```

---

### Task 3: DebtScanner._analyze_one_batch() 改用 router

**Files:**
- Modify: `src/debt_scanner.py:151-201`

- [ ] **Step 1: 写 DebtScanner 使用 router 的 test**

```python
# tests/test_debt_scanner_router.py
import json
from unittest.mock import patch, MagicMock
from src.debt_scanner import DebtScanner

def test_analyze_batch_uses_router():
    """_analyze_one_batch() 应通过 LLMRouter 而不是直接调 subprocess。"""
    mock_db = MagicMock()
    scanner = DebtScanner(db=mock_db)

    batch = [{
        "session_id": "abc123",
        "project": "test-project",
        "slug": "test-slug",
        "total_messages": 10,
        "key_messages": ["found a bug in the parser", "will fix later"],
        "last_assistant": "I'll look into it next time",
    }]

    fake_response = json.dumps([{
        "session_id": "test-slug",
        "project": "test-project",
        "summary": "parser bug未修复",
        "severity": "medium",
        "context": "found a bug in the parser",
    }])

    with patch("src.debt_scanner.get_router") as mock_get_router:
        mock_router = MagicMock()
        mock_router.generate.return_value = fake_response
        mock_get_router.return_value = mock_router

        result = scanner._analyze_one_batch(batch)

    assert len(result) == 1
    assert result[0]["summary"] == "parser bug未修复"
    mock_router.generate.assert_called_once()
    call_args = mock_router.generate.call_args
    assert call_args[1]["task_type"] == "debt_scan" or call_args[0][1] == "debt_scan"

def test_analyze_batch_handles_markdown_fences():
    """响应被 markdown fence 包裹时应正常解析。"""
    mock_db = MagicMock()
    scanner = DebtScanner(db=mock_db)

    batch = [{"session_id": "x", "project": "p", "slug": "s", "total_messages": 5,
              "key_messages": ["error happened"], "last_assistant": "noted"}]

    fenced = '```json\n[{"session_id":"s","project":"p","summary":"bug","severity":"low","context":"err"}]\n```'

    with patch("src.debt_scanner.get_router") as mock_get_router:
        mock_router = MagicMock()
        mock_router.generate.return_value = fenced
        mock_get_router.return_value = mock_router

        result = scanner._analyze_one_batch(batch)

    assert len(result) == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_debt_scanner_router.py -v`
Expected: FAIL — `ImportError` (get_router not imported in debt_scanner.py)

- [ ] **Step 3: 修改 debt_scanner.py — _analyze_one_batch() 改用 router**

在 `src/debt_scanner.py` 中：

1. 添加 import：`from src.llm_router import get_router`
2. 删除死代码：`import subprocess`（L12）和 `MODEL = "claude-haiku-4-5-20251001"`（L32）— 已移入路由表
3. 替换 `_analyze_one_batch()` 中 L187-198 的 subprocess 调用：

```python
# 旧代码（删除）:
#   result = subprocess.run(
#       ["claude", "--dangerously-skip-permissions", "--print",
#        "--model", MODEL, "-"],
#       capture_output=True, text=True, timeout=120,
#       input=prompt,
#   )
#   text = result.stdout.strip()

# 新代码:
    text = get_router().generate(prompt, task_type="debt_scan")
```

完整替换后的 `_analyze_one_batch()` 方法：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_debt_scanner_router.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/debt_scanner.py tests/test_debt_scanner_router.py
git commit -m "feat: DebtScanner uses LLM router (Ollama with Claude fallback)"
```

---

## Chunk 3: Docker 集成和端到端验证

### Task 4: docker-compose.yml 加 Ollama 访问

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: 在 environment 块加 OLLAMA_HOST**

在 `docker-compose.yml` 的 `environment` 部分末尾添加：

```yaml
      # Local LLM via Ollama on host
      - OLLAMA_HOST=http://host.docker.internal:11434
```

- [ ] **Step 2: 在 services.orchestrator 下加 extra_hosts**

在 `restart: "no"` 之后添加：

```yaml
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: expose host Ollama to container via extra_hosts"
```

---

### Task 5: 端到端验证

- [ ] **Step 1: 确认 Ollama 在宿主机运行且 qwen3:32b 可用**

Run: `ollama list | grep qwen3:32b`
Expected: 看到 `qwen3:32b` 条目

- [ ] **Step 2: 本地运行全部测试**

Run: `cd D:\Users\Administrator\Documents\GitHub\orchestrator && python -m pytest tests/test_llm_router.py tests/test_governor_router.py tests/test_debt_scanner_router.py -v`
Expected: 12 passed

- [ ] **Step 3: 本地快速验证 Ollama 实际调用**

```bash
python -c "
from src.llm_router import get_router
router = get_router()
result = router.generate('Reply with exactly: VERDICT: APPROVE\nREASON: test ok', task_type='scrutiny')
print(repr(result[:200]))
assert len(result) > 10, 'Response too short'
print('OK: Ollama responded')
"
```

Expected: 看到 Ollama 实际响应文本，`router:` 日志行

- [ ] **Step 4: 重建并启动容器**

Run: `cd D:\Users\Administrator\Documents\GitHub\orchestrator && docker compose down && docker compose build && docker compose up -d`

- [ ] **Step 5: 验证容器内 Ollama 可达**

Run: `docker compose exec orchestrator python -c "from src.llm_router import get_router; r = get_router(); print('Ollama:', r._ollama_available)"`
Expected: `Ollama: True`

- [ ] **Step 6: 检查日志确认路由生效**

等待下一次 analysis 周期（或手动触发），然后：

Run: `docker compose logs --tail=50 | grep "router:"`
Expected: 看到 `router: [ollama] scrutiny` 或 `router: [ollama] debt_scan` 日志行

- [ ] **Step 7: Final commit**

```bash
git add -A
git commit -m "feat: LLM Router complete — Governor scrutiny and DebtScanner use local Ollama"
```
