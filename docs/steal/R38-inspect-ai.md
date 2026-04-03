# R38 — Inspect AI (UKGovernmentBEIS/inspect_ai)

> UK AI Safety Institute 的 LLM/Agent 评估框架。仓库: https://github.com/UKGovernmentBEIS/inspect_ai
> 偷师时间: 2026-04-03
> 阅读范围: 核心源码 ~15000 行（eval runner, solver, agent, scorer, approval, hooks, sandbox, dataset, transcript, CLI）

---

## 架构概览

```
@task decorator → Task(dataset, solver, scorer, sandbox, approval)
                      │          │        │         │         │
                      ▼          ▼        ▼         ▼         ▼
               Sample[]     Solver→    Score     Docker/   Approver
              input/target  chain()   Protocol   Local     Protocol
                             │
                         generate()
                         use_tools()
                         react() agent
```

Inspect 的核心思路：**一切皆 Protocol + 装饰器注册 + 函数式组合**。没有 class 继承，没有 AbstractBaseClass（除了 SandboxEnvironment），所有核心接口都是 `@runtime_checkable Protocol`。

---

## Pattern 1: Decorator-Registry System (装饰器注册表)

### 工作原理

所有核心组件（task, solver, scorer, tool, agent, approver, hooks）都通过统一的装饰器注册进全局 registry：

```python
# 定义一个 task
@task
def my_eval():
    return Task(dataset=[...], solver=[...], scorer=match())

# 定义一个 tool
@tool
def add():
    async def execute(x: int, y: int):
        """Add two numbers.
        Args:
            x: First number to add.
            y: Second number to add.
        """
        return x + y
    return execute

# 定义一个 scorer
@scorer(metrics=[accuracy(), stderr()])
def my_scorer():
    async def score(state: TaskState, target: Target) -> Score:
        return Score(value="C" if state.output.completion == target.text else "I")
    return score
```

注册表支持的类型：
```python
RegistryType = Literal[
    "agent", "approver", "hooks", "metric", "modelapi", "plan",
    "sandboxenv", "score_reducer", "scorer", "solver", "task", "tool",
    "loader", "scanner", "scanjob",
]
```

每个注册对象携带 `RegistryInfo(type, name, metadata)`，通过 `registry_create(type, name, **kwargs)` 可以用字符串名字动态重建。

### 为什么聪明

1. **CLI 可发现性**：`inspect list tasks` 能自动发现并列出所有 @task 装饰的函数
2. **可序列化**：eval log 里只存 `SolverSpec(solver="my_solver", args={...})`，就能用 `registry_create()` 重建整个 solver 链
3. **插件系统免费**：任何 pip 包只要用 `@task` 装饰函数，就自动被 registry 发现
4. **跨包命名空间**：`registry_name()` 自动加包前缀防冲突

### Orchestrator 适配

Clawvard 考试系统可以用相同模式：
- `@exam` 装饰器注册考题集
- `@grader` 装饰器注册评分器
- `@skill_test` 装饰器注册能力测试
- 全局 registry 实现考试编排的自动发现

---

## Pattern 2: Protocol-Based Composition (协议组合)

### 工作原理

核心接口全是 Protocol（鸭子类型），不是基类：

```python
@runtime_checkable
class Solver(Protocol):
    async def __call__(self, state: TaskState, generate: Generate) -> TaskState: ...

@runtime_checkable
class Scorer(Protocol):
    async def __call__(self, state: TaskState, target: Target) -> Score | None: ...

@runtime_checkable
class Agent(Protocol):
    async def __call__(self, state: AgentState, *args, **kwargs) -> AgentState: ...

@runtime_checkable
class Approver(Protocol):
    async def __call__(self, message: str, call: ToolCall, view: ToolCallView,
                       history: list[ChatMessage]) -> Approval: ...
```

关键设计：Solver 接收 `generate` 函数作为参数而不是继承 Model，实现了 **solver 与 model 的完全解耦**。

### 为什么聪明

- 任何 `async def` 只要签名匹配就是 Solver/Scorer/Agent，零 boilerplate
- 组合就是函数链：`solver=[system_message("..."), use_tools([add()]), generate()]`
- `chain()` 把 Solver 列表串联，每个 Solver 接上个的 TaskState 输出
- Agent 和 Solver 可以互换：`as_solver(agent)` / `as_tool(agent)`

