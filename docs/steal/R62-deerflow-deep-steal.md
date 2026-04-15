# R62 DeerFlow 深度偷师报告

**来源**: https://github.com/bytedance/deer-flow (ByteDance)
**分析日期**: 2026-04-14
**分析师**: Claude Sonnet 4.6
**分支**: steal/round-deep-rescan-r60
**前情**: 2026-04-01 已做过两轮表层扫描 (R57, deep-analysis)。本轮针对近期更新的异步内存系统、中间件架构、subagent 执行引擎做代码级深挖。

---

## 一、执行摘要

这次深扫比 4 月 1 日的扫描质量高出一个数量级——上次只读了 skills / sandbox / gateway，这次直接钻进了最有价值的核心层：

| 模块 | 上次覆盖 | 本次覆盖 |
|------|---------|---------|
| Memory 系统 | 表面 | 完整（updater/queue/storage/middleware/hook/prompt） |
| 中间件架构 | 未覆盖 | 完整（14 个中间件逐一分析） |
| Subagent 执行引擎 | 未覆盖 | 完整（executor/scheduler/isolated-loop） |
| 循环检测 | 未覆盖 | 完整（双层检测机制） |
| 熔断器 | 未覆盖 | 完整（closed/half-open/open 三态） |
| 工具搜索/延迟加载 | 未覆盖 | 完整 |

**核心发现**: DeerFlow 的工程密度远超表面看起来的 demo 项目。它是一个经过生产验证的 Agent 操作系统，最值得偷的是：**中间件管道架构**、**内存异步刷新机制**、**双层循环检测**。

---

## 二、架构全貌（调度层→实践层→消费层→状态层→边界层）

### 2.1 调度层（Scheduling）

```
HTTP 请求
  ↓
FastAPI Gateway (app/gateway/)
  ↓
make_lead_agent(config: RunnableConfig)  ← factory.py 入口
  ↓
create_agent(model, tools, middleware, system_prompt, state_schema=ThreadState)
  ↓
LangGraph CompiledStateGraph
```

`make_lead_agent` 是核心工厂，职责：
1. 解析 `configurable` 字段（model_name、thinking_enabled、is_plan_mode、subagent_enabled 等）
2. 模型名降级（requested → agent_config.model → global_default）
3. 注入 LangSmith trace metadata
4. 组装 middleware chain（14 个中间件，顺序强依赖）

### 2.2 实践层（Execution）

中间件链固定顺序（来自 `factory.py:_build_middlewares` 注释）：

```
0  ThreadDataMiddleware         ← thread workspace 初始化
1  UploadsMiddleware            ← 文件上传路径注入
2  SandboxMiddleware            ← 沙箱生命周期
3  DanglingToolCallMiddleware   ← 修复悬挂的 tool call
4  GuardrailMiddleware          ← 可选，tool call 权限拦截
5  ToolErrorHandlingMiddleware  ← tool 异常 → ToolMessage 转换
6  SummarizationMiddleware      ← 上下文压缩（token 触发）
7  TodoMiddleware               ← plan_mode 任务跟踪
8  TokenUsageMiddleware         ← token 计量日志
9  TitleMiddleware              ← 首轮后生成对话标题
10 MemoryMiddleware             ← 对话结束后异步写内存
11 ViewImageMiddleware          ← vision 模型图片预处理
12 DeferredToolFilterMiddleware ← 隐藏未加载的 MCP 工具
13 SubagentLimitMiddleware      ← 并发 subagent 数量限制
14 LoopDetectionMiddleware      ← 双层循环检测
   (custom middlewares)
15 ClarificationMiddleware      ← 永远最后，拦截澄清请求
```

LLMErrorHandlingMiddleware（熔断器+重试）通过 `build_lead_runtime_middlewares` 插在链首。

### 2.3 消费层（State Access）

`ThreadState` 是图状态 schema：

```python
class ThreadState(AgentState):
    sandbox: NotRequired[SandboxState | None]
    thread_data: NotRequired[ThreadDataState | None]
    title: NotRequired[str | None]
    artifacts: Annotated[list[str], merge_artifacts]   # 自定义 reducer，去重合并
    todos: NotRequired[list | None]
    uploaded_files: NotRequired[list[dict] | None]
    viewed_images: Annotated[dict[str, ViewedImageData], merge_viewed_images]  # 空 dict = 清空
```

`merge_artifacts` 和 `merge_viewed_images` 是 LangGraph Annotated reducer 的典型用法——不是替换，是合并。

### 2.4 状态层（Persistence）

Checkpointer 三后端支持：
- `memory`: InMemorySaver（开发/测试）
- `sqlite`: AsyncSqliteSaver（轻量生产）
- `postgres`: AsyncPostgresSaver（分布式）

