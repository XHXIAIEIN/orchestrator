# Plan: learn-likecc P0 — Model Routes + Config Hot Reload + In-Process Observatory

## Goal

Implement P0-1 (per-model route table), P0-2 (settings hot reload with triple debounce), and P0-3 (in-process HTTP observatory) from R82-learn-likecc steal; `pytest -k "model_routes or config_watcher or observatory" -q` passes green, `curl 127.0.0.1:4310/api/sessions/current` returns valid JSON while Orchestrator is running.

## Context

Source: `docs/steal/R82-learn-likecc-steal.md`
Cross-pollution warning: R78-memto and R81-millhouse steal reports are in the same worktree — they are NOT relevant to this plan. P0-4 (per-window 25-field state isolation) is deferred; not in scope.

## ASSUMPTIONS

- `src/core/llm_backends.py::claude_generate()` takes `model` as a string and builds the Anthropic client via `get_anthropic_client()`; model-route injection at the `claude_generate` call site in `LLMRouter.generate()` is sufficient.
- `src/core/config.py::get_anthropic_client()` currently returns a client with a fixed `base_url` and `api_key` from env/credentials; we need to accept optional overrides.
- `watchdog` is already in `requirements.txt` (grep confirms it is referenced in `src/storage/_tasks_mixin.py`); if not, it must be added.
- The main Orchestrator entry point (not identified in this worktree's scope) calls `build_scheduler()` — the observatory server will be started alongside it.
- Port 4310 is available; if occupied, the server degrades to a warning log (non-blocking).
- Python 3.11+; `asyncio` + `aiohttp` are used (aiohttp already present for network collector).

## File Map

- `D:/Users/Administrator/Documents/GitHub/orchestrator/.claude/worktrees/steal-learn-likecc/config/model_routes.yaml` — Create
- `D:/Users/Administrator/Documents/GitHub/orchestrator/.claude/worktrees/steal-learn-likecc/src/core/model_routes.py` — Create
- `D:/Users/Administrator/Documents/GitHub/orchestrator/.claude/worktrees/steal-learn-likecc/src/core/llm_backends.py` — Modify (add `base_url`, `auth_token`, `extra_headers` params to `claude_generate`)
- `D:/Users/Administrator/Documents/GitHub/orchestrator/.claude/worktrees/steal-learn-likecc/src/core/llm_router.py` — Modify (inject route into `_claude_generate` call path)
- `D:/Users/Administrator/Documents/GitHub/orchestrator/.claude/worktrees/steal-learn-likecc/src/core/config_watcher.py` — Create
- `D:/Users/Administrator/Documents/GitHub/orchestrator/.claude/worktrees/steal-learn-likecc/src/core/observatory.py` — Create
- `D:/Users/Administrator/Documents/GitHub/orchestrator/.claude/worktrees/steal-learn-likecc/src/scheduler.py` — Modify (start observatory server on startup)
- `D:/Users/Administrator/Documents/GitHub/orchestrator/.claude/worktrees/steal-learn-likecc/tests/core/test_model_routes.py` — Create
- `D:/Users/Administrator/Documents/GitHub/orchestrator/.claude/worktrees/steal-learn-likecc/tests/core/test_config_watcher.py` — Create
- `D:/Users/Administrator/Documents/GitHub/orchestrator/.claude/worktrees/steal-learn-likecc/tests/core/test_observatory.py` — Create

---

## Phase A — Per-Model Route Table (P0-1)

### Step 1
Create `config/model_routes.yaml` with this schema and two example entries:

```yaml
# Per-model route overrides (R82 learn-likecc P0-1)
# Keys: exact model id, lowercase model id, or prefix wildcard ending in "*"
# Precedence: exact > lowercase > prefix wildcard
# Fields: base_url, api_key, auth_token, headers (dict)
routes:
  claude-sonnet-4-6:
    base_url: ""          # empty = default Anthropic endpoint
    api_key: ""           # empty = use env/credentials fallback
  "minimax/*":
    base_url: "https://api.minimax.chat/v1"
    api_key: ""           # set MINIMAX_API_KEY in env
```

→ verify: `python -c "import yaml; d=yaml.safe_load(open('config/model_routes.yaml')); assert 'routes' in d"`

### Step 2
Create `src/core/model_routes.py` with:

- `@dataclass ModelRoute`: fields `base_url: str = ""`, `api_key: str = ""`, `auth_token: str = ""`, `headers: dict = field(default_factory=dict)`
- `_FIRST_PARTY_HOSTS = {"api.anthropic.com", "platform.claude.com"}` for apiKey→authToken mirror logic
- `def _load_routes_from_yaml(path: Path) -> dict[str, ModelRoute]` — reads `config/model_routes.yaml`, skips empty/missing fields; returns `{}` on FileNotFoundError
- `def _load_routes_from_env() -> dict[str, ModelRoute]` — reads `ORCHESTRATOR_MODEL_ROUTES_JSON` env var, `json.loads`, returns `{}` on missing/invalid JSON
- `def get_route_for_model(model: str) -> ModelRoute | None` — merge yaml routes (higher priority) over env routes; three-level match: (1) exact `routes[model]`, (2) `routes[model.lower()]`, (3) prefix wildcard where `key.lower().endswith("*")` and `model.lower().startswith(key.lower()[:-1])`; returns `None` if no match
- `def should_mirror_to_auth_token(route: ModelRoute, resolved_base_url: str) -> bool` — returns `True` when `route.api_key` is set AND `route.auth_token` is empty AND the resolved URL's hostname is not in `_FIRST_PARTY_HOSTS`

→ verify: `python -c "from src.core.model_routes import get_route_for_model, ModelRoute; r = get_route_for_model('claude-sonnet-4-6'); print(type(r))"`

- depends on: step 1

### Step 3
Modify `src/core/llm_backends.py::claude_generate()`:

Add three keyword-only parameters after existing `images` param:
```python
base_url: str | None = None,
auth_token: str | None = None,
extra_headers: dict | None = None,
```

Inside the function, before `client = get_anthropic_client()`, add:
```python
client = get_anthropic_client(
    base_url=base_url or None,
    auth_token=auth_token or None,
    extra_headers=extra_headers or None,
)
```

Then in `src/core/config.py::get_anthropic_client()`: add the same three keyword params; when `base_url` is provided set `anthropic.Anthropic(base_url=base_url, ...)`; when `auth_token` is provided set the Authorization header via `default_headers={"Authorization": f"Bearer {auth_token}", **(extra_headers or {})}`.

→ verify: `python -c "import inspect; from src.core.llm_backends import claude_generate; sig=inspect.signature(claude_generate); assert 'base_url' in sig.parameters and 'auth_token' in sig.parameters"`

- depends on: step 2

### Step 4
Modify `src/core/llm_router.py`: in the method that calls `claude_generate` (search for `claude_generate(` call site), inject route lookup:

```python
from src.core.model_routes import get_route_for_model, should_mirror_to_auth_token

route = get_route_for_model(model)
base_url = route.base_url if route else None
api_key = route.api_key if route else None
auth_token = route.auth_token if route else None
headers = route.headers if route else {}

if route and should_mirror_to_auth_token(route, base_url or ""):
    auth_token = api_key
    api_key = None

result = claude_generate(
    prompt=prompt, model=model, timeout=timeout, max_tokens=max_tokens,
    base_url=base_url or None,
    auth_token=auth_token or None,
    extra_headers=headers or None,
)
```

→ verify: `python -c "from src.core.llm_router import LLMRouter; r = LLMRouter(); print('import ok')"`

- depends on: step 3

### Step 5
Create `tests/core/test_model_routes.py` with 5 tests:

1. `test_exact_match`: Set `ORCHESTRATOR_MODEL_ROUTES_JSON='{"claude-sonnet-4-6": {"base_url": "https://custom.api/v1"}}'`; call `get_route_for_model("claude-sonnet-4-6")`; assert `route.base_url == "https://custom.api/v1"`
2. `test_lowercase_match`: JSON key `"CLAUDE-SONNET-4-6"`, query `"claude-sonnet-4-6"`; assert match returned
3. `test_prefix_wildcard_match`: JSON key `"minimax/*"`, query `"minimax/abab6.5s-chat"`; assert route returned
4. `test_no_match_returns_none`: JSON has only `"gpt-4"` entry; query `"claude-haiku-4-5-20251001"`; assert `get_route_for_model(...)` returns `None`
5. `test_mirror_to_auth_token`: Route with `api_key="sk-abc"`, `auth_token=""`, `base_url="https://openrouter.ai/api/v1"`; call `should_mirror_to_auth_token(route, route.base_url)`; assert `True`. Second sub-case: `base_url="https://api.anthropic.com/v1"`; assert `False`

→ verify: `pytest tests/core/test_model_routes.py -v`

- depends on: step 2

---
--- PHASE GATE: Phase A → Phase B ---
[ ] Deliverable: `src/core/model_routes.py` exists with `get_route_for_model` and `should_mirror_to_auth_token`
[ ] Tests: `pytest tests/core/test_model_routes.py -v` exit code 0, 5 tests pass
[ ] No unrelated changes: `git diff --stat` shows only files in Phase A File Map
[ ] Owner review: not required (reversible, <4h)

---

## Phase B — Settings Hot Reload with Triple Debounce (P0-2)

### Step 6
Add `watchdog>=3.0.0` to `requirements.txt` after the existing list (read the file first to find the right insertion point; if already present, skip this step).

→ verify: `python -c "import watchdog; print(watchdog.__version__)"` (install with `pip install watchdog` if missing)

### Step 7
Create `src/core/config_watcher.py` implementing `ConfigWatcher`:

```python
"""Settings hot reload — triple debounce (R82 learn-likecc P0-2).

Three-layer debounce:
  1. stability_threshold_s (default 1.0s): wait for file write to stabilise
     before firing — implemented via watchdog's scheduled Observer + manual
     per-event timer (watchdog has no built-in awaitWriteFinish; we re-arm
     a threading.Timer on each raw event, fire only when no new event arrives
     within the window).
  2. internal_write suppression (default 5.0s): when Orchestrator itself writes
     a settings file, call mark_internal_write(path) first; events arriving
     within the suppress window are silently dropped.
  3. deletion_grace_s (default 1.7s): a deletion event arms a timer; if an
     add/change event for the same path arrives before expiry, the deletion
     is cancelled and treated as a change.
"""
import logging
import threading
import time
from pathlib import Path
from typing import Callable

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, \
    FileModifiedEvent, FileDeletedEvent

log = logging.getLogger(__name__)

STABILITY_THRESHOLD_S: float = 1.0
INTERNAL_WRITE_SUPPRESS_S: float = 5.0
DELETION_GRACE_S: float = 1.7
```

Class `ConfigWatcher`:
- `__init__(self, watch_dirs: list[Path], on_change: Callable[[Path, str], None], stability_s: float = STABILITY_THRESHOLD_S, suppress_s: float = INTERNAL_WRITE_SUPPRESS_S, deletion_grace_s: float = DELETION_GRACE_S)` — stores params; `_internal_writes: dict[Path, float] = {}`; `_pending_stable: dict[Path, threading.Timer] = {}`; `_pending_deletions: dict[Path, threading.Timer] = {}`; creates `Observer()`
- `mark_internal_write(path: Path) -> None` — records `_internal_writes[path] = time.monotonic()`
- `start(self) -> None` — schedules a `_Handler(self)` for each dir in `watch_dirs` (non-recursive, `recursive=False`); calls `self._observer.start()`
- `stop(self) -> None` — calls `self._observer.stop(); self._observer.join()`

Inner class `_Handler(FileSystemEventHandler)`:
- `on_created` and `on_modified` both call `self._watcher._on_raw_change(Path(event.src_path))`
- `on_deleted` calls `self._watcher._on_raw_delete(Path(event.src_path))`

Private methods on `ConfigWatcher`:
- `_on_raw_change(path: Path) -> None`:
  1. Cancel any pending deletion timer for `path`; remove from `_pending_deletions`
  2. Check internal write: if `time.monotonic() - _internal_writes.get(path, 0) < suppress_s`; return silently
  3. Cancel any existing stability timer for `path`
  4. Arm new `threading.Timer(stability_s, self._fire_change, args=[path, "change"])`; store in `_pending_stable[path]`
- `_on_raw_delete(path: Path) -> None`:
  1. If already pending deletion, return
  2. Arm `threading.Timer(deletion_grace_s, self._fire_change, args=[path, "delete"])`; store in `_pending_deletions[path]`
- `_fire_change(path: Path, event_type: str) -> None`:
  - Remove from `_pending_stable` or `_pending_deletions`
  - Call `self.on_change(path, event_type)` (caller-supplied callback)

→ verify: `python -c "from src.core.config_watcher import ConfigWatcher, DELETION_GRACE_S; assert DELETION_GRACE_S == 1.7; print('ok')"`

- depends on: step 6

### Step 8
Create `tests/core/test_config_watcher.py` with 4 tests using `tmp_path` pytest fixture:

1. `test_change_fires_after_stability_window`: Write a file in `tmp_path`; create `ConfigWatcher([tmp_path], callback, stability_s=0.05)`; start; overwrite file; `time.sleep(0.2)`; assert callback called once with `event_type="change"`; stop
2. `test_internal_write_suppressed`: Call `watcher.mark_internal_write(file_path)`; overwrite file immediately; `time.sleep(0.2)`; assert callback NOT called; stop
3. `test_deletion_grace_cancel`: Start watcher; delete file; within 0.05s re-create it (simulating delete-and-recreate); `time.sleep(0.2)`; assert callback called with `event_type="change"` not `"delete"`; stop
4. `test_deletion_fires_after_grace`: Delete file, wait `deletion_grace_s + 0.1s`; assert callback called with `event_type="delete"`; stop

→ verify: `pytest tests/core/test_config_watcher.py -v`

- depends on: step 7

---
--- PHASE GATE: Phase B → Phase C ---
[ ] Deliverable: `src/core/config_watcher.py` with `ConfigWatcher` class
[ ] Tests: `pytest tests/core/test_config_watcher.py -v` exit code 0, 4 tests pass
[ ] No unrelated changes in `git diff --stat`
[ ] Owner review: not required

---

## Phase C — In-Process HTTP Observatory (P0-3)

### Step 9
Create `src/core/observatory.py` with:

```python
"""In-process HTTP observatory — 127.0.0.1:4310 (R82 learn-likecc P0-3).

publish_snapshot(state) pushes the latest OrchestratorState into a module-level
variable. All HTTP handlers read _latest_snapshot — fully stateless, no locks.

GET endpoints (read-only):
  /                           HTML dashboard stub (200 text/html)
  /api/sessions/current       session summary + active tasks
  /api/tasks                  list of tasks from snapshot
  /api/agents                 list of active agents
  /api/health                 {"status": "ok", "uptime_s": float}

POST endpoints (control):
  /api/control/submit         body: {"prompt": str} → schedules prompt injection
  /api/control/interrupt      body: {} → sets _interrupt_flag

Start: call start_observatory() at process startup; if port is taken, logs
       WARNING and returns without raising (CLI stays functional).
"""
import json
import logging
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Any

log = logging.getLogger(__name__)

OBSERVATORY_PORT: int = 4310
OBSERVATORY_HOST: str = "127.0.0.1"

_latest_snapshot: dict[str, Any] | None = None
_server_started: bool = False
_start_time: float = time.monotonic()
_interrupt_flag: bool = False
_pending_prompts: list[str] = []
```

Function `publish_snapshot(state: dict) -> None` — sets `_latest_snapshot = state`.

Function `get_pending_prompts() -> list[str]` — pops and returns all items from `_pending_prompts` (caller drains on each scheduler tick).

Function `is_interrupted() -> bool` — returns `_interrupt_flag`; resets it to `False` after read.

Class `_ObservatoryHandler(BaseHTTPRequestHandler)`:
- `log_message` overridden to use `log.debug` (suppress default stderr output)
- `do_GET`: match `self.path` with `if/elif`:
  - `/` → send 200 `text/html` with minimal HTML: `<title>Orchestrator Observatory</title><pre id="snapshot"></pre><script>fetch('/api/sessions/current').then(r=>r.json()).then(d=>document.getElementById('snapshot').textContent=JSON.stringify(d,null,2))</script>`
  - `/api/sessions/current` → `_write_json(200, {"session": _build_session_summary(), "tasks": _latest_snapshot.get("tasks", []) if _latest_snapshot else []})`
  - `/api/tasks` → `_write_json(200, _latest_snapshot.get("tasks", []) if _latest_snapshot else [])`
  - `/api/agents` → `_write_json(200, _latest_snapshot.get("agents", []) if _latest_snapshot else [])`
  - `/api/health` → `_write_json(200, {"status": "ok", "uptime_s": round(time.monotonic() - _start_time, 1)})`
  - else → `_write_json(404, {"error": "not found"})`
- `do_POST`: read body via `json.loads(self.rfile.read(int(self.headers["Content-Length"])))`
  - `/api/control/submit` → append `body["prompt"]` to `_pending_prompts`; `_write_json(200, {"queued": True})`
  - `/api/control/interrupt` → set `_interrupt_flag = True`; `_write_json(200, {"interrupted": True})`
  - else → `_write_json(404, {"error": "not found"})`
- `_write_json(code: int, data)` helper: send response code, `Content-Type: application/json`, body `json.dumps(data).encode()`

Module-level helper `_build_session_summary() -> dict`:
```python
if _latest_snapshot is None:
    return {"status": "no_snapshot", "task_count": 0}
return {
    "status": _latest_snapshot.get("status", "unknown"),
    "task_count": len(_latest_snapshot.get("tasks", [])),
    "agent_count": len(_latest_snapshot.get("agents", [])),
    "snapshot_keys": list(_latest_snapshot.keys()),
}
```

Function `start_observatory(port: int = OBSERVATORY_PORT, host: str = OBSERVATORY_HOST) -> None`:
```python
global _server_started
if _server_started:
    return
try:
    server = HTTPServer((host, port), _ObservatoryHandler)
    t = Thread(target=server.serve_forever, daemon=True, name="observatory")
    t.start()
    _server_started = True
    log.info("Observatory started at http://%s:%d", host, port)
except OSError as e:
    log.warning("Observatory failed to start (port %d occupied?): %s", port, e)
```

→ verify: `python -c "from src.core.observatory import start_observatory, publish_snapshot, get_pending_prompts; print('import ok')"`

### Step 10
Modify `src/scheduler.py`: read the file first to find where `build_scheduler()` or the scheduler startup code is. Add the following import at the top of the file (after existing imports):

```python
from src.core.observatory import start_observatory
```

Then in the scheduler startup function (the one that creates the APScheduler instance and starts it), add `start_observatory()` as the first call before `scheduler.start()`.

→ verify: `python -c "import ast, pathlib; src=pathlib.Path('src/scheduler.py').read_text(); tree=ast.parse(src); print('parse ok')"`

- depends on: step 9

### Step 11
Create `tests/core/test_observatory.py` with 4 tests:

1. `test_health_endpoint`: Call `start_observatory(port=14310)`; `import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:14310/api/health'); d=json.loads(r.read()); assert d['status']=='ok'`
2. `test_session_current_no_snapshot`: GET `/api/sessions/current` before any `publish_snapshot`; assert response is JSON with `session.status == "no_snapshot"`
3. `test_publish_snapshot_reflects_in_api`: Call `publish_snapshot({"status": "running", "tasks": [{"id": "t1"}], "agents": []})`; GET `/api/sessions/current`; assert `data["session"]["task_count"] == 1`
4. `test_control_submit_queues_prompt`: POST `/api/control/submit` with body `{"prompt": "hello"}`; assert response `{"queued": True}`; assert `get_pending_prompts() == ["hello"]`

Each test must use a unique port (14310, 14311, 14312, 14313) to avoid `_server_started` guard conflicts — use a module-level fixture that resets `src.core.observatory._server_started = False` and `_latest_snapshot = None` before each test.

→ verify: `pytest tests/core/test_observatory.py -v`

- depends on: step 9

---
--- PHASE GATE: Phase C → Integration ---
[ ] Deliverable: `src/core/observatory.py` with `start_observatory`, `publish_snapshot`, GET+POST endpoints
[ ] Tests: `pytest tests/core/test_observatory.py -v` exit code 0, 4 tests pass
[ ] Observatory import does not break existing scheduler: `python -c "from src.scheduler import build_scheduler"` exits 0
[ ] Owner review: not required

---

## Phase D — Integration Regression

### Step 12
Run full test suite for affected modules:

```
pytest tests/core/test_model_routes.py tests/core/test_config_watcher.py tests/core/test_observatory.py tests/test_llm_router.py tests/core/test_llm_router_cascade.py -q
```

Assert exit code 0; no new failures in `test_llm_router.py` or `test_llm_router_cascade.py`.

→ verify: above command exits with code 0

- depends on: step 5, step 8, step 11

### Step 13
Validate end-to-end route injection does not break the existing `LLMRouter` smoke path: run with no model_routes configured (empty env, empty yaml) and confirm default behavior is preserved.

```
ORCHESTRATOR_MODEL_ROUTES_JSON='{}' python -c "
from src.core.model_routes import get_route_for_model
r = get_route_for_model('claude-sonnet-4-6')
assert r is None, f'expected None, got {r}'
print('no-config path ok: returns None, no injection')
"
```

→ verify: command prints `no-config path ok: returns None, no injection` with exit code 0

- depends on: step 4

---

## Non-Goals

- P0-4 (per-window 25-field `SessionTabState` isolation) — deferred to future TUI milestone; no `src/tui/` changes in this plan
- P1 patterns (format-preserving secret redaction, layered config inspection `/show`, `repo-release-governance` skill, settings tri-location) — separate plan when P0 is merged
- WebSocket streaming for observatory — polling is sufficient; scope creep
- `watchdog` upgrade/replace for existing usages in `src/storage/_tasks_mixin.py` — leave untouched

## Rollback

1. `git diff --stat` to confirm only the 10 files in File Map are changed
2. `git stash` to preserve the working tree
3. Revert File Map files individually:
   - Delete creates: `rm src/core/model_routes.py src/core/config_watcher.py src/core/observatory.py tests/core/test_model_routes.py tests/core/test_config_watcher.py tests/core/test_observatory.py config/model_routes.yaml`
   - Restore modifies: `git checkout src/core/llm_backends.py src/core/llm_router.py src/core/config.py src/scheduler.py requirements.txt`
4. `git stash pop` if needed

## Effort Estimate

- Phase A (model routes): ~3h
- Phase B (config watcher): ~4h
- Phase C (observatory): ~6h (including HTML stub + tests)
- Phase D (integration): ~0.5h

Total: ~13.5h. Split over two sessions; commit after each Phase Gate.
