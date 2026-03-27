---
name: orchestrator-steal-sheet-8
description: 2026-03-26 第八轮偷师：Agent Lightning（微软，15.5K star）— Rollout-Attempt-Span 三级生命周期 / Watchdog 嵌入式健康检测 / ComponentSpec 配置驱动 / ExecutionStrategy 双模式 / APO 自动 Prompt 优化 / LLM Proxy 透明代理
type: project
---

## 来源

**Agent Lightning** — https://github.com/microsoft/agent-lightning (15.5K stars)
- "The absolute trainer to light up AI agents" — 用 RL/APO 算法训练优化 AI agent
- 语言：Python | 协议：MIT | 版本：v0.3.1
- 核心架构：Algorithm ↔ LightningStore ↔ Runner 三角循环，Algorithm 和 Runner 零直接通信

详细分析文件：`docs/superpowers/steal-sheets/2026-03-26-agent-lightning.md`

## 新模式清单

### P0 — ✅ 已实施 (2026-03-26)
1. **Rollout-Attempt 重试** — `executor.py` 包 attempt 循环，`RolloutConfig(max_attempts, retry_conditions, backoff_seconds)`，sub_runs 表记录每次 attempt
2. **Watchdog 嵌入式检测** — `_tasks_mixin.py` 的 `update_task()` 搭便车扫描超时/无心跳任务，30s 防抖
3. **ComponentSpec 配置驱动** — `src/core/component_spec.py`，注册表 + `build_component()` 解析（类→实例化，函数→原样返回），executor_session.py 已接入

### P1 — 近期可偷
4. **ExecutionStrategy 双模式** — SharedMemory（debug）/ ClientServer（production），同一逻辑切环境不改代码
5. **APO 自动 Prompt 优化** — Beam Search + Textual Gradient，prompt 迭代优化闭环
6. **LLM Proxy 透明代理** — agent→proxy→LLM，透明 span 采集 + 动态模型切换
7. **Heartbeat Producer-Consumer** — 采集和上报双线程分离，慢 GPU 查询不阻塞
8. **Store Collections 抽象** — Collection/Queue/KeyValue 三接口，换后端不改业务

### P2 — 长线参考
9-14. Tracer 多后端插桩 / Adapter 泛型转换 / Monotonic Sequence ID / Hook 四钩子 / Graceful Shutdown / VERL 分布式 RL

## 与前轮交叉
- Round 4 Supervisor ↔ Watchdog（主动干预 vs 被动检测，可组合）
- Round 5 CostTracking ↔ LLM Proxy（请求级 vs 全链路）
- Round 6 HAND.toml ↔ ComponentSpec（都是配置驱动装配）