通过 `async with make_checkpointer() as cp:` 封装，资源生命周期与 FastAPI lifespan 绑定。

### 2.5 边界层（Boundaries）

**安全边界** — `SandboxAuditMiddleware`:
- 两阶段 Pass：先全字符串扫描，再 shlex 分割子命令分别扫描
- 三级判定：`block` (rm -rf/, curl|sh 等) / `warn` (pip install, chmod 777) / `pass`
- Fail-closed：未闭合引号→视为可疑，直接 block
- 命令长度上限 10000 字符

**权限边界** — `GuardrailMiddleware`:
- 每个 tool call 进 `GuardrailProvider.evaluate()`，返回 allow/deny + reason
- fail_closed=True（默认）：provider 报错也拦截
- 拦截后返回 error ToolMessage，让 Agent 自己决定降级策略

---

## 三、六维扫描

### 维度 1：安全/治理

#### 1.1 双阶段命令扫描（`sandbox_audit_middleware.py`）

```python
def _classify_command(command: str) -> str:
    # Pass 1: 整体高风险扫描（捕获跨语句的模式，如 fork bomb）
    normalized = " ".join(command.split())
    for pattern in _HIGH_RISK_PATTERNS:
        if pattern.search(normalized):
            return "block"
    
    # Pass 2: 拆分子命令，逐条分类
    sub_commands = _split_compound_command(command)
    worst = "pass"
    for sub in sub_commands:
        verdict = _classify_single_command(sub)
        if verdict == "block":
            return "block"  # short-circuit
        if verdict == "warn":
            worst = "warn"
    return worst
```

关键点：`_split_compound_command` 是 quote-aware 的手写解析器（非 shlex），能正确处理 `safe;rm -rf /` 这种没有空格的拼接。

#### 1.2 GuardrailProvider 接口

```python
@dataclass
class GuardrailRequest:
    tool_name: str
    tool_input: dict
    agent_id: str | None
    timestamp: str

@dataclass  
class GuardrailDecision:
    allow: bool
    policy_id: str | None = None
    reasons: list[GuardrailReason] = field(default_factory=list)
```

这是纯接口设计——DeerFlow 自己没有内置 GuardrailProvider 实现，用户自己接。fail_closed 确保没有 provider 时默认拦截。

#### 1.3 Agent 名称路径安全

```python
AGENT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9-]+$")
```
FileMemoryStorage 在写文件路径前验证 agent_name 格式，防止路径穿越。

**我们的差距**: 我们的 hook 系统缺乏 bash 命令的双阶段扫描。`guard-redflags.sh` 只做简单的关键字检测，没有处理 `cmd1&&cmd2;cmd3` 这种无空格拼接，也没有 shlex 解析。

---

### 维度 2：内存/学习

这是本次最大的发现。DeerFlow 的内存系统是一个完整的工程。

#### 2.1 内存结构（`storage.py:create_empty_memory`）

```json
{
  "version": "1.0",
  "lastUpdated": "2026-04-14T...",
  "user": {
    "workContext": {"summary": "...", "updatedAt": ""},
    "personalContext": {"summary": "...", "updatedAt": ""},
    "topOfMind": {"summary": "...", "updatedAt": ""}
  },
  "history": {
    "recentMonths": {"summary": "...", "updatedAt": ""},
    "earlierContext": {"summary": "...", "updatedAt": ""},
    "longTermBackground": {"summary": "...", "updatedAt": ""}
  },
  "facts": [
    {
      "id": "fact_a1b2c3d4",
      "content": "...",
      "category": "preference|knowledge|context|behavior|goal|correction",
      "confidence": 0.85,
      "createdAt": "...",
      "source": "thread_id"
    }
  ]
}
```

分两轴：**用户当前状态**（user 三级：工作/个人/当前关注）和**历史积累**（history 三级：近几月/更早/长期背景）。Facts 是原子事实，带置信度过滤（阈值 0.7）和上限（max 100，超了按置信度排序截断）。

#### 2.2 异步更新核心机制（`updater.py`）

**P0 代码片段 — 嵌套事件循环处理：**

```python
_SYNC_MEMORY_UPDATER_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="memory-updater-sync",
)
atexit.register(lambda: _SYNC_MEMORY_UPDATER_EXECUTOR.shutdown(wait=False))


def _run_async_update_sync(coro: Awaitable[bool]) -> bool:
    """从 sync 代码运行 async 内存更新，包括嵌套 loop 场景"""
    handed_off = False
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        
        if loop is not None and loop.is_running():
            # 已有 event loop 在跑（FastAPI 等）：丢到独立线程的新 loop
            future = _SYNC_MEMORY_UPDATER_EXECUTOR.submit(asyncio.run, coro)
            handed_off = True
            return future.result()
        
        # 没有 event loop：直接 asyncio.run
        handed_off = True
        return asyncio.run(coro)
    except Exception:
        if not handed_off:
            close = getattr(coro, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        logger.exception("Failed to run async memory update from sync context")
        return False
```

