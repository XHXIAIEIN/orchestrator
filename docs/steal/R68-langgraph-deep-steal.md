# R68 — LangGraph 深度偷师报告

**来源**: https://github.com/langchain-ai/langgraph | **Stars**: 28.6K+ | **License**: MIT  
**版本**: 1.1.7a1 | **分析日期**: 2026-04-14 | **类别**: Complete Framework  
**前次分析**: R43（2026-04-07，当时版本 ~1.0.x）  
**Codebase**: libs/langgraph + libs/checkpoint + libs/prebuilt + libs/checkpoint-sqlite/postgres + libs/sdk-py（约 350 个 Python 文件）

---

## TL;DR

R43 偷了核心的 Channel-Reducer 模型和 Checkpoint 持久化策略。R68 发现三个 **R43 完全未覆盖**的高价值新特性：

1. **`Runtime` 对象**（v0.6.0 新增）—— 把 context_schema、store、stream_writer、execution_info 打包成不可变上下文，替代 config 的 dict 传参地狱。Orchestrator 当前每次调用都在 `configurable` 里手动传这些，这是直接可抄的结构。
2. **GraphCallbackHandler lifecycle 钩子**（最新提交 #7429）—— 图执行在 interrupt 和 resume 两个生命周期点触发类型化事件，与 Orchestrator 的 Hook 系统同构，可以直接映射。
3. **task CachePolicy + cache_key**（新增 xxh3_128 内容寻址缓存）—— 同输入 task 的结果可跨会话复用，是 Orchestrator 目前完全没有的。

另外 R43 已偷但**执行层细节大幅进化**的内容：断点/恢复的多 interrupt 映射、`FuturesDict` 并发控制器的 weakref 回调模式、`entrypoint.final` 返回/保存分离原语。

---

## 架构全图

```
┌─────────────────────────────────────────────────────────┐
│               LangGraph 调用链（从上到下）               │
│                                                         │
│  graph.stream(input, config)                            │
│         │                                               │
│  ┌──────▼──────────────────────────────────────┐       │
│  │  Pregel.__stream() / Pregel.__astream()      │       │
│  │  • 创建 SyncPregelLoop / AsyncPregelLoop     │       │
│  │  • 创建 PregelRunner（并发调度器）            │       │
│  │  • BackgroundExecutor（线程池提交器）         │       │
│  └──────┬──────────────────────────────────────┘       │
│         │  loop.tick()  →  loop.after_tick()           │
│  ┌──────▼──────────────────────────────────────┐       │
│  │  PregelLoop（BSP superstep 主循环）          │       │
│  │                                              │       │
│  │  [1] prepare_next_tasks()                   │       │
│  │      • 扫描 TASKS channel（PUSH/Send）       │       │
│  │      • 扫描 trigger_to_nodes 映射（PULL）    │       │
│  │      • 检查 channel_versions vs versions_seen│       │
│  │                                              │       │
│  │  [2] should_interrupt(interrupt_before) ?   │       │
│  │      → GraphInterrupt 异常 → 暂停            │       │
│  │                                              │       │
│  │  [3] PregelRunner.tick(tasks)               │       │
│  │      • FuturesDict 追踪 Future→Task 映射     │       │
│  │      • run_with_retry / arun_with_retry      │       │
│  │      • task.proc.invoke(task.input, config) │       │
│  │      • commit() 收集 task.writes            │       │
│  │                                              │       │
│  │  [4] apply_writes()                         │       │
│  │      • sorted(tasks, path[:3])（确定性）     │       │
│  │      • channel.update(vals)（reducer 聚合）  │       │
│  │      • checkpoint["channel_versions"] 递增  │       │
│  │                                              │       │
│  │  [5] _put_checkpoint()                      │       │
│  │      • durability=="sync": 同步写，阻塞下步  │       │
│  │      • durability=="async": submit() 后台   │       │
│  │      • durability=="exit": 退出时一次性写    │       │
│  │                                              │       │
│  │  [6] should_interrupt(interrupt_after) ?    │       │
│  │      → GraphInterrupt 异常 → 暂停            │       │
│  └──────────────────────────────────────────────┘       │
│                                                         │
│  Channel 层（状态载体）                                  │
│  ┌────────────────────────────────────────────┐         │
│  │  LastValue          仅保留最后写入值        │         │
│  │  LastValueAfterFinish  延迟到 finish() 可读 │         │
│  │  BinaryOperatorAggregate  reducer fn 聚合  │         │
│  │  Topic              pubsub，可 accumulate  │         │
│  │  EphemeralValue     单步生命周期           │         │
│  │  UntrackedValue     不持久化到 checkpoint  │         │
│  │  NamedBarrierValue  N 路 fan-in 屏障       │         │
│  └────────────────────────────────────────────┘         │
│                                                         │
│  Checkpoint 层（状态持久化）                             │
│  ┌────────────────────────────────────────────┐         │
│  │  BaseCheckpointSaver（接口）               │         │
│  │    get_tuple() / put() / put_writes()      │         │
│  │    list() / delete_thread() / prune()      │         │
│  │    copy_thread() / delete_for_runs()       │         │
│  │  SqliteSaver（WAL 模式，线程锁）            │         │
│  │  PostgresSaver（async，pgvector 可选）      │         │
│  │  InMemorySaver（测试用）                   │         │
│  └────────────────────────────────────────────┘         │
│                                                         │
│  Runtime 层（执行上下文，v0.6.0 新增）                   │
│  ┌────────────────────────────────────────────┐         │
│  │  Runtime[ContextT] 不可变 dataclass         │         │
│  │    .context: ContextT   运行时依赖注入      │         │
│  │    .store: BaseStore    跨轮次持久化        │         │
│  │    .stream_writer       自定义事件流        │         │
│  │    .previous            上次返回值          │         │
│  │    .execution_info      当前任务元数据      │         │
│  │    .server_info         平台部署信息        │         │
│  └────────────────────────────────────────────┘         │
└─────────────────────────────────────────────────────────┘
```

