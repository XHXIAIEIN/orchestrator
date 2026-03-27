---
name: orchestrator_steal_sheet_6
description: 第六轮偷师：OpenFang (15.6K stars) — Rust Agent OS，污点追踪/结果感知LoopGuard/ContextBudget/幻觉检测/HAND.toml
type: project
---

## 来源
- https://github.com/RightNow-AI/openfang (15.6K stars, Rust 137K LOC, 14 crates)
- 深度分析: `docs/superpowers/steal-sheets/2026-03-26-openfang-deep-dive.md`

## 新模式 Checklist

- [ ] **P0 污点追踪** — 5 标签 lattice + 3 sink 规则 + declassify → `src/governance/safety/taint.py`
- [ ] **P0 Loop Guard 升级** — 结果感知(同结果=死循环) + Ping-Pong 检测(A-B-A-B) → 升级 `stuck_detector.py`
- [ ] **P0 Context Budget** — 双层截断(单结果30%/全局75%) + UTF-8 安全 → `src/core/context_budget.py`
- [ ] **P1 幻觉动作检测** — LLM 声称执行但无工具调用 → `executor_session.py`
- [ ] **P1 Tool Policy deny-wins** — deny 优先 + glob 匹配工具名 + 子 agent 深度限制
- [ ] **P1 Blueprint 增强** — fallback 模型链 + 工具 profile (Minimal/Coding/Research/Full)
- [ ] **P2 Prompt 注入扫描** — 3 级检测(指令覆盖/数据外泄/异常大小)

## 已有覆盖（不需要偷）
- ✅ Merkle 审计链 — run_logger.py 已有 SHA-256 hash chain
- ✅ 并发控制 — AgentSemaphore 分级控制
- ✅ 背压系统 — SystemMonitor CPU/RAM
- ✅ 成本追踪 — CostTracker per-task

## 核心启示
信息流安全思维：不只问"这个工具能不能用"（静态黑名单），要问"这个数据能不能到那里去"（动态污点追踪）