这个模式解决了一个真实的工程痛点：async web server 里调用 sync code，sync code 又想 await——直接 `asyncio.run()` 会报"cannot be called when another event loop is running"。解法是 `submit(asyncio.run, coro)` 在独立线程开新 loop。

**P0 代码片段 — async 更新主路径：**

```python
async def aupdate_memory(self, messages, thread_id=None, agent_name=None, 
                          correction_detected=False, reinforcement_detected=False):
    try:
        # 阻塞 I/O（读文件、构建 prompt）→ asyncio.to_thread
        prepared = await asyncio.to_thread(
            self._prepare_update_prompt,
            messages=messages, agent_name=agent_name,
            correction_detected=correction_detected,
            reinforcement_detected=reinforcement_detected,
        )
        if prepared is None:
            return False
        
        current_memory, prompt = prepared
        model = self._get_model()
        # LLM 调用 → async
        response = await model.ainvoke(prompt)
        # 阻塞 I/O（写文件）→ asyncio.to_thread
        return await asyncio.to_thread(
            self._finalize_update,
            current_memory=current_memory,
            response_content=response.content,
            thread_id=thread_id,
            agent_name=agent_name,
        )
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse LLM response for memory update: %s", e)
        return False
    except Exception as e:
        logger.exception("Memory update failed: %s", e)
        return False
```

关键设计：`asyncio.to_thread()` 把文件 I/O 包到线程池，LLM 调用走 async——不阻塞事件循环。

#### 2.3 防写入会话临时数据（`updater.py`）

```python
_UPLOAD_SENTENCE_RE = re.compile(
    r"[^.!?]*\b(?:"
    r"upload(?:ed|ing)?(?:\s+\w+){0,3}\s+(?:file|files?|document|..."
    r"|/mnt/user-data/uploads/"
    r"|<uploaded_files>"
    r")[^.!?]*[.!?]?\s*",
    re.IGNORECASE,
)

def _strip_upload_mentions_from_memory(memory_data):
    """文件上传是 session-scoped，写入长期内存会导致下次会话找不到文件"""
```

这个细节说明 DeerFlow 在真实业务中踩过坑：把"用户上传了 X 文件"写进长期记忆，导致下次会话 Agent 去找不存在的文件。

#### 2.4 纠错/强化信号检测（`message_processing.py`）

```python
_CORRECTION_PATTERNS = (
    re.compile(r"\bthat(?:'s| is) (?:wrong|incorrect)\b", re.IGNORECASE),
    re.compile(r"不对"),
    re.compile(r"你理解错了"),
    re.compile(r"重新来"),
    re.compile(r"改用"),
    ...
)
_REINFORCEMENT_PATTERNS = (
    re.compile(r"\bperfect(?:[.!?]|$)", re.IGNORECASE),
    re.compile(r"对[，,]?\s*就是这样(?:[。！？!?.]|$)"),
    re.compile(r"继续保持(?:[。！？!?.]|$)"),
    ...
)
```

中英双语信号检测。触发纠错信号时，prompt 里注入特殊提示，让 LLM 以 confidence ≥ 0.95 记录 "correction" 类别 fact。

#### 2.5 防消重（去重）

```python
def _fact_content_key(content) -> str | None:
    return content.strip().casefold() if isinstance(content, str) else None

# 在 _apply_updates 里：
existing_fact_keys = {fact_key for fact_key in 
    (_fact_content_key(fact.get("content")) for fact in current_memory.get("facts", []))
    if fact_key is not None}

for fact in new_facts:
    ...
    if fact_key is not None and fact_key in existing_fact_keys:
        continue  # 大小写不敏感去重
```

#### 2.6 Debounce Queue（`queue.py`）

```python
class MemoryUpdateQueue:
    """带 debounce 的内存更新队列。
    同一 thread_id 的多次更新会合并——只保留最新的消息，
    但 correction/reinforcement 信号取 OR（两次都触发则合并）。
    """
    def _enqueue_locked(self, *, thread_id, messages, agent_name,
                         correction_detected, reinforcement_detected):
        existing_context = next(
            (context for context in self._queue if context.thread_id == thread_id),
            None,
        )
        # 信号合并
        merged_correction_detected = correction_detected or (
            existing_context.correction_detected if existing_context else False
        )
        # 覆盖旧条目
        self._queue = [c for c in self._queue if c.thread_id != thread_id]
        self._queue.append(context)
```

