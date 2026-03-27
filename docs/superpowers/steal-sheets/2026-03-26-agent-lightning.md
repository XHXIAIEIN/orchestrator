# 偷师报告 Round 8：Agent Lightning

**来源**: microsoft/agent-lightning — https://github.com/microsoft/agent-lightning (15.5K stars)
**定位**: "The absolute trainer to light up AI agents" — 用 RL/APO 算法训练优化 AI agent，几乎零代码改动
**语言**: Python | **协议**: MIT | **版本**: v0.3.1 | **最后活跃**: 2026-02

## 核心架构：三角循环

```
Algorithm ──enqueue_rollout──→ LightningStore ──dequeue_rollout──→ Runner
    ↑                              ↑                                  │
    │                         (单一真相源)                             │
    └───── query spans/rewards ────┘←──── emit spans/rewards ─────────┘
```

- **Algorithm**（大脑）：决定跑什么任务、从结果中学习、更新资源（模型权重/prompt 模板）
- **Runner**（工人）：执行 Algorithm 分配的任务、运行 agent、记录结果
- **LightningStore**（中枢）：单一真相源，任务/结果/资源全在这里，Algorithm 和 Runner **零直接通信**

**关键设计**：Algorithm 和 Runner 之间完全解耦。唯一交汇点是 Store。两侧可独立伸缩。

## 目录结构

```
agentlightning/
├── adapter/          # TraceAdapter: raw spans → 算法可消费格式
├── algorithm/        # Algorithm ABC + APO（自动 Prompt 优化）+ VERL（RL 训练）
│   ├── apo/          # Beam Search + Textual Gradient
│   └── verl/         # vLLM + FSDP/Megatron RL
├── cli/              # agl 命令行
├── emitter/          # emit_reward / emit_message / emit_object
├── execution/        # ExecutionStrategy: SharedMemory / ClientServer
├── instrumentation/  # 自动插桩：agentops / litellm / vllm / weave
├── litagent/         # LitAgent ABC — agent 基类
├── runner/           # LitAgentRunner — rollout 执行 + heartbeat + hook
├── store/            # LightningStore ABC + InMemory / Mongo / ClientServer / Threaded
├── tracer/           # Tracer ABC + AgentOps / OTel / Weave / Dummy
├── trainer/          # Trainer — 顶层编排器
├── types/            # Rollout, Attempt, Span, Task, Hook 等数据模型
└── verl/             # Ray + Hydra 配置的 RL PPO 训练
```

## 新模式清单

### P0 — 直接可偷

#### 1. Rollout → Attempt → Span 三级生命周期

任务执行不是一个扁平状态，而是三层嵌套：

- **Rollout**：工作单元，状态机 `queuing → preparing → running → succeeded/failed/cancelled/requeuing`
- **Attempt**：一个 Rollout 可以有多次执行尝试（重试），每次独立追踪
- **Span**：Attempt 内部的结构化事件，`(rollout_id, attempt_id, sequence_id)` 三维索引

重试由 `RolloutConfig` 控制：`max_attempts`、`retry_condition`、`timeout_seconds`、`unresponsive_seconds`。

**偷法→ governance/executor**:
- 当前任务系统是扁平的（run → 成功/失败）
- 升级为 Rollout-Attempt 模型：executor 执行失败 → 自动创建新 Attempt 重试
- 每次 LLM 调用、工具调用记录为 Span，供 reviewer 回溯分析
- `max_attempts` + `retry_condition` 做智能重试（不是所有失败都值得重试）

#### 2. Watchdog 嵌入式健康检测

不是独立守护线程，而是在 Store 变更操作前顺便调用：

- `now - start_time > timeout_seconds` → 标记 timeout
- `now - last_heartbeat > unresponsive_seconds` → 标记 unresponsive
- 新 span 到达可以把 unresponsive 恢复为 running

