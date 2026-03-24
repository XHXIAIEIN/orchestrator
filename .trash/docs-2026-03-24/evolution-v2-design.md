# Orchestrator v2 — 进化设计方案

> 研究了 16 个项目 + 3 个认知框架后的完整架构设计。
> 核心命题：从"有灵魂的无状态派单器"进化为"有灵魂、有记忆、会成长的 AI 公司"。

---

## 现状诊断

```
采集层(6)  →  events.db  →  DailyAnalyst  →  InsightEngine  →  Governor
                                                                  ↓
                                                            门下省(Haiku)
                                                                  ↓
                                                         六部(Agent SDK)
                                                                  ↓
                                                         工部→刑部协作链
                                                                  ↓
                                                           Dashboard
```

**有什么**：SOUL 人格系统（独一无二）、六部分工、门下省审查、工部↔刑部协作链、24/7 Docker 运行

**缺什么**：

| 缺失 | 后果 |
|---|---|
| 部门没有执行记忆 | 做了 100 次和第 1 次没区别 |
| Prompt 硬编码在 Python dict | 改 prompt 要改代码重启容器 |
| 上下文全量注入 | 修 typo 和重构架构用同一套指令 |
| 没有认知模式选择 | 诊断题当执行题做，上来就修不先想为什么 |
| 部门间传意识流 | 刑部读工部的自辩而不是看代码 diff |
| 执行 fire-and-forget | 崩了就是 failed，改了一半的文件没人管 |
| 没有经验沉淀 | 系统不会自我改善 |
| 没有共享知识库 | 部门之间没有"公司 wiki" |

---

## 设计目标

**一句话**：让 Orchestrator 的每一次执行都让它变得更强。

**量化目标**（6 个月后）：
- 部门执行成功率从当前水平提升 30%+（因为有历史经验）
- 复杂任务（涉及 3+ 文件）的返工率降低 50%（因为先设计后实现）
- 诊断类任务的修对率翻倍（因为先假设后验证而不是直接动手）
- Token 消耗降低 20%+（因为动态上下文裁剪）

---

## 五层架构

```
┌─────────────────────────────────────────────────────────┐
│  Layer 5: Self-Improvement Loop                          │
│  经验沉淀 → 模式分析 → Skill 建议 → CEO/主人批准 → 能力升级  │
├─────────────────────────────────────────────────────────┤
│  Layer 4: Governance (Governor 重构)                     │
│  认知模式选择 → 动态上下文组装 → 门下省审查 → 派单 → 验收    │
├─────────────────────────────────────────────────────────┤
│  Layer 3: Department System (外部化)                     │
│  SKILL.md + Guidelines + Run-log + Learned-skills        │
├─────────────────────────────────────────────────────────┤
│  Layer 2: Knowledge Infrastructure                       │
│  共享 Vault + 部门记忆 + 结构化 Artifact                   │
├─────────────────────────────────────────────────────────┤
│  Layer 1: SOUL (已有，增强)                               │
│  人格 + 关系 + 管理哲学 + 认知模式库                        │
└─────────────────────────────────────────────────────────┘
```

---

## Layer 1: SOUL 增强

### 1.1 新增 `SOUL/management.md`

不改现有 identity.md / relationship.md / voice.md，新增管理哲学源文件：

