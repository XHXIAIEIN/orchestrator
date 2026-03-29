# Round 12 — 定期巡查（2026-03-29）

> 13 个仓库定期复查，筛选 2026 年 2-3 月新增模式

## 仓库状态总览

| 仓库 | Stars | 活跃度 | 结论 |
|------|-------|--------|------|
| gstack | 54.8K | 🔥 爆发（v0.11→v0.13，50+ commits） | 大量新货 |
| Axe | 33 | 活跃 | 新检索引擎 + 多模型注册表 |
| OpenHands | 70K (+1K) | 活跃 | Planning Agent + SDK 重构 |
| Firecrawl | 100K (+2K) | 活跃 | 破十万，Parallel Agents + Interact |
| OpenViking | 19.8K | 🔥 爆发（一周 6 版本） | 记忆冷热 + 去重流水线 |
| Swarm → Agents SDK | — | 已迁移 | Swarm 废弃，Agents SDK v0.13 |
| Agent Lightning | — | 低频 | v0.3.0 后零星更新 |
| OpenFang | 15.6K | 🔥 活跃（月发 5 版） | Fallback Chain + Session Repair |
| OpenAkita | 1.4K | 🔥 极活跃（3 track 并行） | 插件权限 + 图记忆 + 自动冻结 |
| Parlant | 17.8K | 活跃 | Relational Resolver + healthz |
| Hermes | — | 🔥🔥 爆发（2.5 周 4 大版本） | Webhook + Skill Templates + Hooks |
| Carbonyl | 17.1K | ☠️ 死（3 年没动） | **移除监控** |
| bytebot | 10.6K | ☠️ 停滞（2025-09 起） | **移除监控** |

---

## P0 — 立即可偷（高价值 + 低实施成本）

### 1. Webhook Event-Driven Agent（Hermes）
- 外部事件（GitHub/Stripe/CI）POST 进来自动触发 agent run
- 文件级热重载（mtime-gated），零 gateway 重启
- **适用**：Orchestrator 采集器和通知体系，事件驱动 > 轮询/cron

### 2. 多模型交叉审查 + User Sovereignty（gstack）
- `/autoplan` 用 Claude + Codex 双模型审查 plan，产出共识表格
- 关键原则：两个 AI 都同意也只是 recommendation
- **适用**：三省六部关键决策交叉验证

### 3. 记忆去重流水线（OpenViking）
- 向量预筛找候选重复 → LLM 判决 CREATE/SKIP/MERGE/DELETE
- **适用**：学习笔记 / SOUL 记忆质量跃升，当前只有 append 没有 merge

### 4. 记忆冷热分离 + Hotness Scoring（OpenViking）
- 根据访问频率给记忆打热度分，低热度归档冷存储
- **适用**：与已有 RedisCache 天然配合

### 5. Model Fallback Chain（OpenFang）
- 主模型失败自动切下一个，带 cost tracking
- **适用**：IntentGateway 加一层 LLM-A → LLM-B fallback，防单点故障

### 6. 信任阶梯（gstack）
- 首次运行 = dry run + 完整验证，后续 = 自动信任
- Config Decay Detection：部署配置指纹变化时重新验证
- **适用**：Claw 审批系统，首次操作确认，重复操作自动放行

### 7. Auto-Freeze Circuit Breaker（OpenAkita）
- 连续空转检测 + 实例级 force_tool_call + 自动冻结熔断
- **适用**：防部门 agent 空转烧 token

### 8. Autonomous Skill Templates（Hermes #492）
- SKILL.md + tool allowlist + requirement declarations + agent config + cron = 自治能力包
- **适用**：Orchestrator 技能体系缺失的自治层

### 9. Event Loop Health `/healthz`（Parlant）
- 测量 event loop callback 延迟，返回 healthy/degraded/unhealthy + peak latency
- **适用**：gateway 健康监控

---

## P1 — 近期值得做

### 10. Handoff input_filter + on_handoff 回调（Agents SDK）
- 交接时裁剪上下文（户部不需要看工部技术细节）
- on_handoff 记录审计日志、更新 Kanban
- **适用**：六部间任务交接

### 11. Plan-then-Execute 双模态（OpenHands）
- Plan Mode 生成结构化 PLAN.md，Code Mode 执行
- **适用**：复杂任务先出方案再执行

### 12. Plugin Lifecycle Hooks（Hermes）
- `pre_llm_call` / `post_llm_call` / `on_session_start` / `on_session_end`
- **适用**：agent loop 关键节点审计、计费、context injection

