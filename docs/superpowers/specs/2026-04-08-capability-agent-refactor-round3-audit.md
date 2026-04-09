# Capability + Agent Refactor — Round 3 Deep Audit

**Date**: 2026-04-08
**Analyst**: Orchestrator (third-pass audit, post-Round 1 + Round 2 resolution)
**Target**: `2026-04-08-capability-agent-refactor-design.md`
**Verdict**: Design claims "all P0/P1 resolved" — audit finds 1 P0 + 5 P1 remaining, plus 4 P2

---

## 一、修复声称成立但有漏洞的问题

### 1. Specializations 迁移覆盖不完整 — Clawvard exam 消费端断链

设计加了 `specializations/` 子目录，给出了 20 个 division → capability/specialization 的映射表。但：

- **exam_cases.jsonl 的消费端代码没有提及**。当前 Clawvard 考试通过 `departments/{dept}/divisions/{div}/exam_cases.jsonl` 加载题目。新路径是 `capabilities/{key}/specializations/{spec}/exam_cases.jsonl`，但 Clawvard 的加载逻辑在哪里改？设计的 "File Changes" 节完全没提 Clawvard 相关代码。
- **`dimensions`（primary/secondary/boost）迁移到 `agents/{key}.yaml → dimensions`** — 但 Clawvard 评估是按 department 粒度的，不是按 agent 粒度。一个 `engineer` agent 的 `dimensions` 跟原来 `engineering` 的 `dimensions` 不同：engineer 不包含 orchestrate（被移到了 plan/orchestrate），所以 dimensions 语义变了。

**严重度**: P1（Clawvard 运行时 FileNotFoundError，考试直接崩）

### 2. `authority_cap` 未声明时的默认值未定义

```python
active_caps = [
    c for c in caps
    if AUTHORITY_ORDER[c.authority] <= AUTHORITY_ORDER[intent.authority_cap]
]
```

如果 intent 没声明 `authority_cap`（可选字段），默认值是什么？
- `None` → `AUTHORITY_ORDER[None]` 抛 KeyError
- `APPROVE`（最高）→ 所有 prompt 都注入，等于没过滤

设计里 engineer 的所有 intent 都声明了 cap，但其他 agent 呢？**默认行为未定义。**

**严重度**: P2

### 3. FSM `rubric_override` 的 YAML 语法不合法

```yaml
transitions:
  fact_layer: __self__
    rubric_override:        # ← scalar 后面追加子键，YAML 不合法
      discipline: 0.6
      review: 0.4
```

YAML 里 `fact_layer: __self__` 是 scalar value。不能在 scalar 后面追加 `rubric_override` 子键——parser 报语法错误。正确写法：

```yaml
transitions:
  fact_layer:
    target: __self__
    rubric_override:
      discipline: 0.6
      review: 0.4
```

transition value 需要支持 `string | {target, rubric_override}` 联合类型。当前设计的 transition 解析逻辑只处理 string，**没有提到联合类型解析**。

**严重度**: P2

### 4. DB 迁移 `ELSE department` 保留旧值但无验证步骤

```sql
ELSE department  -- 保留未知值
```

未知值不丢了，但新代码只查 `WHERE agent = 'engineer'` 之类的新值。ELSE 保留的旧值变成幽灵行。

应追加迁移后验证：
```sql
SELECT DISTINCT agent FROM tasks WHERE agent NOT IN ('engineer','architect','reviewer','sentinel','operator','analyst','inspector','verifier');
```

**严重度**: P2

---

## 二、两轮 Review 都没发现的新问题

### 5. `_defaults.yaml` 的 `fact_layer: reviewer` 创造隐式终态陷阱 — P0

```yaml
# _defaults.yaml
transitions:
  fact_layer: reviewer

# reviewer.yaml
transitions:
  done: approved    # ← 终态
  fact_layer: __self__
```

**所有非 reviewer agent 继承了 `fact_layer: reviewer`。**

场景：engineer 执行中触发 `fact_layer`（dispatcher 的 `_needs_fact_expression_split()` 返回 true）：
1. engineer.fact_layer → reviewer
2. reviewer 执行完 → reviewer.done → `approved`（终态）
3. **engineer 的主任务还没完成，流程被终止**

原系统里 `("*", "fact_layer") → quality` 之后 quality.done 会通过 rework 或其他路径回到主流程。新 FSM 里 reviewer 的 `done: approved` 是终态，没有回路。

**这是流程断裂 bug：fact_layer 中断了所有非 reviewer agent 的主任务执行。**

