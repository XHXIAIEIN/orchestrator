# R38-autoagent — kevinrgu/autoagent 深度偷师

| Field | Value |
|-------|-------|
| Date | 2026-04-03 |
| Source | https://github.com/kevinrgu/autoagent |
| Stars | ~0 (个人项目，thirdlayer.inc) |
| Category | Meta-Agent Engineering, Agent Self-Improvement Loop |
| Files | 10 文件，核心 3 个 (agent.py / agent-claude.py / program.md) |

---

## 项目概述

**一句话定位**：让 Meta-Agent (Claude Code) 在夜间自动迭代改进 Agent Harness，通过 benchmark score 驱动 hill-climbing，实现"人写指令，AI 改代码"的 agent 自演化循环。

本质是一个 **Agent-that-builds-Agents** 范式——用一个外层 Agent 反复修改、基准测试、保留或丢弃内层 Agent 的配置，形成自动化的进化压力。

---

## 架构描述

```
程序员
  │
  ├── 编辑 program.md（指令/约束/策略）
  │
  v
Meta-Agent (Claude Code / 人类)
  │
  ├── 读 program.md → 理解目标和约束
  ├── 读 agent.py → 理解当前 harness
  ├── 读 run.log / results.tsv → 诊断失败
  ├── 修改 agent.py EDITABLE 区域
  ├── git commit
  ├── docker build + harbor run (benchmark suite)
  ├── 记录 results.tsv
  └── keep/discard 决策 → 循环
       │
       v
内层 Agent (agent.py → OpenAI/Claude SDK)
  │
  ├── SYSTEM_PROMPT + TOOLS + MODEL 配置
  ├── 在 Docker sandbox 内执行
  ├── 输出 ATIF trajectory JSON
  └── 被 Harbor verifier 打分
```

核心分层：
1. **程序层 (program.md)** — 人写的元指令，不碰代码
2. **Harness 层 (agent.py)** — 被 meta-agent 迭代的实际代码
3. **适配层 (Harbor Adapter)** — 固定不动的 benchmark 对接代码
4. **执行层 (Docker sandbox)** — 隔离的评估环境

---

## 核心模式清单

### 模式 1: Editable / Fixed Boundary（可编辑/固定边界分离）

**实现位置**: `agent.py` 中的 `# EDITABLE HARNESS` 和 `# FIXED ADAPTER BOUNDARY` 注释

**描述**: 文件被显式分为两个区域——上半部分是 meta-agent 可以自由修改的（prompt、tools、model、orchestration），下半部分是固定的 benchmark adapter 代码。通过注释和 program.md 中的规则来强制执行。

**代码关键片段**:
```
# ============================================================================
# EDITABLE HARNESS — prompt, tools, agent construction
# ============================================================================
... (SYSTEM_PROMPT, create_tools, create_agent, run_task)

# ============================================================================
# FIXED ADAPTER BOUNDARY: do not modify unless the human explicitly asks.
# Harbor integration and trajectory serialization live here.
# ============================================================================
... (to_atif, AutoAgent class)
```

**可借鉴程度**: ★★★★☆ (4/5)

**分析**: 这个模式解决了一个关键问题——当 AI 自我修改代码时，如何防止它破坏基础设施。Orchestrator 的 Governor 目前没有这种"可变/不可变"区域的概念。当 agent 修改自身配置时（比如调整 SOUL/boot.md 或 tools.py），没有显式的保护边界。

**对 Orchestrator 的启示**: 在 agent 自修改场景（如 Clawvard 考试后自动调参）中，需要一个类似的 boundary 机制。可以在 CLAUDE.md 的 Gate Functions 中增加一个 "Self-Modification Gate"。

---

### 模式 2: Score-Driven Keep/Discard Loop（分数驱动的保留/丢弃循环）

**实现位置**: `program.md` 中的 "Keep / Discard Rules" 和 "Experiment Loop"

**描述**: 严格的决策规则——pass 数增加则保留，相同 pass 数但更简单则保留，否则丢弃。搭配 `results.tsv` 作为 experiment ledger，记录每次实验的 commit hash、score、cost、状态。

**核心决策逻辑**:
```
- If `passed` improved → keep
- If `passed` stayed the same AND harness is simpler → keep
- Otherwise → discard
```

附带 "Simplicity Criterion"：同等性能时，更简单的 harness 赢。

