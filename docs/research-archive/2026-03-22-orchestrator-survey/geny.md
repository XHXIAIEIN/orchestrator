# Geny (CocoRoF)

- **URL**: https://github.com/CocoRoF/Geny
- **语言**: Python (FastAPI + LangGraph) + React + Three.js
- **评级**: B 级

## 一句话

多 Claude Code 进程管理 + LangGraph 状态图弹性编排 + 3D 城市可视化。

## 可偷模式

### 1. 结构化完成信号协议 ⭐⭐⭐⭐
CompletionSignal enum: TASK_COMPLETE / CONTINUE:{next} / BLOCKED:{reason} / ERROR:{desc}。边函数读 state 字段决策，不碰原始文本。

### 2. Context Guard 图节点 ⭐⭐⭐⭐
双阈值（warn 75% / block 90%），多种压缩策略（保留最近 N 条 / 截断早期 / 删除工具调用细节）。

→ 长任务必备，三省六部长链条很容易爆上下文。

### 3. Model Fallback Runner ⭐⭐⭐⭐
错误分类（rate limit/overloaded/timeout/context overflow/auth/network/abort），候选模型按优先级排队，记住上次成功的模型优先。AbortError 直接穿透不降级。

→ 六部通用弹性层。

### 4. Proxy MCP 模式 ⭐⭐⭐⭐
Python 工具 → 子进程 MCP server → HTTP 转发回主进程。工具崩了不影响 Agent 进程。

### 5. 难度分级路由 ⭐⭐⭐
Easy（直接回答）/ Medium（回答+自审查循环）/ Hard（拆 TODO→逐条执行→进度检查→终审）。

### 6. 双层记忆注入 ⭐⭐⭐
每 10 轮才重注入 + 字符预算控制 + 长期记忆 1.2x 权重。XML 标签包裹注入块。

## 不偷
- 3D 城市可视化（炫但无信息增益）
- spawn CLI 子进程（你已有 Agent SDK）
