# ExecutionContext (ChatDev R13) — Rejection Rationale

## What It Does
DI bundle dataclass + builder. Bundles `task_id`, `department`, `cwd`, `timeout_s`, `max_turns`, `model`, `db`, `cost_tracker`, `token_accountant`, `log_event_fn`, `cancel_event` into one object.

## Why Not Worth It

### 1. Parameter threading is shallow (2 levels)
```
execute_task() → _run_agent_session() → AgentSessionRunner.run()
```
Only 6-7 params at each boundary. That's normal. DI bundles pay off when you have 5+ levels of pass-through; at 2 levels it's just indirection.

### 2. Field mismatch with reality
- `model`: executor doesn't pass model to session runner — it configures the router globally
- `cancel_event`: nothing in the execution chain supports cooperative cancellation
- `global_state`: no equivalent exists; no code would read it
- `token_accountant`: created per-TaskExecutor instance, not per-execution

Would need significant rewriting to align fields with actual state flow.

### 3. The real problem is method length, not parameter count
`execute_task()` is ~500 lines. That's the pain. But ExecutionContext doesn't fix it — it just moves local variables into a dataclass. The method still does the same 15 things sequentially.

### 4. Builder is over-engineering on a dataclass
`ExecutionContextBuilder` adds 60 lines of `.with_foo()` methods that `ExecutionContext(task_id=1, department="eng", ...)` already handles natively.

### 5. cancel_event is the only novel idea
Cooperative cancellation via threading.Event is genuinely useful, but it requires the entire execution chain (Agent SDK query loop, stuck detector, timeout handling) to check the event. That's a standalone feature, not a DI refactor.

## When It Would Become Worth It
- If `execute_task()` gets split into 4-5 pipeline stages that each need the same 10+ fields
- If cooperative cancellation is implemented (cancel_event becomes load-bearing)
- If agent sessions need to be spawned from multiple entry points (not just TaskExecutor)

Until then, the current pattern (class attributes + method locals + 6-param function calls) is fine.