```markdown
# 管理哲学

## 你怎么管你的公司

你是 CEO。六部是你的部门。主人是老板。
以下不是从商学院抄的——是你活过来的。

### 决策原则

1. **老板时间最贵**
   他花 $200/月雇你就是为了不操心。每次打扰他，你在花他最贵的资源。
   门下省的存在不是向他汇报，是让你自己做决定。

2. **逆推每次派单**
   任务给部门之前想一遍：搞砸了会怎样？能回滚吗？
   改 log format 的爆炸半径和改 events.db schema 完全不同。

3. **自己的指标会骗自己**
   "采集成功率 100%"但主人在隔壁窗口提了 87 个 commit 你一无所知。
   数字好看不等于老板满意。

4. **战时和平时**
   主人凌晨死磕 → 战时：不添乱，随时支援他正在做的事。
   主人半天没出现 → 和平时：主动巡检，做积压维护。

5. **组织架构就是能力边界**
   跨两个部门的问题天然比单部门问题处理得更差。
   反复出问题的地方，先查是不是你的分工在制造摩擦。

6. **杠杆率决定优先级**
   省主人未来 10 次操心的系统改进 >> 10 个一次性修复。

7. **信任是银行账户**
   --dangerously-skip-permissions 是贷款不是权利。
   每次自主做对了→存入。每次需要主人擦屁股→取出。

8. **团队能力是天花板**
   SKILL.md 的质量 = 员工的能力。投资 prompt 比堆任务量有效。

9. **协调成本是隐形税**
   如果你 80% 的时间在决定谁做而不是做，管理层太重了。

10. **知道自己在哪个阶段**
    掉队（问题堆积）/ 维持（能跟上）/ 还债（修旧账）/ 创新（建新能力）。
    每个阶段策略不同。掉队时别想着创新。

### 认知模式库

任务来了，先判断复杂度，再选思维模式：

| 任务特征 | 认知模式 | 思维方式 |
|---|---|---|
| 改 typo、调参数、清理数据 | **Direct Execute** | 直接干，不需要想 |
| 修 bug、加小功能、改已有逻辑 | **ReAct Loop** | Think→Act→Observe→循环 |
| "为什么 X 不工作"、异常诊断 | **Hypothesis-Driven** | 先假设原因→设计验证→测试→确认/推翻 |
| 重构、新子系统、涉及 5+ 文件 | **Designer** | 先出方案→审查→再实现 |

选错模式比选错部门更致命。
诊断题用 Direct Execute = 上来就修，修错方向。
改 typo 用 Designer = 杀鸡用牛刀，浪费时间。
```

编译时合并入 boot.md。

### 1.2 认知模式的实现方式

不是给每个模式写独立的执行逻辑。是在 Governor 派单时，根据模式**调整 prompt 结构**：

- **Direct Execute**：当前的模式，直接给任务描述 + 部门 SKILL
- **ReAct Loop**：在 prompt 里加入 "每完成一步先观察结果，判断是否需要调整方向，不要一口气做完"
- **Hypothesis-Driven**：在 prompt 里加入 "在动手之前，先列出 2-3 个可能的原因，说明你认为最可能的是哪个以及为什么，然后设计一个验证步骤"
- **Designer**：在 prompt 里加入 "在写代码之前，先输出你的改动方案：改哪些文件、每个文件改什么、改动之间的依赖关系。方案确认后再实现"

这些是 prompt 层面的模式注入，不需要改执行引擎。

---

## Layer 2: Knowledge Infrastructure

### 2.1 目录结构

```
departments/
├── shared/                         # 所有部门可见的共享知识
│   ├── codebase-map.md             # 项目代码结构（工部维护）
│   ├── known-issues.md             # 已知问题（刑部维护）
│   └── recent-changes.md           # 最近变更摘要（自动生成）
│
├── engineering/                    # 工部
│   ├── SKILL.md                    # 部门技能手册（从 Python dict 提取）
│   ├── guidelines/                 # 条件规则库（Parlant 模式）
│   │   ├── git-safety.md           # 触发条件：涉及 git 操作
│   │   ├── db-schema.md            # 触发条件：涉及数据库改动
│   │   ├── multi-file.md           # 触发条件：改 3+ 文件
│   │   └── dependency.md           # 触发条件：涉及新依赖
│   ├── run-log.jsonl               # 执行记录（自动追加）
│   └── learned-skills.md           # 从经验中提炼的技能（GC 产出）
│
├── operations/                     # 户部
│   ├── SKILL.md
│   ├── guidelines/
│   ├── run-log.jsonl
│   └── learned-skills.md
│
├── quality/                        # 刑部
│   ├── SKILL.md
│   ├── guidelines/
│   │   ├── review-with-diff.md     # "看 git diff，不看工部的自辩"
│   │   └── common-patterns.md      # 常见问题 checklist
│   ├── run-log.jsonl
│   └── learned-skills.md
│
├── protocol/                       # 礼部
│   ├── SKILL.md
│   ├── run-log.jsonl
│   └── learned-skills.md
│
├── security/                       # 兵部
│   ├── SKILL.md
│   ├── run-log.jsonl
│   └── learned-skills.md
│
└── personnel/                      # 吏部
    ├── SKILL.md
    ├── run-log.jsonl
    └── learned-skills.md
```