---

## 六维扫描

### 维度 1：架构设计（Architecture）

**核心抽象：BSP（Bulk Synchronous Parallel）算法的状态机实现**

LangGraph 在 StateGraph API 之下的真正运行时是 **Pregel**，它把图执行建模为：

```
(channels, nodes) → superstep → (updated_channels, new_checkpoint)
```

每个 superstep 严格分三阶段：Plan（prepare_next_tasks）→ Execute（PregelRunner.tick）→ Update（apply_writes）。各阶段之间有版本屏障：Execute 阶段的写入对同 superstep 内的其他节点不可见，只在 Update 之后才对下一 superstep 可见。这不是设计偏好——这是 BSP 的定义要求。

**两套 API 层最终都编译到同一 Pregel**：

```python
# StateGraph API
builder = StateGraph(State)
builder.add_node("agent", agent_fn)
compiled = builder.compile()      # → CompiledStateGraph → Pregel

# Functional API
@entrypoint(checkpointer=saver)
def workflow(input): ...           # → entrypoint.__call__() → Pregel
```

两种写法内部等价。StateGraph 把节点/边编译为 PregelNode + channel 规则，Functional API 直接创建最小 Pregel 图。

**类层次**：
```
Pregel (core runtime)
  ├── CompiledStateGraph (compiled from StateGraph builder)
  ├── RemoteGraph (HTTP client, same interface)
  └── entrypoint.__call__() → returns Pregel directly
```

**subgraph 隔离**：每个 subgraph 有独立的 `checkpoint_ns`（用 `|` 分隔的路径），checkpoint 存储时以 `(thread_id, checkpoint_ns, checkpoint_id)` 为主键。父子图通过 `CONFIG_KEY_CHECKPOINT_MAP` 共享 checkpoint ID，但写入互不干扰。

---

### 维度 2：执行与调度（Execution，重点 40%）

#### 2.1 任务调度：PUSH vs PULL

`prepare_next_tasks()` 返回本 superstep 要执行的所有任务 dict：

```python
# PUSH 路径 — 来自 Send() 显式路由
tasks_channel = channels.get(TASKS)  # Topic[Send]
for idx, _ in enumerate(tasks_channel.get()):
    task = prepare_single_task((PUSH, idx), ...)

# PULL 路径 — 来自 channel 版本变化自动触发
for name in candidate_nodes:
    # 检查: channel_versions[trigger] > versions_seen[node][trigger] ?
    if _triggers(channels, checkpoint["channel_versions"], 
                 checkpoint["versions_seen"].get(name), ...):
        task = prepare_single_task((PULL, name), ...)
```

`updated_channels + trigger_to_nodes` 构成优化路径：只检查被更新的 channel 能触发哪些节点，而不扫描所有节点。这是一个 O(updated) 而不是 O(nodes) 的优化。

#### 2.2 任务 ID 生成：内容寻址

```python
task_id = xxh3_128_hexdigest(
    checkpoint_id_bytes,
    checkpoint_ns,      # "parent|child:uuid"
    str(step),
    name,               # 节点名
    PULL,
    *triggers,          # 触发 channel 列表（已排序）
)
```

同一 checkpoint + 同一步骤 + 同一节点触发条件 → 始终生成同一 task_id。这使 checkpoint 中的 `pending_writes` 可以在重启后与任务精确匹配，而不依赖时间戳或随机性。

#### 2.3 并发执行器：FuturesDict

