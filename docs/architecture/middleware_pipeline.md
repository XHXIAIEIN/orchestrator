# Governor Middleware Pipeline

> Source: DeerFlow 2.0 middleware chain (Round 28 steal)
> Status: Architecture spec — implementation in phases

## Problem

Governor's cross-cutting concerns (error recovery, loop detection, token counting, memory updates, persona injection) are scattered across:
- Shell hooks (.claude/hooks/) — external, bash-based
- Python modules (governance/pipeline/) — internal, ad-hoc
- Prompt injection (pre-compact, persona anchor) — text-based

No unified way to compose, reorder, or conditionally enable these concerns.

## Solution: Middleware Chain

Each middleware is a function that receives a `Context` and a `next` callback. It can:
1. **Pre-process**: modify context before the core handler runs
2. **Post-process**: inspect/modify the result after the core handler
3. **Short-circuit**: return early without calling `next()` (e.g., rate limiting)
4. **Error-wrap**: catch exceptions and apply recovery logic

```python
from typing import Protocol, Callable, Awaitable
from dataclasses import dataclass, field

@dataclass
class MiddlewareContext:
    """Shared state flowing through the middleware chain."""
    task_id: int | None = None
    task_spec: dict = field(default_factory=dict)
    messages: list = field(default_factory=list)
    tool_calls: list = field(default_factory=list)
    token_usage: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)  # arbitrary k/v for cross-middleware communication

class Middleware(Protocol):
    async def __call__(
        self, ctx: MiddlewareContext, next: Callable[[], Awaitable[MiddlewareContext]]
    ) -> MiddlewareContext: ...
```

## Default Middleware Stack

Order matters. Listed from outermost (first to run) to innermost (closest to core):

| # | Middleware | Purpose | Short-circuits? |
|---|-----------|---------|-----------------|
| 1 | **ToolErrorRecovery** | Catch tool execution errors, retry or degrade | On fatal error |
| 2 | **TokenCounter** | Track cumulative token usage per task | Never |
| 3 | **LoopDetection** | Hash tool calls, detect repetition patterns | At 5× threshold |
| 4 | **MemoryUpdate** | Extract learnings/memories from conversation | Never |
| 5 | **PersonaAnchor** | Inject persona reminders every N calls | Never |
| 6 | **DeferredFilter** | Queue low-priority results for batch delivery | Never |
| 7 | **SubagentLimit** | Cap concurrent sub-agents, truncate excess tool calls | On limit |
| 8 | **Clarification** | Detect ambiguous requests, inject clarification prompt | On ambiguity |

## Composition

```python
def compose_middleware(middlewares: list[Middleware]) -> Middleware:
    """Compose a list of middleware into a single handler."""
    async def composed(ctx: MiddlewareContext, core: Callable) -> MiddlewareContext:
        async def build_chain(index: int):
            if index >= len(middlewares):
                return await core(ctx)
            return await middlewares[index](ctx, lambda: build_chain(index + 1))
        return await build_chain(0)
    return composed
```

## Migration Plan

### Phase 1: Interface + 2 middlewares (current)
- Define `Middleware` protocol and `MiddlewareContext`
- Port LoopDetection from shell hook to Python middleware
- Port TokenCounter from inline code to middleware

### Phase 2: Shell hook bridge
- Create `ShellHookMiddleware` that wraps existing .claude/hooks/* as middleware
- Allows gradual migration without breaking existing hooks

### Phase 3: Full pipeline
- Port remaining concerns (persona, memory, error recovery)
- Governor executor uses `compose_middleware()` as its main loop wrapper

## Integration with Existing System

The middleware pipeline does NOT replace Claude Code hooks (settings.json). Those operate at a different layer:
- **Claude Code hooks**: External, bash-based, run by the harness, see raw tool calls
- **Governor middleware**: Internal, Python, run inside our code, see task-level context

They are complementary:
- Hooks handle security (guard.sh), persona (anchor), and git safety
- Middleware handles agent-level orchestration (loops, tokens, memory, routing)
