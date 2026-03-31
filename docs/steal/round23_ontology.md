# Round 23: ontology @oswalpalash — Typed Knowledge Graph for Agent Memory

**Source**: https://clawhub.ai/oswalpalash/ontology | [GitHub](https://github.com/openclaw/skills/tree/main/skills/oswalpalash/ontology)
**Version**: v1.0.4 (33.4k downloads, 76 stars)
**License**: MIT-0

## 概述

一个文件级的 typed knowledge graph，用 JSONL append-only log + YAML schema 约束实现结构化 agent 记忆。核心思想：**所有知识都是 entity + relation，所有变更都过 type constraint 校验后才写入**。

## 核心机制

### 1. 数据模型

```
Entity: { id, type, properties, relations, created, updated }
Relation: { from_id, relation_type, to_id, properties }
```

存储：`memory/ontology/graph.jsonl`，每行一个 op（create/update/delete/relate/unrelate），append-only，可回溯全部变更历史。

### 2. Type System

12 个核心 entity type，分 6 组：

| 组 | Types | 用途 |
|---|---|---|
| Agents & People | Person, Organization | 人和组织 |
| Work | Project, Task, Goal | 任务管理 |
| Time & Place | Event, Location | 时空 |
| Information | Document, Message, Thread, Note | 信息 |
| Resources | Account, Device, Credential | 资源 |
| Meta | Action, Policy | 元数据 |

### 3. Constraint System (schema.yaml)

四层校验：
- **Required properties**: `Task` 必须有 `title` + `status`
- **Enum validation**: `status` 只能是 `open|in_progress|blocked|done|cancelled`
- **Forbidden properties**: `Credential` 禁止存 `password/secret/token/key/api_key`，只能存 `secret_ref`（指向 keychain）
- **Relation constraints**: from/to 类型检查 + 基数约束（one-to-one/one-to-many/many-to-one）+ 无环检测（DFS）

### 4. Skill Contract（composable skills 机制）

Skills 声明自己读写的 entity 类型 + 前置/后置条件：

```yaml
ontology:
  reads: [Task, Project, Person]
  writes: [Task, Action]
  preconditions:
    - "Task.assignee must exist"
  postconditions:
    - "Created Task has status=open"
```

跨 skill 通信通过共享 entity——email skill 创建 `Commitment`，task skill 查询后转成 `Task`。

### 5. Planning as Graph Transformation

多步计划建模为 op 序列（CREATE → RELATE → ...），每步校验约束，约束违规则 rollback。

---

## 可偷模式

### P0 — 直接可用

#### [Typed Entity Memory] — 从平面文件到 typed graph

**现状**: Orchestrator 的记忆是 MEMORY.md 中的无结构 markdown 条目 + SOUL/private/ 下的散文件。没有类型系统、没有约束校验、没有关系建模。

**偷法**: 在现有 SOUL/memory/ 旁边加一层 typed entity 层。不需要全盘替换，而是把高频实体（Project, Person, Feedback, StealPattern）建 schema，用 JSONL 持久化。

**价值**: 现在找"某个 round 偷了什么模式"要 grep 散文件。有 graph 后就是一条 query。

**适配**:
- entity types 从 ontology 的 12 个精简到 Orchestrator 需要的 6-8 个
- 存储路径: `SOUL/memory/graph.jsonl` + `SOUL/memory/schema.yaml`
- 与现有 MEMORY.md 共存，不替换

#### [Constraint-Before-Commit] — 写前校验

**现状**: 任何 agent/hook 都能往 memory 文件里写任何东西，没有格式校验。

**偷法**: schema.yaml 定义约束，写入前过一遍 validate。forbidden_properties 模式直接偷——防止 secret 明文入库。

**价值**: 避免 memory corruption。Credential 的 `forbidden_properties` 思路可以推广到所有敏感字段。

**适配**:
- 做成 pre-commit hook 或 skill 内校验
- 先从 `Credential` 和 `StealPattern` 两个类型开始

### P1 — 需要适配

#### [Skill Contract Declaration] — skill 读写声明

**现状**: Orchestrator 的 skills 没有声明自己读写什么数据。任何 skill 都能动任何文件。