**可借鉴程度**: ★★★★★ (5/5)

**分析**: 这是整个仓库最值得偷的模式。Orchestrator 现在的三省六部绩效系统（吏部）是 **观察型** 的——记录绩效但不自动做"保留/丢弃"决策。缺少的是一个 **闭环**：配置变更 → 跑评估 → score 比较 → 自动保留或回滚。

**对 Orchestrator 的启示**:
- `results.tsv` 模式可以直接搬到吏部绩效系统，作为 experiment journal
- Keep/Discard 逻辑可以接入 eval/ 的 ScoringResult，当 Clawvard 考试成绩下降时自动回滚配置
- "同分取简" 原则对 prompt 优化特别有价值——两个 prompt 效果一样时，取更短的那个

---

### 模式 3: Program-Driven Meta-Agent（程序驱动的元代理）

**实现位置**: `program.md` 全文

**描述**: 不直接编辑 agent 代码，而是编辑一个 Markdown "程序"来指导 meta-agent 的行为。program.md 包含完整的决策框架：目标、约束、实验流程、失败分析方法、过拟合检测规则。

**关键约束设计**:
```
## Overfitting Rule
Do NOT add task-specific hacks...
Use this test: "If this exact task disappeared, would this still
be a worthwhile harness improvement?"
If the answer is no, it is probably overfitting.
```

**可借鉴程度**: ★★★★☆ (4/5)

**分析**: 本质上是 "Prompt as Program" 范式的极端运用。Orchestrator 已经有 SOUL/boot.md 和 CLAUDE.md 做类似的事，但 program.md 的独到之处在于：
1. 它是为 **自动化循环** 设计的，不需要人在环
2. 包含显式的 **反过拟合** 机制
3. 有明确的 **NEVER STOP** 指令——循环不需要人确认

**对 Orchestrator 的启示**: Orchestrator 的 dispatch 系统目前是人触发的。如果未来做自动化改进循环（比如夜间自动优化 prompt → 跑 Clawvard → 比较分数），需要一个类似 program.md 的 "autonomy contract"。

---

### 模式 4: ATIF Trajectory Schema（标准化轨迹格式）

**实现位置**: `agent.py` 的 `to_atif()` 和 `agent-claude.py` 的 `_trajectory_to_atif()`

**描述**: 定义了一个标准化的 Agent Trajectory Interchange Format (ATIF)，包含 schema_version、session_id、agent info、steps 数组、final_metrics。每个 step 有 step_id、timestamp、source (user/agent)、message、tool_calls、observation。

**关键结构**:
```python
{
    "schema_version": "ATIF-v1.6",
    "session_id": "...",
    "agent": {"name": "autoagent", "version": "0.1.0", "model_name": "gpt-5"},
    "steps": [
        {
            "step_id": 1,
            "timestamp": "...",
            "source": "agent",
            "message": "Tool: run_shell",
            "tool_calls": [...],
            "observation": {"results": [...]},
            "reasoning_content": "...",
            "model_name": "..."
        }
    ],
    "final_metrics": {
        "total_prompt_tokens": ...,
        "total_completion_tokens": ...,
        "total_cached_tokens": ...,
        "total_cost_usd": ...,
        "total_steps": ...,
        "extra": {"duration_ms": ..., "num_turns": ...}
    }
}
```

**可借鉴程度**: ★★★☆☆ (3/5)

**分析**: Orchestrator 已经有 `TrajectoryStep` 和 `Trajectory` 数据结构（在 `eval/trajectory.py` 中），但格式不同。ATIF 的优势在于：
1. 有 `schema_version`（版本化，方便迁移）
2. 把 `reasoning_content` 和 `observation` 分开存（Orchestrator 的 TrajectoryStep 没有）
3. 有 `model_name` per step（支持多模型 agent）

**差距**: Orchestrator 的 trajectory 更偏"内部评分"（efficiency/correctness/recovery 四维度），而 ATIF 更偏"数据交换格式"。两者解决不同问题。

---

### 模式 5: Dual-SDK Harness（双 SDK 适配层）

**实现位置**: `agent.py` (OpenAI Agents SDK) + `agent-claude.py` (Claude Agent SDK)

**描述**: 同一个 harness 架构，两套实现——一套用 OpenAI Agents SDK，一套用 Claude SDK (claude_agent_sdk)。通过相同的 Harbor adapter 接口实现互换，只改上层的 agent 配置。

