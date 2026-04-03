# R38 — Agent Evaluation Frameworks 偷师报告

> 2026-04-03 | 8 frameworks + 15 benchmarks | 目标：为 Orchestrator 建立 agent 自评体系

---

## 一、框架全景表

| 框架 | GitHub | Stars | 语言 | 核心定位 |
|------|--------|-------|------|---------|
| **Inspect AI** | [UKGovernmentBEIS/inspect_ai](https://github.com/UKGovernmentBEIS/inspect_ai) | 1.9k | Python | UK AISI 官方 LLM eval 框架，100+ 预置 eval |
| **tau-bench** | [sierra-research/tau-bench](https://github.com/sierra-research/tau-bench) | 1.2k | Python | 对话式 agent benchmark，用户模拟 + 策略合规 |
| **AgentBench** | [THUDM/AgentBench](https://github.com/THUDM/AgentBench) | 3.3k | Python | 8 环境跨域 agent 综合基准 |
| **SWE-bench** | [princeton-nlp/SWE-bench](https://github.com/princeton-nlp/SWE-bench) | 4.6k | Python | 真实 GitHub issue 软件工程 agent 评测 |
| **GAIA** | [HuggingFace Leaderboard](https://huggingface.co/spaces/gaia-benchmark/leaderboard) | — | Python | 通用 AI 助手基准（450 题，3 级难度） |
| **promptfoo** | [promptfoo/promptfoo](https://github.com/promptfoo/promptfoo) | 19.2k | TS/JS | prompt/agent 测试 + 红队框架，声明式 YAML 配置 |
| **Braintrust (AutoEvals)** | [braintrustdata/autoevals](https://github.com/braintrustdata/autoevals) | 851 | Python/TS | 可组合 scorer 库 + 实验追踪平台 |
| **AWS agent-evaluation** | [awslabs/agent-evaluation](https://github.com/awslabs/agent-evaluation) | 354 | Python | LLM-as-evaluator 对话式 agent 测试 |

**额外发现：**
| 框架 | GitHub | Stars | 核心价值 |
|------|--------|-------|---------|
| **LangChain AgentEvals** | [langchain-ai/agentevals](https://github.com/langchain-ai/agentevals) | 536 | 轨迹匹配评估（strict/unordered/subset） |
| **Strands Evals** | [strands-agents/evals](https://github.com/strands-agents/evals) | 99 | ActorSimulator 动态对话 + OpenTelemetry trace 评估 |

---

## 二、架构深度拆解

### 1. Inspect AI — 最完整的 eval 框架

**四层抽象：**
```
Task = Dataset + Solver(s) + Scorer
         ↓          ↓           ↓
    input/target   处理链      评分逻辑
```

- **Dataset**: `input` + `target` 列表，支持 CSV/JSON/HuggingFace
- **Solver**: 可链式组合的处理器（`generate()` → `chain_of_thought()` → `self_critique()`）
- **Scorer**: 评分器，内置 `match()` / `includes()` / `model_graded_qa()` / `f1()` / `math()`
- **Agent**: 继承 Solver 接口，内置 ReAct + Agent Bridge（接入 OpenAI Agents SDK / LangChain / Pydantic AI）

**Sandboxing（杀手级）：**
- 每个 sample 独立容器实例
- 支持 Docker / Kubernetes / Modal / Proxmox
- 自动生成 compose.yaml，支持 `network_mode: none` 隔离
- Scorer 可直接访问 sandbox 检查 agent 产物（文件/DB 状态）
- 资源限制：CPU/mem_limit，10MB 输出限制

**Multi-Scorer 聚合：**
```python
multi_scorer(
    scorers=[model_graded_qa(model=m) for m in ["gpt-4", "gemini-2.5"]],
    reducer="mode"  # 投票制
)
```

**Epoch 策略：**
```python
epochs=Epochs(5, reducer=["mean", "mode", "pass_at_2"])
```

**可偷模式：**
- `@scorer` 装饰器 + `Score(value, answer, explanation, metadata)` 结构化返回
- Sandbox 内评分（检查 agent 是否真的创建了文件/修改了 DB）
- 模板变量驱动的 model grading（`{question}`, `{answer}`, `{criterion}`）
- Clustered standard errors（按分类分组计算标准误差）

---

### 2. promptfoo — 最实用的测试工具

**声明式 YAML 配置：**
```yaml
prompts:
  - file://prompt.txt
providers:
  - openai:gpt-4o
  - anthropic:claude-sonnet-4-20250514
tests:
  - vars: { input: "..." }
    assert:
      - type: contains
        value: "expected"
      - type: llm-rubric
        value: "response is helpful and accurate"
      - type: similar
        value: "reference answer"
        threshold: 0.8
```

**Assertion 体系（40+ 类型）：**

| 类别 | 代表类型 |
|------|---------|
| 字符串 | `equals`, `contains`, `icontains`, `starts-with`, `regex` |
| 数据格式 | `is-json`, `contains-json`, `is-html`, `is-sql`, `is-xml` |
| 统计指标 | `rouge-n`, `bleu`, `meteor`, `levenshtein`, `f1` |
| 模型评分 | `llm-rubric`, `factuality`, `g-eval`, `model-graded-closedqa` |
| RAG 专属 | `context-faithfulness`, `context-recall`, `context-relevance`, `answer-relevance` |
| Agent 专属 | `trajectory:tool-used`, `trajectory:tool-args-match`, `trajectory:tool-sequence`, `trajectory:step-count` |
| 性能 | `cost`, `latency` |
| 安全 | `is-refusal`, `guardrails`, `moderation` |
| 可观测 | `trace-span-count`, `trace-span-duration`, `trace-error-spans` |

**红队能力：**
- `promptfoo redteam run` = generate + eval 一步完成
- 插件化攻击策略（注入、越狱、信息泄露）
- 多语言测试（`language` 字段全局配置）
- CI/CD GitHub Action 集成

**可偷模式：**
- 加权 assertion 聚合：`(score1 × weight1 + score2 × weight2) / (weight1 + weight2)`
- `not-` 前缀取反任何 assertion
- Named metrics 聚合到 dashboard
- Agent trajectory assertions（工具调用序列验证）

---

### 3. tau-bench → τ²-bench → τ³-bench 演进

**核心创新：Dual-Control Environment**

tau-bench 独创了"双控环境"——不只 agent 能调 API，用户也能操作共享世界状态。

```
传统 benchmark:  User (被动) → Agent (主动) → Tools
tau-bench:       User (主动) ⇄ Agent (主动) → Shared World State
```

**架构：**
- **域**: airline / retail / telecom / banking
- **用户模拟**: LLM-based，支持 `llm` / `react` / `verify` / `reflection` 4 种策略
- **评分**: Pass@k（Pass^1 ~ Pass^4）
- **Dec-POMDP 建模**: 双方都是部分可观测的，需要协调沟通

**τ²-bench 四大贡献：**
1. Telecom 双控域（Dec-POMDP 建模）
2. 组合式任务生成器（原子组件程序化组合，确保覆盖率）
3. 环境约束型用户模拟器（行为受工具和可观测状态约束）
4. 细粒度错误分析（推理错误 vs 沟通/协调错误分离）

**数据点**: Solo → Dual-Control 切换后，Pass@1 下降高达 40%

**可偷模式：**
- 用户模拟作为 benchmark 组件（不是固定脚本，是 LLM 驱动的动态对话）
- 策略合规评估（agent 在政策约束下工作）
- 自动错误归因（fault assignment + 错误分类）

---

### 4. SWE-bench — 最接近真实的工程评测

**架构：**
```
GitHub Issue → Model generates patch → Docker container → Run tests → Pass/Fail
```

- 每个 issue 一个独立 Docker 容器（x86_64 预构建镜像）
- 最低要求：120GB 存储 / 16GB RAM / 8 核
- 并行度推荐：`min(0.75 × cpu_count, 24)`
- 变体：SWE-bench / Lite / Verified / Multimodal

**生态：**
- SWE-agent（执行框架）
- SWE-smith（数据生成）
- CodeClash（对抗评测）
- sb-cli（云端评测工具，支持 Modal / AWS）

**可偷模式：**
- 真实 repo + 真实 issue = 无法作弊的评测
- Multimodal 扩展（ICLR 2025，视觉软件领域）
- Private test set 防泄露

---

### 5. AgentBench — 跨域综合评测

**架构：Controller-Worker 模式**
```
Controller (port 5000)
    ├── Assigner (任务分配)
    ├── Task Worker: OS
    ├── Task Worker: Database
    ├── Task Worker: Knowledge Graph
    ├── Task Worker: Card Game
    ├── Task Worker: Puzzles
    ├── Task Worker: ALFWorld
    ├── Task Worker: WebShop
    └── Task Worker: Mind2Web
```

- Docker-compose 编排，支持并发 worker
- v2.0+ 支持 function-calling 风格 prompt
- 与 AgentRL 集成（端到端多任务多轮 RL 训练）

**可偷模式：**
- 8 环境"通考"思路（OS/DB/KG/Game/Puzzle/Home/Web）
- 真容器化环境（不是模拟，是真 OS/真 DB）
- VisualAgentBench 多模态扩展

---

### 6. GAIA — 通用助手基准

**设计哲学**: 人类能做到（92%）但 AI 做不到（GPT-4 仅 15%）的问题

- **3 级难度**: Level 1（好 LLM 可破）→ Level 3（能力跃迁标志）
- **450 题**: 需要推理 + 多模态 + 网页浏览 + 工具使用
- **评分**: 单一正确答案，无模糊地带
- **当前 SOTA**: H2O.ai h2oGPTe Agent（75%），Level 3 最高 61%

**可偷模式：**
- "简单但人类能做"的问题设计哲学
- 明确答案 = 零评分争议
- 多能力交叉测试（不是单维度）

---

### 7. Braintrust / AutoEvals — Scorer 工具箱

**AutoEvals 评分方法矩阵：**

| 类别 | 方法 |
|------|------|
| LLM-as-Judge | Battle, ClosedQA, Humor, Factuality, Moderation, Security, Summarization, SQL, Translation |
| RAG | Context Precision/Relevancy/Recall, Faithfulness, Answer Relevancy/Similarity/Correctness |
| 统计 | Embedding Similarity, Levenshtein |
| 复合 | Semantic List Contains, JSON Validity |

**Braintrust 实验工作流：**
```
Playground (可变, 探索) → Experiment (不可变, 可比较) → CI/CD (自动回归检测) → Production (在线评分)
```

**杀手级反馈环路：**
> "Pull interesting production traces into datasets to improve offline test coverage"
> 从生产环境拉有趣的 trace 回来充实测试集

**可偷模式：**
- Prompt 模板驱动的评分（YAML 模板可调试 evaluation 逻辑）
- 生产→测试的闭环（production traces → datasets）
- 在线 scorer（无 ground truth 时用 LLM-as-judge）

---

### 8. AWS agent-evaluation — LLM-as-Evaluator

**架构：**
```
Evaluator Agent (LLM) → orchestrates conversations → Target Agent (你的 agent)
                       → scores responses during conversation
```

- 并发多轮对话
- Hook 系统（conversation 前后执行集成测试）
- CI/CD pipeline 集成
- 内置 Bedrock / Q Business / SageMaker 支持

**可偷模式：**
- "用 agent 测 agent" 的元评估模式
- Hook 在对话中注入集成测试

---

### 额外：LangChain AgentEvals + Strands Evals

**AgentEvals 轨迹匹配模式：**
- `strict`: 相同顺序 + 相同调用
- `unordered`: 相同调用，任意顺序
- `subset`: 参考轨迹是输出的子集
- `superset`: 输出是参考轨迹的子集
- 支持自定义 tool argument 匹配逻辑

**Strands Evals 独创功能：**
- **ActorSimulator**: 目标驱动的动态对话（根据 agent 响应自适应，不是固定脚本）
- **Trace-based Helpfulness**: 7 级评分体系（0.0~1.0），通过 OpenTelemetry span 分析
- **Tool 粒度评估**: 评估每个工具选择和参数准确度
- **自动测试生成**: 从工具描述生成多样化测试用例

---

## 三、Benchmark 全景（按领域）

| 领域 | Benchmark | 核心特色 |
|------|-----------|---------|
| Web/浏览器 | WebArena | 自托管交互式 web 环境，GPT-4 ~14% → CUGA ~62% |
| | Mind2Web | 137 真实网站，2350 任务，跨域泛化测试 |
| | BrowserGym/WorkArena | 统一浏览器接口 + 682 企业工作流任务 |
| OS/桌面 | OSWorld | Ubuntu + Windows VM，369 任务，多模态截图 |
| | OSUniverse | 图评估（子目标 partial credit） |
| 工具调用 | BFCL v4 | 2000 QA → 2025 扩展到多步 agent 评估 |
| | HammerBench | 多轮手机助手，参数动态变化 |
| 对话 | tau-bench 系列 | 双控环境 + 用户模拟 + 策略合规 |
| | MINT | 多轮交互 + 动态用户反馈 + 学习能力 |
| 工程 | SWE-bench | 真实 GitHub issue 补丁生成 |
| | LiveSWEBench | 过程 + 结果双评估 |
| | ColBench | 协作编码（团队成员视角） |
| 安全 | CyBench | 网络安全 CTF 类任务 |
| 深度研究 | DeepResearch Bench | 100 任务 / 22 领域，RACE + FACT 双框架 |
| 行业 | FieldWorkArena | 工厂监控，视频 + 文档多模态 |

---

## 四、模式提炼（可直接用于 Orchestrator）

### Pattern 1: 结构化 Scorer 装饰器
```python
@scorer(metrics=[accuracy(), stderr()])
def check_tool_output():
    async def score(state, target):
        # 检查 sandbox 里 agent 是否真的完成了任务
        result = await sandbox().exec(["cat", target.text])
        return Score(value=1.0 if "expected" in result.stdout else 0.0)
    return score
```
**来源**: Inspect AI | **价值**: 把评分变成可组合的一等公民

### Pattern 2: 声明式 Assertion Pipeline
```yaml
assert:
  - type: trajectory:tool-sequence
    value: ["search", "read_file", "edit_file"]
  - type: cost
    threshold: 0.05
  - type: latency
    threshold: 30000
  - type: llm-rubric
    value: "output correctly addresses the user's request"
    weight: 2
```
**来源**: promptfoo | **价值**: 非程序员也能写 agent 评测

### Pattern 3: Dual-Control 用户模拟
```
不要把用户当成一个固定 prompt。
用户也是 agent，也能操作环境，也有自己的目标。
评测的是"两个 agent 能不能协作完成任务"。
```
**来源**: tau-bench | **价值**: Orchestrator 本身就是双控场景（主人 + agent）

### Pattern 4: 轨迹匹配评估
```python
trajectory_strict(outputs=agent_steps, reference=expected_steps)
trajectory_unordered(outputs=agent_steps, reference=expected_steps)
trajectory_subset(outputs=agent_steps, reference=expected_steps)
```
**来源**: LangChain AgentEvals | **价值**: 不只看结果，看路径是否合理

### Pattern 5: 生产→测试闭环
```
Production traces → 筛选有趣/失败的 → 加入 test dataset → 回归测试
```
**来源**: Braintrust | **价值**: 测试集持续从真实场景中生长

### Pattern 6: Multi-Scorer 投票
```python
multi_scorer(
    scorers=[gpt4_grader, gemini_grader, claude_grader],
    reducer="mode"  # 多数投票
)
```
**来源**: Inspect AI | **价值**: 单 LLM 评分有偏差，投票制消除

### Pattern 7: Sandbox 产物检查
```
评分器直接进 agent 的 sandbox 检查：
- 文件是否创建？
- 数据库是否正确修改？
- 服务是否在运行？
```
**来源**: Inspect AI + SWE-bench | **价值**: 不信 agent 说了什么，信它做了什么

### Pattern 8: 组合式任务生成
```
原子任务组件 × 参数空间 = 程序化生成大量测试用例
确保领域覆盖率 + 控制复杂度等级
```
**来源**: τ²-bench | **价值**: 手工写 case 不可扩展，程序化生成才行

### Pattern 9: ActorSimulator 自适应对话
```
不是固定脚本，而是给模拟用户一个目标，
让它根据 agent 的实际响应动态调整对话策略。
```
**来源**: Strands Evals | **价值**: 比脚本化测试更能暴露 agent 弱点

### Pattern 10: Agent Trajectory Assertions
```yaml
# promptfoo 独创的 agent 行为断言
- type: trajectory:tool-used
  value: web_search
- type: trajectory:tool-args-match
  value: { tool: edit_file, args: { path: "*.py" } }
- type: trajectory:step-count
  threshold: 10  # 不超过 10 步
```
**来源**: promptfoo | **价值**: 约束 agent 行为边界

---

## 五、对 Orchestrator 的建议

### 立即可用（Phase 1）
1. **引入 promptfoo 做部门 prompt 回归测试** — YAML 声明式，无需写代码，CI/CD 友好
2. **用 AutoEvals 的 Factuality + ClosedQA scorer** 评估三省六部的输出质量
3. **加 trajectory assertions** 到现有的 agent dispatch 流程（工具调用序列是否合理）

### 中期建设（Phase 2）
4. **仿 Inspect AI 的 Scorer 装饰器模式** 建 Orchestrator 自己的评分体系
5. **实现 Production → Test 闭环**（从 events.db 拉失败 trace 充实测试集）
6. **借鉴 tau-bench 的用户模拟** 测试 Telegram/Claw channel 的对话质量

### 远期目标（Phase 3）
7. **Sandbox 评分** — 让 agent 在 Docker 里完成任务，评分器检查容器状态
8. **Multi-scorer 投票** — 多个 LLM 交叉评分消除偏差
9. **Clawvard 考试系统改造** — 用 Inspect AI 的 Epoch + Pass@k 替代当前单次考试

---

## 六、统计摘要

- 研究框架: 8 个 evaluation frameworks + 15 个 benchmarks
- 总 GitHub Stars: ~30k+
- 最高星数: promptfoo (19.2k) — 说明实用工具比学术 benchmark 受欢迎得多
- 最新颖的想法: τ²-bench 的 Dec-POMDP 双控环境（唯一把"用户也是 agent"建模的）
- 最完整的框架: Inspect AI（Task/Dataset/Solver/Scorer 四层 + Sandbox + Agent Bridge）
- 最适合 Orchestrator: promptfoo（声明式 + 红队 + CI/CD） + Inspect AI（sandbox + scorer）的组合
