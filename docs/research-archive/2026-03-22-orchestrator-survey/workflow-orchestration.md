# claude-code-workflow-orchestration (barkain)

- **URL**: https://github.com/barkain/claude-code-workflow-orchestration
- **语言**: Python | **Stars**: 36
- **评级**: A 级

## 一句话

Claude Code 插件——用 hook 把主 agent 阉割成纯调度器，"约束即能力"。

## 核心哲学: Capability Through Constraint

通过 PreToolUse hook 禁止主 agent 直接使用工具（只允许 Agent/TaskCreate/EnterPlanMode），迫使它走 plan-delegate-verify 路径。

## 可偷模式

### 1. Scratchpad 文件传递 ⭐⭐⭐⭐⭐
Agent 输出写到 scratchpad 文件，只返回 `DONE|{path}`。主 agent 永远不读 TaskOutput。彻底杜绝 context 膨胀。

→ 多 agent 并行时的 token 管理核心策略。

### 2. Token 三层压缩 ⭐⭐⭐⭐⭐
- 行为引导（教 agent 用 `git -sb` 而非 `git status`）
- 命令改写（hook 劫持 Bash 命令，compact_run.py 压缩输出）
- 条件注入（需要时才加载 11K token orchestrator prompt）

### 3. Binding Contract Protocol ⭐⭐⭐⭐
规划结果视为"合同"，执行时禁止简化/合并/跳过/改 agent。解决 LLM 执行时"偷懒"。

### 4. 特权衰减 ⭐⭐⭐⭐
委派权限在每个用户消息后自动清除，session >1h 自动失效。防权限泄漏。

### 5. Wave 并行调度 ⭐⭐⭐
同 wave 并行，wave 间串行。Task Graph 合规检查防跳 wave。

### 6. 8 个 Specialized Agent ⭐⭐⭐
关键词 >=2 匹配选中，否则 fallback general-purpose。复杂度评分决定分解深度。
