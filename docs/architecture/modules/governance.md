# Governance

> 三省六部执行层 — 任务派单、Agent 会话管理、运行时监督、安全约束。

## Key Files

| File | Purpose |
|------|---------|
| `dispatcher.py` | 派单管线：创建 → 分类 → 预检 → 审查 → 入队，含僵尸任务收割 |
| `executor.py` | Agent SDK 会话管理，Rollout-Attempt 生命周期（重试+追踪） |
| `executor_prompt.py` | 构建执行 prompt（部门 SKILL + 认知模式 + 上下文） |
| `executor_session.py` | AgentSessionRunner，管理单次 Agent 会话的实际运行 |
| `supervisor.py` | RuntimeSupervisor — 检测签名重复/编辑抖动/空转循环，分级干预 |
| `scrutiny.py` | Scrutinizer — 认知模式分类（routine/analytical/creative） |
| `dispatcher.py` → `policy/` | blueprint 加载、预检、novelty 策略、确定性回退 |
| `safety/` | 不可变约束（工具白名单、超时）、agent 信号量 |
| `context/` | prompt 模板、部门配置、上下文组装 |
| `pipeline/` | Scout 侦查任务（预执行信息收集） |

## Architecture

Dispatcher 是入口。每个任务经过复杂度分类（gateway/complexity）、预检（blueprint.yaml preflight）、审查（scrutiny）后入队。Executor 从队列取任务，构建 prompt 并启动 Agent SDK 会话。每次执行是一个 Rollout，失败时按 RETRYABLE_CONDITIONS（timeout/stuck/cost_limit）自动创建新 Attempt。

Supervisor 嵌入执行循环，滑窗检测三类失控模式。干预等级：NONE → NUDGE → STRATEGY_SWITCH → ESCALATE → TERMINATE。不做决策，只产出 Intervention 信号，Executor 自行决定如何响应。

## Authority Levels

每个部门的 `blueprint.yaml` 定义权限天花板：

| Level | Meaning |
|-------|---------|
| `READ` | 只读，不可修改文件 |
| `MUTATE` | 可修改文件，不可 commit/push |
| `APPROVE` | 需人工审批（保留级别） |

## Departments

| Directory | 中文名 | Role |
|-----------|--------|------|
| `engineering/` | 工部 | 写代码、修 bug、重构 |
| `operations/` | 礼部 | 运维、监控、部署 |
| `protocol/` | 中书省 | 协议、规范、文档 |
| `security/` | 兵部 | 安全审计、威胁检测 |
| `quality/` | 刑部 | 质量门禁、测试 |
| `personnel/` | 吏部 | 绩效、人事管理 |

## Related

- Department blueprints: `departments/{name}/blueprint.yaml`
- Department skills: `departments/{name}/SKILL.md`
