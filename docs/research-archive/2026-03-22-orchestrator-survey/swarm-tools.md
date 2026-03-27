# swarm-tools (joelhooks/FelipeDaza7)

- **URL**: https://github.com/FelipeDaza7/swarm-tools
- **语言**: TypeScript/Bun + Effect-TS | **架构**: Event Sourcing + Actor Model
- **评级**: A 级

## 一句话

嵌入式事件溯源消息系统——为多 AI agent 协作提供通信原语（锁、信箱、Deferred Promise）。

## 核心：Hub-and-Spoke，不是 P2P

Coordinator 中心调度，Workers 不直接通信。通过 shared event log 广播。

## 可偷模式

### 1. WorkerHandoff 契约 ⭐⭐⭐⭐⭐
JSON 三段式：contract（files_owned/success_criteria，机器校验）+ context（WHY/上下游，给 LLM）+ escalation（卡住找谁）。完成时校验 files_touched ⊆ files_owned，scope creep 自动检测。

→ 三省六部派单格式升级。

### 2. 事件即学习信号 ⭐⭐⭐⭐⭐
SubtaskOutcomeEvent 记录 planned_files vs actual_files、scope_violation、duration_ms。反馈给分解策略选择。

→ 吏部绩效评估的数据源。

### 3. Ask 模式（Request/Response over streams）⭐⭐⭐⭐
DurableMailbox + DurableDeferred 组合成同步风格 RPC。envelope 模式：payload + replyTo + commit()。

### 4. 四种分解策略 ⭐⭐⭐⭐
File-based / Feature-based / Risk-based / Research-based，根据任务关键词自动选择。

### 5. Inbox 硬上限 ⭐⭐⭐⭐
MAX_INBOX_LIMIT = 5，防 LLM context 爆炸。消息默认不含 body。

### 6. CAS 分布式锁 ⭐⭐⭐
locks(resource, holder, seq, expires_at) + TTL 自动过期。File reservation 是 warning 不是 blocker。

## 关于"六部小弟自主协调"
swarm-tools 回答了你的问题：它是 Hub-and-Spoke，不是 P2P。Workers 间不直接通信。
→ 你的三省六部可以做"部门级自治 + 跨部门联席会（shared event log）"，比纯中心更灵活。