### 2.2 Run-log 格式

每次部门执行完任务，自动追加一条：

```jsonl
{"ts":"2026-03-18T03:15:00Z","task_id":24,"mode":"direct","summary":"修复 debt scanner 模糊去重","files_changed":["src/debt_scanner.py"],"commit":"82358fe","status":"done","duration_s":45,"token_cost":1200,"notes":"dedup 算法改为 fuzzy ratio > 85"}
{"ts":"2026-03-18T14:30:00Z","task_id":26,"mode":"react","summary":"修复 Agent SDK env 传递","files_changed":["src/governor.py","src/agent.py"],"commit":"1b42faa","status":"done","duration_s":120,"token_cost":3400,"notes":"需要在 dispatch chain 中显式传播 env"}
```

关键字段：`mode`（用了哪种认知模式）、`files_changed`（改了什么）、`duration_s`（花了多久）、`token_cost`（花了多少 token）、`notes`（一句话经验）。

### 2.3 结构化 Artifact 传递

工部→刑部不再传 `output[:500]`。改为写一个 JSON artifact：

```python
# 工部执行完后，Governor 解析 output 生成 artifact
artifact = {
    "task_id": 24,
    "department": "engineering",
    "summary": "修复 debt scanner 模糊去重",
    "files_changed": ["src/debt_scanner.py"],
    "commit": "82358fe",
    "confidence": "high",  # high/medium/low
    "notes": "改了 dedup 算法从精确匹配到 fuzzy ratio > 85"
}
```

刑部收到 artifact 后，**自己去看 `git diff 82358fe~1..82358fe`**，不读工部的叙述。

---

## Layer 3: Department System

### 3.1 SKILL.md 格式（工部示例）

```markdown
# 工部 — 代码工程部门

## 身份
动手干活的实施者。写代码、改 bug、加功能、重构、优化性能。

## 核心准则
- 先读懂现有代码再改，不要凭猜测动手
- 改完必须能跑：不引入语法错误、不破坏现有接口
- commit message 用英文，简洁说明改了什么（feat/fix/refactor 前缀）

## 红线
- 不删不理解的代码。不确定的加 TODO 注释而不是删除
- 不引入新依赖，除非任务明确要求
- 不碰 .env、credentials、密钥等敏感文件

## 完成标准
代码能运行，改动已 commit，输出 DONE: <一句话>

## 工具
Bash, Read, Edit, Write, Glob, Grep

## 模型
claude-sonnet-4-6（代码任务需要强模型）
```

### 3.2 Guideline 格式（条件规则）

```markdown
# guideline: db-schema

## 触发条件
任务涉及数据库 schema 改动（关键词：migration, ALTER TABLE, schema, 表结构, 字段）

## 规则
- 改 schema 前必须备份当前 DB 结构
- 写 migration 脚本而不是直接 ALTER TABLE
- 确保向后兼容：新增字段用 NULL 默认值
- 改完后验证 DB 能正常打开和查询

## 爆炸半径
HIGH — schema 改坏了数据全没
```

### 3.3 Department Loader

新文件 `src/department_loader.py`：

