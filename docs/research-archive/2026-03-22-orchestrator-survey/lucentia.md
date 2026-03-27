# Lucentia (wngfra)

- **URL**: https://github.com/wngfra/Lucentia
- **语言**: TypeScript + Bun | **测试**: 177 | **LOC**: ~3,500
- **评级**: A 级（设计优先，实现未完）

## 一句话

事件驱动多 Agent 编排——预算降级链 + 结构化辩论引擎 + 记忆 supersede。

## 可偷模式

### 1. TokenAccountant 预算降级链 ⭐⭐⭐⭐⭐
每个 agent 日预算 + 单任务上限。超预算不报错，自动降级模型：o3 → Opus → Sonnet → Gemini。

→ 三省六部加 token 预算管理。

### 2. AgentSemaphore 分级并发 ⭐⭐⭐⭐
按 agent 类型不同并发上限（Coder 1, Researcher 3），全局上限 8。

→ 防同时跑太多 Claude 进程吃光 API quota。

### 3. Memory Supersede ⭐⭐⭐⭐
新记忆与旧记忆向量相似度 > 0.90 → 旧的标记 superseded。半衰期 90 天时间衰减。compact 时清理。

→ 解决 agent 记忆"永远膨胀"问题。

### 4. 结构化辩论引擎 ⭐⭐⭐⭐
2-5 agent 参与 → 独立立场 → 收敛检测 → 交叉质询（用证据反驳弱论点）→ 合成（共识+分歧+建议）。最多 3 轮。

### 5. Trigger DSL ⭐⭐⭐⭐
JSON 嵌套 predicate（and/or/not + eq/gt/contains/matches/in），带 cooldown + dedup 防重复派单。

### 6. DAG 任务分解 ⭐⭐⭐
LLM 拆 2-5 子任务声明依赖，拓扑序执行，无依赖并行。依赖子任务输出作为上下文。

### 7. Reviewer 独立质量关卡 ⭐⭐⭐
accept/rework/flag 三级决策 + 自动重做循环。

## 注意
- 项目 2 天前创建，backend 都是 mock
- waitForResult 是空 Promise，NATS 订阅未实现