默认 debounce 30 秒。同一线程内多次对话触发写入时，只处理最后一次消息，但不丢 correction 信号。

#### 2.7 总结前钩子（`summarization_hook.py`）

这是 Memory 和 Context Compression 的联动：**Summarization 压缩前，先把即将被删除的消息 flush 到 Memory Queue**，防止上下文压缩导致记忆丢失。

```python
def memory_flush_hook(event: SummarizationEvent) -> None:
    """把即将被 summarize 掉的消息提前写入 memory"""
    filtered_messages = filter_messages_for_memory(list(event.messages_to_summarize))
    ...
    queue.add_nowait(  # 立即触发，不 debounce
        thread_id=event.thread_id,
        messages=filtered_messages,
        ...
    )
```

---

### 维度 3：执行/编排

#### 3.1 中间件 @Next/@Prev 插槽系统（`factory.py`）

这是这次最有创意的发现。DeerFlow 的中间件链不是硬编码的列表，而是支持通过装饰器指定相对位置：

```python
@Next(LoopDetectionMiddleware)
class MyCustomMiddleware(AgentMiddleware):
    """这个中间件会被插入到 LoopDetectionMiddleware 之后"""
    pass

@Prev(ClarificationMiddleware)  
class AnotherMiddleware(AgentMiddleware):
    """这个中间件会被插入到 ClarificationMiddleware 之前"""
    pass
```

`_insert_extra` 函数处理冲突检测（两个 middleware 都 @Next 同一个锚点 → 报错）和循环依赖检测。ClarificationMiddleware 必须永远在链尾——即使 @Next 把它推走，最后也会被拉回来。

#### 3.2 Subagent 三重执行路径（`executor.py`）

```
SubagentExecutor.execute(task)
  ├─ 没有运行中的 event loop
  │    └─ asyncio.run(self._aexecute(task))
  │
  └─ 已有运行中的 event loop（FastAPI 环境）
       └─ _isolated_loop_pool.submit(self._execute_in_isolated_loop, task)
             └─ 新线程里：asyncio.new_event_loop() → loop.run_until_complete(_aexecute)
                           + 完整的 cleanup（cancel pending tasks, shutdown_asyncgens）
```

关键设计：新线程里的 isolated loop 避免了与父 loop 共享 httpx client 等 async primitive 的冲突。

#### 3.3 协作式取消（`executor.py`）

```python
# 执行中，每次 astream yield 都检查
async for chunk in agent.astream(state, config=run_config, stream_mode="values"):
    if result.cancel_event.is_set():
        logger.info("Subagent cancelled by parent")
        result.status = SubagentStatus.CANCELLED
        return result
    final_state = chunk
    # 收集 AI messages...
```

`SubagentResult.cancel_event` 是 `threading.Event`，父线程通过 `request_cancel_background_task(task_id)` 发送取消信号，子线程在 astream 迭代边界检测。**不是强制 kill**，是协作式——取消只在 tool call 完成、拿到 chunk 时才生效。

#### 3.4 Background Task 调度架构

```
_scheduler_pool (3 threads) ← 编排层，负责超时管理
  └─ _execution_pool (3 threads) ← 执行层，运行实际的 subagent
       └─ _isolated_loop_pool (3 threads) ← 事件循环隔离层
```

三层线程池分离关注点。scheduler 负责等待 `future.result(timeout=config.timeout_seconds)` 并处理 FuturesTimeoutError；execution 负责实际运行；isolated 处理嵌套 event loop。

#### 3.5 RuntimeFeatures 声明式特性开关（`features.py`）

```python
@dataclass
class RuntimeFeatures:
    sandbox: bool | AgentMiddleware = True
    memory: bool | AgentMiddleware = False
    summarization: Literal[False] | AgentMiddleware = False
    subagent: bool | AgentMiddleware = False
    vision: bool | AgentMiddleware = False
    auto_title: bool | AgentMiddleware = False
    guardrail: Literal[False] | AgentMiddleware = False
```

`True` = 用默认实现，`False` = 禁用，`AgentMiddleware 实例` = 用自定义实现。`summarization` 和 `guardrail` 没有默认实现，`True` 会 raise——必须传实例。

---

### 维度 4：上下文/预算

#### 4.1 SummarizationMiddleware（`summarization_middleware.py`）

触发机制配置（`summarization_config.py`）：

```python
class SummarizationConfig(BaseModel):
    trigger: ContextSize | list[ContextSize] | None  # 触发条件，支持多条件
    keep: ContextSize  # 保留多少上下文（默认保留 20 条消息）
    trim_tokens_to_summarize: int | None = 4000  # 给 LLM 看的历史最大 tokens
    summary_prompt: str | None  # 自定义 prompt
```