### Orchestrator 适配

Clawvard 的评分链可以用同样模式：
```python
# 考试 = 数据集 + 解题策略 + 评分器
Exam(dataset=questions, solver=agent_under_test, scorer=rubric_grader())
```

---

## Pattern 3: TaskState 流水线 (Immutable-ish State Pipeline)

### 工作原理

`TaskState` 是贯穿整个 eval 的状态载体，每个 Solver 接收并返回它：

```python
class TaskState:
    model: ModelName           # 被评估的模型
    sample_id: int | str       # 样本 ID
    epoch: int                 # 第几轮
    input: str | list[ChatMessage]  # 原始输入（不可变）
    messages: list[ChatMessage]     # 对话历史（可变）
    output: ModelOutput        # 最终输出
    tools: list[Tool]          # 当前可用工具
    store: Store               # 任意键值存储（跨 solver 共享）
    target: Target             # 期望答案
    scores: dict[str, Score]   # 分数
    completed: bool            # 是否完成
    message_limit: int | None  # 消息数上限
    token_limit: int | None    # token 上限
    cost_limit: float | None   # 成本上限
```

**Store** 特别聪明 —— 它是一个 per-sample 的键值 dict，但可以通过 `StoreModel`（Pydantic BaseModel 子类）获得类型安全的视图：

```python
class MyAgentState(StoreModel):
    attempts: int = 0
    found_answer: bool = False

# 在 solver 里用
state.store_as(MyAgentState).attempts += 1
```

StoreModel 底层读写 Store dict，但提供了类型验证 + IDE 补全。

### 为什么聪明

1. **input 不可变，messages 可变**：原始题目永远可追溯
2. **Store 解耦**：多个 solver 之间共享状态但不知道彼此
3. **限制内置**：message_limit / token_limit / cost_limit / time_limit 直接内嵌 state，每次 generate 自动检查
4. **StoreModel** 在 dict 上叠 Pydantic 验证 —— 同时兼顾灵活和安全

### Orchestrator 适配

Agent 执行任务时的 TaskContext 可以借鉴 Store + StoreModel 模式：
- 核心 state 是 dict（灵活）
- 但每个 agent skill 通过 StoreModel 视图访问自己关心的字段（安全）
- 成本/token/时间限制内嵌状态，不需要外部 guardian

---

## Pattern 4: Approval System (工具审批链)

### 工作原理

这是 Inspect 最与 Orchestrator 相关的模式。整个审批系统是：

```
ApprovalPolicy(approver=Approver, tools="bash*")  # glob 匹配工具名
    ↓
policy_approver() → 编译成匹配器链
    ↓
对每个 tool call:
    1. fnmatch(tool_call, pattern) 找到匹配的 approver
    2. approver(message, call, view, history) → Approval
    3. Approval.decision ∈ {approve, modify, reject, terminate, escalate}
    4. "escalate" → 交给下一个 approver
    5. "modify" → 可以修改 tool call 参数再执行
```

审批策略可以用 YAML 配置：

```yaml
approvers:
  - name: bash_allowlist
    tools: bash*
    allowed_commands: [ls, cat, grep]
  - name: human
    tools: python*, bash*
    choices: [approve, reject]
  - name: auto
    tools: "*"
    decision: approve
```

具体实现：
- `auto_approver` —— 自动通过/拒绝
- `human_approver` —— 弹 TUI panel 或 console 让人审批
- 用户自定义的如 `bash_allowlist` / `python_allowlist` —— AST 解析 + 白名单

`ContextVar` 管理当前审批策略，`approval()` context manager 可以临时替换：

```python
with approval(policies):  # 临时使用这组策略
    await execute_tools(messages, tools)
```

### 为什么聪明

1. **5 种决策** 比 approve/reject 丰富得多：`modify`（改参数再执行）和 `escalate`（传给下一个审批人）是亮点
2. **glob 模式匹配工具名**：`bash*` 匹配 bash, bash_safe 等，灵活
3. **链式回退**：auto → allowlist → human，逐级升级
4. **ToolCallView** 自定义渲染 —— 审批人看到的不一定是原始 JSON，可以渲染成 Markdown 代码块
5. **ContextVar 作用域** —— 每个 agent 可以有自己的审批策略

### Orchestrator 适配