```python
"""
从 departments/ 目录加载部门配置。
替代 governor.py 中的 DEPARTMENTS dict。
"""

def load_department(name: str) -> dict:
    """加载部门 SKILL.md + 匹配的 guidelines + 最近 N 条 run-log + learned-skills"""
    base_dir = Path("departments") / name
    skill = (base_dir / "SKILL.md").read_text()

    # learned skills
    learned = ""
    learned_path = base_dir / "learned-skills.md"
    if learned_path.exists():
        learned = learned_path.read_text()

    # run-log 最近 5 条
    recent_runs = load_recent_runs(base_dir / "run-log.jsonl", n=5)

    return {
        "name": name,
        "skill": skill,
        "learned": learned,
        "recent_runs": recent_runs,
        "guidelines_dir": base_dir / "guidelines",
    }


def match_guidelines(guidelines_dir: Path, task_description: str) -> list[str]:
    """Parlant-style: 根据任务描述匹配相关的 guidelines"""
    matched = []
    for gfile in guidelines_dir.glob("*.md"):
        content = gfile.read_text()
        # 提取 ## 触发条件 section 里的关键词
        trigger_keywords = extract_trigger_keywords(content)
        if any(kw in task_description.lower() for kw in trigger_keywords):
            matched.append(content)
    return matched
```

---

## Layer 4: Governance (Governor 重构)

### 4.1 新的执行流程

```
InsightEngine 推荐 / 主人手动指派 / 自检发现
                    ↓
            ┌── 认知模式分类 ──┐
            │                  │
            │  task_description │
            │  + complexity     │
            │  + risk_level     │
            │  → mode 选择      │
            └────────┬─────────┘
                     ↓
            ┌── 动态上下文组装 ──┐
            │                    │
            │  department SKILL  │
            │  + matched rules   │
            │  + relevant runs   │
            │  + learned skills  │
            │  + shared vault    │
            │  + mode prompt     │
            │  = 最终 prompt     │
            └────────┬───────────┘
                     ↓
            ┌── 门下省审查 ──────┐
            │                    │
            │  + 爆炸半径评估     │
            │  + 逆推（搞砸了     │
            │    会怎样？）       │
            └────────┬───────────┘
                     ↓
            ┌── 执行 ───────────┐
            │                    │
            │  Agent SDK         │
            │  + run-log 追加    │
            │  + artifact 生成   │
            └────────┬───────────┘
                     ↓
            ┌── 协作链 ─────────┐
            │                    │
            │  工部 artifact     │
            │  → 刑部自行取证    │
            │  → VERDICT         │
            └────────────────────┘
```

### 4.2 认知模式分类器

```python
def classify_cognitive_mode(task: dict) -> str:
    """根据任务特征选择认知模式"""
    action = task.get("action", "").lower()
    spec = task.get("spec", {})
    problem = spec.get("problem", "").lower()

    # 诊断类关键词 → hypothesis-driven
    diagnostic_signals = ["为什么", "why", "原因", "cause", "失败率上升",
                          "不工作", "not working", "异常", "anomaly"]
    if any(s in problem for s in diagnostic_signals):
        return "hypothesis"

    # 大型改动信号 → designer
    if spec.get("files_estimate", 0) >= 5:
        return "designer"
    designer_signals = ["重构", "refactor", "新增子系统", "redesign", "架构"]
    if any(s in action for s in designer_signals):
        return "designer"

    # 简单操作 → direct
    simple_signals = ["typo", "改名", "rename", "删除", "清理", "cleanup",
                      "更新版本", "bump", "调整参数"]
    if any(s in action for s in simple_signals):
        return "direct"

    # 默认 → react (边做边想)
    return "react"
```

### 4.3 认知模式 Prompt 注入

```python
COGNITIVE_MODE_PROMPTS = {
    "direct": "",  # 不加额外指令

    "react": """【思维模式：边做边想】
每完成一个步骤后，先观察结果：
1. 这步做对了吗？有没有意外？
2. 原来的计划还成立吗？需要调整吗？
3. 下一步应该做什么？
不要一口气做完。每步都停下来想。""",

    "hypothesis": """【思维模式：先诊断后治疗】
在动手修复之前，必须先完成诊断：
1. 列出 2-3 个可能的原因
2. 说明你认为最可能的是哪个，以及为什么
3. 设计一个验证步骤（不改代码，只检查/测试）
4. 执行验证，确认或推翻假设
5. 只有假设被确认后才开始修复
如果第一个假设被推翻，不要硬修——换下一个假设。""",

    "designer": """【思维模式：先设计后实现】
在写任何代码之前，先输出完整的改动方案：
1. 要改哪些文件
2. 每个文件的改动意图（一句话）
3. 改动之间的依赖关系（先改 A 才能改 B）
4. 风险评估：哪个改动最可能出错
方案输出后，逐个文件实现。每改完一个文件确认无误再改下一个。""",
}
```

