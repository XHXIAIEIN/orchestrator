---
name: orchestrator-steal-sheet-4
description: 第四轮偷师：OpenAkita — ReAct checkpoint/rollback、8检测×5级干预Supervisor、三层记忆、自我演化
type: project
---

## 偷师来源

**OpenAkita** (https://github.com/openakita/openakita)
- 1400+ star，Apache 2.0，Python 3.11+
- 定位：多 Agent AI 助手框架，桌面(Tauri)+Web+移动三端
- 和 Orchestrator 愿景高度重叠但走了更产品化路线

## P0 — 立刻可偷

1. **Signature Repeat 检测** — `tool_name(md5(params)[:8])` 签名去重，3次NUDGE/5次TERMINATE。加到 Governor 审批前。
2. **Progress-Aware Timeout** — 监控指纹 `(iteration, status, tools_count)`，只在"无进展"时杀。替换硬超时。
3. **截断免回滚** — 截断错误不触发回滚（回滚会丢错误上下文导致重复犯错），改为扩 max_tokens。
4. **快速规则扫描** — 零LLM成本正则匹配强信号词，上下文压缩前抢救关键规则。

## P1 — 需要设计

5. **5级分级干预** — NUDGE→STRATEGY_SWITCH→MODEL_SWITCH→ESCALATE→TERMINATE，升级Governor。
6. **运行时Supervisor** — 8种检测模式（编辑抖动/推理死循环/token异常/空转），观察者模式。
7. **持久性失败计数器** — rollback不清零，累计5次强制策略切换。
8. **Sub-budget比例分配** — 子任务按比例分配token/cost预算。
9. **三层记忆** — SemanticMemory+Episode+Scratchpad，SQLite+FTS5。
10. **superseded_by更新链** — 记忆不覆盖，新链接旧保留溯源。

## P2 — 长线演进

11. 自我演化三阶段（日志+复盘+历史→LLM分析→分级自修复，核心不碰只修工具层）
12. Citation Scoring（记忆检索后回写有效性分数）
13. 人格偏好自动晋升（高置信度记忆→identity文件→prompt重编译）
14. DELEGATION span（run-log加委派链追踪）
15. 滑动窗口自动降级（连续3次失败→切fallback，成功1次恢复）
16. Ephemeral Agent（临时profile不写磁盘）
17. 双轨提取（用户画像vs任务经验分开跑）

## 关键差异

- 他们的强项：运行时监控（8检测×5级干预）、结构化记忆（SQLite+FTS5）、自愈能力、预算管控
- 我们的强项：SOUL身份传承、三省六部文化内核、Claw审批体系、声音样本传承机制
- 最大差距：运行时监控（完全空白）和预算管控（完全空白）
