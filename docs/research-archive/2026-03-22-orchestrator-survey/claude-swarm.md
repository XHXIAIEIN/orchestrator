# claude-swarm (AudiRamadyan)

- **URL**: https://github.com/AudiRamadyan/claude-swarm
- **类型**: MCP Server for Claude Code worker 集群
- **评级**: A 级

## 一句话

MCP 服务器编排并行 Claude Code worker——Notebook Pattern + Competitive Planning + Protocol Governance。

## 可偷模式

### 1. Notebook Pattern 状态外置 ⭐⭐⭐⭐⭐
所有状态写入 `.claude/orchestrator/state.json`，进度写入 `claude-progress.txt`。Agent context 不是 source of truth，文件系统才是。Context compaction 后调 `orchestrator_status` 恢复。

### 2. File-Based Prompt Passing ⭐⭐⭐⭐
Worker prompt 写入 `.prompt` 文件（权限 0600），不走 shell string。防 prompt injection。

### 3. Competitive Planning ⭐⭐⭐⭐
复杂度 >= 60 的 feature 同时启动两个 planner 各出方案，plan-evaluator 比较打分选最优。

### 4. Frustration Detection ⭐⭐⭐⭐
分析 worker 输出中的挫折语言（"I'm stuck"/"not working"）判断 worker 是否在挣扎。把自然语言输出当遥测信号。

### 5. Protocol Governance ⭐⭐⭐⭐
7 种约束类型（tool_restriction/file_access/output_format/behavioral/temporal/resource/side_effect）。
Object.freeze() 冻结基础安全约束，LLM 生成的 protocol 只能更严格不能更宽松。
Fail-Closed：未知约束类型默认阻止。

### 6. Git Snapshot 回滚 ⭐⭐⭐
每个 worker 启动前创建 `swarm/{featureId}` 分支快照，失败可精确回滚。

### 7. Confidence Scoring ⭐⭐⭐
三信号融合：工具活动模式 35% + worker 自报置信度 35% + 输出文本分析 30%。

### 8. Circuit Breaker on Monitor ⭐⭐⭐
Monitor 轮询错误计数器 MAX=5 后自动停止，防 worker 炸了拖死编排器。
