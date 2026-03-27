---
name: orchestrator_steal_sheet
description: 偷师研究汇总：三轮共 56 个项目/产品，52+ 个模式已实施
type: project
---

## 偷师研究 Round 1（2026-03-22）— 32 个开源 Orchestrator ✅ 全部完成

**位置**: `tmp/research-2026-03-22/`

### 推荐实施路径 — 全部完成

Phase 1: ✅ 哈希链日志 + Authority Ceiling + Gateway 三路分流
Phase 2: ✅ Intent routing + Scratchpad 传递 + PLAN→ACT→EVAL 闭环
Phase 3: ✅ Token 预算降级 + Scout-Synthesize + Doom Loop Detection
Phase 4: ✅ 两级记忆 + Learn-from-edit + Canary prompt 部署

---

## 偷师研究 Round 2（2026-03-23）— Understand-Anything ✅ 核心完成

### 5 个可偷模式

1. ✅ **阶段门控流水线 + 文件级 IPC** → `stage_pipeline.py` + `scratchpad.py`
2. ✅ **Git Hash 增量策略** → `debt_scanner.py` 已用 commit hash 增量
3. ⬜ **知识图谱边分类 + 爆炸半径分析** → 部分（blast_radius 在 scrutiny.py），完整图谱版暂缓
4. ✅ **搜索→扩展→裁剪上下文构建** → `context_assembler.py` HOT/WARM/COLD 三层
5. ✅ **双轨生成（LLM + 启发式 fallback）** → token_budget.py 模型降级链

---

## 总纲

**实施率**: Round 1 12/12 (100%) + Round 2-UA 4/5 (80%) + Round 2-P0~P2 20/23 (87%)
**总计**: ~36/40 核心模式已实施 (90%)

**Why:** 为三省六部下一步演进提供外部参照系
**How to apply:** 偷师表已基本清空。剩余模式为独立项目级别（prompt injection 测试套件、Dual-AI 完整版、跨部门信号协议）。