```python
class FuturesDict(dict[F, PregelExecutableTask | None]):
    """Future→Task 的追踪字典，带事件通知。"""
    event: threading.Event | asyncio.Event
    callback: weakref.ref[Callable]
    counter: int    # 活跃 Future 数
    done: set[F]    # 已完成 Future

    def __setitem__(self, key: F, value: PregelExecutableTask | None):
        ...
        key.add_done_callback(partial(self.on_done, value))
    
    def on_done(self, task, fut):
        # 收集完成的 Future，counter--
        # counter==0 或有任务应该中止时 → event.set()
```

PregelRunner.tick 是一个 generator，yield 点是"给调用者机会消费已完成任务的输出"。外层 stream 循环在每次 yield 后立即发出 stream 事件，这就是 streaming 不等待全部完成的原因。

```python
def tick(self, tasks, ...) -> Iterator[None]:
    futures = FuturesDict(...)
    yield  # 1. 控制权回给调用者（发出首次事件）
    # ... 调度所有 tasks ...
    while len(futures) > 0:
        done, inflight = concurrent.futures.wait(...)
        if _should_stop_others(done):
            break
        yield  # 2. 每有任务完成，控制权回给调用者
    yield  # 3. 最终一次
```

#### 2.4 Retry 机制

RetryPolicy 支持多策略链（优先匹配第一个能处理异常的策略），带指数退避 + jitter：

```python
@dataclass
class RetryPolicy:
    initial_interval: float = 0.5
    backoff_factor: float = 2.0
    max_interval: float = 128.0
    max_attempts: int = 3
    jitter: bool = True
    retry_on: type[Exception] | Sequence[type[Exception]] | Callable = default_retry_on
```

重试时通过 `CONFIG_KEY_RESUMING=True` 告知 subgraph "我是在重试，跳过已完成的子任务"。这是一个优雅的 idempotency 设计。

#### 2.5 Interrupt-Resume 协议（进化版）

R43 偷了基本的 interrupt/resume。R68 看到的进化：

**多 interrupt 精确匹配**：
```python
# interrupt_id 用 xxh3_128 从 task_checkpoint_ns 派生
# PregelScratchpad.interrupt_counter 在每次 interrupt() 调用时递增
# 这样同一节点第 N 次 interrupt → 固定 interrupt_id

def interrupt(value):
    scratchpad = get_scratchpad()
    idx = scratchpad.interrupt_counter()
    interrupt_id = xxh3_128_hexdigest(task_checkpoint_ns, str(idx))
    # ...

# 恢复时，client 传 Command(resume={interrupt_id: value})
# 或者只有一个 pending interrupt 时传 Command(resume=value)（简化路径）
```

**_pending_interrupts() 追踪**：循环时比对 INTERRUPT 写和 RESUME 写，确定哪些 interrupt 还没有匹配的 resume。这解决了并发多 interrupt 场景的对应关系。

#### 2.6 CachePolicy（新特性，R43 未覆盖）

```python
@dataclass
class CachePolicy:
    key_func: Callable[..., str | bytes]  # 输入 → 缓存 key
    ttl: float | None = None
    # 存储到 BaseCache，key 格式: (CACHE_NS_WRITES, func_identifier, node_name)

# 使用时：
cache_key = CacheKey(
    (CACHE_NS_WRITES, identifier(proc), name),
    xxh3_128_hexdigest(args_key),
    cache_policy.ttl,
)
```

命中缓存的任务被标记为 `cached=True`，输出仍然通过 `output_writes` 发出（保持 stream 事件一致性），但不重新执行节点函数。

---

### 维度 3：状态持久化（Persistence）

#### 3.1 Checkpoint 数据结构（v4 格式）

```python
class Checkpoint(TypedDict):
    v: int                              # 版本号，当前 4
    id: str                             # uuid6，单调递增（可排序）
    ts: str                             # ISO 8601 时间戳
    channel_values: dict[str, Any]      # channel 名 → 序列化值
    channel_versions: ChannelVersions   # channel 名 → 版本号
    versions_seen: dict[str, ChannelVersions]  # 节点名 → {channel: version}
    updated_channels: list[str] | None  # 本 step 更新的 channel 列表
```

`versions_seen` 是驱动 PULL 调度的核心：`channel_versions[c] > versions_seen[node][c]` → 该节点被触发。这个设计使 checkpoint 自包含：仅凭 checkpoint 就能重建所有调度状态，不需要额外的"下一步执行什么"字段。

#### 3.2 SQLite Schema

```sql
-- WAL 模式，检查点合并
PRAGMA journal_mode=WAL;

CREATE TABLE checkpoints (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',  -- subgraph 命名空间路径
    checkpoint_id TEXT NOT NULL,             -- uuid6，可时序排序
    parent_checkpoint_id TEXT,
    type TEXT,          -- 序列化类型（msgpack / jsonplus）
    checkpoint BLOB,    -- 序列化的 Checkpoint 对象
    metadata BLOB,      -- 序列化的 CheckpointMetadata
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);

CREATE TABLE writes (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    idx INTEGER NOT NULL,   -- WRITES_IDX_MAP 中的特殊 channel 用 -1, -2 等负数
    channel TEXT NOT NULL,
    type TEXT,
    value BLOB,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
);
```

