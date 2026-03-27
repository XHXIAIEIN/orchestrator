# codingbuddy (JeremyDev87)

- **URL**: https://github.com/JeremyDev87/codingbuddy
- **语言**: TypeScript (NestJS + MCP SDK) | **Agents**: 35
- **评级**: A 级

## 一句话

MCP server + 规则引擎，寄生在 Claude Code/Cursor 上，35 个专业化 agent 模拟团队协作。

## 三层 Agent 体系

| 层 | 数量 | 职责 |
|---|---|---|
| Mode Agent | 4 | plan/act/eval/auto 状态机 |
| Primary Agent | 16 | 实际执行 |
| Specialist Agent | 15 | 领域评审 |

## 可偷模式

### 1. PLAN→ACT→EVAL 循环 ⭐⭐⭐⭐⭐
AUTO 模式循环直到 criticalCount===0 && highCount===0。达上限 fallback 回 PLAN 让人类介入。

→ 三省六部"评估-回炉"的量化退出标准。

### 2. Anti-Sycophancy ⭐⭐⭐⭐⭐
EVAL mode 禁止恭维词（"Great job"/"Well done"），必须先说问题再说优点，必须至少 3 个改进点。

→ 质检部评审 prompt 加入。

### 3. Wave Splitter 图着色 ⭐⭐⭐⭐
贪心图着色算法把有文件冲突的 issue 分成无冲突 wave，实现安全并行。

→ 多 agent 并行修改文件的冲突预防。

### 4. Complexity Classifier ⭐⭐⭐⭐
加权关键词 → SIMPLE/COMPLEX 分流。复杂任务注入 SRP 结构化推理模板。

### 5. Agent Profile JSON Schema ⭐⭐⭐⭐
`role.expertise[]`, `role.responsibilities[]`, `delegates_to`, `activation.mandatory_checklist`。

→ agent 管理变成数据管理问题。

### 6. Context Document 持久化 ⭐⭐⭐
每个 cycle 写入 context 文件，ACT 读上一轮 PLAN 的推荐 agent。解决 context compaction 后丢失决策。