**直接移植到 Claw 审批体系**：
- 当前 Claw 只有 approve/reject —— 加 `modify`（改 tool 参数后自动执行）和 `escalate`（从 Claw 升级到 TG）
- 审批策略 YAML 配置化 —— 目前写在代码里，应该外置
- Glob 匹配工具名 —— `desktop_*` 走人审，`read_file` 自动通过
- ToolCallView 定制 —— 在 Claw/TG 通知里渲染更友好的工具调用预览

---

## Pattern 5: Hooks (生命周期事件系统)

### 工作原理

Hooks 是一个完整的 eval 生命周期事件系统：

```python
class Hooks:
    async def on_eval_set_start(data: EvalSetStart) -> None
    async def on_eval_set_end(data: EvalSetEnd) -> None
    async def on_run_start(data: RunStart) -> None
    async def on_run_end(data: RunEnd) -> None
    async def on_task_start(data: TaskStart) -> None
    async def on_task_end(data: TaskEnd) -> None
    async def on_sample_init(data: SampleInit) -> None        # sandbox 创建前
    async def on_sample_start(data: SampleStart) -> None      # solver 执行前
    async def on_sample_event(data: SampleEvent) -> None      # 每个事件
    async def on_sample_end(data: SampleEnd) -> None           # 完成或最终失败
    async def on_sample_attempt_start(data: SampleAttemptStart) -> None  # 含重试
    async def on_sample_attempt_end(data: SampleAttemptEnd) -> None
    async def on_sample_scoring(data: SampleScoring) -> None   # 评分前
    async def on_model_usage(data: ModelUsageData) -> None     # 模型调用完成
    async def on_model_cache_usage(data: ModelCacheUsageData) -> None
    def override_api_key(data: ApiKeyOverride) -> str | None   # API key 覆盖
```

注册方式：

```python
@hooks(name="my_audit", description="Audit logging to S3")
class MyAuditHooks(Hooks):
    async def on_task_end(self, data: TaskEnd) -> None:
        upload_to_s3(data.log)
```

关键设计：
- **所有 hook 调用都包在 try/except 里** —— hook 崩溃不影响 eval
- **`enabled()` 方法** —— hook 可以自己判断是否启用（检查环境变量等）
- **`LimitExceededError` 例外** —— 这是唯一允许从 hook 穿透的异常（限制必须被执行）
- **SampleEvent 用 anyio 内存通道异步 drain** —— 高频事件不阻塞 solver 执行

### 为什么聪明

1. **hook 故障隔离** —— `_emit_to_all` 里每个 hook 独立 try/except
2. **attempt vs sample 区分** —— `on_sample_start/end` 只触发一次，`on_sample_attempt_start/end` 重试时也触发
3. **同步 `override_api_key`** —— 不是 async，因为 key rotation 必须在请求前完成，不能等
4. **示例丰富** —— MLflow tracing, W&B Weave, 审计日志等

### Orchestrator 适配

三省六部的 dispatch / audit 可以用 Hooks 模式重构：
- `on_task_dispatch` / `on_task_complete` / `on_agent_error`
- 吏部绩效统计就是一个 Hook subscriber
- Hook 故障隔离 —— 绩效记录挂了不影响任务执行

---

## Pattern 6: Epochs + ScoreReducer (多轮评估 + 分数聚合)

### 工作原理

```python
Task(
    dataset=samples,
    solver=react(tools=[...]),
    scorer=match(),
    epochs=Epochs(5, reducer=[mean()]),  # 每个样本跑 5 次，取均值
)
```

同一个 sample 运行多次（epochs），然后用 reducer 聚合：
- `mean()` —— 均值
- `mode()` —— 众数
- `max()` —— 取最好
- 自定义 reducer

### 为什么聪明

Agent 行为有随机性，单次评估不可靠。Epochs + Reducer 让评估结果更稳定。

### Orchestrator 适配

Clawvard 考试可以对关键题目做 epochs=3 + mode reducer：
- 同一题跑 3 次，取众数作为最终成绩
- 减少 Claude 随机性导致的误判

---

## Pattern 7: Model-Graded Scoring (模型评分 + 多评委投票)

### 工作原理

