# claude-prove (mjmorales)

- **URL**: https://github.com/mjmorales/claude-prove
- **PROVE** = Plan, Research, Orchestrate, Validate, Execute
- **评级**: A 级

## 一句话

Claude Code 插件，提供创意到合并的完整生命周期——核心创新是 ACB (Agent Change Brief)。

## 可偷模式

### 1. Agent Change Brief (ACB) ⭐⭐⭐⭐⭐
Agent commit 时声明 intent manifest（"为什么做这个改动"）。改动按意图分组而非按文件分组。

分类法:
- Classification: explicit(用户要求) / inferred(推断) / speculative(自行判断)
- AmbiguityTag: underspecified / conflicting_signals / assumption / scope_creep
- NegativeSpaceReason: out_of_scope / possible_other_callers / intentionally_preserved

→ 让 reviewer 秒定位"哪些是 agent 自作主张"。

### 2. Negative Space ⭐⭐⭐⭐⭐
显式列出 agent 没有改但可能应该改的地方及原因。

→ 加到三省六部的报告格式中。

### 3. Comprehend Skill ⭐⭐⭐⭐
苏格拉底式问答，quiz 用户对 agent 生成代码的理解。跨多代码段、直指真实 bug。

### 4. CAFI 文件索引 ⭐⭐⭐⭐
用 Claude 为每个文件生成 routing hint（"什么时候该读这个文件"），缓存 hash diff 增量更新。

### 5. Hook-Driven Reporter ⭐⭐⭐⭐
PostToolUse hook grep commit 消息 pattern 触发通知，不依赖 LLM 记住调用。

### 6. 确定性脚本 + LLM 分离 ⭐⭐⭐⭐
Shell 做收集/diff/发现，LLM 只做需要理解力的部分。

### 7. 自动缩放执行模式 ⭐⭐⭐
<=3 步 Simple（顺序，无 worktree）/ 4+ 步 Full（并行，有架构审查）。

### 8. 5 阶段验证门控 ⭐⭐⭐
build → lint → test → custom → llm。LLM 验证用 Haiku 做成本优化。