**OpenAI 版关键差异**:
```python
from agents import Agent, Runner, function_tool
# 用 Runner.run() 驱动
result = await Runner.run(agent, input=instruction, max_turns=MAX_TURNS)
```

**Claude 版关键差异**:
```python
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
# 用 async stream 驱动
async with ClaudeSDKClient(options=opts) as client:
    await client.query(instruction)
    async for msg in client.receive_response():
        trajectory.append(msg)
```

**可借鉴程度**: ★★☆☆☆ (2/5)

**分析**: Orchestrator 目前绑定 Claude SDK (Agent SDK)，短期没有多 SDK 需求。但 Claude 版的 `get_options()` 配置模式值得看——它把所有 agent 配置集中到一个函数，返回一个 options 对象，非常干净。

---

### 模式 6: Failure Classification Pattern（失败分类模式）

**实现位置**: `program.md` 的 "Failure Analysis" 小节

**描述**: 提供了一个系统化的失败分类框架，用于诊断 agent benchmark 失败：

```
- misunderstanding the task
- missing capability or missing tool
- weak information gathering
- bad execution strategy
- missing verification
- environment or dependency issues
- silent failure (agent thinks it succeeded but output is wrong)
```

附带一个关键原则：**Prefer changes that fix a class of failures, not a single task.**

**可借鉴程度**: ★★★★☆ (4/5)

**分析**: 这个分类直接适用于 Orchestrator 的 corpus.py（生产失败捕获）。目前 corpus.py 的 `_auto_tag()` 做的是关键词匹配（timeout_related, permission_error, import_error 等），但 autoagent 的分类更 **结构化** 且更 **面向改进方向**。

**对 Orchestrator 的启示**: `_auto_tag()` 可以增加以下标签维度：
- `misunderstanding` — agent 理解错任务
- `missing_tool` — 缺少必要工具
- `weak_exploration` — 信息收集不充分
- `silent_failure` — agent 以为成功但实际失败（最危险）
- `strategy_error` — 方法论错误

---

### 模式 7: Tool Strategy Philosophy（工具策略哲学）

**实现位置**: `program.md` 的 "Tool and Agent Strategy" 小节

**描述**: 明确指出 prompt tuning 有递减收益，specialized tools 是高杠杆改进轴。单一 `run_shell` 工具迫使 agent 每次从零写样板代码，浪费 token 且容易出错。专用工具通过结构化数据、清晰错误消息、名称匹配模型先验来降低失败率。

**关键洞察**: "models pattern-match tool names before reading descriptions" — 模型先看工具名后看描述。

**可借鉴程度**: ★★★☆☆ (3/5)

**分析**: Orchestrator 的 tools.py 已经有丰富的专用工具（不只是 bash），但"工具名称影响模型选择"这个洞察值得注意。当前 Orchestrator 的工具命名是否直觉化？比如 `create_task` vs `dispatch_task` vs `submit_task`——哪个名称让模型更容易正确使用？

---

### 模式 8: Docker-Isolated Evaluation（Docker 隔离评估）

**实现位置**: `Dockerfile.base` + `program.md` 中的运行命令

**描述**: 每次评估在全新 Docker 容器中运行，通过 Harbor 框架编排。agent 代码被 COPY 进镜像，任务指令通过文件上传注入，输出通过 trajectory JSON 回收。

**可借鉴程度**: ★★☆☆☆ (2/5)

**分析**: Orchestrator 已经用 Docker compose 运行，但评估层（eval/）目前没有容器隔离。如果未来要跑 SWE-bench 类的重评估，需要类似的沙箱方案。当前优先级不高。

---

## 与 Orchestrator 对比分析

| 维度 | AutoAgent | Orchestrator | 差距 |
|------|-----------|-------------|------|
| **定位** | 夜间自动迭代 agent harness | 实时生产调度 + 治理 | 互补：一个面向优化，一个面向执行 |
| **评估体系** | Harbor benchmark + pass/fail 打分 | 四维 trajectory scoring + LLM-as-Judge rubric | Orchestrator 更丰富 |
| **自改进** | meta-agent 自动修改 → 跑分 → keep/discard | 吏部绩效记录（观察型，不闭环） | **AutoAgent 领先**：有自动闭环 |
| **失败分析** | 7 类结构化分类 + "fix a class" 原则 | 关键词标签 + 捕获到 corpus | AutoAgent 分类更系统 |
| **轨迹格式** | ATIF（交换格式，有版本） | TrajectoryStep（内部评分，无版本） | ATIF 更适合跨系统交换 |
| **工具设计** | 从 run_shell 起步，meta-agent 自己加工具 | 已有丰富工具集 | Orchestrator 领先 |
| **隔离** | Docker per-eval | Docker compose（整体服务） | AutoAgent 更适合评估隔离 |
| **复杂度** | ~400 LOC，极简 | ~5000+ LOC，功能全面 | 不同阶段不同需求 |