```python
@scorer(metrics=[accuracy(), stderr()])
def model_graded_qa(template, instructions, grade_pattern, model, ...):
    async def score(state: TaskState, target: Target) -> Score:
        # 1. 格式化评分提示词
        prompt = template.format(question=..., answer=..., criterion=...)
        # 2. 调用评分模型
        result = await model.generate([prompt])
        # 3. 正则提取 GRADE: C/P/I
        match = re.search(r"GRADE\s*:\s*([CPI])", result.completion)
        return Score(value=match.group(1), explanation=result.completion)
    return score
```

**多评委投票**：

```python
model_graded_qa(model=["openai/gpt-4", "anthropic/claude-3-opus"])
# 内部变成 multi_scorer(scorers, reducer="mode")
# 每个模型独立评分，取众数
```

评分结果的 Score 结构：

```python
class Score(BaseModel):
    value: Value          # "C" / "I" / 0.5 / True 等
    answer: str | None    # 模型的回答
    explanation: str | None  # 评分理由
    metadata: dict | None    # 额外数据（含评分 prompt 和模型回复）
```

### 为什么聪明

1. `GRADE: C/P/I` 三级制 —— 支持 partial credit
2. 评分模板可定制 + metadata 变量注入
3. 多评委模式内置 —— 直接传 list[Model]
4. `include_history=True` 让评分模型看到完整对话历史，而不只是最终回答

### Orchestrator 适配

Clawvard 的"情商/反思力"题目可以用 model_graded_qa 模式：
- 用 Claude 作为评分模型（model_role="grader"）
- 自定义评分模板：检查回答是否体现了反思、同理心等
- 多评委：同一题同时用 Claude + GPT-4 评分取众数

---

## Pattern 8: Sandbox Lifecycle (沙箱生命周期管理)

### 工作原理

```python
class SandboxEnvironment(abc.ABC):
    async def exec(self, cmd, input=None, cwd=None, env=None, user=None,
                   timeout=None) -> ExecResult
    async def read_file(self, file: str) -> str
    async def write_file(self, file: str, contents: str | bytes) -> None
    async def connection(self) -> SandboxConnection  # 含 docker exec 命令、VSCode 命令
```

生命周期：

```
task_init("startup", config)     # 启动容器（per-task，复用）
  sample_init(config, files)     # per-sample 文件复制
    solver 执行...
  sample_cleanup(config, envs)   # 清理 sample 文件
task_cleanup("shutdown", config) # 关闭容器
```

每个 Sample 可以有自己的 sandbox spec：

```python
Sample(
    input="Solve this CTF challenge",
    sandbox=("docker", "compose.yaml"),  # 这个样本用自己的 compose 配置
    files={"challenge.py": "..."},       # 自动复制到沙箱
    setup="pip install -r requirements.txt",  # 初始化脚本
)
```

### 为什么聪明

1. **per-sample sandbox** —— 不同的题目可以用不同的环境配置
2. **files + setup** —— 直接在 Sample 里声明需要的文件和初始化脚本
3. **SandboxConnection** —— 提供 `docker exec` 命令甚至 VSCode Remote 命令，方便调试
4. **task 级复用** —— 容器在 task 级别启动，sample 级别只做文件操作

### Orchestrator 适配

Agent 执行环境可以借鉴：
- 每个 agent task 可以声明 sandbox 类型 + files + setup
- Docker sandbox 在 task batch 级别复用，sample 级别隔离

---

## Pattern 9: Agent ↔ Solver ↔ Tool 互转 (三重身份)

### 工作原理

```python
# Agent 当 Solver 用（顶层执行）
Task(solver=react(tools=[bash()]))  # react() 返回 Agent，自动 as_solver()

# Agent 当 Tool 用（被另一个 agent 调用）
react(tools=[as_tool(code_agent)])

# Agent 通过 handoff 交接
react(tools=[handoff(code_agent), handoff(search_agent)])
# → 自动生成 transfer_to_code_agent() / transfer_to_search_agent() 工具
```

**handoff 机制**：
- `handoff(agent)` 创建一个 `AgentTool`，名字是 `transfer_to_{name}`
- `execute_tools()` 检测到 AgentTool 时特殊处理：初始化 AgentState，调用 agent，合并结果
- `input_filter` / `output_filter` 控制传给 agent 和从 agent 返回的消息格式
- `content_only` 默认输出过滤器 —— 去掉 system messages、reasoning blocks、tool calls，只留内容

### 为什么聪明

