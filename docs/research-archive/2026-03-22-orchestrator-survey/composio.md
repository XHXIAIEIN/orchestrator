# ComposioHQ/agent-orchestrator

- **URL**: https://github.com/ComposioHQ/agent-orchestrator
- **Stars**: 5000+ | **语言**: TypeScript 92.7% | **测试**: 3288
- **评级**: S 级

## 一句话

并行 AI 编程 Agent 的调度中心——拆 issue、派 worker、监控 CI、自动闭环。

## 架构

```
ao CLI → Orchestrator Agent (只读 Claude Code) → Session Manager
  → Runtime(tmux) / Agent(claude) / Workspace(worktree) / Tracker(github) / SCM / Notifier / Terminal / Lifecycle
```

Monorepo: packages/core + cli + plugins/* + web(Next.js) + mobile(React Native)

## 可偷模式

### 1. 八槽插件系统 ⭐⭐⭐⭐⭐
8 个功能槽位（Runtime/Agent/Workspace/Tracker/SCM/Notifier/Terminal/Lifecycle），`slot:name` 复合键注册，支持内置包/npm/本地路径三种加载源。

→ 三省六部的部门/采集器可以用类似模式，运行时可插拔替换。

### 2. Orchestrator 即 Agent ⭐⭐⭐⭐
调度器本身是 Claude Code 实例，但被限制为只读。用 prompt 而非代码定义调度逻辑。

→ 三省六部的派单逻辑可以让一个受限 Agent 做决策，而非纯规则引擎。

### 3. 反应式 YAML 生命周期 ⭐⭐⭐⭐⭐
CI 失败 → 自动喂给 Agent → Agent 修 → 再跑 CI → 通过 → 通知人类。YAML 声明式配置反应规则（auto/retries/escalateAfter）。

→ 采集器失败自动重试、质量检查不过自动返工。

### 4. LLM 递归任务分解 ⭐⭐⭐⭐
Claude 判断原子/复合，递归拆分（最深 3 层），"宁可不拆不要过度拆"，拆完人类审批。

### 5. Git Worktree 隔离 ⭐⭐⭐
每个 Worker 独立 worktree，共享 .git，比 clone 快比分支切换安全。

### 6. 文件系统即状态 ⭐⭐⭐
Session 状态用 key=value 文件存磁盘，崩溃恢复扫文件即可。

## 局限
- Agent 间无直接通信，所有协调经过 Orchestrator
- 轮询而非事件驱动
- Orchestrator 是单点