**偷法**: 在 skill frontmatter 加 `ontology:` 声明，列出 reads/writes/preconditions。不强制执行（先 advisory），但让 Governor 在 dispatch 时知道 skill 的数据依赖。

**价值**: 为未来的并发 agent dispatch 做数据冲突检测。两个 agent 同时写同一类 entity = 冲突风险。

#### [Append-Only Event Log] — 不可变操作日志

**现状**: SOUL/private/experiences.jsonl 已经是 append-only，但只记"经验感悟"，不记结构化操作。

**偷法**: 把 entity 变更也写成 op log（create/update/delete/relate），保留完整变更历史。支持"这个 entity 的时间线"查询。

**价值**: 比 git log 更细粒度的变更追踪。experiences.jsonl 记的是高层反思，graph.jsonl 记的是具体操作。

#### [Cross-Skill State Sharing] — 通过 entity 共享状态

**现状**: skill 之间没有显式通信机制。偷师 skill 生成的报告是 markdown 文件，别的 skill 不知道它的存在。

**偷法**: 偷师 skill 产出 `StealPattern` entity（带 status/priority/project_ref），实施追踪 skill 查询 `status=pending` 的 pattern。

**价值**: 把偷师→实施→验证的 pipeline 从"人工翻文件"变成"query status"。

### P2 — 长期方向

#### [Acyclicity Enforcement] — 依赖关系无环检测

ontology 在 `blocked_by` 等关系上做 DFS 无环检测。Orchestrator 的任务依赖图（如果做的话）可以直接复用这个模式。

#### [Schema Merge] — 增量 schema 扩展

`schema-append` 命令支持 skill 在运行时往 schema 里加类型定义。Orchestrator 可以让新 skill 自带 schema fragment，自动 merge 进全局 schema。

---

## 知识图谱设计细节

| 层 | 实现 |
|---|---|
| **Type** | 12 entity types，YAML 定义，required/enum/forbidden 三层约束 |
| **Relation** | typed 边，带 from_types/to_types + cardinality + acyclicity |
| **Query** | CLI + Python API，支持 type filter、property filter、relation traversal、path finding |
| **Storage** | JSONL append-only，op = create/update/delete/relate/unrelate |
| **Schema** | YAML，支持 merge/append 增量扩展 |
| **Security** | path traversal 防护（resolve_safe_path）、secret indirection、no network/subprocess |

---

## 与 Orchestrator 记忆系统的差异

| 维度 | Orchestrator 现状 | ontology |
|---|---|---|
| **结构** | 散文件 markdown（MEMORY.md, feedback_*.md, steal_round*.md） | typed entity + relation graph |
| **类型系统** | 无。任何格式都能写入 | 12 type，YAML schema 约束 |
| **关系** | 隐式（文件间靠人工维护交叉引用） | 显式 typed relation，可查询可遍历 |
| **约束** | 无校验 | required/enum/forbidden/cardinality/acyclicity |
| **查询** | grep / 人工阅读 | CLI query + Python API |
| **历史** | git log（文件级） | JSONL op log（字段级） |
| **跨 skill 通信** | 无 | skill contract + 共享 entity |
| **安全** | 依赖 guard hook | path traversal + secret indirection + forbidden properties |

**核心差距**: Orchestrator 的记忆是**文档驱动**的（人写 markdown，agent 读 markdown），ontology 是**数据驱动**的（agent 写 typed entity，agent 查 typed entity）。前者对人友好但 agent 难以程序化操作；后者对 agent 友好但人可读性降低。

**推荐路径**: 不是替换，是**双层**——保留 markdown 文档层给人看，加一层 typed graph 给 agent 操作。两层通过 sync hook 保持一致。

---

## 实施建议（优先级排序）

1. **Phase 1**: 抽取 ontology.py 核心逻辑（~300 行），放到 `SOUL/tools/ontology.py`，定义 Orchestrator 专用的 6 类 entity（Project, Person, Feedback, StealPattern, Skill, Experience）
2. **Phase 2**: 给偷师 pipeline 建 graph——每个 round 的 pattern 变成 `StealPattern` entity，带 `status`/`priority`/`source_url`
3. **Phase 3**: skill contract declaration，先 advisory 后 enforcement
4. **Phase 4**: cross-skill state sharing via entity query
