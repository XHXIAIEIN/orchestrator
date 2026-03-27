# SoulFlow-Orchestrator (berrzebb)

- **URL**: https://github.com/berrzebb/SoulFlow-Orchestrator
- **语言**: TypeScript | **Stars**: 14 | **规模**: 141 工作流节点, 178 工具, 1800+ i18n 键
- **评级**: S 级

## 一句话

自托管、云无关的 AI agent 运行时——9 个 agent 后端 + CircuitBreaker fallback + AES-256-GCM 密封 + 多渠道接入。

## 可偷模式

### 1. Gateway 三路分流 ⭐⭐⭐⭐⭐
每个请求分类：no-token（斜杠命令）/ model-direct（单轮）/ agent（多步推理+工具）。简单请求不走 agent loop。

→ 节省大量 token 和延迟。

### 2. Role/Protocol 策略编译 ⭐⭐⭐⭐⭐
RolePolicyResolver + ProtocolResolver → PromptProfileCompiler 编译成 PromptProfile。system prompt 可组合可继承。

→ 比字符串拼接 system prompt 好太多。

### 3. Phase Loop + Critic Gate ⭐⭐⭐⭐⭐
多阶段工作流，每阶段可 parallel/interactive/sequential_loop。阶段边界有 Critic Gate 审查。

### 4. 并行调和确定性优先 ⭐⭐⭐⭐⭐
并行分支产出 → ReconcileNode 冲突检测 → 先走确定性规则 → 只有无法确定性解决的分歧才升级给 critic。

"把确定性可解的冲突发给模型仲裁是设计错误"

### 5. Novelty Policy ⭐⭐⭐⭐
阻止 agent 重试已失败路径（除非有新信息）。Failed-Attempt Short-Circuit。

### 6. ToolIndex 词法检索 ⭐⭐⭐⭐
FTS5/BM25 持久化索引，按请求动态缩小工具集，不是全部塞给模型。

### 7. Soul/Heart 分离 ⭐⭐⭐
agent 人格拆成 soul（身份原则）+ heart（表达风格）+ extra_instructions，可 fork 可 scope。

### 8. 三输出消毒层 ⭐⭐⭐
Level 1 清理协议泄漏，Level 2 清理 streaming 噪音，Level 3 清理 secrets。