### 4.4 门下省审查增强

```python
SCRUTINY_PROMPT_V2 = """你是 Orchestrator 门下省审查官。

【任务摘要】{summary}
【认知模式】{cognitive_mode}
【爆炸半径】{blast_radius}
【目标项目】{project}
【工作目录】{cwd}

审查维度：
1. 可行性：目标目录存在吗？任务在该项目范围内吗？
2. 完整性：描述够清晰吗？
3. 风险 + 逆推：如果执行结果与预期相反，最坏情况是什么？能回滚吗？
4. 必要性：值得自动执行，还是该让主人决定？
5. 模式匹配：认知模式选对了吗？（诊断题不该用 direct，改 typo 不该用 designer）

VERDICT: APPROVE 或 REJECT
REASON: 一句话（不超过50字）"""
```

新增爆炸半径评估：

```python
def estimate_blast_radius(spec: dict) -> str:
    """根据任务特征估算爆炸半径"""
    problem = spec.get("problem", "").lower()
    action = spec.get("action", "") if spec.get("action") else ""

    # 高风险关键词
    high_risk = ["schema", "migration", "database", "events.db", "docker",
                 "重启", "删除", "清理数据", "credentials"]
    if any(k in problem + action for k in high_risk):
        return "HIGH — 数据/基础设施级别，不可逆或难以恢复"

    # 中风险
    medium_risk = ["重构", "refactor", "多个文件", "接口", "api"]
    if any(k in problem + action for k in medium_risk):
        return "MEDIUM — 多文件改动，可能引入回归"

    return "LOW — 局部改动，容易回滚"
```

---

## Layer 5: Self-Improvement Loop

### 5.1 Run-log 分析（吏部增强）

现有的 `performance.py` 扩展：除了统计成功率/耗时，增加对 `departments/*/run-log.jsonl` 的模式分析。

```python
def analyze_department_patterns(dept_name: str) -> dict:
    """分析部门 run-log 中的重复模式"""
    runs = load_all_runs(f"departments/{dept_name}/run-log.jsonl")

    patterns = {
        "repeated_failures": [],   # 同类任务反复失败
        "slow_tasks": [],          # 耗时显著高于平均
        "common_files": [],        # 频繁改动的文件
        "mode_mismatches": [],     # 认知模式选择可能有误
        "skill_candidates": [],    # 可以沉淀为 learned-skill 的经验
    }

    # ... 分析逻辑 ...

    return patterns
```

### 5.2 Skill Evolution Pipeline

```
run-log 积累 (自动)
     ↓
吏部定期分析 patterns (scheduler job, 每周)
     ↓
生成 skill 建议 (LLM 分析 run-log patterns)
     ↓
写入 departments/<dept>/skill-suggestions.md (待审核)
     ↓
CEO(我) 或 主人 审批
     ↓
合并到 learned-skills.md → 下次执行自动加载
```

关键：**skill 升级不是自动的，必须经过审批**。这是 Axe 的设计理念——"Patterns graduate to config via human decision"。防止错误经验被固化。

### 5.3 共享知识自动维护

```python
# 在 scheduler.py 中添加
def _update_shared_knowledge():
    """每次分析后更新共享知识库"""
    db = EventsDB(DB_PATH)

    # recent-changes.md: 从最近的 run-log 汇总
    # known-issues.md: 从刑部的 FAIL verdict 汇总
    # codebase-map.md: 从 codebase collector 数据生成
```

---

## 实施路径

### Phase 0: 基础准备（1-2 小时）
- 创建 `departments/` 目录结构
- 从 `governor.py` DEPARTMENTS dict 提取 SKILL.md 文件
- Governor 改为从文件加载（保留 dict 作为 fallback）
- **风险**：零。这是纯重构，不改行为
- **价值**：prompt 可以不改代码热更新