`writes` 表存储的是 **task 级中间写入**，不是最终 checkpoint。断点恢复时先从 `writes` 表重建 `pending_writes`，再重建各 task 的 `writes` 字段，从而精确恢复中断状态。

#### 3.3 Durability 三模式

| 模式 | 写入时机 | 使用场景 |
|------|----------|----------|
| `sync` | 每步后同步等待写完 | 默认，高可靠性 |
| `async` | `submit()` 后台并行写 | 长任务性能优化 |
| `exit` | 仅退出时写一次 | 无持久化需求的嵌套图 |

`async` 模式通过 `_put_checkpoint_fut = self.submit(...)` 链式等待：每次提交前等待上一次的 Future，保证 checkpoint 顺序写入，但下一步可以立即开始执行。

#### 3.4 CheckpointSaver 新增接口（R43 未覆盖）

```python
def delete_thread(self, thread_id: str) -> None: ...
def delete_for_runs(self, run_ids: Sequence[str]) -> None: ...
def copy_thread(self, source_thread_id: str, target_thread_id: str) -> None: ...
def prune(self, thread_ids: Sequence[str], *, strategy: str = "keep_latest") -> None: ...
```

这些是生产运维必要接口：线程删除、按 run_id 清理、线程克隆（fork 用于实验）、checkpoint 裁剪（保留最新 N 个）。

---

### 维度 4：流式输出（Streaming）

#### 4.1 StreamMode 类型

| 模式 | 内容 | 典型用途 |
|------|------|----------|
| `values` | 每步后完整 state | 外部消费者订阅状态变化 |
| `updates` | 节点名 → 输出 delta | 调试，了解哪个节点改了什么 |
| `messages` | token 级 LLM 输出 + metadata | 前端打字机效果 |
| `custom` | node 内通过 StreamWriter 写的任意值 | 进度通知、中间结果 |
| `checkpoints` | checkpoint 快照 | 持久化观测 |
| `tasks` | task 开始/完成事件 | 执行追踪 |
| `debug` | tasks + checkpoints 的 wrapper | 开发调试 |

#### 4.2 多模式复用：DuplexStream

```python
def DuplexStream(*streams: StreamProtocol) -> StreamProtocol:
    def __call__(value: StreamChunk) -> None:
        for stream in streams:
            if value[1] in stream.modes:  # value[1] 是 mode 字段
                stream(value)
    return StreamProtocol(__call__, {mode for s in streams for mode in s.modes})
```

调用者可以同时订阅多个 mode，底层只有一个事件流，DuplexStream 按 mode 过滤分发。

#### 4.3 messages 模式的实现

`StreamMessagesHandler` 是一个 `BaseCallbackHandler`，挂在 LangChain callback 链上。当节点内调用 LLM 时，`on_llm_new_token` 等回调触发 token 流式输出：

```python
def _emit(self, meta: Meta, message: BaseMessage, *, dedupe: bool = False):
    self.stream((meta[0], "messages", (message, meta[1])))
    # meta[1] 包含 langgraph_step, langgraph_node, langgraph_triggers 等元数据
```

subgraph 的 messages 是否向上传播由 `subgraphs=True/False` 控制，通过 `parent_ns` 判断事件来源。

#### 4.4 流事件携带 namespace

每个流事件格式：`(checkpoint_ns: tuple[str,...], mode: StreamMode, data: Any)`。`checkpoint_ns` 是从根图到当前 subgraph 的路径，消费者可以通过 ns 区分事件来自哪一层图。

---

### 维度 5：Human-in-the-Loop（HITL）

#### 5.1 interrupt() 原语

```python
# 节点内调用
def my_node(state):
    review = interrupt({"question": "是否批准？", "context": state})
    # 此处暂停。恢复后 review = Command(resume=value).resume
    if review == "approve":
        ...
```

底层：`interrupt()` 调用 `PregelScratchpad.interrupt_counter()` 生成 idx，用 `xxh3_128(task_checkpoint_ns, str(idx))` 生成唯一 `interrupt_id`，写入 INTERRUPT 特殊 channel，抛出 `GraphInterrupt` 异常。

#### 5.2 PregelScratchpad：执行上下文

```python
@dataclasses.dataclass
class PregelScratchpad:
    step: int
    stop: int
    call_counter: Callable[[], int]       # 生成 call idx
    interrupt_counter: Callable[[], int]  # 生成 interrupt idx（确保唯一 id）
    get_null_resume: Callable[[bool], Any]
    resume: list[Any]                     # 已解析的 resume 值列表
    subgraph_counter: Callable[[], int]   # 同一个节点多次调用 subgraph 的计数
```