1. **一个组件三种用法** —— 不用为不同场景写三套代码
2. **handoff 自动命名** —— `transfer_to_` 前缀让模型理解这是"移交"
3. **submit 工具清理** —— 子 agent 的 submit() 调用在返回父 agent 前被清除，避免父 agent 误以为整个任务完成
4. **output_filter** —— 跨模型时自动去掉不兼容的消息格式

### Orchestrator 适配

六部之间的协作可以用 handoff 模式：
- 兵部 handoff 到 工部 = `transfer_to_engineering()`
- 自动消息过滤避免跨 agent 的格式冲突
- submit 清理机制防止子任务完成误报为主任务完成

---

## Pattern 10: Transcript + Span Tracing (事件追踪)

### 工作原理

每个 sample 执行过程中产生的所有事件都被 Transcript 记录：

```python
# 自动记录
ModelEvent      # 模型调用（input, output, usage, timing）
ToolEvent       # 工具调用（call, result, error）
ScoreEvent      # 评分事件
StoreEvent      # Store 变化（前后 diff）
SpanBeginEvent  # span 开始
SpanEndEvent    # span 结束

# 手动记录
transcript().info("Agent exceeded context window, truncating")
```

**Span** 提供结构化的嵌套追踪：

```python
async with span(name="scorers"):
    async with span(name="accuracy", type="scorer"):
        result = await scorer(state, target)
```

Span 通过 ContextVar 维护 parent-child 关系，形成树形结构。

**内存优化**：ModelEvent 的 API call 数据立即 condense（压缩 + 移到 attachments dict），防止 O(N) 内存增长。

### 为什么聪明

1. **StoreEvent 自动 diff** —— 只记录 store 变化，不记录完整快照
2. **SpanBeginEvent + SpanEndEvent** 而非单个 SpanEvent —— 支持流式写入，不用等 span 结束
3. **内存 condense** —— 大的 API response body 移到 attachments，transcript 事件列表保持轻量
4. **Inspect View** 前端用事件流重建完整执行过程

### Orchestrator 适配

Agent 任务的执行追踪可以用 Transcript + Span：
- 每个 agent 执行是一个 span
- 工具调用、模型调用、审批决策都是事件
- Store diff 记录让回放成为可能

---

## Pattern 11: EvalSet + Parallel Task Scheduling (评估集 + 并行调度)

### 工作原理

`eval_set()` 管理一组 eval 的增量执行（只跑没跑过的）。

`run_multiple()` 的调度逻辑很巧妙：
```python
# 跟踪每个 model 的当前并发数
model_counts = {model: 0 for model in models}

# 选下一个 task 时，挑当前并发最少的 model
model = min(models_with_pending, key=lambda m: model_counts[m])
```

这样做保证了：
- 多个 model 不会排队等同一个 model provider
- 吞吐量最大化

### Orchestrator 适配

多 agent 并行派单时可以借鉴 model_counts 策略：
- 跟踪每个 agent 的当前负载
- 派新任务时选最空闲的 agent

---

## Pattern 12: Early Stopping Protocol (自适应早停)

### 工作原理

```python
class EarlyStopping(Protocol):
    async def start_task(task, samples, epochs) -> str     # 注册
    async def schedule_sample(id, epoch) -> EarlyStop | None  # 每个 sample 前检查
    async def complete_sample(id, epoch, scores) -> None   # sample 完成后回调
    async def complete_task() -> dict[str, JsonValue]      # 返回诊断信息
```

在调度循环中，每个 sample 执行前调用 `schedule_sample()`，如果返回 `EarlyStop` 就跳过。

每个 sample 完成后调用 `complete_sample(scores)`，让 EarlyStopping 更新内部状态（比如"这个 sample 已经连续 3 轮正确了，后续 epoch 可以跳过"）。

### 为什么聪明

1. **Protocol 不是 ABC** —— 无需继承，实现签名就行
2. **per-sample 粒度** —— 不是"整个 eval 停"，是"这个 sample 的后续 epochs 停"
3. **双向通信** —— schedule 前问、complete 后报，EarlyStopping 有完整信息

### Orchestrator 适配

Clawvard 考试系统可以用 EarlyStopping：
- 如果 agent 已经连续 3 次答对某类题，跳过该类剩余题目
- 自适应难度调整的基础设施

---

## Pattern 13: React Agent + AgentAttempts (多次尝试 + 运行时评分)

### 工作原理

