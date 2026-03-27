# Conitens (seunghwaneom)

- **URL**: https://github.com/seunghwaneom/Conitens
- **语言**: Python (Core 3900 行) + TypeScript
- **评级**: A 级

## 一句话

外部 CLI Agent 的 verify-gated 控制平面——Agent 负责思考，Conitens 负责纪律。

## 可偷模式

### 1. Verify Gate 硬约束 ⭐⭐⭐⭐⭐
非可谈判：任何涉及代码的关闭路径必须通过 verify。所有代码路径（workflow/MCP/Telegram/hook）都不能跳过。

→ 某些规则不该有"跳过"选项。

### 2. Typed Handoff 状态机 ⭐⭐⭐⭐⭐
Agent 间移交有完整生命周期：requested → started → blocked → completed → rejected。

→ 比"发消息就完了"的派单更可追踪。

### 3. Provider Manifest ⭐⭐⭐⭐
`.agent/providers/` 下 YAML 声明如何启动不同 runtime。spawn 时模板渲染。Runtime-agnostic。

### 4. Gate Record 持久化 ⭐⭐⭐⭐
每个审批决策 JSON 记录：gate_id, decision, evidence_refs, resume_token。可回溯可审计。

### 5. Room 概念 ⭐⭐⭐
`.agent/rooms/` 定义共享空间，成员列表 + 共享文件列表。Agent 间上下文边界。

### 6. 三层审批体系 ⭐⭐⭐
AUTO-APPROVE / AUTO-APPROVE with GUARD / ASK。白名单 + 尺寸限制 + 人工。

### 7. Append-only 事件 + 自动脱敏 ⭐⭐⭐
内置 redaction patterns（API key/token/路径），append 时脱敏。

### 8. Markdown-as-Contract ⭐⭐⭐
Workflow 用 Markdown + YAML frontmatter 定义，既是文档也是可执行合约。schema_v 版本控制。
