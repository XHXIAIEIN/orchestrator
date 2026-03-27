# Ferment (diapod)

- **URL**: https://github.com/diapod/ferment
- **语言**: Clojure | **协议**: Apache-2.0
- **评级**: S 级

## 一句话

质量感知的 AI 能力调度内核——intent-based routing + canary/shadow 部署 + 内建训练管线。

## 四层架构

| 层 | 职责 |
|---|---|
| Domain | 意图分类、计划构建、路由（纯函数，无 I/O） |
| Orchestration | 步骤编排、重试/超时/回退策略、质量控制 |
| Adapter | LLM/非 LLM 适配器，协议映射 |
| Runtime | 入口点、配置引导、服务生命周期 |

## 可偷模式

### 1. Intent-based Routing ⭐⭐⭐⭐⭐
`intent->cap` + `intent->policy-profile` 映射。`:call` 节点声明意图+要求+候选者，不是"调模型 X"。

→ 三省六部派单抽象为 intent → department 路由，带策略 profile。

### 2. 质量感知重试 ⭐⭐⭐⭐⭐
`same-cap-max`（同能力重试）+ `fallback-max`（回退跳数）+ `score-min` + `switch-on` 触发条件。三级策略 profile: low-latency/balanced/high-quality。

→ 每个部门设定质量阈值，低于阈值自动切换执行者。

### 3. Canary/Shadow Prompt 部署 ⭐⭐⭐⭐⭐
Protocol artifact versioning，trace-id hash 做百分比路由。Canary 分流新版本，Shadow 并行对比不影响实际响应。

→ Prompt 迭代时 canary 部署，shadow 模式对比新旧效果。

### 4. 内建训练管线 ⭐⭐⭐⭐
Teacher → 训练数据收集（append-only JSONL，自动轮转去重）→ 确定性数据集构建 → Student 评估 → 晋升门控。完整的 self-improvement loop。

### 5. Effect Scope 隔离 ⭐⭐⭐⭐
每个工具节点必须声明 effects/allowed。白名单路径/命令/网络 + RBAC。不是象征性权限检查。

### 6. Gateway 策略 ⭐⭐⭐
`:latency-first`/`:quality-first`/`:cost-first`，带 EMA 平滑、熔断器、投机执行。

### 7. "一切都是能力" ⭐⭐⭐
LLM 和非 LLM 求解器通过统一 capability registry 注册，棋引擎和 GPT-4 是同等公民。

## Router Charter 哲学
核心范围有"不做什么"清单——每个新功能必须证明改善路由指标，否则只能是可选中间件。防 scope creep。
