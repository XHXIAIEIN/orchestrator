# DeerFlow 2.0 Deep Analysis — Skills / Sandbox / MCP / Gateway / IM Channels

**Source**: https://github.com/bytedance/deer-flow (ByteDance)
**Date**: 2026-04-01
**Analyst**: Claude Opus 4.6
**Verdict**: 成熟的生产级 Agent 框架，5 个领域共 12 个可偷模式

---

## 1. Skills System

### Architecture

```
skills/
├── public/           # 内置 skills（git tracked）
│   ├── bootstrap/
│   │   ├── SKILL.md
│   │   ├── templates/SOUL.template.md
│   │   └── references/conversation-guide.md
│   ├── deep-research/SKILL.md
│   ├── chart-visualization/
│   │   ├── SKILL.md
│   │   ├── scripts/generate.js
│   │   └── references/*.md   # 30+ chart type references
│   ├── data-analysis/
│   ├── find-skills/          # meta-skill: install new skills
│   ├── frontend-design/
│   ├── image-generation/
│   ├── podcast-generation/
│   └── ...
└── custom/           # 用户安装的 skills
```

### SKILL.md Format

**File**: `skills/public/bootstrap/SKILL.md`

```yaml
---
name: bootstrap
description: Generate a personalized SOUL.md through a warm, adaptive onboarding conversation...
---
```

Frontmatter fields (allowed set, validated):
- `name` (required, hyphen-case, max 64 chars)
- `description` (required, max 1024 chars, no angle brackets)
- `license`, `allowed-tools`, `metadata`, `compatibility`, `version`, `author`

Body is free-form Markdown — the agent reads it via `read_file` at runtime.

**Validation**: `backend/packages/harness/deerflow/skills/validation.py:12`
```python
ALLOWED_FRONTMATTER_PROPERTIES = {"name", "description", "license", "allowed-tools", "metadata", "compatibility", "version", "author"}
```

### Skill Loading Pipeline

**Files**:
- `deerflow/skills/loader.py` — walks `public/` + `custom/`, parses SKILL.md
- `deerflow/skills/parser.py` — extracts YAML frontmatter (hand-rolled, not PyYAML for parsing)
- `deerflow/skills/types.py` — `Skill` dataclass with container path helpers
- `deerflow/config/extensions_config.py` — tracks enabled/disabled state per skill

**Flow**:
1. `load_skills()` walks `skills/{public,custom}/` via `os.walk`
2. Each `SKILL.md` parsed → `Skill` object with `name`, `description`, `category`, `relative_path`
3. `ExtensionsConfig.from_file()` read from disk (NOT cached singleton — deliberate, see below)
4. `skill.enabled` set based on config
5. Sorted by name for deterministic ordering

### Skill Injection into Agent Prompt

**File**: `deerflow/agents/lead_agent/prompt.py:383-424`

```python
def get_skills_prompt_section(available_skills):
    skills = load_skills(enabled_only=True)
    skill_items = "\n".join(
        f"<skill>\n<name>{skill.name}</name>\n"
        f"<description>{skill.description}</description>\n"
        f"<location>{skill.get_container_file_path(container_base_path)}</location>\n"
        f"</skill>" for skill in skills
    )
    return f"""<skill_system>
    ...Progressive Loading Pattern:
    1. When a user query matches a skill's use case, immediately call `read_file` on the skill's main file
    2. Read and understand the skill's workflow and instructions
    3. The skill file contains references to external resources under the same folder
    4. Load referenced resources only when needed during execution
    ...
    {skills_list}
    </skill_system>"""
```

### Skill Installation (Runtime)

**File**: `deerflow/skills/installer.py`

Skills can be installed at runtime via `.skill` files (ZIP archives):
- Security: path traversal check, symlink rejection, zip bomb defense (512MB max)
- Validates frontmatter before installing
- Installs to `skills/custom/<skill_name>/`
- Gateway API: `POST /api/skills/install`

### Pattern: **Progressive Skill Loading** (P0)

Skills are NOT loaded into context upfront. The agent sees only `<name>` + `<description>` + `<location>`. When triggered, it calls `read_file` to load the actual skill content. Sub-resources (references, templates, scripts) are loaded only when the skill instructions reference them.

