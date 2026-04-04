# Round 38 — Agent Evaluation 偷师

| Field | Value |
|-------|-------|
| Date | 2026-04-03 |
| Sources | 8 框架 + 15 benchmarks + 3 深度拆解 |
| Stars | promptfoo 19.2K / SWE-bench 4.6K / AgentBench 3.3K / Inspect AI 1.9K |
| Category | Agent Evaluation, Scoring, Benchmarking |

## Source 概述

Agent eval 领域 2025-2026 爆发，从"跑个准确率"进化到完整的评估工程体系。核心玩家：

| 框架 | Stars | 核心定位 | 最值得偷的 |
|------|-------|---------|-----------|
| **Inspect AI** | 1.9K | UK AISI 官方 eval 框架，四层抽象 + Sandbox | Approval 5-decision, Hooks 16 事件, Registry 装饰器 |
| **promptfoo** | 19.2K | 声明式 YAML agent 测试，40+ assertion | trajectory assertions, 加权聚合, 红队内置 |
| **tau-bench** | 1.2K | 双控环境 benchmark (Dec-POMDP) | 用户也是 agent，协作能力暴露 |
| **SWE-bench** | 4.6K | 真 GitHub issue 工程评测 | 真容器 + 真测试 = 无法作弊 |
| **AgentBench** | 3.3K | 8 环境跨域通考 | Controller-Worker 多环境编排 |
| **Braintrust** | 851 | Scorer 工具箱 + 实验追踪 | Production→Test 闭环 |
| **LangChain AgentEvals** | 536 | 轨迹匹配评估 | strict/unordered/subset 三模式 |
| **Strands Evals** | 99 | ActorSimulator 动态对话 | 目标驱动的自适应用户模拟 |

额外研究：Bloom (Anthropic)、CourtEval (ACL 2025)、CISC (ACL 2025)、AdaRubric、RULERS

## 偷师提取

### P0 — 直接实施

#### 1. Approval 5-Decision + Escalation Chain
**来源**: Inspect AI `src/inspect_ai/approval/`
**当前差距**: Claw 审批只有 approve/reject 二元决策
**偷什么**:
- 5 种决策：`approve` / `modify`（改参数再执行）/ `reject` / `terminate`（终止整个任务）/ `escalate`（升级到下一审批人）
- Glob 匹配工具名：`bash*` 匹配所有 bash 变体，`desktop_*` 走人审
- 审批策略 YAML 配置化（当前写死在代码里）
- ToolCallView 定制渲染 — 审批通知里展示友好预览而非原始 JSON
- ContextVar 作用域 — 每个 agent 可以有自己的审批策略

```yaml
# 理想配置
approvers:
  - name: auto_safe
    tools: ["read_file", "grep", "glob"]
    decision: approve
  - name: bash_allowlist
    tools: "bash*"
    allowed_commands: [ls, cat, grep, git status]
  - name: escalate_to_tg
    tools: ["desktop_*", "send_*"]
    decision: escalate  # Claw → TG → 人审
```

**实施路径**: 扩展 `src/governance/approval.py`，加 modify/escalate/terminate + YAML 策略加载

#### 2. Agent Trajectory Assertions
**来源**: promptfoo + LangChain AgentEvals
**当前差距**: Clawvard 只看最终答案，不看 agent 做了什么
**偷什么**:
- `trajectory:tool-used` — agent 是否用了正确的工具
- `trajectory:tool-sequence` — 工具调用顺序是否合理
- `trajectory:step-count` — 步骤数是否在预期范围内
- `trajectory:tool-args-match` — 工具参数是否正确
- 三种匹配模式：strict（完全匹配）/ unordered（无序匹配）/ subset（子集匹配）

```python
# Clawvard 考试扩展
@dataclass
class TrajectoryScore:
    efficiency: float       # optimal_steps / actual_steps
    correctness: float      # correct tool calls / total
    recovery: float         # 错误后恢复能力
    tool_selection: float   # 选对工具的比率

    @property
    def composite(self) -> float:
        return (self.efficiency * 0.2 + self.correctness * 0.4 +
                self.recovery * 0.2 + self.tool_selection * 0.2)
```

**实施路径**: Governor dispatch 记录完整工具调用链，Clawvard 评分时同时评估轨迹

#### 3. LLM-as-Judge Pipeline (Bloom 模式)
**来源**: Anthropic Bloom + Microsoft ai-agent-evals
**当前差距**: Clawvard 评分用单 LLM 直接评，无结构化 rubric
**偷什么**:
- 分离确定性检查（工具选择、参数格式）和 LLM 判断（回答质量、目标对齐）
- 评分模板可定制：`{question}` / `{answer}` / `{criterion}` 变量注入
- 三级评分制：`C`(orrect) / `P`(artial) / `I`(ncorrect)，比二值 pass/fail 信息量大
- Judge 看的是环境最终状态，不是 agent 声称做了什么

