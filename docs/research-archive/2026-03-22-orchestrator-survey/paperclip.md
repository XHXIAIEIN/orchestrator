# Paperclip (paperclipai)

- **URL**: https://github.com/paperclipai/paperclip
- **语言**: TypeScript | **Stars**: 31K | **创建**: 2026-03-02
- **评级**: S 级

## 一句话

开源 AI 公司控制平面——Org Chart + Ticket System + Budget + Governance，给 AI agent 用的 Jira。

## 核心架构

Control Plane（调度/追踪/治理）与 Execution Plane（agent 运行时）完全分离。
10 个 adapter：claude_local / codex_local / cursor / gemini_local / opencode_local 等。

## 可偷模式

### 1. Atomic Task Checkout ⭐⭐⭐⭐⭐
`POST /issues/{id}/checkout`，409 冲突就放弃。单一分配人模型，防双重工作。

→ 三省六部多 agent 并发派单的核心机制。

### 2. Heartbeat Protocol ⭐⭐⭐⭐⭐
标准化 9 步心跳：Identity → Approval → Get assignments → Pick → Checkout → Context → Work → Update → Delegate。靠 Skill prompt 注入，不硬编码。

→ 部门 agent "工作规范"的标准化方式。

### 3. Budget Hard Stop ⭐⭐⭐⭐⭐
月度预算（company → project → agent），warn 阈值 + hard stop。超预算自动 pause agent + 取消 run。

→ Orchestrator 刚需。

### 4. Wakeup Coalescing ⭐⭐⭐⭐
同一 agent 已有排队/运行中的 run，新唤醒合并不重复。DB-backed 队列。优先级：on_demand > assignment > timer。

→ 防事件风暴。

### 5. Task-Scoped Session Persistence ⭐⭐⭐⭐
`agent_task_sessions` 表按 (agent_id, task_key) 存，跨心跳恢复上下文。

→ Agent 不用每次从头理解任务。

### 6. Org Chart 层级委派 ⭐⭐⭐⭐
严格树形 reports_to。做不了标 blocked，不能自己取消必须上报。billingCode 跨团队成本归因。

→ 三省六部天然对应。

### 7. Run Log Store 三后端 ⭐⭐⭐
local_file / object_store / postgres。摘要进 DB，全量外存。

### 8. Portable Company Templates ⭐⭐⭐
整个公司配置导出/导入。ClipMart 市场构想。

## 与三省六部的映射

| Paperclip | 三省六部 |
|-----------|---------|
| Board (人类审批) | 朕 |
| CEO Agent | 中书省 |
| Department Heads | 六部尚书 |
| Worker Agents | 六部吏员 |
| Budget Policy | 户部预算 |
| Governance Rules | 御史台 |
| Ticket System | 奏折系统 |