`ContextSize` 三种类型：
- `fraction`: 达到模型 max tokens 的 80%
- `tokens`: 绝对 token 数
- `messages`: 消息条数

`DeerFlowSummarizationMiddleware` 扩展了 LangChain 的基础 `SummarizationMiddleware`，增加了 `before_summarization` 钩子列表，用于在压缩前触发 memory flush。

压缩后用 `RemoveMessage(id=REMOVE_ALL_MESSAGES)` 一次性清除所有历史，再写入 summary + preserved messages。

#### 4.2 DeferredToolFilterMiddleware

大量 MCP 工具接入时，所有工具 schema 都塞进 system prompt 会爆 token。DeerFlow 的解法：

```
agent 看到的工具：
  - 全量可用工具（直接可调用）
  - <available-deferred-tools> 列表（名字+描述，无 schema）

agent 需要某个 deferred tool 时：
  → 调 tool_search 获取完整 schema
  → DeferredToolRegistry.promote() 从延迟列表移除
  → 下次 bind_tools 时该工具变为直接可用
```

DeferredToolFilterMiddleware 在每次 model 调用前从 bind_tools 里过滤掉还在 deferred 列表里的工具 schema。

#### 4.3 Token 计量

```python
class TokenUsageMiddleware(AgentMiddleware):
    def _log_usage(self, state):
        last = state["messages"][-1]
        usage = getattr(last, "usage_metadata", None)
        if usage:
            logger.info("LLM token usage: input=%s output=%s total=%s", ...)
```

读 `usage_metadata`，这是 LangChain AIMessage 的标准字段，跨 provider 兼容。

---

### 维度 5：故障/恢复

#### 5.1 LLMErrorHandlingMiddleware — 熔断器 + 重试（`llm_error_handling_middleware.py`）

**P0 代码片段：**

```python
class LLMErrorHandlingMiddleware(AgentMiddleware):
    retry_max_attempts: int = 3
    retry_base_delay_ms: int = 1000
    retry_cap_delay_ms: int = 8000
    
    circuit_failure_threshold: int = 5
    circuit_recovery_timeout_sec: int = 60
    
    # 熔断器三态：closed → open → half_open → closed
    _circuit_state = "closed"
    
    def _check_circuit(self) -> bool:
        """返回 True 表示熔断器打开（快速失败）"""
        with self._circuit_lock:
            if self._circuit_state == "open":
                if now < self._circuit_open_until:
                    return True  # 还在冷却
                self._circuit_state = "half_open"
                self._circuit_probe_in_flight = False
            if self._circuit_state == "half_open":
                if self._circuit_probe_in_flight:
                    return True  # 已有探针在飞，不再发
                self._circuit_probe_in_flight = True
                return False  # 让这个请求当探针
            return False  # closed 状态
```

错误分类：
- `quota`/`auth` → 不重试，直接返回用户可读错误消息
- `transient`/`busy` → 指数退避重试，Retry-After header 优先
- 可重试错误积累到阈值 → 熔断

`GraphBubbleUp` 被特殊处理——这是 LangGraph 的 interrupt/pause 信号，不能被 try/except 吃掉。

#### 5.2 DanglingToolCallMiddleware — 断口修复

```python
def _build_patched_messages(self, messages):
    """检测 AIMessage 有 tool_calls 但没有对应 ToolMessage 的断口，
    在断口处插入合成的错误 ToolMessage"""
    
    existing_tool_msg_ids = {msg.tool_call_id for msg in messages if isinstance(msg, ToolMessage)}
    
    patched = []
    for msg in messages:
        patched.append(msg)
        if getattr(msg, "type", None) != "ai":
            continue
        for tc in self._message_tool_calls(msg):
            tc_id = tc.get("id")
            if tc_id and tc_id not in existing_tool_msg_ids and tc_id not in patched_ids:
                patched.append(ToolMessage(
                    content="[Tool call was interrupted and did not return a result.]",
                    tool_call_id=tc_id,
                    name=tc.get("name", "unknown"),
                    status="error",
                ))
```

**用 `wrap_model_call` 而不是 `before_model`**：关键设计决策。`before_model` 添加的消息会被 LangGraph 的 add_messages reducer 追加到列表末尾，破坏消息顺序。`wrap_model_call` 直接修改发给 LLM 的请求，保持正确的插入位置。

#### 5.3 LoopDetectionMiddleware — 双层检测

**层 1：Hash 检测（精确循环）**

```python
def _hash_tool_calls(tool_calls):
    """对 tool calls 集合做 order-independent 的稳定 hash"""
    normalized = []
    for tc in tool_calls:
        name = tc.get("name", "")
        args, fallback_key = _normalize_tool_call_args(tc.get("args", {}))
        key = _stable_tool_key(name, args, fallback_key)
        normalized.append(f"{name}:{key}")
    normalized.sort()  # 顺序无关
    blob = json.dumps(normalized, sort_keys=True, default=str)
    return hashlib.md5(blob.encode()).hexdigest()[:12]
```