**修复方向**：fact_layer 转移需要携带 return context，执行完后回到原 agent 的流程。可以用 `fact_layer: {target: reviewer, return_to: __self__}` 或栈式 FSM。

**严重度**: P0

### 6. EXECUTE 权限级别的工具集未定义

设计引入 4 级权限：`READ < EXECUTE < MUTATE < APPROVE`。

当前 `blueprint.py` 的 `CEILING_TOOL_CAPS`：
```python
READ:    {"Read", "Glob", "Grep", "Bash"}
PROPOSE: {"Read", "Glob", "Grep", "Bash", "Write"}
MUTATE:  {"Read", "Glob", "Grep", "Bash", "Write", "Edit"}
```

**EXECUTE 级别允许哪些工具？** READ 已经包含 Bash。EXECUTE 和 READ 的差异在哪？

- EXECUTE = READ + Bash → 跟 READ 一模一样（READ 已有 Bash）
- EXECUTE = READ + "可以跑 pytest 但不能 edit" → 需要 Bash 内部的命令过滤器

设计引入了新权限级别但没有定义工具约束。**实现者无法知道 EXECUTE 允许哪些操作。**

注：当前 `_DANGEROUS_PATTERNS` 是黑名单（阻止 `rm -rf /`），不是白名单。EXECUTE 需要的是白名单式约束（只允许测试/诊断命令）。

**严重度**: P1

### 7. `PARALLEL_SCENARIOS` 硬编码未纳入迁移范围

`src/governance/context/prompts.py` 里：

```python
PARALLEL_SCENARIOS = {
    "full_audit": ["security", "quality", "protocol"],
    "code_and_review": ["engineering", "quality"],
    "system_health": ["operations", "personnel"],
    ...
}
```

设计的 "Hardcoded Reference Scan" 列了 5 个已知位置，**没有包含 `prompts.py`**。重构后这些 department 名全部失效。

设计的 `scenarios.yaml` 是新文件，但旧的 `PARALLEL_SCENARIOS` 不会自动消失。两套 scenario 并存会导致路由混乱。

**严重度**: P1

### 8. Prompt 拼接顺序对 LLM 行为影响未验证

当前系统用单一 SKILL.md，由人精心调教——指令顺序、语气、重点分配都是有意为之。

新系统拆成 capability.prompt.md 片段机械拼接。LLM 对 prompt 中指令位置的敏感度很高（recency bias：末尾指令权重更大）。

engineer = develop.prompt → test.prompt。test.prompt 在末尾，LLM 可能过度关注测试而忽略开发质量。

**没有 prompt 拼接的 A/B eval 验证，就无法确认拼接版不会退化。**这是最大的隐性风险——用户不会看到 prompt 变了，只会感觉"以前一次修好的 bug 现在要两轮"。

**严重度**: P1

### 9. Intent-level capability filtering 缺失 — 不相关 prompt 污染

operator = operate(0.5) + collect(0.3) + compress(0.2)。

场景 "Docker 挂了帮我修"：
- 路由到 operator, docker_fix intent
- compose 注入 operate.prompt + collect.prompt + compress.prompt
- collect.prompt（"处理事件流数据"）和 compress.prompt（"上下文压缩"）跟 Docker 修复毫无关系
- LLM 可能在修 Docker 的过程中尝试压缩上下文或处理事件流

同理 inspector 的 TODO 扫描任务会被 express.prompt（"语气调整"）污染，导致 TODO 列表被优美散文体包装。

**根因**：authority_cap 只管权限过滤，不管 prompt 过滤。agent 的所有 capability prompt 无条件注入。

**修复建议**：intent 声明 `active_capabilities`：
```yaml
intents:
  docker_fix:
    active_capabilities: [operate]  # 只加载 operate.prompt
  data_pipeline:
    active_capabilities: [operate, collect]
```

**严重度**: P1

### 10. `→` Unicode 前缀的编码风险

设计用 `→engineer` 表示 agent 引用。`→` 是 U+2192，在不同编辑器/CI 环境中可能有编码问题。建议用 ASCII 前缀（`@engineer` 或 `>engineer`）替代。

**严重度**: P3

---

## 三、消费端体验走查（补充场景）

### 场景 F："Docker 挂了，帮我修一下" — operator 路径

```
用户输入 → operator, operate
  → compose(operate, collect, compress) → model: sonnet, authority: MUTATE
```

| 维度 | 分析 |
|------|------|
| Prompt | 三段拼接：operate + collect + compress |
| 问题 | collect/compress prompt 跟 Docker 修复无关，污染 LLM 注意力 |
| 行为 | LLM 可能输出事件流处理或上下文压缩的无关内容 |