每个 task 拿到一个独立的 Scratchpad 实例，counter 从 0 开始。这确保同一 task 的第 N 次 `interrupt()` 调用总是生成同一 interrupt_id（只要代码路径不变），从而支持确定性恢复。

#### 5.3 恢复协议

```python
# 恢复单个 interrupt
graph.invoke(Command(resume="approved"), config)

# 恢复多个 pending interrupts（必须指定 id）
graph.invoke(Command(resume={
    "abc123...": "approved",    # interrupt_id → resume value
    "def456...": "rejected",
}), config)
```

`_first()` 方法在收到 `Command(resume=...)` 时判断是否进入 resuming 模式：不清除 RESUME writes，保留之前解析的 resume 值。

---

### 维度 6：扩展与生态（Extensibility）

#### 6.1 Runtime 对象（v0.6.0，重要新特性）

```python
@dataclass(frozen=True, slots=True)
class Runtime(Generic[ContextT]):
    context: ContextT        # 不可变依赖（user_id, db_conn 等）
    store: BaseStore | None  # 跨会话持久化存储
    stream_writer: StreamWriter   # 写自定义流事件
    previous: Any            # 上次 entrypoint 返回值
    execution_info: ExecutionInfo | None   # 当前 task 元数据
    server_info: ServerInfo | None         # 部署平台信息

    def merge(self, other: Runtime) -> Runtime: ...
    def override(self, **overrides) -> Runtime: ...
    def patch_execution_info(self, **overrides) -> Runtime: ...
```

节点函数通过类型注解注入：
```python
def my_node(state: State, runtime: Runtime[Context]) -> State:
    user_id = runtime.context.user_id
    store = runtime.store
    stream_writer = runtime.stream_writer
```

这彻底解决了"依赖通过 configurable dict 传递"的痛点：类型安全、IDE 可补全、不可变（无副作用风险）。

#### 6.2 context_schema 取代 config_schema

`config_schema` 已 deprecated（v1.0），`context_schema` 是替代品：

```python
graph = StateGraph(state_schema=State, context_schema=Context)
result = graph.invoke(input, context=Context(user_id="123"))  # 直接传对象
```

运行时 context 通过 `Runtime.context` 注入节点，与 RunnableConfig 彻底分离。

#### 6.3 GraphCallbackHandler（最新 commit #7429）

```python
class GraphCallbackHandler(BaseCallbackHandler):
    def on_interrupt(self, event: GraphInterruptEvent) -> Any: ...
    def on_resume(self, event: GraphResumeEvent) -> Any: ...

@dataclass(frozen=True)
class GraphInterruptEvent:
    run_id: UUID | None
    status: GraphLifecycleStatus    # "interrupt_before" | "interrupt_after"
    checkpoint_id: str
    checkpoint_ns: tuple[str, ...]
    interrupts: tuple[Interrupt, ...]

@dataclass(frozen=True)
class GraphResumeEvent:
    run_id: UUID | None
    status: GraphLifecycleStatus
    checkpoint_id: str
    checkpoint_ns: tuple[str, ...]
```

通过 `config["callbacks"]` 注入，在 interrupt 和 resume 时被调用。这是 **第一个类型化的图生命周期钩子**，之前只能靠 stream 事件推断。

#### 6.4 entrypoint.final：保存与返回值分离

```python
@entrypoint(checkpointer=saver)
def workflow(input: int, *, previous: Any = None) -> entrypoint.final[int, int]:
    # value: 返回给调用者的值
    # save: 存入 checkpoint 的值（下次 previous）
    return entrypoint.final(value=previous or 0, save=2 * input)
```

用途：返回一个计算结果，同时保存另一个（可能更精简的）状态用于下次恢复，两者无需相同。

#### 6.5 Pregel.prune / copy_thread（新增 API）

```python
checkpointer.prune(["thread_1", "thread_2"], strategy="keep_latest")
checkpointer.copy_thread("prod-thread", "experiment-thread-fork")
```

`copy_thread` 用于 time-travel 调试：把生产 thread 克隆到实验 thread，然后在实验环境重放或修改。

---

## 五层深度分析（核心模块）

以 `PregelLoop._loop` 流程为分析对象：

### 调度层（Dispatch Layer）
`prepare_next_tasks()` → `_triggers()` → `task_id = xxh3_128(checkpoint_id, ns, step, name, ...)`

关键：任务 ID 是从 checkpoint 内容派生的，不是随机的。同一 checkpoint、同一步骤、同一触发条件 → 同一 ID。这使"断点恢复后精确匹配 pending_writes"成为可能。

