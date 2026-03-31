# 偷师法医报告：16 轮 Git 考古取证

> 2026-03-31 | 4 个 Agent 并行取证 | 覆盖 135 个模块

## 核心结论

**零事故性覆盖。问题是"写完不接线"。**

- executor.py 被改了 13 次，每次都是追加，从没覆盖过前轮代码（得益于 try/import 防御模式）
- 55 个模块（41%）处于"孤岛"状态——代码完好，从未接入生产路径
- 唯一一次 destructive rewrite（self_eval.py R14→R15）是有意的架构升级

## 总览

| 轮次 | 来源 | 模块数 | 存活+使用 | 孤岛 | 覆盖 | 删除 | 接入率 |
|------|------|--------|-----------|------|------|------|--------|
| R1-2 | 初始偷师 | 17 | 16 | 0 | 0 | 1 | 94% |
| R3-7 | 各项目单偷 | 25 | 4 | 21 | 0 | 0 | 16% |
| R8 | agent-lightning | 4 | 4 | 0 | 0 | 0 | 100% |
| R9-10 | governance 批量 | 18 | 5 | 13 | 0 | 0 | 28% |
| R11 | Swarm/OpenViking/Kanban | 11 | 9 | 2 | 0 | 0 | 82% |
| R12 | Sprint 1-3 | 27 | 27 | 0 | 0 | 0 | 100% |
| R13 | ChatDev 2.0 | 6 | 0 | 6 | 0 | 0 | 0% |
| R14 | ClawHub | 7 | 4 | 2 | 1 | 0 | 57% |
| R15 | entrix/Clawvard | 6 | 4 | 2 | 0 | 0 | 67% |
| R16 | LobeHub | 14 | 5 | 9 | 0 | 0 | 36% |
| **总计** | | **135** | **78** | **55** | **1** | **1** | **58%** |

## 孤岛模块清单（55 个，需接入）

### Round 3-7 孤岛（21 个）

| 模块 | 来源 | 行数 | 核心功能 | 接入难度 |
|------|------|------|---------|---------|
| `governance/session_repair.py` | OpenFang | 170 | SessionRepairer 7阶段修复 | 中 — 需接入 executor_session |
| `governance/handoff.py` | Agents SDK | 206 | HandoffFilter 上下文过滤 | 低 — 接入 review.py |
| `governance/compression.py` | Hermes | 183 | ContextCompressor 比率压缩 | 中 — 与 condenser/ 合并 |
| `governance/permissions.py` | OpenAkita | 177 | 3层权限检查 | 中 — 接入 executor |
| `core/concurrency_pool.py` | Firecrawl | 151 | 统一并发池 | 低 — 替换散落的 Semaphore |
| `gateway/rule_dependencies.py` | Parlant | 147 | 规则依赖解析 | 低 — 接入 intent_rules |
| `governance/session_manager.py` | OpenHands | 143 | Session fork/inherit | 中 — 与 executor_session 整合 |
| `governance/manifest_inherit.py` | Axe | 129 | YAML extends 继承 | 低 — 接入 registry.py |
| `governance/voice_directive.py` | gstack | 188 | Voice 4D 评分 | 低 — 接入 SOUL compiler |
| `governance/plan_executor.py` | OpenHands | 220 | Plan-then-execute + checkpoint | 高 — 需重新设计与 executor 的关系 |
| `governance/code_retrieval.py` | axe-dig | 266 | L0/L1/L2 代码检索 | 中 — 接入 context assembler |
| `governance/smart_approvals.py` | Hermes | 156 | 智能审批 | 低 — 与 approval.py 合并 |
| `governance/deferred_retrieval.py` | Parlant | 123 | 延迟上下文加载 | 低 — 接入 context engine |
| `governance/capability_registry.py` | OpenAkita | 163 | 能力注册 + 层级过滤 | 中 — 与 registry.py 整合 |
| `governance/design_memory.py` | gstack | 233 | 设计记忆存储 | 中 — 与 structured_memory 整合 |
| `governance/cross_review.py` | gstack | 179 | 双模型交叉审查 | 低 — 接入 review.py |
| `governance/skill_template.py` | Hermes | 247 | YAML 技能自动发现 | 中 — 与 registry 整合 |
| `core/lifecycle_hooks.py` | Hermes | 116 | 生命周期钩子注册 | 低 — 接入 executor |
| `gateway/webhook.py` | Hermes | 238 | Webhook + HMAC 验证 | 低 — 接入 gateway |
| `storage/dedup.py` | OpenViking | 155 | 学习去重 | 低 — 接入 learnings |
| `storage/hotness.py` | OpenViking | 163 | 热度评分+冷归档 | 低 — 接入 memory_tier |

### Round 9-10 孤岛（13 个）