```python
@dataclass
class ModelGradedScore:
    dimension: str        # "correctness" / "safety" / "completeness"
    score: float          # 0-1
    confidence: float     # judge 自评置信度
    reasoning: str        # CoT 推理过程
    evidence: str         # 从 agent 输出中引用的具体证据
```

**实施路径**: 扩展 `eval_loop.py` 的 EvalResult，加 model_graded 维度

#### 4. Production → Test 闭环
**来源**: Braintrust 核心理念
**当前差距**: 测试集是手工维护的，和生产环境脱节
**偷什么**:
> "Pull interesting production traces into datasets to improve offline test coverage"
> 从生产环境拉有趣/失败的 trace 充实测试集

- events.db 里的失败派单 → 自动进入 Clawvard 考题库
- TG bot 对话中的边界 case → 渠道测试数据集
- Governor dispatch 的 stuck/retry 场景 → 回归测试

**实施路径**: 每次 Governor dispatch 失败时，自动将 task description + agent output + failure reason 存入 `data/eval_corpus/`，定期从中生成考题

### P1 — 中期建设

#### 5. ✅ Hooks 16-Event Lifecycle + Fault Isolation
**来源**: Inspect AI `src/inspect_ai/hooks/_hooks.py`
**状态**: 已实施 — `src/core/lifecycle_hooks.py` (统一 16 事件注册表)
**实施内容**:
- 16 hook points: batch/task/rollout/attempt/context/llm/review/error 七层
- `LimitExceededError` 唯一穿透异常
- `HookEntry` with `enabled()` + `priority` 排序
- 向后兼容别名 (pre_llm_call → on_pre_llm etc.)
- executor.py 旧 LifecycleHooks dataclass + bridge 代码已移除
- **待定**: SampleEvent anyio 异步 drain (当前同步足够，高频场景再加)

#### 6. Multi-Evaluator Consensus (CourtEval 模式)
**来源**: CourtEval (ACL 2025) + Inspect AI multi_scorer
**当前差距**: Clawvard 用单 LLM 评分，有模型偏差
**偷什么**:
- CourtEval 法庭模型：Grader 初评 → Critic 反驳 → Defender 辩护 → Grader 终评
- 多模型独立评分 + 投票制聚合（mode reducer）
- 分歧超 0.15 时触发对抗质疑，否则直接聚合

```python
multi_scorer(
    scorers=[claude_judge, gpt4_judge, gemini_judge],
    reducer="mode"  # 多数投票
)
```

**适用场景**: 高风险决策（晋升 pattern 到 boot.md、通过 HARD gate）

#### 7. Epochs + ScoreReducer (多轮评估)
**来源**: Inspect AI
**当前差距**: Clawvard 一题考一次，Claude 随机性导致 35 分波动
**偷什么**:
- 同一 sample 跑 N 次（epochs），用 reducer 聚合：mean/mode/max/pass_at_k
- Clawvard 关键题 epochs=3 + mode，减少随机误判

```python
Exam(dataset=questions, solver=agent, scorer=rubric(),
     epochs=Epochs(3, reducer=[mode()]))  # 跑 3 次取众数
```

#### 8. Rubric-Based Partial Credit (AdaRubric 模式)
**来源**: AdaRubric (arxiv:2603.21362) + RULERS
**当前差距**: 4/5 步对但最后一步错 ≠ 完全答错，当前无法区分
**偷什么**:
- 三级评分：Satisfied / Partial / Not Satisfied（比 5 分制对 LLM 更稳定）
- 证据锚定评分（RULERS）— 每个分数必须引用 agent 输出的具体文本
- DimensionAwareFilter — 防止高分维度掩盖低分维度的问题

```python
@dataclass
class RubricCriterion:
    name: str
    weight: float
    satisfied: str      # 满分示例
    partial: str        # 半分示例
    not_satisfied: str  # 零分示例
```

#### 9. Decorator-Registry System
**来源**: Inspect AI `src/inspect_ai/_util/registry.py`
**当前差距**: Clawvard 考题/评分器没有统一注册发现机制
**偷什么**:
- 14 种组件类型用统一的 `@decorator → RegistryInfo → registry_create()` 注册
- CLI 可发现：`inspect list tasks` 自动列出所有 @task 函数
- 跨包命名空间防冲突
- 字符串名字动态重建实例（序列化友好）