### 实践层（Execution Layer）
`PregelRunner.tick()` + `FuturesDict` + `run_with_retry()`

关键：FuturesDict 用 `weakref.WeakMethod(self.commit)` 作为 done_callback，避免循环引用（runner→futures→runner）。`commit()` 在任务完成时把 `task.writes` 通过 `put_writes()` 写入 `pending_writes` 并触发 stream 输出。

### 消费层（Consumer Layer）
`output_writes()` → `_emit("updates", ...)` → stream

关键：stream 事件在 task 完成时 **立即** 发出（不等 superstep 结束），但写入不对本 superstep 内其他任务可见（写入在 `apply_writes` 后才生效）。这是 streaming 的"最早出" vs 状态隔离的平衡。

### 状态层（State Layer）
`apply_writes()` → `channel.update(vals)` → `checkpoint["channel_versions"][chan] = next_version`

关键：`sorted(tasks, key=lambda t: task_path_str(t.path[:3]))` 保证 reduce 顺序确定性，即使并发执行的任务完成顺序不同，聚合结果也一致。

### 边界层（Boundary Layer）
`should_interrupt()` + `GraphInterrupt` 异常 + `_suppress_interrupt()`

关键：`GraphInterrupt` 是一个特殊异常，在 loop 退出时被 `_suppress_interrupt()` 捕获并 **suppress**（返回 True，不向上传播）。这使调用者看到的是"正常完成"，而不是异常。subgraph 内的 interrupt 会向上冒泡，由根图处理。

---

## Steal Sheet

### P0 — 必偷（3 个，R43 未覆盖）

#### P0-1：Runtime 对象 — 类型安全依赖注入容器

| 项目 | 内容 |
|------|------|
| **来源文件** | `libs/langgraph/langgraph/runtime.py` |
| **核心代码** | `@dataclass(frozen=True, slots=True) class Runtime(Generic[ContextT])` |
| **我们现状** | 依赖通过 `configurable` dict 传递，无类型，必须写字符串 key，IDE 无法补全 |
| **差距** | 无法在节点函数中类型安全地访问 user_id、store、stream_writer 等运行时依赖 |
| **适配方案** | 在 `src/governance/executor.py` 创建 `AgentRuntime` dataclass，包含 `task_id, thread_id, context, store_ref, stream_fn`。在 task 准备阶段构建，作为参数注入而非 dict 传递 |
| **复杂度** | ~3h，非侵入式（可在新参数位置加，保持向后兼容） |

**验证三重**：
1. `Runtime` 是 frozen dataclass，强制不可变，节点无法意外修改共享状态 ✓
2. `merge()` 和 `override()` 方法支持 subgraph 继承父图 runtime 并选择性覆盖 ✓  
3. `execution_info.node_attempt` 记录当前是第几次重试，节点可感知 ✓

**知识不可替代性**：frozen + slots dataclass 作为依赖注入容器，比 dict 快（slots 无 __dict__），比类实例更安全（frozen 防止修改）。这不是简单的"用 dataclass 封装 dict"，关键是通过泛型 `Runtime[ContextT]` 把 context 类型推导出来，节点函数的类型注解才能工作。

---

#### P0-2：GraphCallbackHandler — 类型化生命周期钩子

| 项目 | 内容 |
|------|------|
| **来源文件** | `libs/langgraph/langgraph/callbacks.py` |
| **核心代码** | `class GraphCallbackHandler(BaseCallbackHandler)` + `GraphInterruptEvent` + `GraphResumeEvent` |
| **我们现状** | hook 系统基于 shell 脚本（`.claude/hooks/`），无法感知 agent 执行内部的 interrupt/resume 生命周期 |
| **差距** | 当一个 agent 被人工审批打断、或从断点恢复时，我们无法触发自定义逻辑（如审计日志、通知、状态同步）|
| **适配方案** | 在 `src/governance/approval.py` 的 ApprovalGateway 添加 `on_interrupt(event: InterruptEvent)` 和 `on_resume(event: ResumeEvent)` 回调接口。在 executor 的 interrupt/resume 路径调用这些钩子 |
| **复杂度** | ~2h，主要是定义事件类型 + 在 executor 中插入调用点 |

**对比矩阵**：

| 特性 | LangGraph GraphCallbackHandler | Orchestrator 现有 Hook |
|------|-------------------------------|----------------------|
| 触发点类型 | interrupt, resume（图层级） | PreToolUse, PostToolUse 等（工具层级） |
| 事件类型化 | frozen dataclass，强类型 | dict / 环境变量 |
| checkpoint 关联 | 携带 checkpoint_id 和 ns | 无 |
| 调用方式 | Python callback 对象 | shell 进程 |
| subgraph 区分 | checkpoint_ns 路径 | 无 |