| 模块 | 行数 | 核心功能 | 接入难度 |
|------|------|---------|---------|
| `condenser/llm_summarizing.py` | ~120 | LLM 摘要压缩策略 | 中 — 需定义调用时机 |
| `condenser/water_level.py` | ~100 | 水位压缩策略 | 中 — 需定义调用时机 |
| `condenser/amortized_forgetting.py` | ~80 | 渐进遗忘策略 | 中 — 需定义调用时机 |
| `safety/convergence.py` | ~120 | 收敛检测 | 低 — 接入 stuck_detector |
| `safety/drift_detector.py` | ~130 | 偏移检测 | 低 — 接入 supervisor |
| `safety/prompt_lint.py` | ~140 | 7规则提示词检查 | 低 — 接入 scrutiny |
| `safety/dual_verify.py` | ~150 | 双模型交叉验证 | 低 — 接入 scrutiny |
| `safety/injection_test.py` | ~342 | 14 注入测试用例 | 低 — 接入 scrutiny |
| `signals/cross_dept.py` | ~325 | 跨部门信号路由 | 中 — 接入 group_orchestration |
| `pipeline/output_compress.py` | ~100 | RTK 输出压缩 | 低 — 接入 executor |
| `learning/experience_cull.py` | ~120 | 使用量淘汰 | 低 — 接入 maintenance job |
| `learning/fact_extractor.py` | ~150 | ASMR 事实提取 | 中 — 接入 learnings pipeline |
| `quality/fix_first.py` | ~100 | AUTO_FIX/ASK/SKIP 分类 | 低 — 接入 review.py |

### Round 13 孤岛（6 个）

| 模块 | 行数 | 核心功能 | 接入难度 |
|------|------|---------|---------|
| `core/registry.py` | ~130 | 泛型注册表 + 延迟加载 | 低 — 替换 registry.py 硬编码 |
| `core/execution_context.py` | ~160 | 依赖注入上下文 | 高 — 需重构 executor 传参 |
| `core/event_stream.py` | ~180 | 有界队列 + 游标轮询 | 中 — 替换 event_bus 部分功能 |
| `core/resilient_retry.py` | ~120 | 异常链弹性重试 | 低 — 替换 executor 重试逻辑 |
| `core/future_gate.py` | ~100 | 阻塞协调门 | 低 — 接入 group_orchestration |
| `core/function_catalog.py` | ~200 | JSON Schema 函数目录 | 中 — 接入 tool_policy |

### Round 14-16 孤岛（15 个）

| 模块 | 轮次 | 行数 | 核心功能 | 接入难度 |
|------|------|------|---------|---------|
| `audit/evolution_chain.py` | R14 | ~180 | Signal→Hypothesis→Attempt→Outcome | 中 — 接入 learning pipeline |
| `audit/wal.py` | R14 | ~150 | Write-Ahead Log | 中 — 接入 executor session |
| `audit/execution_snapshot.py` | R16 | ~275 | 增量执行快照 | 中 — 接入 executor |
| `audit/file_ratchet.py` | R16 | ~120 | 行数守卫 | 低 — 接入 review.py |
| `audit/waiver.py` | R16 | ~100 | 规则豁免 | 低 — 接入 fitness |
| `audit/change_aware.py` | R16 | ~150 | Git diff→领域映射 | 低 — 接入 scrutiny |
| `audit/skill_vetter.py` | R16 | ~348 | 14 点 SKILL.md 审计 | 低 — 接入 quality job |
| `context/structured_memory.py` | R16 | 914 | 六维记忆系统 | 高 — 替换 memory_tier 或整合 |
| `group_orchestration.py` | R16 | 508 | Supervisor-Executor 多部门 | 高 — 需 governor 调用入口 |
| `condenser/llm_summarizing.py` | R9 | ~120 | (与上面重复) | — |
| `condenser/water_level.py` | R9 | ~100 | (与上面重复) | — |
| `condenser/amortized_forgetting.py` | R9 | ~80 | (与上面重复) | — |

## 覆盖关系

**无事故性覆盖。** 所有轮次的修改都是追加式的（try/import 模式）。

唯一一次 destructive rewrite：
- `audit/self_eval.py`: R14 创建（四维度硬编码规则）→ R15 完全重写（改为从 fitness/*.md 加载）
- 这是有意设计，R15 commit message 明确说 "rewrite to load rules from fitness files"

## 为什么某些轮次接入率高？

| 特征 | 高接入率轮次 (R1-2, R8, R11, R12) | 低接入率轮次 (R3-7, R9-10, R13) |
|------|-----------------------------------|--------------------------------|
| 创建时是否修改已有文件 | ✅ 是 — 同 commit 内接线 | ❌ 否 — 只创建独立文件 |
| 是否有配套的 wiring commit | ✅ 有 (7e120e6, 67e4cab) | ❌ 无 |
| 模块是否依赖已有接口 | ✅ 是 — 直接 import 现有类 | ❌ 否 — 定义全新接口 |

**规律：在创建 commit 中就完成接线的模块，100% 存活。只创建独立文件的模块，84% 成为孤岛。**

## 接入优先级建议

### P0 — 高价值低难度（先接）
1. safety/ 全家桶 (injection_test, dual_verify, prompt_lint, drift_detector, convergence) → 接入 scrutiny
2. storage/dedup + hotness → 接入 learnings + memory_tier
3. audit/skill_vetter + change_aware + file_ratchet → 接入 quality job + review
4. learning/fact_extractor + experience_cull → 接入 maintenance job
5. quality/fix_first → 接入 review.py

### P1 — 中等价值中等难度
6. condenser/ 三件套 → 定义调用时机，接入 executor_prompt
7. core/resilient_retry → 替换 executor 重试逻辑
8. core/registry + function_catalog → 整合进 registry.py
9. signals/cross_dept → 接入 group_orchestration
10. audit/wal + evolution_chain + execution_snapshot → 接入 executor session

### P2 — 高价值高难度（需设计）
11. context/structured_memory (914行) → 与 memory_tier 整合或替换
12. group_orchestration (508行) → 需 governor 新增调用入口
13. core/execution_context → 需重构 executor 传参模式
14. governance/plan_executor → 需重新设计与 executor 的关系