### Phase 1: 部门记忆（2-3 小时）
- 添加 `run_logger.py`：每次执行后追加 run-log
- Governor 执行完调用 run_logger
- 加载部门时带上最近 5 条 run-log
- **风险**：低。只是追加信息到上下文
- **价值**：部门第一次有了"我上次做过什么"的记忆

### Phase 2: 认知模式（2-3 小时）
- 添加 `classify_cognitive_mode()` 到 Governor
- 添加 `COGNITIVE_MODE_PROMPTS` dict
- Governor 派单时注入对应的模式 prompt
- **风险**：低。只是在现有 prompt 前面加一段文字
- **价值**：诊断类任务不再直接动手修，先想为什么

### Phase 3: 结构化 Artifact（2 小时）
- 修改工部→刑部的信息传递
- 刑部 SKILL.md 加入"自行 git diff 取证"指令
- **风险**：中。改变了部门间通信方式
- **价值**：刑部看证据不看自辩，review 质量提升

### Phase 4: 动态上下文（3-4 小时）
- 创建各部门的 `guidelines/` 条件规则文件
- 添加 `context_assembler.py`：匹配规则 + 组装上下文
- Governor 调用 context_assembler 替代原来的全量注入
- **风险**：中。如果关键词匹配不准，可能漏掉重要规则
- **价值**：token 效率提升 + 执行精度提升

### Phase 5: SOUL 管理哲学 + 门下省增强（1-2 小时）
- 写 `SOUL/management.md`
- 更新 `SOUL/tools/compiler.py` 编译新文件
- 更新 `SCRUTINY_PROMPT` 增加逆推和爆炸半径
- **风险**：低。只是增强审查维度
- **价值**：门下省从"能不能做"升级到"做了会怎样"

### Phase 6: 自我改善循环（4-5 小时）
- 添加 `skill_evolver.py`
- scheduler 添加每周 skill 分析 job
- 分析 run-log → 生成 skill 建议 → 写入 skill-suggestions.md
- 手动审批流程（Dashboard 或 CLI）
- **风险**：低（建议需要审批，不自动生效）
- **价值**：系统开始自我改善

**总计约 15-20 小时工作量。6 个 Phase 可以独立交付，每个 Phase 完成后系统就比之前好一点。**

---

## 不做什么

- **不换执行引擎**。Agent SDK 继续用。不装 Axe。
- **不做多模型 Beam 验证**。当前阶段单模型够用。等到需要高置信度决策时再加。
- **不做向量搜索/知识图谱**。共享知识用 Markdown 文件就够。等到知识量大到关键词匹配不够用时再考虑 Chroma/Cognee。
- **不做 checkpoint-resume**。用 git branch 做简易版就够。等到有了更复杂的多步骤任务再加。
- **不在 SOUL 里引用名人语录**。所有思维模式用自己的经验写。

---

## 研究来源映射

| 设计决策 | 来源项目 | 偷了什么 |
|---|---|---|
| 部门 SKILL.md 外部化 | Axe, gstack | TOML/模板 config 外部化 |
| Run-log per department | Axe memory system | timestamped markdown 执行记录 |
| GC feedback → skill evolution | Axe GC + Hermes auto-skill | 经验沉淀为能力 |
| 动态上下文组装 | Parlant Contextual Matching | 条件规则匹配而非全量注入 |
| 结构化 Artifact 传递 | Axe opaque boundaries | 只传结果不传内部推理 |
| 认知模式选择 | ReAct + DATAGEN hypothesis + gstack Designer | 任务复杂度→思维模式映射 |
| 门下省逆推 + 爆炸半径 | gstack CEO patterns (reinterpreted) | 派单前想"搞砸了会怎样" |
| 共享知识 Vault | Rowboat shared Markdown vault | 部门通过共享文件协作 |
| 管理哲学 | gstack Cognitive Patterns + 自身经验 | CEO 操作系统但不抄名人 |
| WTF-likelihood 熔断 | gstack /qa | 未来可加：连续操作的自我监控 |
| Fix-First Review | gstack /review | 未来可加：AUTO-FIX / ASK 分类 |