---

#### P0-3：task-level CachePolicy — 跨会话结果缓存

| 项目 | 内容 |
|------|------|
| **来源文件** | `libs/langgraph/langgraph/pregel/_algo.py`（第 648-665 行），`libs/langgraph/langgraph/types.py`（CachePolicy 定义） |
| **核心代码** | `CacheKey = (CACHE_NS_WRITES, identifier(proc), name, xxh3_128(args_key))` |
| **我们现状** | `src/governance/agent_cache.py` 存在，但粒度是 task 级别的全结果缓存，没有内容寻址 |
| **差距** | 我们的缓存以 task_id（随机）为 key，同样输入的两次执行不命中缓存 |
| **适配方案** | 在 `agent_cache.py` 的 cache key 生成逻辑中加入内容哈希：`xxh3_128(prompt_content + tool_calls_json)`，替换当前的 `task_id` |
| **复杂度** | ~1.5h，修改 cache key 生成逻辑，其余不变 |

---

### P1 — 应偷（3 个，执行层细化）

#### P1-1：FuturesDict weakref 回调模式

当前 `src/governance/group_orchestration.py` 的 `ThreadPoolExecutor + as_completed` 在任务完成时没有细粒度的 Task→Future 追踪。FuturesDict 模式的价值：

```python
# 当前做法（粗粒度）
futures = {executor.submit(run, task): task for task in tasks}
for future in as_completed(futures):
    result = future.result()
    task = futures[future]
    handle_result(task, result)

# FuturesDict 模式（细粒度）
futures = FuturesDict(callback=weakref.WeakMethod(self.commit), ...)
futures[submit(run, task)] = task
# done_callback 自动触发，counter 自动递减，event 自动 set
```

好处：不需要 `as_completed` 阻塞等待，任务完成时立即通过回调处理，可以在等待期间处理其他逻辑（如发出中间 stream 事件）。适配代价 ~2h。

#### P1-2：entrypoint.final 的返回值/存储分离

当前 `src/governance/executor.py` 的 ExecutionResponse 只有一个值。某些任务需要"向调用者返回摘要，但保存完整结果供下次恢复"。添加 `ExecutionFinal(value, save)` 原语，适配代价 ~1h。

#### P1-3：subgraph checkpoint_ns 路径系统

当前 Orchestrator 的嵌套执行（子任务调用子任务）没有 checkpoint 命名空间隔离，恢复时无法定位特定层的状态。需要引入 `"parent_task:id|child_task:id"` 格式的 ns 路径，适配代价 ~4h（需要修改 executor 和 checkpoint_recovery）。

---

### P2 — 参考（2 个）

#### P2-1：Updated_channels + trigger_to_nodes 的 O(updated) 优化

当前 `prepare_next_tasks` 每步都扫描全部节点判断是否触发。LangGraph 的优化：维护一个 `trigger_to_nodes: dict[channel_name, list[node_name]]` 映射，只在有 channel 被更新时才检查对应的节点。对于大型图（100+ 节点）有显著性能提升。Orchestrator 当前规模不到 20 个"节点"，收益有限，可以在规模增长后考虑。

#### P2-2：`prune` + `copy_thread` 运维接口

生产环境 checkpoint 积累后需要清理和分叉能力。参考 SQLite 的实现，在 Orchestrator 的 `checkpoint_recovery.py` 添加对应接口。当前优先级低（数据量小），但接口设计值得参考。

---

## 架构对比：我们 vs LangGraph（逐层）

```
LangGraph                          Orchestrator
─────────────────────────────      ─────────────────────────────
Pregel（BSP 超步引擎）          ←→  TaskExecutor + group_orchestration
  ├─ PregelLoop.tick()           ←→  executor.py 的主循环
  ├─ PregelRunner（并发器）       ←→  ThreadPoolExecutor + as_completed
  └─ FuturesDict（追踪器）        ←→  ❌ 无对应（直接 dict[future]）

Channel 系统                    ←→  channel_reducer.py（R43 已偷）
  ├─ LastValue / BinaryOp        ←→  LastValueChannel / ReducerChannel ✓
  ├─ EphemeralValue              ←→  ❌ 无对应（值跨步骤持久化）
  ├─ UntrackedValue              ←→  ❌ 无对应（所有值都被 checkpoint）
  └─ NamedBarrierValue           ←→  ❌ 无对应（fan-in 屏障）

Checkpoint 系统                 ←→  checkpoint_recovery.py（R43 已偷基础）
  ├─ channel_versions 版本管理   ←→  StructuredCheckpoint.channel_versions ✓
  ├─ versions_seen 调度引擎      ←→  ❌ 无对应（需要自己判断触发条件）
  ├─ pending_writes 中间写入     ←→  StructuredCheckpoint.pending_writes ✓
  ├─ Durability 三模式           ←→  Durability 三模式 ✓
  ├─ prune / copy_thread         ←→  ❌ 无对应
  └─ delete_thread / for_runs   ←→  ❌ 无对应

Runtime 对象                    ←→  ❌ 无对应（用 configurable dict）
  ├─ context（类型安全依赖）     ←→  无类型的 spec dict 传递
  ├─ store（跨会话存储）         ←→  MemoryStore / storage/ 目录
  ├─ stream_writer               ←→  event_bus.py（松散）
  └─ execution_info              ←→  无统一追踪对象

GraphCallbackHandler            ←→  .claude/hooks/（shell 脚本，粗粒度）
  ├─ on_interrupt                ←→  approval.py（逻辑存在，无钩子接口）
  └─ on_resume                  ←→  ❌ 无对应

CachePolicy                     ←→  agent_cache.py（存在，key 设计不同）
  └─ xxh3 内容寻址               ←→  ❌ task_id 随机 key（不命中同输入）
```

