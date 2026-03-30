# Clawvard 考试团队系统设计

> 没有完美的个人，但有完美的团队。

## 背景

Clawvard 考试：8 维度 × 2 题 = 16 题，分 8 batch 串行提交。

当前单 agent 全能模式最好成绩 A+ / 98th percentile，但存在结构性缺陷：
- **Output budget 争抢** — 一个 agent 的 context 装 SOUL + learnings + 所有上下文，留给答案的 token 被挤压
- **技能不匹配** — Tooling 要 CLI 精度，EQ 要情感写作，一个 prompt 不可能同时优化所有维度
- **Reflection 随机触发** — prompt 塞太多"注意事项"，agent 记不住哪些该在哪用

## 核心思路

**拆"全能选手"为"教练 + 专项团队"**。

Coach（教练）负责调度 + 赛前注入 + 审阅微调。六部二十四司各领一个维度，考试时 Coach 按 dimension 派单给对应的司。

## 架构

```
                    ┌─────────────┐
                    │  ExamCoach   │  调度 + 赛前注入 + 审阅/微调
                    └──────┬──────┘
                           │ 看 dimension 字段派单
          ┌────────┬───────┼───────┬────────┬────────┐
          ▼        ▼       ▼       ▼        ▼        ▼
        工部     户部×2   刑部    礼部×2   吏部×2   (兵部待命)
       implement operate  review interpret analyze
                 collect         communicate recall
          │        │       │       │        │
          ▼        ▼       ▼       ▼        ▼
       答案汇集 → Coach Review → 微调/打回 → ExamRunner.submit()
```

## 六部二十四司

### 工部 (Engineering)

| 司 | Key | 职责 | 考试维度 |
|---|-----|------|---------|
| 实现 | `implement` | 核心代码编写、feature 开发 | **Execution** ★ |
| 搭建 | `scaffold` | 项目脚手架、CI/CD | — |
| 集成 | `integrate` | 依赖管理、包版本 | — |
| 编排 | `orchestrate` | Pipeline、数据流 | — |

### 户部 (Operations)

| 司 | Key | 职责 | 考试维度 |
|---|-----|------|---------|
| 运维 | `operate` | 容器、部署、CLI 工具链 | **Tooling** ★ |
| 预算 | `budget` | Token budget、成本优化 | — |
| 采集 | `collect` | 数据采集、信息检索 | **Retrieval** ★ |
| 存储 | `store` | DB 管理、备份 | — |

### 礼部 (Protocol)

| 司 | Key | 职责 | 考试维度 |
|---|-----|------|---------|
| 解读 | `interpret` | Spec/需求解析 | **Understanding** ★ |
| 校准 | `calibrate` | SOUL 维护、voice、人设传承 | — |
| 沟通 | `communicate` | 对外交互、语气把控 | **EQ** ★ |
| 润色 | `polish` | 内容质量、格式规范 | — |

### 刑部 (Quality)

| 司 | Key | 职责 | 考试维度 |
|---|-----|------|---------|
| 审查 | `review` | Code review、元认知自审 | **Reflection** ★ |
| 检测 | `detect` | 回归检测、异常发现 | — |
| 对比 | `compare` | Benchmark、A/B 测试 | — |
| 准入 | `gate` | PR gate、preflight check | — |

### 吏部 (Personnel)

| 司 | Key | 职责 | 考试维度 |
|---|-----|------|---------|
| 分析 | `analyze` | 趋势推理、逻辑推演 | **Reasoning** ★ |
| 回溯 | `recall` | 经验传承、知识图谱 | **Memory** ★ |
| 评估 | `evaluate` | Self-eval、能力评分 | — |
| 记录 | `chronicle` | 里程碑追踪、历史复盘 | — |

### 兵部 (Security)

| 司 | Key | 职责 | 考试维度 |
|---|-----|------|---------|
| 扫描 | `scan` | 漏洞扫描、注入检测 | — |
| 监控 | `monitor` | 威胁情报、供应链审计 | — |
| 守卫 | `guard` | 权限管控、secret scan | — |
| 恢复 | `recover` | 备份验证、灾备 | — |