```python
react(
    tools=[bash(), python()],
    attempts=AgentAttempts(
        attempts=3,
        incorrect_message="Your answer was wrong. Try again.",
        score_value=value_to_float(),
    ),
    submit=AgentSubmit(name="submit", answer_only=True),
)
```

关键流程：
1. Agent 循环 generate → tool_calls → execute → generate...
2. 当 agent 调用 `submit(answer)` 时：
   - **运行时调用 scorer** 检查答案是否正确
   - 如果正确（score == 1.0），结束
   - 如果错误且还有 attempts，发 `incorrect_message` 继续
3. `on_continue` hook 控制无工具调用时的行为

**submit 工具清理**：执行完后，`_remove_submit_tool()` 从消息历史中移除所有 submit 相关的 tool_calls 和 tool messages，让历史看起来像普通对话。

### 为什么聪明

1. **运行时评分** —— 不用等 eval 结束才知道对不对，agent 可以立刻调整
2. **submit 清理** —— 多 agent 系统中，子 agent 的 submit 不会干扰父 agent
3. **AgentContinue 返回多种类型** —— `True`（默认消息继续）/ `False`（停止）/ `str`（自定义消息）/ `AgentState`（直接替换状态）

### Orchestrator 适配

Clawvard 考试可以用 AgentAttempts：
- 给 agent 3 次答题机会
- 每次答错给提示（"注意看题目中的条件"）
- 最终分数取最佳尝试

---

## Pattern 14: `task_with()` — 非破坏性任务变体

### 工作原理

```python
base = my_task()
variant = task_with(base, solver=react(tools=[...]), epochs=10)
```

用 `NotGiven` sentinel 区分"没传"和"传了 None"：

```python
if not isinstance(solver, NotGiven):
    task.solver = resolve_solver(solver)
```

### 为什么聪明

一个 base task 可以派生出多个变体（不同 solver、不同 epochs），而不用重新定义 dataset 和 scorer。

### Orchestrator 适配

考试模板 → 考试实例：
```python
base_exam = clawvard_exam()
speed_run = exam_with(base_exam, time_limit=60)
hard_mode = exam_with(base_exam, scorer=strict_grader())
```

---

## Pattern 15: CLI 设计 (Click + auto_envvar)

### 工作原理

```python
@click.group(invoke_without_command=True)
def inspect(ctx, version): ...

inspect.add_command(eval_command)
inspect.add_command(list_command)
inspect.add_command(view_command)
inspect.add_command(sandbox_command)
inspect.add_command(trace_command)
# ...

def main():
    init_dotenv()
    inspect(auto_envvar_prefix="INSPECT")  # INSPECT_MODEL → --model
```

`auto_envvar_prefix="INSPECT"` 让所有 CLI 参数自动映射到 `INSPECT_*` 环境变量。

子命令：
- `inspect eval` — 运行评估
- `inspect eval-set` — 增量评估集
- `inspect eval-retry` — 重试失败的
- `inspect list tasks/models` — 发现可用组件
- `inspect view` — 启动 Web 查看器
- `inspect sandbox` — 管理沙箱（连接、清理）
- `inspect trace` — 查看跟踪
- `inspect score` — 重新评分
- `inspect log` — 管理日志
- `inspect cache` — 管理缓存

### 为什么聪明

`inspect eval task.py --model openai/gpt-4` 一行搞定评估。环境变量自动映射减少配置负担。

---

## 总结：Top 5 最值得偷的模式

| 优先级 | 模式 | 偷法 | 收益 |
|--------|------|------|------|
| **P0** | Approval 5-decision + glob matching + escalation chain | 扩展 Claw 审批体系 | 安全+灵活 |
| **P0** | Hooks 生命周期 + 故障隔离 | 三省六部 dispatch/audit 重构 | 可观测性 |
| **P1** | Decorator-Registry 全家桶 | Clawvard @exam/@grader 注册 | 可扩展性 |
| **P1** | AgentAttempts + 运行时评分 | Clawvard 多次答题 + 即时反馈 | 考试精度 |
| **P2** | Store + StoreModel 类型安全视图 | Agent TaskContext 重构 | 开发体验 |

---

Sources:
- [UKGovernmentBEIS/inspect_ai](https://github.com/UKGovernmentBEIS/inspect_ai)
- [Inspect AI Documentation](https://inspect.aisi.org.uk/)
- [Inspect Evals](https://github.com/UKGovernmentBEIS/inspect_evals)