特殊处理：`read_file` 按行号范围分桶（200 行/桶），避免对同一文件的不同范围读取误判为循环；`write_file`/`str_replace` 用全量 args hash（内容变化了不算循环）。

**层 2：频率检测（跨调用累积）**

同一 tool name 调用次数超 30 次警告，超 50 次强制停止。捕获"读 40 个不同文件"这种跨 hash 的变体循环。

**警告注入方式**：注入 `HumanMessage` 而非 `SystemMessage`。原因：Anthropic 不允许对话中间出现多个非连续的 system messages，用 HumanMessage 兼容所有 provider。

**强制停止**：清空 AIMessage 的 tool_calls，并把 `finish_reason` 从 `"tool_calls"` 改为 `"stop"`，让 Agent 只能输出文本。

**线程隔离**：用 OrderedDict 做 LRU，最多跟踪 100 个 thread 的状态，防内存无限增长。

---

### 维度 6：质量/审查

#### 6.1 ClarificationMiddleware — 中断澄清

```python
def _handle_clarification(self, request: ToolCallRequest) -> Command:
    """拦截 ask_clarification tool call，中断执行"""
    formatted_message = self._format_clarification_message(args)
    tool_message = ToolMessage(
        content=formatted_message,
        tool_call_id=tool_call_id,
        name="ask_clarification",
    )
    return Command(
        update={"messages": [tool_message]},
        goto=END,  # 直接结束当前 graph 执行
    )
```

用 `Command(goto=END)` 中断 LangGraph 执行，而不是 raise，让 frontend 能接收到完整的中间状态。

#### 6.2 TodoMiddleware — 实时任务可视化

明确的 "三步及以下不用" 规则、"立即标完成" 规则、"每次只有一个 in_progress"（除非并行） 规则——这些是通过 prompt 工程强制执行的行为规范，写进 system_prompt 和 tool description 两处（双重绑定）。

#### 6.3 Memory 质量控制

- 置信度阈值 0.7 过滤低质量 fact
- max_facts=100 + 按置信度排序截断
- casefold 去重防冗余
- `correction` 类别 + sourceError 字段记录 Agent 错误（用于学习）
- 过滤 upload 相关内容防止幻觉

---

## 四、P0 模式提取（最高优先级，我们缺的）

### P0-1：异步 I/O 包装的嵌套 Loop 逃逸

**问题**：在 async server 里 sync → async 的正确方式不是 `asyncio.run()`（会报错），而是丢给独立线程。

**他们的实现**：
```python
_SYNC_MEMORY_UPDATER_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4)

def _run_async_update_sync(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    
    if loop is not None and loop.is_running():
        future = _SYNC_MEMORY_UPDATER_EXECUTOR.submit(asyncio.run, coro)
        return future.result()
    return asyncio.run(coro)
```

**我们的现状**：Python hooks 直接用 subprocess + sync 调用，没有这个问题。但如果我们有 FastAPI 服务，这个模式是必须的。

**三重验证**：
1. Python 官方文档确认 `asyncio.run()` 在已运行 loop 中不可用
2. DeerFlow 测试 `test_memory_updater.py` 有完整测试覆盖
3. FastAPI + uvicorn 场景下实测有效

**知识不可替代性**：这是"遇到才知道踩坑"的类型。DeerFlow 的处理方式是 battle-tested 的。

---

### P0-2：中间件 @Next/@Prev 位置声明系统

**问题**：中间件链硬编码顺序脆。插一个新中间件要看整个链，容易改错位置。

**他们的实现**：
```python
def Next(anchor: type[AgentMiddleware]):
    """声明这个中间件应该插在 anchor 之后"""
    def decorator(cls):
        cls._next_anchor = anchor
        return cls
    return decorator

# 使用：
@Next(LoopDetectionMiddleware)
class MySecurityMiddleware(AgentMiddleware):
    pass
```

插入算法支持：冲突检测（两个 @Next 同一锚）、循环依赖检测、跨 extra-middleware 的锚定（外部 middleware 可以锚定另一个外部 middleware）。

**我们的现状**：`.claude/hooks` 是 bash 脚本，通过 settings.json 配置顺序，没有声明式定位。不直接适用，但思路可迁移到 Python agent 构建。

**三重验证**：
1. `test_create_deerflow_agent.py` 覆盖了 Next/Prev 各种边界情况
2. 设计来自 Django middleware / Express middleware 的成熟模式
3. 与 LangGraph middleware API 兼容

---

### P0-3：双层 Loop 检测（Hash + 频率）