**偷法→ executor + storage**:
- 在 `db.update_run()` 等写操作前顺便扫描超时任务
- 零额外开销，不需要起新线程
- 与 Round 5 Firecrawl 的 `isWorkerStalled` 互补：那个是并发级别的，这个是任务级别的

#### 3. ComponentSpec 统一组件规格

```python
ComponentSpec[T] = Union[T, type[T], Callable[[], T], str, Dict[str, Any], None]
```

用户可以传实例、类、工厂函数、注册表字符串、或配置字典。`build_component()` 统一解析。

**偷法→ Trainer / executor 配置化**:
- 当前 executor/reviewer/advisor 是代码硬编码初始化
- 用 ComponentSpec 模式让 `config.yaml` 驱动组件装配
- 好处：换 LLM backend、换审批策略不用改代码

#### 4. ExecutionStrategy 策略分离

"怎么跑"和"跑什么"彻底分离：

- **SharedMemoryExecutionStrategy**：单进程多线程，Store 加锁
- **ClientServerExecutionStrategy**：跨进程 HTTP，Store 变 Server/Client

Runner Bundle 和 Algorithm Bundle 是 Protocol callable，Strategy 不关心内部实现。

**偷法→ executor**:
- Debug 模式（同步执行，方便断点调试）
- Production 模式（异步/多进程，吞吐优先）
- 同一套 executor 逻辑，切策略不改代码

### P1 — 近期可偷

#### 5. Heartbeat Producer-Consumer 双线程

```
Producer Thread: 定期 system_snapshot()（CPU/内存/GPU）
Consumer Thread: 定期推送最新快照到 Store
```

- 慢速 GPU 查询不阻塞主线程
- 快照有 stale 检测（太旧就跳过）

**偷法→ system_monitor**:
- 当前 system_monitor 是同步采集
- 分离采集和上报，避免 nvidia-smi 卡住影响主循环

#### 6. APO — Beam Search + Textual Gradient 自动 Prompt 优化

完整实现 ProTeGi/TextGrad 风格：
1. 用当前 prompt 跑 rollout → 收集 reward
2. LLM 生成 "textual gradient"（文本批评/反馈）
3. 另一个 LLM 将批评转为编辑 → 生成新 prompt
4. Beam search：保留 top-k prompt → 重复

用 POML（Prompt Optimization Markup Language）模板化。

**偷法→ policy_advisor 升级**:
- 当前 advisor 是"建议"模式（建议改 prompt）
- 升级为 APO 迭代优化：实际执行 → 评估 → 生成梯度 → 编辑 prompt → 再执行
- 自动化 prompt 调优闭环

#### 7. LLM Proxy 透明代理层

在 agent 和 LLM 之间插入 HTTP 代理：
- 自动采集 span（补充 tracer 无法插桩的场景）
- 统一后端接口
- 算法可动态换模型（换微调后的新版本），agent 代码不用改
- streaming → non-streaming 转换

**偷法→ llm_router 升级**:
- 当前 llm_router 是直连 LLM
- 加 proxy 层 = 透明成本追踪 + span 采集 + 动态模型切换
- 与 Round 5 的 CostTracking 模式互补

#### 8. Store Collections 抽象层

Store 分两层：
- **Collections Layer**：`Collection[T]`（CRUD）、`Queue[T]`（FIFO）、`KeyValue[K,V]`
- **Store Layer**：在 Collections 之上实现业务逻辑

支持 `atomic()` 上下文管理器事务。InMemory 和 Mongo 是两个实现。

