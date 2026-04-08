# R45: Claude-to-IM-skill — IM Bridge for Claude Code

**Source**: https://github.com/op7418/Claude-to-IM-skill
**Stars**: 2025 | **Language**: TypeScript/Node.js
**Date**: 2026-04-08

## 项目概述

Claude Code / Codex 的 IM 桥接技能，Node.js daemon 把 AI 编码会话桥接到 Telegram/Discord/飞书/QQ/微信 5 个平台。从 CodePilot 桌面应用抽取的轻量版。

## 核心架构

```
Daemon (main.ts) → DI 组装
  ├── llm-provider.ts   → Claude Agent SDK query() → SSE stream
  ├── codex-provider.ts → Codex SDK → 同格式 SSE stream
  ├── permission-gateway.ts → Promise Map 异步等待用户审批
  ├── store.ts          → JSON 文件 + 内存缓存写透
  ├── sse-utils.ts      → 统一事件格式
  ├── logger.ts         → 正则脱敏 + 日志轮转
  └── adapters/weixin-adapter.ts → 微信长轮询 + 消息处理
```

## 可偷模式 (8 个)

### P0 — 直接可用

**1. Permission Gateway Promise-Map**
`PendingPermissions` 用 `Map<id, {resolve, timer}>` 实现异步审批等待，5 分钟超时自动 deny，`denyAll()` 优雅关闭。比 Orchestrator 的 Claw 审批链更轻量，适合实时 IM 交互。

**2. Secret 脱敏日志**
三条正则覆盖 `token/secret/password/api_key` 键值对、Telegram bot token 格式、Bearer token。每条日志过一遍，保留最后 4 位。Orchestrator 的日志目前没有系统性脱敏。

### P1 — 需要改造

**3. SSE 统一事件协议**
`sseEvent(type, data)` 产出标准格式，type 有 text/tool_use/tool_result/permission_request/result/error/status。两个 Provider 输出相同流，IM 适配层完全不感知后端。

**4. 微信 context_token 持久化 + batch cursor 确认**
context_token 存 JSON 文件（daemon 重启不丢失），用 `pendingCursors` Map 跟踪 batch 消息的 cursor 确认。Orchestrator 的微信 context_token 只在内存缓存，重启会丢。

**5. 微信 Session Guard**
session 过期（errcode -14）时暂停轮询而不是崩溃，等待重新登录。指数退避重试。

### P2 — 参考

**6. 双 Runtime 适配** — `resolveProvider()` 根据配置选 Claude SDK 或 Codex SDK，auto 模式先检测 CLI 可用性再 fallback。

**7. CLI Preflight Check** — 启动前验证 CLI 版本、必需 flag、多候选路径优先选兼容版本。

**8. SKILL.md AI-First UI** — 整个 SKILL.md 是超长 system prompt，"AI as the UI layer" 的极致体现。

## 集成建议

| 优先级 | 动作 | 涉及文件 |
|--------|------|----------|
| 高 | 加 secret 脱敏到 logging | `src/channels/` 全局 |
| 高 | 微信 context_token 持久化到 DB | `src/channels/wechat/api.py` |
| 中 | 微信 session guard + 指数退避 | `src/channels/wechat/handler.py` |
| 中 | Permission Gateway 模式用于 IM 审批 | 新增或增强 `src/channels/base.py` |
| 低 | SSE streaming adapter | `src/channels/` |