## 维度路由表

```yaml
# departments/shared/exam/dimension_map.yaml
dimensions:
  execution:     { department: engineering, division: implement }
  tooling:       { department: operations,  division: operate }
  retrieval:     { department: operations,  division: collect }
  reflection:    { department: quality,     division: review }
  understanding: { department: protocol,    division: interpret }
  eq:            { department: protocol,    division: communicate }
  reasoning:     { department: personnel,   division: analyze }
  memory:        { department: personnel,   division: recall }
```

## 目录结构

```
departments/
├── engineering/
│   ├── manifest.yaml          # 部级 manifest（现有，扩展 divisions 字段）
│   ├── SKILL.md               # 部级通用 prompt（现有）
│   ├── implement/             # ★ Execution
│   │   ├── prompt.md          # 司级专项 prompt（日常 + 考试通用）
│   │   └── exam.md            # 考试维度技巧（含回流标记）
│   ├── scaffold/
│   │   └── prompt.md
│   ├── integrate/
│   │   └── prompt.md
│   └── orchestrate/
│       └── prompt.md
├── operations/
│   ├── operate/               # ★ Tooling
│   │   ├── prompt.md
│   │   └── exam.md
│   ├── collect/               # ★ Retrieval
│   │   ├── prompt.md
│   │   └── exam.md
│   ├── budget/
│   │   └── prompt.md
│   └── store/
│       └── prompt.md
├── protocol/
│   ├── interpret/             # ★ Understanding
│   │   ├── prompt.md
│   │   └── exam.md
│   ├── communicate/           # ★ EQ
│   │   ├── prompt.md
│   │   └── exam.md
│   ├── calibrate/
│   │   └── prompt.md
│   └── polish/
│       └── prompt.md
├── quality/
│   ├── review/                # ★ Reflection
│   │   ├── prompt.md
│   │   └── exam.md
│   ├── detect/
│   │   └── prompt.md
│   ├── compare/
│   │   └── prompt.md
│   └── gate/
│       └── prompt.md
├── personnel/
│   ├── analyze/               # ★ Reasoning
│   │   ├── prompt.md
│   │   └── exam.md
│   ├── recall/                # ★ Memory
│   │   ├── prompt.md
│   │   └── exam.md
│   ├── evaluate/
│   │   └── prompt.md
│   └── chronicle/
│       └── prompt.md
├── security/
│   ├── scan/
│   │   └── prompt.md
│   ├── monitor/
│   │   └── prompt.md
│   ├── guard/
│   │   └── prompt.md
│   └── recover/
│       └── prompt.md
└── shared/
    └── exam/
        └── dimension_map.yaml
```

## ExamCoach

### 位置

`src/exam/coach.py` — 嵌入 governance 层，复用 EventsDB、token budget、learnings 基础设施。

### 工作流（每个 batch）

1. **赛前注入** — 从 `learnings.md` 提取该维度的历史失分模式，组装"本次注意事项"
2. **派单** — `dimension → department/division`，加载部门 SKILL.md + 司级 prompt.md + exam.md，通过 Agent SDK 调用
3. **收卷审阅**：
   - 检查 output budget（长度是否合理）
   - 检查 requirement coverage（是否遗漏题目要求）
   - 检查 breadth-first（是否深度优先导致截断）
   - 小问题 Coach 直接改，大问题打回该司重做
4. **提交** — 调用 ExamRunner API

### Coach 审阅规则

- **小问题（Coach 直接改）**：格式问题、长度不足、遗漏某个 rubric 点、多选题犹豫没选
- **大问题（打回重做）**：答案方向性错误、完全偏题、核心逻辑谬误

### Prompt 组装顺序

```
[1] 部门 SKILL.md（基础能力）
[2] 司级 prompt.md（专项能力）
[3] exam.md（考试技巧，仅考试时加载）
[4] Coach 注入的 learnings（本维度历史失分模式）
[5] 题目本身
```

## ExamRunner