**偷法→ storage/**:
- 当前直接 SQLite 操作
- 抽象一层 Collection 接口，换后端（SQLite → Mongo → Redis）不改业务逻辑
- 与 Round 5 NuQ 自建队列思路一致

### P2 — 长线参考

#### 9. Tracer 自动插桩 + 多后端

Tracer ABC 支持 AgentOps、OTel、Weave、Dummy。通过 instrumentation 模块自动 hook 库的关键方法。`trace_context` 异步上下文管理器自动关联 span 到 rollout。

#### 10. Adapter 数据转换管道

`Generic[T_from, T_to]` 转换器：
- `TracerTraceToTriplet`：span → `(prompt, response, reward)` 三元组给 RL
- `TraceToMessages`：span → 聊天消息列表给 APO

#### 11. Monotonic Sequence ID 保序

分布式环境下时钟漂移导致乱序。解决：每个 span 创建前从 Store 获取单调递增 sequence_id。

#### 12. Hook 生命周期四钩子

`on_rollout_start` → `on_trace_start` → `on_trace_end` → `on_rollout_end`。异常被捕获不中断主流程。

#### 13. Graceful Shutdown

SharedMemoryExecutionStrategy 优雅关闭：
1. Ctrl+C → 设置 stop_evt
2. 给 bundle grace period 自行退出
3. 超时后 cancel
4. join 所有线程，记录僵尸线程

#### 14. VERL 集成 — Ray + vLLM + FSDP/Megatron

Ray Remote Actor 分布式训练，Hydra 配置驱动。AgentDataset 适配器对接 VERL 数据管线。

## 与典型 Agent 框架的差异

| 维度 | 典型框架（LangChain/CrewAI） | Agent Lightning |
|------|---------------------------|-----------------|
| 目标 | 构建 agent | 训练/优化 agent |
| 核心循环 | Prompt → LLM → Tool → 输出 | Algorithm → Rollout → Span → 学习 → 更新 |
| 框架绑定 | 绑定特定框架 | Framework Agnostic |
| 数据流 | 实时单次执行 | 批量训练 + Online Learning |
| 优化手段 | 无 | APO + RL + SFT |
| Store | 无或简单 KV | 完整 Rollout-Attempt-Span 生命周期 |
| 伸缩性 | 通常单进程 | SharedMemory / ClientServer 双策略 |

## 与前轮偷师的交叉

| 前轮模式 | 本轮对应 | 互补点 |
|---|---|---|
| Round 4 OpenAkita Supervisor | Watchdog 嵌入式健康检测 | Akita 是"主动干预"，Lightning 是"被动检测"，可组合 |
| Round 5 Firecrawl CostTracking | LLM Proxy 透明代理 | Firecrawl 是请求级成本，Lightning 是 Rollout 级全链路 |
| Round 5 Firecrawl Engine Waterfall | ExecutionStrategy | Firecrawl 是引擎 fallback，Lightning 是执行环境 fallback |
| Round 5 Firecrawl Transformer Pipeline | Adapter 数据转换管道 | 都是纯函数管道，但 Lightning 的是泛型的 |
| Round 4 OpenAkita 三层记忆 | Store Collections 抽象 | 都在做存储抽象，可融合 |
| Round 6 OpenFang HAND.toml | ComponentSpec | 都在做配置驱动组件装配 |

## Orchestrator 偷师优先级

### 立即可偷（P0）
1. **Rollout-Attempt 生命周期** → executor 任务支持自动重试 + Attempt 级追踪
2. **Watchdog 嵌入式检测** → storage 写操作顺便扫描超时任务
3. **ComponentSpec 配置驱动** → executor/reviewer/advisor 支持配置文件装配

### 近期规划（P1）
4. **ExecutionStrategy 双模式** → debug 同步 / production 异步
5. **APO 自动 Prompt 优化** → policy_advisor 迭代优化闭环
6. **LLM Proxy 透明代理** → llm_router 升级为 proxy + span 采集 + 动态切换
7. **Heartbeat Producer-Consumer** → system_monitor 采集/上报分离
8. **Store Collections 抽象** → storage 换后端不改业务

### 长线参考（P2）
9. Tracer 自动插桩多后端
10. Adapter 泛型转换管道
11. Monotonic Sequence ID 保序
12. Hook 四钩子生命周期
13. Graceful Shutdown 优雅关闭
14. VERL Ray 分布式 RL 训练