### 场景 G："检查代码里的 TODO" — inspector 路径

```
用户输入 → inspector, inspect
  → compose(inspect, express) → model: haiku, authority: READ
```

| 维度 | 分析 |
|------|------|
| 模型 | haiku 做 TODO 扫描 — 合理 |
| 问题 | express.prompt（"语气调整、表达层改写"）被注入到 TODO 扫描任务 |
| 行为 | TODO 扫描结果可能被优美散文体包装，而不是简洁列表 |

### 场景 H：Clawvard 考试 — 隐性崩溃

```
考试系统加载 engineer 的 exam
  → 路径从 departments/engineering/divisions/implement/exam_cases.jsonl
  → 变为 capabilities/develop/specializations/implement/exam_cases.jsonl
  → 但 Clawvard 加载代码未更新 → FileNotFoundError
  → engineer 不包含 orchestrate（移到 plan/orchestrate）
  → 如果 architect.yaml 没有 dimensions → Clawvard 评分维度丢失
```

### 场景 I：engineer 触发 fact_layer — 流程断裂（P0 #5）

```
用户输入 "帮我写个回答" → engineer, code_fix
  → dispatcher._needs_fact_expression_split() = true（answer 类 intent）
  → Phase 1: engineer.fact_layer → reviewer
  → reviewer 执行事实层审查 → reviewer.done → "approved" (终态)
  → engineer 的主任务永远不会执行
  → 用户等待超时，没有任何输出
```

---

## 四、严重度汇总

| # | 问题 | 严重度 | 类型 |
|---|---|---|---|
| 5 | `_defaults.yaml` fact_layer → reviewer → approved 终态，主任务流程断裂 | **P0** | 新发现 |
| 1 | Clawvard exam 加载路径/dimensions 未迁移 | **P1** | 修复不完整 |
| 6 | EXECUTE 权限级别的工具集未定义 | **P1** | 新发现 |
| 7 | `PARALLEL_SCENARIOS` 硬编码未纳入迁移扫描 | **P1** | 新发现 |
| 8 | Prompt 拼接顺序对 LLM 行为影响未验证 | **P1** | 新发现 |
| 9 | Intent-level capability filtering 缺失，不相关 prompt 污染 | **P1** | 新发现 |
| 2 | `authority_cap` 默认值未定义 | **P2** | 修复不完整 |
| 3 | `rubric_override` YAML 语法不合法，需联合类型 | **P2** | 修复不完整 |
| 4 | DB 迁移后无验证查询 | **P2** | 修复不完整 |
| 10 | `→` Unicode 前缀编码风险 | **P3** | 新发现 |

---

## 五、建议

### 进入实施前必须解决（P0 + P1）

1. **修复 FSM 终态 bug**（#5）：fact_layer/expression_layer 是临时转移，需要 return 机制。建议：
   - 方案 A：栈式 FSM——push(reviewer) → reviewer.done → pop() 回到 caller
   - 方案 B：fact_layer transition 携带 `return_to: __caller__` 语义
   - 方案 C：reviewer 在 fact_layer 上下文中的 `done` 不走 `approved`，走 `return`

2. **Clawvard 消费端代码纳入 File Changes**（#1）：列出所有读取 exam_cases.jsonl 和 dimensions 的代码路径，加入迁移步骤。

3. **定义 EXECUTE 工具集**（#6）：明确 EXECUTE 在 `CEILING_TOOL_CAPS` 里的映射。建议 EXECUTE = READ 工具集 + Bash（带命令白名单过滤），区别于 READ 的 Bash（只允许诊断命令如 `git log`, `docker ps`）。

4. **补全硬编码扫描**（#7）：在 grep 扫描步骤里加入 `prompts.py` 的 `PARALLEL_SCENARIOS`。

5. **追加 prompt 质量 eval 基线**（#8）：迁移前用当前 SKILL.md 跑一轮 eval baseline，迁移后用拼接 prompt 跑同样的 eval，对比得分。

6. **加入 intent-level `active_capabilities`**（#9）：让 intent 声明只激活哪些 capability 的 prompt。

### 实施中可迭代（P2）

7. `authority_cap` 默认值定义为 agent 的 compose authority（即不过滤）
8. Transition value 支持 `string | {target, rubric_override}` 联合类型
9. DB 迁移后跑验证查询

### 收尾处理（P3）

10. `→` 前缀改用 ASCII 字符