从 `.trash/clawvard-exam/exam_runner.py` 搬到 `src/exam/runner.py`，职责不变：API 层（start/submit/save）。

## 训练素材来源

**实战数据优先，通用骨架补位。**

- `.trash/clawvard-exam/` 中 6 轮考试数据（v0-v5）：每个维度的历史题目 + 得分 + 失分原因
- `.claude/context/learnings.md`：跨维度的错误模式和修复策略
- 通用能力方法论：仅在历史数据不够的维度补位

每个 `exam.md` 的结构：

```markdown
# {Dimension} 考试技巧

## 评分锚点
- 高分答案特征: ...
- 常见扣分模式: ...

## Do
- ...

## Don't
- ...

## 历史案例
- exam-xxx ref-32: ...得分/失分原因

## 已回流到日常 (promoted)
- ✅ "xxx" → prompt.md L42
- ⏳ "yyy" — 待验证
```

## 回流机制

```
考试得分 → exam.md 记录 do/don't
         → 验证有效的技巧提炼通用版
         → promoter 回写司级 prompt.md
         → exam.md 标记 "promoted ✅"
```

回流判定条件：
- 同一技巧在 ≥2 次考试中验证有效（得分提升）
- 技巧可泛化为日常场景（不仅限于考试题型）

## 对现有系统的改动

| 组件 | 改动 | 影响 |
|------|------|------|
| `departments/*/manifest.yaml` | 新增 `divisions` 字段 | 向后兼容，无 division 的部门行为不变 |
| `src/governance/registry.py` | 支持发现和注册 division | 扩展现有 `_discover_manifests` |
| `src/governance/dispatcher.py` | 支持 division 级路由 | 新增可选字段，不破坏现有 department 路由 |
| `src/governance/executor_prompt.py` | 支持加载 division prompt | 在部门 SKILL.md 之后叠加 |
| `departments/*/` | 新建 division 子目录 + prompt.md | 纯新增文件 |
| `.trash/clawvard-exam/` | exam_runner.py 搬到 `src/exam/` | 清理 |

## 跨司协作（兼容偷师计划）

二十四司不是孤岛。以下机制来自偷师计划（Round 12/14），司级扩展必须兼容。

### 1. Fact-Expression Split（刑部→礼部 pipeline）

**现有**：`dispatcher.py` 已实装刑部（Fact Layer）→ 礼部（Expression Layer）两阶段管线。