**问题**：单纯 hash 检测无法捕获"同一工具不同参数的高频调用"（读 40 个文件）。

**他们的实现**：见维度 5 的 LoopDetectionMiddleware 分析。

**我们的现状**：`loop-detector.sh` 是 bash 脚本，基于行数/模式检测，没有 tool call hash 机制。

**对比矩阵**：

| 特性 | DeerFlow | 我们 |
|------|---------|------|
| Hash 检测相同调用 | ✅ md5 hash，order-independent | ❌ 无 |
| 频率检测高频调用 | ✅ 按 tool 类型计数，上限可配 | ❌ 无 |
| 警告注入 | ✅ HumanMessage（跨 provider 兼容） | ❌ 无 |
| 强制停止 | ✅ 清空 tool_calls，改 finish_reason | ❌ 无 |
| LRU 线程追踪 | ✅ OrderedDict + 100 线程上限 | ❌ 无 |
| 特殊工具处理 | ✅ read_file 分桶，write 全量 hash | ❌ 无 |

**三重验证**：
1. `test_loop_detection_middleware.py` 有完整测试（含 write_file、cross-file read 等场景）
2. 双层机制来自 DeerFlow 自己踩坑：纯 hash 检测在 code review 任务（读很多文件）中误判
3. HumanMessage 代替 SystemMessage 有 Anthropic API 文档为证

---

### P0-4：Summarization 前 Memory Flush Hook

**问题**：上下文压缩会删掉重要对话，这些内容没机会写入长期记忆。

**他们的实现**：
```python
# 在创建 DeerFlowSummarizationMiddleware 时注册钩子
hooks = []
if get_memory_config().enabled:
    hooks.append(memory_flush_hook)

DeerFlowSummarizationMiddleware(**kwargs, before_summarization=hooks)

# memory_flush_hook 实现
def memory_flush_hook(event: SummarizationEvent) -> None:
    filtered = filter_messages_for_memory(list(event.messages_to_summarize))
    queue.add_nowait(  # 立即处理，不等 debounce
        thread_id=event.thread_id,
        messages=filtered,
        ...
    )
```

**我们的现状**：我们没有 Summarization 机制，但如果将来加了，这个联动是必须的。

**知识不可替代性**：这是压缩-记忆联动的关键设计，遗漏会导致历史知识在压缩时丢失。

---

## 五、P1 模式（值得学习，有中等实施成本）

### P1-1：FileMemoryStorage 的原子写入

```python
temp_path = file_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
with open(temp_path, "w", encoding="utf-8") as f:
    json.dump(memory_data, f, indent=2, ensure_ascii=False)
temp_path.replace(file_path)  # 原子替换
```

`Path.replace()` 在 POSIX 上是原子 rename，防止写一半断电导致文件损坏。

### P1-2：mtime 缓存失效

```python
def load(self, agent_name=None):
    current_mtime = file_path.stat().st_mtime if file_path.exists() else None
    cached = self._memory_cache.get(agent_name)
    if cached is None or cached[1] != current_mtime:
        memory_data = self._load_memory_from_file(agent_name)
        self._memory_cache[agent_name] = (memory_data, current_mtime)
        return memory_data
    return cached[0]
```

用文件修改时间作缓存 key，多进程修改文件后不需要手动清缓存。

### P1-3：背景任务 cancel_event 协作取消

比直接 `future.cancel()` 更优雅——Thread 无法被 cancel，只能协作。`threading.Event` + astream 迭代边界检测是正确的协作取消模式。

### P1-4：三 pool 背景任务架构

scheduler_pool → execution_pool → isolated_loop_pool 三层分离：
- scheduler 持有超时判断逻辑
- execution 持有实际 agent 执行
- isolated_loop 处理 async/sync 转换

单层 pool 做不到正确的超时+取消行为。

### P1-5：多语言纠错/强化信号

内置中英双语 pattern（不对/you're wrong, 对就是这样/that's right）。我们的 Memory 如果要做，也应该支持中文信号。

---

## 六、P2 模式（可参考，低优先级）

### P2-1：Agent 名称路径安全

`AGENT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9-]+$")` 在写文件前验证，简单有效。

### P2-2：LLM 响应内容统一抽取

```python
def _extract_text(content: Any) -> str:
    """处理 str / list[str|dict] 两种格式"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        # 混合 str chunk 和 dict block 的情况
        ...
```

Anthropic thinking mode 等会返回 list content，直接 str() 会得到 repr 字符串。

### P2-3：CircuitBreaker Retry-After 解析