---

## 路径依赖分析

### 不应直接引入 LangGraph 的原因

1. **LangChain 依赖**：LangGraph 深度耦合 `langchain_core.runnables`，引入等于拉入整个 LangChain 生态（RunnableConfig、callbacks manager 等）。Orchestrator 已经有自己的 executor/router 抽象，替换代价远高于偷设计。

2. **异步模型冲突**：LangGraph 的 AsyncPregelLoop 基于 asyncio event loop，而 Orchestrator 混用 asyncio + threading（executor.py 里有 `anyio`）。直接混用会引发 loop 冲突。

3. **Checkpoint 格式不兼容**：LangGraph checkpoint 格式（uuid6 ID + msgpack 序列化）与 Orchestrator 现有 `StructuredCheckpoint` 结构不同，迁移需要数据转换。

### 应该偷的是设计模式，而不是代码

- **Runtime 模式** → 在现有 executor 里添加 AgentRuntime dataclass（不引入任何 LangGraph 依赖）
- **FuturesDict 模式** → 100 行 Python，完全自包含，可以直接 copy-paste-adapt
- **CachePolicy 模式** → 修改 agent_cache.py 的 key 生成逻辑（1 行核心变化）
- **GraphCallbackHandler 模式** → 在 approval.py 定义 Protocol 接口，现有逻辑不动

---

## 实施路线图

| 优先级 | 目标文件 | 变更说明 | 工时 |
|--------|---------|---------|------|
| P0 | `src/governance/execution_context.py`（新增或扩展） | AgentRuntime dataclass：task_id, context, store_ref, stream_fn, execution_info | 3h |
| P0 | `src/governance/approval.py` | 添加 on_interrupt(event) / on_resume(event) Protocol 接口 | 2h |
| P0 | `src/governance/agent_cache.py` | cache key 改为 `xxh3_128(prompt + tools)` 内容寻址 | 1.5h |
| P1 | `src/governance/group_orchestration.py` | FuturesDict 模式替换 as_completed，支持边完成边 stream | 2h |
| P1 | `src/governance/executor.py` | 支持 ExecutionFinal(value, save) 分离返回值和存储值 | 1h |
| P2 | `src/governance/checkpoint_recovery.py` | prune/copy_thread 接口 | 3h |

**总工时估计**: P0 = 6.5h，P1 = 3h，P2 = 3h

---

## 关键代码快照

**apply_writes 排序确保 reducer 确定性**：
```python
# libs/langgraph/langgraph/pregel/_algo.py:242
tasks = sorted(tasks, key=lambda t: task_path_str(t.path[:3]))
```

**interrupt_id 内容寻址（不是随机）**：
```python
# 来自 _scratchpad + _algo.py
interrupt_id = xxh3_128_hexdigest(task_checkpoint_ns.encode())
# task_checkpoint_ns = f"{checkpoint_ns}{NS_END}{task_id}"
# → 同一节点的同一次 interrupt() 调用始终生成同一 id
```

**Durability 触发点**：
```python
# libs/langgraph/langgraph/pregel/_loop.py:394
if self.durability != "exit" and self.checkpointer_put_writes is not None:
    self.submit(self.checkpointer_put_writes, ...)
```

**Runtime 注入节点**：
```python
# libs/langgraph/langgraph/runtime.py:230
def get_runtime(context_schema=None) -> Runtime[ContextT]:
    runtime = cast(Runtime, get_config()[CONF].get(CONFIG_KEY_RUNTIME))
    return runtime
```

**checkpoint 版本驱动调度**：
```python
# libs/langgraph/langgraph/pregel/_algo.py（_triggers 函数）
# channel_versions[c] > versions_seen[node_name][c]  → 节点被触发
```

---

*分析完成。P0 项目可直接开始实施，无需等待其他条件。*
