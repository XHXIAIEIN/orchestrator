# spencermarx/orc

- **URL**: https://github.com/spencermarx/orc
- **语言**: Bash | **创建**: 2026-03-18 | **Stars**: 4
- **评级**: A 级

## 一句话

Unix 哲学的 agent 编排器——shell over runtime, markdown is the control plane, files are the message bus。

## 四层 Agent 层级

```
Root Orchestrator → Project Orchestrator → Goal Orchestrator → Engineer → Reviewer(临时)
```

## 可偷模式

### 1. Scout-Synthesize ⭐⭐⭐⭐⭐
编排器永远不自己读源码——派 scout sub-agent 并行侦察，自己只做综合分析。保护 context window。

→ 六部不自己调查，派"吏员"侦察。

### 2. 两层 Review ⭐⭐⭐⭐⭐
Dev review（快循环，bead 级）+ Goal review（慢循环，深度审查用独立 sub-agent）。配置化 verify_approval。

→ 质量部：小任务快审 + 大功能深审。

### 3. 文件信号协议 ⭐⭐⭐⭐
`.worker-status` + `.worker-feedback` 纯文本文件，编排器 60-90 秒轮询。任何人都能 echo 修改。

### 4. Adapter Pattern ⭐⭐⭐⭐
每个 agent CLI 一个 bash 文件 6 个函数。`_adapter_build_launch_cmd`、`_adapter_yolo_flags` 等。

### 5. 硬边界设计哲学 ⭐⭐⭐⭐
每个角色"Never does"清单——Engineer 不能 push/merge，Reviewer 不能改代码。Prompt-level RBAC。

### 6. Beads (Dolt DB) 工作追踪 ⭐⭐⭐
MySQL-compatible 的 Git-for-data，支持依赖图、状态查询、版本化。