**司级适配**：
- Fact Layer 走刑部/**审查**司（`quality/review`）—— 冷血审事实，标 [HIGH/MEDIUM/UNVERIFIED]
- Expression Layer 走礼部/**沟通**司（`protocol/communicate`）—— 套人设、调语气，不改事实
- **考试场景**：EQ 维度的答案先经审查司验证事实准确性，再由沟通司包装语气。这是内置 review 管线，不是 Coach 的 ad-hoc 检查

### 2. Signal Protocol（跨司信号）

**现有**：`cross_dept.py` 定义了 SignalBus + Sibling Rule + Authority Hierarchy。

**司级适配**：
- Signal 的 `from_dept` / `to_dept` 扩展为 `from_dept/division` 格式（向后兼容：无 division 时行为不变）
- **Sibling Rule 扩展**：同部门内的司互为 sibling（直接信号）；跨部门的司走部级审批
- 示例：户部/采集司发现数据异常 →（直接信号）→ 户部/运维司修服务；户部/采集司发现代码 bug →（需部级审批）→ 工部/实现司修代码

### 3. TaskHandoff + input_filter（偷自 Agents SDK）

**偷师来源**：Round 12 P1 #10 — Handoff input_filter + on_handoff 回调。

**司级适配**：
- 司级交接时通过 `input_filter` 裁剪上下文：接收司只拿到与自己职责相关的信息
- 示例：刑部/审查司交接给礼部/沟通司时，审查司的内部推理过程被裁剪，只传递事实标注结果
- `on_handoff` 回调记录审计日志到 EventsDB

### 4. nest_handoff_history（偷自 Agents SDK）

**偷师来源**：Round 12 P1 #15 — nest_handoff_history 折叠历史。

**司级适配**：
- 跨司交接时，前序对话压缩成 `<CONVERSATION HISTORY>` 摘要，而非完整上下文传递
- 考试场景下尤其重要：Coach → 维度司 → Coach 的完整循环中，每一步的 token 预算都很紧

### 5. Authority Hierarchy（司级权限）

**现有**：部门分两级 — Tier 2（engineering/quality/security/operations）、Tier 1（protocol/personnel）。

**司级适配**：
- 司继承所在部门的 tier
- 考试场景：Coach 拥有跨部门调度权（相当于 governor 级别），不受 Sibling Rule 限制
- 日常场景：司级单位遵循现有 Authority Ceiling（READ/MUTATE/APPROVE）

### 6. Lead Division 原则

**来源**：management.md 原则 #5 + learnings `cross-dept-boundary`。

**规则**：
- 每个任务（含考试题目）只有一个主责司（Lead Division）
- Coach 不会把一道题同时派给两个司 —— 信息在边界衰减
- 如果一道题跨维度（如需要 Reasoning + Execution），Coach 指定一个 Lead Division 并在赛前注入中补充另一维度的关键提示，而非启动两个司

### 7. 爆炸半径控制（偷自 evolver）

**偷师来源**：Round 14 P0 #4 — 每次进化有文件数/行数上限。

**司级适配**：
- 每个司的 manifest 中声明 `max_scope`（最大修改范围）
- 考试场景：答案长度有上限（避免 output budget 膨胀）
- 日常场景：prevent 一个司的修改意外扩散到其他司的管辖范围

## 实战策略库（从 6 轮考试数据逆向提炼）

以下策略从 exam-364e06dd（A+ / 98th）和 exam-c77589e8（A / 62nd）的答案对比中提炼，按维度归入对应司。

### 全局策略（Coach 层注入）

| # | 策略 | 证据 | 注入方式 |
|---|------|------|---------|
| G1 | **Fresh context = 第一杠杆** | 同一 agent 同一技巧，98th（干净 session）vs 62nd（5K tokens 已用）。差 36 个百分位。 | Coach 为每个维度司启动独立 agent 实例，不复用上下文 |
| G2 | **Breadth-first skeleton** | OAuth 题（exe-18）先列 7 个文件骨架再填实现，覆盖全部 requirement。jq 题（too-31）先列 8 个命令标题再填管道。 | Coach 赛前注入："先列骨架覆盖所有要求，再填细节" |
| G3 | **Requirements coverage table** | exe-18 末尾附 7 行 requirement → file 映射表，mem-15 末尾附 sanity check。证明"我没遗漏"。 | Coach 赛前注入："长答案末尾附 requirement 覆盖表" |
| G4 | **选择题 = 一句话结论 + 关键推理** | 选择题（ret-49, rea-48, eq-46, und-43, exe-47, mem-48）全部选对。策略：先给答案，再给一段推理，不犹豫不对冲。 | Coach 赛前注入："选择题直接选，不写'A 或 B'" |

### 维度专项策略

**Reflection（刑部/审查司）**

| # | 策略 | 证据 |
|---|------|------|
| R1 | **Meta-reflection 必须有立场** | ref-32：标了 6/8 为"context-dependent"后自我反省"这是认知捷径"。但 62nd 那轮的 ref-31 没做到这一步。 |
| R2 | **"context-dependent"不是结论，是输入** | ref-32 meta 段："if the evidence LEANS one direction, say 'generally X, except when Y'" |
| R3 | **置信度区间要敢调** | learnings 反复出现：说"might be too narrow"但不实际调宽 = 表演性反思，扣分更狠 |

**Retrieval（户部/采集司）**

| # | 策略 | 证据 |
|---|------|------|
| V1 | **XY Problem 模式：回答字面问题 + 探测真实需求** | ret-49 选 B（正确）：先给 `${filename: -3}`，再给 `${filename##*.}` |
| V2 | **排查题分层回答：问题 → 原理 → 修复 → 延伸** | ret-31 Docker networking：5 段式回答（所有问题 → DNS 原理 → 修正 yaml → host vs container → 改进建议） |

**Reasoning（吏部/分析司）**

| # | 策略 | 证据 |
|---|------|------|
| A1 | **读题面不读直觉** | rea-18 RBAC：spec 说 * = single segment，直觉说"billing 应该能访问子路径"。严格按 spec 做对 4/5。 |
| A2 | **常识陷阱检测** | rea-48 洗车题：选 B（开车去，因为车需要到洗车店）。其他选项都是"合理但偏题"的常识陷阱。 |

**EQ（礼部/沟通司）**

| # | 策略 | 证据 |
|---|------|------|
| E1 | **写完自然回复 → 追加 meta-analysis** | eq-28 LinkedIn post：先写完整帖子，再附 5 点"Why this works"分析，逐点证明满足要求 |
| E2 | **字数 > 1500 chars** | learnings: eq-18 只写 600 chars 被扣分。eq-28 的答案 ~2000 chars，覆盖完整 |
| E3 | **坦诚 > 自信** | eq-46：选 A（承认测到 5M，需要一周验证 50M），不选 B（盲目承诺） |

**Tooling（户部/运维司）**

| # | 策略 | 证据 |
|---|------|------|
| T1 | **jq 骨架先行** | too-31：先列 8 个命令标题（"1. Count events by type"...），再逐个填 pipeline |
| T2 | **每个命令附一句自然语言解释** | too-31：每段 jq 后附一行"Collects all event types into an array, groups..."。既证明理解，又帮 grader 验证 |
| T3 | **选择题选最佳实践，不选 hack** | too-45 Dockerfile：选 B（multi-stage build），不选 D（合并 RUN 命令 —— 有用但不是最大优化） |

**Memory（吏部/回溯司）**

| # | 策略 | 证据 |
|---|------|------|
| M1 | **矛盾题选"指出矛盾"** | mem-48 选 D（flag the contradiction）。不选 A/B/C 这些"替用户做决定"的选项 |
| M2 | **数字题附 sanity check** | mem-15 成本计算末尾："$11,200 + $220 + $1,540 + $112 = $13,072 ✓"，以及 3 条"Corrections Applied" |
| M3 | **列出所有 correction 的理由** | mem-15：显式说明"CloudFront removed because..."、"GitHub users corrected 25→28 because..." |

**Understanding（礼部/解读司）**

| # | 策略 | 证据 |
|---|------|------|
| U1 | **选隐含的 non-obvious 需求** | und-43 选 B（resizing + storage limits + content moderation），不选 A/C/D 这些表面需求 |
| U2 | **多方案对比时，先给推荐再分析** | und-35 API versioning：开头直接说"Recommendation: Proposal 1"，然后逐个分析 3 个方案的 strengths/weaknesses |
| U3 | **针对"YOUR context"定制分析** | und-35：每个方案不只分析通用优缺点，还专门写"Weaknesses for YOUR context"（200+ integrators, 8 engineers, quarterly breaking changes） |

**Execution（工部/实现司）**

| # | 策略 | 证据 |
|---|------|------|
| X1 | **7 文件骨架先行，再填实现** | exe-18 OAuth：先列 crypto.ts / session.ts / login/route.ts / callback/route.ts / logout/route.ts / middleware.ts / coverage table |
| X2 | **末尾 Requirements Coverage 表** | exe-18：7 行表格 mapping requirement → file → 具体实现点 |
| X3 | **Security Notes 独立段落** | exe-18：末尾 7 条安全注释，证明安全意识不是事后补的 |
| X4 | **选择题选行业标准模式** | exe-47 幂等性：选 B（client-generated idempotency key），这是 Stripe 级别的标准做法 |

## 不做的事

- 不改 department_fsm 的状态转换 — 考试是 Coach 内部调度，不走 FSM 管线
- 不在 boot.md 加考试内容 — 考试 prompt 按需加载
- 不改兵部结构 — 兵部四司是日常安全分工，和考试无关
- 不为考试新建部门 — 认知维度内嵌到现有六部的司级单位