### 13. Ratio-Based Context Compression（Hermes）
- `compression.target_ratio` + `protect_last_n` + `threshold` 动态压缩
- **适用**：比硬编码 token 上限更适应不同模型

### 14. Agent YAML 继承体系（Axe）
- YAML 定义 agent：system prompt + tools + subagents
- `extend: default` 继承父 agent，只 override 需要的
- **适用**：部门 agent 管理更结构化

### 15. nest_handoff_history 折叠历史（Agents SDK）
- 交接时前序对话压缩成 `<CONVERSATION HISTORY>` 摘要
- **适用**：跨部门交接省 token

### 16. Session Repair / Tool Call Orphan Recovery（OpenFang）
- 7 阶段消息历史验证 + 自动修复孤儿 tool call
- **适用**：agent 崩溃恢复

### 17. Voice Directive + LLM Eval（gstack）
- 25 个 skill 注入声音指令（语气 + 具体性标准）
- LLM eval 测试：直接性、具体性、反企业腔
- **适用**：SOUL 输出一致性保证

### 18. Relational Resolver with Tag Dependencies（Parlant）
- Guidelines 通过 tag 声明依赖，`AnyOf/AllOf` 语义，传递性级联失活
- **适用**：intent rule engine 规则间依赖

### 19. 3-Tier Plugin Permission（OpenAkita）
- Basic（只读）/ Advanced（可调用工具）/ System（可改系统配置）
- **适用**：部门权限分级

### 20. Session Inheritance — 清上下文保环境（OpenHands）
- `/clear` 创建新 conversation，通过 parent_id 链接旧会话，继承 sandbox
- **适用**：agent session 管理

### 21. 统一并发池 + TTL（Firecrawl）
- Interact 会话共享团队级并发池，注册在创建时、清理在销毁时
- **适用**：多 agent/collector 并发控制

### 22. axe-dig 五层精确检索（Axe）
- AST → Call Graph → Control Flow → Data Flow → Program Dependence
- 同样理解一个函数：raw 21K tokens → 175 tokens（99% 节约）
- **适用**：code review agent、impact analysis

---

## P2 — 有空再看

### 23. 3-Layer Memory Encoding Pipeline（OpenAkita）
- 实时规则编码 → 压缩摘要回填 → 会话后批量 LLM 精炼
- 5 维图编码（temporal/causal/entity/action/contextual）

### 24. Unified Capability Pipeline（OpenAkita）
- AgentProfile 统一管理 tools/mcp/plugins，AgentFactory 统一过滤注入

### 25. Design Memory — 审美偏好累积（gstack）
- `$D extract` 用 vision 分析批准的 mockup，写入 DESIGN.md

### 26. Prompt Injection 三层防御（gstack）
- XML trust boundary + bash 白名单 + DeBERTa 分类器（规划中）

### 27. Guardrails 并行执行（Agents SDK）
- 输入/输出校验和 agent 执行并行跑，tripwire 提前终止

### 28. Deferred Retrievers（Parlant）
- 数据检索延迟到 composition 阶段按需触发

### 29. 分级文档解析 fast/auto/ocr（Firecrawl PDF v2）
- Rust 重写，Auto 模式检测复杂情况自动升级

### 30. Scrape Profile 持久化（Firecrawl Interact）
- 浏览器状态/登录态跨任务复用

### 31. Skill 开关 per-user（OpenHands）
- `disabled_microagents` 全链路打通

### 32. PolicyReward 学习信号（Agent Lightning）
- 治理违规转 RL 惩罚（违规率 12.3%→0%）

### 33. 多模型注册表 + 隔离子进程（Axe Bodega）
- 动态加载/卸载模型，硬件隔离

### 34. Smart Approvals 学习型审批（Hermes）
- 记住用户偏好，已批准的安全命令自动放行

### 35. TG Private Chat Topics（Hermes）
- 一个聊天内通过 topic 隔离不同项目

### 36. URI 统一寻址 orch://scope/path（OpenViking）
- resources/user/agent/session 四个 namespace

---

## 安全提醒

- OpenViking v0.2.10 和 Hermes 都紧急禁用了 **LiteLLM**（供应链攻击）
- 如果引入第三方 LLM SDK，需要有依赖锁定 + 快速禁用机制

## 已移除监控

- **Carbonyl**：最后 commit 2023-02-26，三年没动
- **bytebot**：最后功能提交 2025-09-11，半年没动

## ETHOS 新原则（gstack）

- **Boil the Lake**：AI 时代完整实现的边际成本趋近零，不走捷径
- **Search Before Building**：三层知识模型（Tried & True / New & Popular / First Principles）
- **User Sovereignty**：AI 推荐，用户决定
