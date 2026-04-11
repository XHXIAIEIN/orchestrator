# R48 — Hermes Agent v0.7-v0.8 Steal Report

**Source**: https://github.com/NousResearch/hermes-agent | **Stars**: 53.9K | **License**: MIT
**Date**: 2026-04-11 | **Category**: Complete Framework (follow-up to R35b v0.6)
**Commit**: e902e55 | **run_agent.py**: 10,237 lines (528KB, up from 431KB)

## TL;DR

v0.6→v0.8 的核心进化：**从静态配置驱动转向动态自适应系统**。三大方向：
1. Activity-based timeout 取代 wall-clock timeout（活跃度感知）
2. Pluggable Context Engine ABC + Plugin lifecycle（可插拔架构）
3. Delegation 系统加 reasoning_effort 分级（子代理成本控制）

99 commits、两个大版本。上次偷的 6 个 P0 中 Skin Engine 和 Cheap/Strong Routing 已被 hermes 自己大幅增强（live model switching、self-optimized guidance）。

## Architecture Overview

```
Layer 4: Platform Gateway (Telegram/Discord/Slack/Matrix/Signal/WX/Feishu)
  ├── Activity-based timeout (inactivity detection, not wall-clock)
  ├── Approval buttons (native platform UI)
  ├── Duplicate message prevention
  └── Session model override (live /model switching)

Layer 3: Agent Loop (run_agent.py 10K+ lines)
  ├── Context Engine ABC (pluggable compaction: compressor/LCM/custom)
  ├── Memory Provider ABC (pluggable: built-in/Honcho/Supermemory)
  ├── Plugin system (hooks: pre/post_tool_call, pre/post_llm_call, session lifecycle)
  ├── Type coercion (model sends wrong types → auto-fix)
  └── Self-optimized guidance (behavioral benchmarking → model-specific patches)

Layer 2: Delegation (tools/delegate_tool.py)
  ├── reasoning_effort override (parent xhigh → child low)
  ├── Credential pooling with lease/release
  ├── Heartbeat propagation (child → parent activity timestamp)
  ├── Interrupt propagation (parent SIGINT → all children)
  └── Progress relay (child tool calls → parent display)

Layer 1: Execution (terminal backends × 6)
  ├── Background task notifications (notify_on_complete)
  ├── Progressive directory discovery
  └── Exit code context for failure understanding
```

## Steal Sheet

### P0 — Must Steal (6 patterns)

| Pattern | Mechanism | Our Current State | Adaptation | Effort |
|---------|-----------|------------------|------------|--------|
| Activity-Based Timeout | `_touch_activity()` 每次 API/tool 调用刷新时间戳，gateway 查 `get_activity_summary().seconds_since_activity` vs threshold | 无此概念 | Channel 层 TG bot 需要。长任务（爬取/编译）会被误杀 | ~2h |
| Context Engine ABC | 可插拔压缩引擎：ABC 定义 `should_compress()/compress()/get_tool_schemas()`，config.yaml 一行切换 | `.remember/` 固定流程 | 为 RAG 系统预留扩展点。Context engine 可以提供自己的 tools | ~3h |
| Delegation reasoning_effort | 子代理独立配置 reasoning level（xhigh/high/medium/low/minimal/none），省 thinking tokens | Claude Code agent 无此控制 | `.claude/agents/*.md` 可加 `model: haiku` 但没有 reasoning 粒度 | ~1h |
| Heartbeat Propagation | 子代理每 30s 通过 `_touch_activity()` 向父代理报告存活，防止父被 gateway 判定超时 | 无 | Agent dispatch 期间 TG 可能判定超时。加心跳 | ~1h |
| No-Evict-on-Fail Anti-Loop | 失败的 run 保留 cached agent，快速返回错误；成功的 fallback 才 evict 触发重试主 provider | 无缓存 agent 概念 | Gateway/Channel 层如果引入 agent 缓存，必须有这个保护 | ~1h |
| Plugin Hook Lifecycle | 10 个 hook 点（pre/post tool/llm/api call + session start/end/finalize/reset），返回 context 注入 | hooks 系统有但缺 session lifecycle | 加 `on_session_finalize` 和 `on_session_reset` hook | ~2h |

### P1 — Worth Doing (5 patterns)

| Pattern | Mechanism | Adaptation | Effort |
|---------|-----------|------------|--------|
| Progressive Directory Discovery | Agent 导航时逐步学习项目结构，作为 subdirectory hints 注入 | Skill 可以声明 workspace hints | ~2h |
| Credential Pool Lease/Release | 多 API key 池化，`acquire_lease()` / `release_lease()` 防止并发冲突 | llm_router 多 key 轮转 | ~3h |
| Skill Config Interface | Skill 在 frontmatter 声明所需 config 变量，安装时 prompt 用户填写，运行时自动注入 | 我们的 skill 没有 config 声明机制 | ~2h |
| Truthful Compress Responses | 压缩前检查 protected context 边界，报告真实的可压缩空间 | `.remember/` 压缩无状态报告 | ~1h |
| Self-Request Service Restart | SIGUSR1 信号触发 graceful drain → 自重启，避免 systemd force-kill 丢失 in-flight 工作 | Docker 容器内无此机制 | ~3h |

### P2 — Reference Only (5 patterns)

| Pattern | Mechanism | Why ref-only |
|---------|-----------|-------------|
| Type Coercion for Tool Args | 模型返回 `"42"` 但 schema 要 `integer`，自动 coerce | Claude 模型很少犯这种错，主要是 GPT/Codex 的问题 |
| Save Oversized Tool Results to File | 大于阈值的 tool output 写文件而非截断 | 我们通过 Claude Code 的 Read 工具自然分页 |
| Jittered Retry Backoff | 指数退避 + 随机 jitter 防止 thundering herd | 标准模式，已有类似实现 |
| OSV Malware Check for MCP | 安装 MCP extension 时用 OSV 扫描 | 好想法但我们 MCP 安装量小，优先级低 |
| MCP OAuth 2.1 PKCE | 标准 OAuth client 支持 MCP server 认证 | 目前不需要 OAuth MCP |