---

## 可直接偷的具体模式

### 1. [P0] Keep/Discard 自动闭环 → 吏部绩效

**来源**: program.md Keep/Discard Rules

**落地方式**:
在 `src/governance/eval/` 下新增 `experiment.py`，实现：
- `ExperimentLedger`: 类似 results.tsv 的实验记录
- `evaluate_change()`: 跑评估 → 比较 → 决策
- 决策逻辑：score 提升 → keep，score 相同 + 更简 → keep，else discard
- 集成到 Clawvard 考试流：考试成绩下降 → 自动回滚上次配置变更

**实现复杂度**: 中（需要定义"配置 snapshot"和"回滚"机制）

### 2. [P0] 失败分类系统升级 → corpus.py

**来源**: program.md Failure Analysis

**落地方式**:
扩展 `_auto_tag()` 加入根因分类维度：
```python
ROOT_CAUSE_TAGS = {
    "misunderstanding": ["误解", "wrong interpretation", "不是要求的"],
    "missing_tool": ["no tool", "not available", "不支持"],
    "weak_exploration": ["didn't read", "没检查", "assumed"],
    "strategy_error": ["wrong approach", "应该用", "更好的方式"],
    "silent_failure": ["以为成功", "actually failed", "output mismatch"],
    "verification_gap": ["没验证", "didn't verify", "claimed complete"],
}
```

**实现复杂度**: 低（扩展现有标签逻辑即可）

### 3. [P1] Self-Modification Gate → CLAUDE.md Gate Functions

**来源**: agent.py Editable/Fixed Boundary

**落地方式**:
在 CLAUDE.md Gate Functions 增加：
```
**Gate: Agent Self-Modification (prompt, tools, config)**
1. Is there a baseline score for current config?  → NO: Run eval first.
2. After modification, did eval score improve?     → NO: Revert.
3. Is the change simpler than the previous version? → Track complexity.
4. Proceed and log to experiment ledger.
```

**实现复杂度**: 低（纯 prompt 层面的约束）

### 4. [P1] Trajectory Schema 版本化

**来源**: ATIF schema_version

**落地方式**:
在 `Trajectory` dataclass 加 `schema_version: str = "orch-v1.0"` 字段，为未来数据迁移预留。当 trajectory 格式变更时，老数据仍可被识别和转换。

**实现复杂度**: 极低

### 5. [P2] "NEVER STOP" 自治循环协议

**来源**: program.md 最后一节

**落地方式**:
定义一个 "Autonomous Improvement Loop" skill，用 program.md 的模式：
- 一次性指令 → agent 进入循环
- 每轮: 诊断 → 修改 → 评估 → keep/discard → 下一轮
- 只有人打断才停
- 需要安全边界：cost cap、max iterations、score regression hard stop

**实现复杂度**: 高（需要完整的 autonomy 框架）

---

## 关键洞察总结

1. **观察型绩效 vs 闭环型绩效**: Orchestrator 的吏部是"看绩效单"，AutoAgent 是"根据绩效自动进化"。补上这个闭环是最大增量价值。

2. **反过拟合测试**: "如果这个任务消失了，这个改进还值得吗？" 这个检验标准可以直接用在 Orchestrator 的 prompt 优化中——每次改 system prompt，问一下这个问题。

3. **Simplicity as tiebreaker**: 同等效果取更简单的方案。Orchestrator 的 prompt 和 config 有膨胀趋势（CLAUDE.md 已经很长了），需要定期做 "simplicity audit"。

4. **Tool name > Tool description**: 模型先看名字再看描述。Orchestrator 的工具命名应该做一轮审计——名字是否自解释？

5. **"Fix a class, not a task"**: 失败分析的最高原则。不要因为一个任务挂了就加 hack，要找出背后的 failure class。