**What's clever**:
- Token-efficient: only pays for skills actually used
- Skills can be arbitrarily large (deep-research is 199 lines of methodology)
- Sub-resource tree enables compositional skills (bootstrap has templates + conversation guide)
- Container path abstraction (`/mnt/skills/public/bootstrap/SKILL.md`) hides local vs Docker differences

**What's naive**:
- Parser is hand-rolled YAML (line-by-line `key: value` split), not proper YAML — breaks on multiline values, nested structures
- Validation uses full PyYAML but parser doesn't — inconsistency
- No skill versioning or dependency management
- No skill capability declarations (what tools a skill needs)

### Pattern: **Hot-Reload via File mtime** (P1)

**File**: `deerflow/skills/loader.py:83-84`

```python
# NOTE: We use ExtensionsConfig.from_file() instead of get_extensions_config()
# to always read the latest configuration from disk.
```

Gateway and LangGraph Server are separate processes. When Gateway writes a config change, LangGraph Server picks it up on next skill load by re-reading from disk. Same pattern in MCP cache (`mcp/cache.py:31-53`).

**What's clever**: No IPC/signaling needed between processes — eventual consistency via filesystem
**What's naive**: Polling on every request. No file watcher. No config version number.

---

## 2. Sandbox Architecture

### Two-Tier Provider System

**Abstract interface**: `deerflow/sandbox/sandbox.py` — `Sandbox` ABC with `execute_command`, `read_file`, `write_file`, `list_dir`, `update_file`

**Provider interface**: `deerflow/sandbox/sandbox_provider.py` — `SandboxProvider` ABC with `acquire(thread_id) -> sandbox_id`, `get(sandbox_id)`, `release(sandbox_id)`

**Implementations**:
1. **LocalSandboxProvider** — direct host execution (dev mode, dangerous)
2. **AioSandboxProvider** — Docker container orchestration (production)

### LocalSandbox: Virtual Path Mapping

**File**: `deerflow/sandbox/local/local_sandbox.py:42-167`

The LocalSandbox maintains `path_mappings: dict[str, str]` that translates container paths (`/mnt/skills`, `/mnt/user-data`) to host paths. Three methods handle this:
- `_resolve_path(path)` — container → host (for file operations)
- `_resolve_paths_in_command(command)` — rewrites paths inside shell commands
- `_reverse_resolve_paths_in_output(output)` — host → container (for output back to agent)

**What's clever**: Agent code always uses virtual paths; the sandbox transparently maps them. This means the same agent prompts work in both local and Docker modes.

### AioSandboxProvider: Production Container Orchestration

**File**: `deerflow/community/aio_sandbox/aio_sandbox_provider.py`

**Architecture**: 3-layer sandbox discovery

```
Layer 1: In-process cache (_thread_sandboxes dict)
  ↓ miss
Layer 1.5: Warm pool (released but still-running containers)
  ↓ miss
Layer 2: Backend discovery + create (with cross-process file lock)
```

### Pattern: **Deterministic Sandbox ID** (P0)

**File**: `aio_sandbox_provider.py:181-187`

```python
@staticmethod
def _deterministic_sandbox_id(thread_id: str) -> str:
    return hashlib.sha256(thread_id.encode()).hexdigest()[:8]
```

All processes derive the same sandbox_id from a thread_id. No shared state needed for cross-process sandbox discovery — any process can compute the container name and check if it exists.

**What's clever**: Eliminates the need for a shared database or distributed lock for sandbox mapping. File lock (`thread_id.lock`) only serializes creation, not lookup.

### Pattern: **Warm Pool with LRU Eviction** (P0)

**File**: `aio_sandbox_provider.py:99-103, 550-574`

Released sandboxes go to `_warm_pool` instead of being destroyed. On next acquire for the same thread, the container is reclaimed instantly (no cold-start). When `replicas` limit is hit, oldest warm container is evicted.

```python
def release(self, sandbox_id):
    # Park in warm pool — container keeps running
    if info and sandbox_id not in self._warm_pool:
        self._warm_pool[sandbox_id] = (info, time.time())
```

**What's clever**: Warm pool is the key performance optimization. Docker container startup is 5-10s; warm reclaim is instant.
**What's naive**: Replicas is a soft cap — active sandboxes can exceed it. No backpressure mechanism.

### Pattern: **DooD (Docker-outside-Docker) Path Translation** (P1)

**File**: `docker/docker-compose.yaml:77-78, 99-100`