## Comparison Matrix (P0 Patterns)

| Capability | Their impl | Our impl | Gap size | Action |
|-----------|-----------|---------|----------|--------|
| Activity-based timeout | `_touch_activity()` + `get_activity_summary()` 双方法，gateway 两层检测（idle + wall-clock 10x 兜底） | 无 | **Large** | Steal：Channel 层加 activity tracking |
| Pluggable context engine | ABC 185 行，7 个 optional methods，plugin 注册 + config 选择，engine 可提供自己的 tools | `.remember/` 硬编码流程 | **Large** | Steal：抽象 ContextEngine 接口 |
| Delegation reasoning_effort | `parse_reasoning_effort()` 6 级，config 优先 > parent 继承 > default | agent dispatch 无 reasoning 控制 | **Medium** | Steal：agent prompt 加 reasoning hint |
| Heartbeat propagation | 30s 心跳线程，`_touch_activity()` 从 child 传播到 parent | 无 | **Medium** | Steal：dispatch 期间保持 parent 活跃 |
| No-evict-on-fail | `_run_failed` flag 区分"失败的 run"和"成功的 fallback" | 无 agent 缓存 | **Medium** | Steal：如果引入缓存，这是必备防护 |
| Plugin hook lifecycle | 10 个 hook 点，`invoke_hook()` 逐个回调，error isolation | hooks 系统有 PreToolUse/PostToolUse/Stop | **Small** | Enhance：加 session lifecycle hooks |

## Gaps Identified

| Dimension | Their Coverage | Our Gap |
|-----------|---------------|---------|
| **Security / Governance** | Cross-session isolation, SSRF protection, approval escalation prevention, timing-safe state validation | 我们有 guard.sh 但缺 cross-session 隔离概念 |
| **Memory / Learning** | Multi-tenant memory scoping, thread user ID routing, memory plugin drift overhaul | `.remember/` 单用户，无 multi-tenant |
| **Execution / Orchestration** | Background notify_on_complete, exit code context, activity-based timeout | 无 activity tracking |
| **Context / Budget** | Pluggable Context Engine ABC, engine-provided tools | 硬编码 `.remember/` 流程 |
| **Failure / Recovery** | Drain in-flight, no-evict-on-fail, partial construction tolerance, staleness eviction | 缺乏 graceful degradation |
| **Quality / Review** | Self-optimized guidance (behavioral benchmarking), truthful compress responses | 无 self-diagnostic |

## Adjacent Discoveries

1. **Skill 分类体系**：hermes 有 28 个 skill 类别（creative/devops/gaming/research/...），每类有 DESCRIPTION.md。Progressive disclosure 三层：类别索引 → 名称+描述 → 全文内容。**Token 高效**。
2. **Creative Divergence Strategies**：SCAMPER / Conceptual Blending / Distance Association / Forced Connections / Oblique Strategies。不是随机创意，是**结构化发散**。可以移植到我们的 brainstorming skill。
3. **Constraint-Driven Ideation**：15 个约束模板（"Solve your own itch" / "Subtract" / "Hostile UI"），按 intent 匹配。创意 ≠ 自由发挥，创意 = 约束内最大化。
4. **Snapshot Caching for Skills**：`.skills_prompt_snapshot.json` 缓存 skill 元数据，基于 mtime/size manifest 校验。避免每次启动全扫文件系统。

## Meta Insights

### 1. Activity vs Wall-Clock：从"跑了多久"到"在不在干活"

这是整个 v0.7-v0.8 最深层的思维转变。Wall-clock timeout 假设"时间 = 资源消耗"，但长任务（编译/爬取/大文件处理）可能活跃但耗时。Activity-based timeout 问的是"你还在动吗？"——这才是真正的卡死检测。

**对 Orchestrator 的启示**：TG bot dispatch 任务时，不应该设 30 分钟硬上限，而应该追踪最后一次 tool 调用时间。

### 2. Context Engine 作为一等公民

把压缩/上下文管理从"内部实现细节"提升为"可插拔协议"。ABC 只有 185 行，但定义了完整的生命周期（init → update → should_compress → compress → end）。关键创新：engine 可以提供自己的 tools（如 LCM 的 `lcm_grep`）——压缩引擎不只是被动裁剪，它可以主动提供新能力。

### 3. Delegation 的成本工程

reasoning_effort 分级是成本控制的精妙实现。Parent 用 xhigh 做复杂推理，子代理用 low 做搜索/收集——同一任务内按角色差异化投入。Credential pooling + lease 机制更进一步：多 API key 轮转，子代理 acquire 独占凭证，用完 release。这是**资源管理工程化**。

### 4. run_agent.py 的技术债是一面镜子

从 R35b 的 431KB 膨胀到 528KB（10,237 行），hermes 选择了"一个文件集中所有逻辑"的路线。这让他们的 plugin/context engine/delegation 都是"从大泥球中抽象出接口"。我们用 Claude Code plugin 分散模块的路线更健康——但也要警惕分散过度导致跨模块协调成本。

### 5. 自我诊断 > 静态配置

v0.8 最令人印象深刻的是 "Self-Optimized Tool-Use Guidance"——agent 通过自动化 behavioral benchmarking 发现 5 个 GPT/Codex 故障模式，然后自己写补丁。这不是人类写规则让 agent 遵守，是 agent 自己发现问题自己修。**自我治理的下一步是自我诊断**。