```python
def _extract_retry_after_ms(exc):
    for key in ("retry-after-ms", "Retry-After-Ms", "retry-after", "Retry-After"):
        raw = headers.get(key)
        if raw:
            break
    # 支持两种格式：毫秒数字，或 HTTP 日期字符串
    try:
        multiplier = 1 if "ms" in header_name.lower() else 1000
        return int(float(raw) * multiplier)
    except:
        target = parsedate_to_datetime(str(raw))
        delta = target.timestamp() - time.time()
        return int(delta * 1000)
```

自动识别 ms 单位和 HTTP 日期格式。

---

## 七、路径依赖分析

### 7.1 选择了 LangGraph，锁定了

DeerFlow 基于 `langchain.agents.create_agent` + LangGraph 的 `CompiledStateGraph`，整个中间件架构（`AgentMiddleware`、`wrap_tool_call`、`after_model` 等 hooks）都是 LangChain 内部 API。这个 API 在 2026-04 的版本是稳定的，但并非公开文档化的稳定接口。

**对我们的影响**：我们没有 LangGraph 依赖，我们的 hooks 系统是 claude-code 的 bash hooks。这意味着大部分中间件代码不能直接搬用，但**架构思路可以迁移**：我们的 hook chain 也可以有类似的 @Next/@Prev 声明式插槽。

### 7.2 选择了 Python 异步，放弃了简单性

`asyncio.to_thread`、isolated loop pool、_run_async_update_sync 这些复杂性都是为了兼容 async server + sync library 的现实。如果 DeerFlow 当初选了全同步架构，这些问题就不存在。

但全 async 带来了更好的并发性能和 subagent 并行能力。这个 tradeoff 是合理的，他们为此付出了清晰的实现代价（代码量和复杂度都不低）。

### 7.3 Memory → JSON 文件，而非向量数据库

他们选了结构化 JSON（facts + summaries），而不是向量检索。这个选择：
- **优点**：确定性、可 debug、无需部署 vectordb
- **代价**：检索只能线性扫描，无法做语义相似度搜索
- **自我强化**：一旦 facts 数量上去（max 100），置信度排序截断就是唯一的质量控制机制

### 7.4 错过的分叉

DeerFlow 的 Memory 没有实现"遗忘曲线"——所有 facts 的权重是静态的，只有初始 confidence 和被删除两种状态，没有随时间衰减。像 Mem0/MemGPT 那种基于访问频率的遗忘机制他们没做。这是一个主动选择的简化，还是没想到？从代码看更像前者——他们知道 max_facts 会是上限。

---

## 八、对 Orchestrator 的实施建议

**立即可做（P0，本轮）**：

1. **双层循环检测**：在 Python agent 中实现 `LoopDetectionMiddleware` 等价逻辑。我们的 bash `loop-detector.sh` 无法做 tool call hash 检测，需要在 Python agent 层面补。核心算法 50 行左右，投入产出比极高。

2. **LLM 错误熔断器**：`LLMErrorHandlingMiddleware` 的熔断器 + 指数退避重试是生产必需品。我们如果有 Python agent 调 LLM，这套直接拿来用。

3. **DanglingToolCall 修复**：断开的 tool call 会导致下游 LLM 报错，这个 middleware 是防御性的必要 patch。

**中期（P1，下轮）**：

4. **Memory flush before summarization**：如果我们实现上下文压缩，必须先实现这个 hook。

5. **@Next/@Prev 声明式 hook 定位**：把思路迁移到我们的 bash hook 注册机制——目前 settings.json 里的 hooks 是无序列表，改成支持 before/after 锚点会让 hook 管理更清晰。

**参考（P2，有空看）**：

6. 原子文件写入（`tmp_path.replace(file_path)`）——我们写内存文件时可以用。
7. 多语言信号检测 pattern——偷他们的中文 pattern。

---

## 九、与 4 月 1 日扫描的增量

| 内容 | 4-01 覆盖 | 本次新增 |
|------|---------|---------|
| Memory 系统 | 提到存在，未展开 | 完整代码分析（updater/queue/storage/prompt/middleware/hook） |
| 中间件架构 | 未覆盖 | 14 个中间件完整分析，含顺序依赖 |
| 循环检测 | 未覆盖 | 双层机制完整代码 |
| 熔断器 | 未覆盖 | 三态 circuit breaker 完整代码 |
| Subagent 执行引擎 | 未覆盖 | 三重执行路径 + 协作取消完整代码 |
| @Next/@Prev 系统 | 未覆盖 | 声明式位置系统完整分析 |
| 工具延迟加载 | 未覆盖 | DeferredToolRegistry 机制 |
| DanglingToolCall | 未覆盖 | 断口修复逻辑 |

**上次报告的价值**：Skills / Sandbox / MCP / Gateway / IM Channels 的分析仍然有效，本轮不重复。

---

*报告结束。可实施 P0 模式 3 个，P1 模式 5 个，P2 模式 3 个。*