```yaml
volumes:
  - ${DEER_FLOW_DOCKER_SOCKET}:/var/run/docker.sock  # DooD
environment:
  - DEER_FLOW_HOST_BASE_DIR=${DEER_FLOW_HOME}
  - DEER_FLOW_HOST_SKILLS_PATH=${DEER_FLOW_REPO_ROOT}/skills
```

Gateway/LangGraph containers mount the host Docker socket. When they create sandbox containers, they use `DEER_FLOW_HOST_*` env vars to compute volume mounts from the HOST's perspective (not from inside the gateway container).

### Security Boundaries

**File**: `deerflow/sandbox/security.py`

- `LocalSandboxProvider` has `allow_host_bash` flag (default: false)
- When false, bash tool is completely disabled — agent can only use file tools
- `AioSandboxProvider` runs commands inside isolated containers
- Skills mounted read-only in sandbox containers
- Sandbox audit middleware logs all operations

---

## 3. MCP Server Integration

### Architecture

**Files**:
- `deerflow/mcp/client.py` — builds server params for `MultiServerMCPClient`
- `deerflow/mcp/tools.py` — loads tools from all enabled MCP servers
- `deerflow/mcp/oauth.py` — OAuth token management for HTTP/SSE servers
- `deerflow/mcp/cache.py` — singleton cache with file-mtime staleness detection
- `deerflow/config/extensions_config.py` — MCP server config model

### MCP Tool Loading

**File**: `deerflow/mcp/tools.py:56-113`

```python
async def get_mcp_tools() -> list[BaseTool]:
    extensions_config = ExtensionsConfig.from_file()  # fresh read
    servers_config = build_servers_config(extensions_config)

    # Inject OAuth headers for initial connection
    initial_oauth_headers = await get_initial_oauth_headers(extensions_config)

    # Build interceptors for ongoing OAuth token refresh
    oauth_interceptor = build_oauth_tool_interceptor(extensions_config)

    client = MultiServerMCPClient(servers_config,
        tool_interceptors=tool_interceptors,
        tool_name_prefix=True)
    tools = await client.get_tools()

    # Patch tools for sync invocation
    for tool in tools:
        if tool.func is None and tool.coroutine is not None:
            tool.func = _make_sync_tool_wrapper(tool.coroutine, tool.name)
```

### Pattern: **OAuth Token Manager with Async Lock** (P1)

**File**: `deerflow/mcp/oauth.py:25-119`

```python
class OAuthTokenManager:
    def __init__(self, oauth_by_server):
        self._locks = {name: asyncio.Lock() for name in oauth_by_server}

    async def get_authorization_header(self, server_name):
        # Check cache first (no lock)
        if token and not self._is_expiring(token, oauth):
            return f"{token.token_type} {token.access_token}"
        # Double-check under lock
        async with lock:
            if token and not self._is_expiring(token, oauth):
                return ...
            fresh = await self._fetch_token(oauth)
```

Two grant types: `client_credentials` and `refresh_token`. Configurable field names (`token_field`, `expires_in_field`) for non-standard OAuth servers.

**What's clever**: Per-server async locks prevent thundering herd on token refresh. Configurable field names handle non-standard OAuth implementations.

### Pattern: **Sync-Async Bridge for MCP Tools** (P1)

**File**: `deerflow/mcp/tools.py:19-53`

```python
_SYNC_TOOL_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=10)

def _make_sync_tool_wrapper(coro, tool_name):
    def sync_wrapper(*args, **kwargs):
        loop = asyncio.get_running_loop()
        if loop is not None and loop.is_running():
            future = _SYNC_TOOL_EXECUTOR.submit(asyncio.run, coro(*args, **kwargs))
            return future.result()
        else:
            return asyncio.run(coro(*args, **kwargs))
    return sync_wrapper
```

MCP tools are async but LangGraph can invoke them synchronously. A global thread pool bridges the gap.

---

## 4. Gateway/API Layer

### Architecture

**File**: `backend/app/gateway/app.py`

FastAPI app with 12 routers:

