# Orchestra (Traves-Theberge)

- **URL**: https://github.com/Traves-Theberge/Orchestra
- **语言**: Go + Electron + React | **Stars**: 15
- **评级**: B 级

## 一句话

Go 后端多 agent 编排平台——从 issue tracker 拉任务 → 分派 agent → 监控 SSE → 失败重试 → 交付。

## 可偷模式

### 1. Claim-Execute-Release ⭐⭐⭐⭐
`ClaimNextRunnable()` → 执行 → `RecordRunSuccess/Failure`。类似行级锁，防重复派发。

### 2. Reconciliation Loop ⭐⭐⭐⭐
`PerformRefresh()` 定期对账：拉 tracker 状态 → 对比内存 → 清理已完成 → 释放到期 retry → 入队新候选。K8s controller reconcile 思想。

### 3. Provider Cascade ⭐⭐⭐⭐
失败 3 次自动换 provider（Claude → Codex），不是重试同一个。

### 4. Stall Detection ⭐⭐⭐
20 分钟无事件 = stalled，自动回收。

### 5. Snapshot 模式 ⭐⭐⭐
整个状态做 point-in-time 快照，前端只读快照。并发安全好调试。

### 6. 环境白名单 ⭐⭐⭐
`safeSubprocessEnv()` 只传白名单环境变量给 agent 子进程。

## 局限
- 调度太简单，无优先级/负载均衡
- 无 DAG 工作流
- 内存为主，无 crash recovery