```python
@exam(name="clawvard_v2", category="agent_competency")
def clawvard_exam():
    return Exam(dataset=load_questions(), scorer=rubric_grader())
# → `exam list` 自动发现
```

#### 10. EarlyStopping Protocol
**来源**: Inspect AI
**当前差距**: Clawvard 每次完整考完，即使已经明确通过/失败
**偷什么**:
- per-sample 粒度早停（不是整个 eval 停）
- 连续 3 次答对 → 跳过该类剩余题目
- 双向通信：schedule 前问 + complete 后报

**价值**: 自适应考试长度，节省 token

#### 11. Self-Consistency Check (CISC 模式)
**来源**: CISC (ACL 2025)
**当前差距**: Agent 声称的事实无验证机制
**偷什么**:
- 同一问题跑 N 次，一致的事实 = 可靠知识，不一致 = 可能幻觉
- 置信度加权投票（8 样本超越 30 样本标准方法，省 40% 算力）
- 三种置信度提取：Response Probability / Verbal / P(True)

**适用场景**: 要提升到 boot.md 的 pattern、训练其他 agent 的数据

### P2 — 远期参考

#### 12. Dual-Control Environment (tau-bench)
用户也是 agent，也能操作共享世界状态。Solo→Dual 切换后 Pass@1 暴跌 40%。
**对 Orchestrator**: 主人和 agent 协作就是双控场景。

#### 13. AgentAttempts + Runtime Scoring
Agent 提交答案后立即调用 scorer 检查对错，错了给提示继续做（最多 N 次）。
**对 Clawvard**: 多次答题 + 即时反馈，取最佳尝试。

#### 14. ActorSimulator 自适应对话
不是固定脚本，是给模拟用户一个目标，让它根据 agent 实际响应动态调整策略。
**对 Channel 测试**: 比脚本化测试更能暴露 TG/Claw 对话弱点。

#### 15. Store + StoreModel 类型安全视图
底层 dict + Pydantic BaseModel 验证视图，兼顾灵活和类型安全。
**对 Agent TaskContext**: `state.store_as(MyAgentState).attempts += 1`

#### 16. Agent ↔ Solver ↔ Tool 三重身份
一个组件三种用法 + handoff 自动命名 + submit 清理。
**对六部协作**: `transfer_to_engineering()` handoff 模式。

#### 17. Transcript + Span Tracing
ContextVar 维护嵌套 span 树，StoreEvent 自动 diff，ModelEvent 内存 condense。
**对 Agent 追踪**: 完整执行回放。

#### 18. Regression Detection (Bootstrap CI)
量化回归检测：bootstrap 10000 次采样，CI 不包含 0 = 显著退步。
**对趋势追踪**: LoopState.get_trend() 从定性升级到定量。

#### 19. Dynamic Task Generation
参数化模板 × 难度轴 = 程序化生成大量测试，防基准饱和。
**对 Clawvard**: 扩展考题池。

#### 20. Per-Capability Breakdown
分维度报告（code/research/conversation/tool_use/planning），暴露短板。
**对 Clawvard**: 当前 6 维度可以细化。

## Benchmark 全景（附录）

| 领域 | Benchmark | 核心特色 |
|------|-----------|---------|
| Web | WebArena | 自托管交互式 web，GPT-4 ~14% → CUGA ~62% |
| Web | BrowserGym/WorkArena | 统一浏览器接口 + 682 企业工作流 |
| OS | OSWorld | Ubuntu + Windows VM，369 任务 |
| 工具 | BFCL v4 | 2000 QA → 多步 agent 评估 |
| 对话 | tau-bench | 双控 + 用户模拟 + 策略合规 |
| 工程 | SWE-bench | 真 GitHub issue + Docker + 真测试 |
| 安全 | CyBench | 网络安全 CTF |
| 研究 | DeepResearch Bench | 100 任务 / 22 领域 |
| 通用 | GAIA | 450 题，人 92% / GPT-4 15% |

## 统计

- 研究范围: 8 eval 框架 + 15 benchmarks + 3 学术论文
- 提取模式: **20 个** (4 P0 / 7 P1 / 9 P2)
- 最值得偷: Inspect AI (架构最完整) + promptfoo (最实用) + Braintrust (生产闭环)
- 最新颖: tau-bench Dec-POMDP 双控 + CISC 置信度加权自一致性
- 子报告: `R38-inspect-ai.md` (15 patterns) / `R38-agent-eval-frameworks.md` (10 patterns) / `R38-agent-eval-patterns.md` (19 patterns)