| Route | Purpose |
|-------|---------|
| `/api/models` | Available AI models |
| `/api/mcp/config` | GET/PUT MCP server configs |
| `/api/memory` | Memory facts |
| `/api/skills` | List/update/install skills |
| `/api/threads/{id}/artifacts` | Thread artifacts |
| `/api/threads/{id}/uploads` | File uploads |
| `/api/threads/{id}` | Thread cleanup |
| `/api/agents` | Custom agent CRUD |
| `/api/threads/{id}/suggestions` | Follow-up suggestions |
| `/api/channels` | IM channel status/restart |
| `/api/assistants` | LangGraph Platform compat stub |
| `/api/runs` | Stateless run lifecycle |

### Pattern: **Nginx as Traffic Splitter** (P0)

```
Client → nginx:2026
           ├── /api/* → gateway:8001 (FastAPI)
           └── /langgraph/* → langgraph:2024 (LangGraph Server)
```

Gateway handles custom business logic (skills, MCP config, channels). LangGraph handles agent execution. Nginx splits traffic. CORS handled by nginx, not FastAPI.

**What's clever**: Clean separation of concerns. Gateway can be scaled independently of LangGraph Server.

### Pattern: **Lifespan-Managed Channel Service** (P1)

**File**: `app/gateway/app.py:37-74`

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with langgraph_runtime(app):
        channel_service = await start_channel_service()
        yield
        await stop_channel_service()
```

IM channels start/stop with the gateway's lifecycle. Channel service is a singleton.

---

## 5. IM Channel Integration

### Architecture

```
                   MessageBus (asyncio.Queue)
                  ┌──────────┴──────────┐
          inbound │                      │ outbound
                  ▼                      ▼
     ┌─────────────────┐    ┌─────────────────┐
     │  TelegramChannel │    │  ChannelManager  │
     │  SlackChannel    │    │  (dispatch loop) │
     │  FeishuChannel   │    │                  │
     └────────┬────────┘    └────────┬─────────┘
              │                      │
              │  publish_inbound()   │  runs.wait() / runs.stream()
              │                      │  → LangGraph Server
              ▼                      ▼
```

### MessageBus

**File**: `app/channels/message_bus.py`

- `asyncio.Queue` for inbound (channels → manager)
- Callback list for outbound (manager → channels)
- Typed messages: `InboundMessage` (chat/command), `OutboundMessage` (text + artifacts + attachments)

### ChannelManager

**File**: `app/channels/manager.py`

Core dispatcher:
1. Reads from inbound queue in a loop
2. Creates/reuses LangGraph threads (via `ChannelStore`)
3. Sends messages via `client.runs.wait()` (non-streaming) or `client.runs.stream()` (streaming)
4. Extracts response text + artifacts from LangGraph result
5. Resolves artifact paths → host filesystem → `ResolvedAttachment`
6. Publishes outbound with text + file attachments

### Pattern: **Thread-per-Topic Mapping** (P0)

**File**: `app/channels/store.py:75-78`

```python
@staticmethod
def _key(channel_name, chat_id, topic_id=None):
    if topic_id:
        return f"{channel_name}:{chat_id}:{topic_id}"
    return f"{channel_name}:{chat_id}"
```

- Private chats: `topic_id=None` → single thread per chat
- Group chats: `topic_id=reply_to_message_id` → thread per conversation branch
- JSON file store with atomic writes (tempfile + rename)

**What's clever**: Topic-based threading lets group chats have multiple parallel conversations, each with its own DeerFlow thread.

### Pattern: **Streaming with Rate-Limited Updates** (P1)

**File**: `app/channels/manager.py:588-690`

```python
STREAM_UPDATE_MIN_INTERVAL_SECONDS = 0.35

async def _handle_streaming_chat(self, ...):
    async for chunk in client.runs.stream(..., stream_mode=["messages-tuple", "values"]):
        # Accumulate text
        if latest_text == last_published_text:
            continue
        if now - last_publish_at < STREAM_UPDATE_MIN_INTERVAL_SECONDS:
            continue
        await self.bus.publish_outbound(OutboundMessage(..., is_final=False))
```

Feishu supports streaming updates (edit-in-place). Telegram/Slack don't. Rate limit prevents API spam.

### Pattern: **Artifact Delivery with Security Boundary** (P1)

**File**: `app/channels/manager.py:265-341`

```python
_OUTPUTS_VIRTUAL_PREFIX = "/mnt/user-data/outputs/"

def _resolve_attachments(thread_id, artifacts):
    for virtual_path in artifacts:
        if not virtual_path.startswith(_OUTPUTS_VIRTUAL_PREFIX):
            logger.warning("rejected non-outputs artifact path: %s", virtual_path)
            continue
        actual = paths.resolve_virtual_path(thread_id, virtual_path)
        actual.resolve().relative_to(outputs_dir)  # path traversal guard
```

Only `/mnt/user-data/outputs/` files can be sent via IM channels. Prevents exfiltrating uploads or workspace files.

### Telegram Implementation Details

**File**: `app/channels/telegram.py`

- Long-polling (no webhook, no public IP needed)
- Runs in dedicated thread with own event loop (can't use `run_polling()` in non-main thread due to signal handlers)
- `allowed_users` whitelist
- Retry with exponential backoff on send failure
- File upload: photos < 10MB as photo, others as document, skip > 50MB

---

## Steal Summary

| # | Pattern | Priority | Source File | Our Gap |
|---|---------|----------|-------------|---------|
| 1 | **Progressive Skill Loading** — agent sees name+desc, reads full content on demand | P0 | `lead_agent/prompt.py:383-424` | 我们的 skills 是全量注入 system prompt |
| 2 | **Deterministic Sandbox ID** — `sha256(thread_id)[:8]` eliminates cross-process coordination | P0 | `aio_sandbox_provider.py:181-187` | 我们没有 sandbox 隔离 |
| 3 | **Warm Pool + LRU Eviction** — released containers stay warm for instant reclaim | P0 | `aio_sandbox_provider.py:99-103, 550-574` | 无 |
| 4 | **Nginx Traffic Splitter** — Gateway (business logic) vs LangGraph (agent execution) | P0 | `docker/docker-compose.yaml` | 我们的 Gateway 还没分离 |
| 5 | **Thread-per-Topic IM Mapping** — `channel:chat_id:topic_id` key enables group chat threading | P0 | `channels/store.py:75-78` | 我们的 TG bot 是 per-chat 不分 topic |
| 6 | **Hot-Reload via File mtime** — cross-process config sync without IPC | P1 | `mcp/cache.py:31-53`, `skills/loader.py:83` | 我们用 in-memory singleton |
| 7 | **OAuth Token Manager** — per-server async lock + configurable field names | P1 | `mcp/oauth.py:25-119` | 我们的 MCP 没有 OAuth |
| 8 | **Sync-Async MCP Bridge** — global thread pool for sync invocation of async tools | P1 | `mcp/tools.py:19-53` | 不需要（我们是纯 async） |
| 9 | **Streaming Rate Limiter** — 0.35s min interval prevents API spam | P1 | `channels/manager.py:634` | 我们的飞书 streaming 没有 rate limit |
| 10 | **Artifact Security Boundary** — only `/mnt/user-data/outputs/` can be sent via IM | P1 | `channels/manager.py:265-285` | 我们没有路径白名单 |
| 11 | **Skill Archive Installer** — `.skill` ZIP with traversal/symlink/zipbomb defense | P2 | `skills/installer.py:73-115` | 不需要（我们不做动态安装） |
| 12 | **DooD Path Translation** — `DEER_FLOW_HOST_*` env vars for Docker-in-Docker volume mounts | P2 | `aio_sandbox_provider.py:226-243` | 我们的 Docker 不嵌套 |

---

## Key Architectural Insights

### 1. Skills = Markdown Files, Not Code

DeerFlow skills are pure Markdown with optional scripts. The agent reads them via `read_file` at runtime. There's no skill registry, no function dispatch, no special runtime. The skill IS the prompt.

This is fundamentally different from Claude Code's skills (which are also Markdown but injected by the harness). DeerFlow's approach is more decoupled — the harness only provides the skill list, the agent decides when and how to load.

### 2. Sandbox = Agent's Filesystem Abstraction

The sandbox isn't just for running code. It's the agent's entire filesystem. Skills at `/mnt/skills`, user files at `/mnt/user-data`, ACP workspace at `/mnt/acp-workspace`. The `LocalSandbox` virtualizes this with path mappings; `AioSandbox` makes it real with Docker volumes.

### 3. Gateway ≠ LangGraph Server

They run as separate processes/containers. Gateway handles business logic (CRUD for skills, MCP config, channels). LangGraph Server handles agent execution. They share config via filesystem.

### 4. IM Channels are First-Class

Not an afterthought. Three channels (Feishu, Slack, Telegram) with proper lifecycle management, thread mapping, streaming support, file attachments, and a message bus for decoupling.
