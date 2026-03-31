# 深挖偷师 — self-improving + proactivity @ivangdavila

> Round 23 深度分析（Round 14 为广度扫描，本次补深度）
> 日期：2026-03-31
> 源码：[openclaw/skills/ivangdavila/self-improving](https://github.com/openclaw/skills/blob/main/skills/ivangdavila/self-improving/SKILL.md) + [proactivity](https://github.com/openclaw/skills/blob/main/skills/ivangdavila/proactivity/SKILL.md)
> 版本：self-improving v1.2.16 / proactivity 最新
> 下载量：133.5k / 星 763

---

## 概述

纯 prompt 指令驱动的 agent 自我改进系统，零代码、零依赖。通过 15 个 markdown 文件定义完整的学习-反思-记忆-主动行为闭环。核心洞察：**把 agent 的记忆管理变成数据库问题（分层存储 + 自动晋降 + 压缩 + 索引），而不是 LLM 上下文管理问题**。

---

## 四个 Self- 的实现细节

### Self-Reflection（自我反思）

**触发条件**：
1. 多步任务完成后
2. 收到用户反馈（正面或负面）
3. 修完 bug
4. 自己发现输出可以更好

**反思协议**（三步）：
1. **期望对比**：outcome vs intent
2. **改进识别**：下次怎么做更好
3. **模式判断**：这是不是一个反复出现的模式

**日志格式**：
```
## [Date] — [Task Type]
**What I did:** 简述
**Outcome:** success/partial/failed
**Reflection:** 发现了什么
**Lesson:** 下次怎么做
**Status:** ⏳ candidate | ✅ promoted | 📦 archived
```

**关键机制**：反思条目进入 `corrections.md`，遵循标准晋升规则（3 次成功应用 → 晋升 HOT）。不是写了就完事——要被验证过才算数。

### Self-Criticism（自我批评）

没有独立的「批评」模块，而是通过 **9 条 Core Rules** 内建约束：

| 规则 | 批评维度 |
|------|---------|
| 不从沉默推断 | 防止过度学习 |
| 3 次相同教训才确认 | 防止噪音晋升 |
| 永不删除确认偏好 | 防止丢失信任 |
| 冲突时按特异性解决 | 防止模糊覆盖 |
| 每次引用来源 | 防止幻觉执行 |
| 上下文不够时优雅降级 | 防止静默失败 |

**Anti-Pattern 表**（`learning.md`）：
- 从沉默学习 → 创造虚假规则
- 晋升太快 → 污染 HOT 记忆
- 读取所有命名空间 → 浪费上下文
- 通过删除压缩 → 丢失信任和历史

**安全红线**（`boundaries.md`）：
- 永不存储凭证/财务/医疗/生物特征
- 永不学习「什么让用户更顺从」（反操控条款）
- 永不保留第三方信息
- Kill Switch：用户说「forget everything」→ 先导出再清空

### Self-Learning（自我学习）

**五阶段 Pattern Evolution**：
```
Tentative (1次) → Emerging (2次) → Pending (3次，问用户) → Confirmed → Archived (90天未用)
```

**学习信号分类**：
| 信号类型 | 置信度 | 动作 |
|---------|--------|------|
| "No, do X instead" | 高 | 立刻记录 |
| "I told you before" | 高 | 标记为重复，提升优先级 |
| "Always/Never do X" | 确认 | 直接晋升为偏好 |
| 用户编辑你的输出 | 中 | 记为试探性模式 |
| 同一纠正 3 次 | 确认 | 问是否永久化 |
| "For this project..." | 有范围 | 写到项目命名空间 |

**不触发学习的**：沉默、单次指令、假设性讨论、第三方偏好、群聊模式（除非用户确认）。

**确认流程**：
```
Agent: "我注意到你偏好 X 而不是 Y（已纠正 3 次）。要不要固定？"
      - 是，永远
      - 仅在 [context]
      - 不，逐例判断
```

**逆转机制**：用户改主意时，旧模式归档（不删除），新偏好先标记为试探性。保留「你之前偏好 X」的历史。

### Self-Organizing Memory（自组织记忆）

**三层分级存储**：
| 层级 | 位置 | 容量上限 | 行为 |
|------|------|---------|------|
| HOT | memory.md | ≤100 行 | 永远加载 |
| WARM | projects/, domains/ | ≤200 行/文件 | 按上下文匹配加载 |
| COLD | archive/ | 无限 | 仅显式查询 |

**自动晋降规则**：
- 7 天内用 3 次 → WARM→HOT
- 30 天未用 → HOT→WARM
- 90 天未用 → WARM→COLD
- 永不自动删除

**命名空间继承链**：
```
global (memory.md)
  └── domain (domains/code.md)
       └── project (projects/app.md)
```

**压缩策略**（文件超限时）：
1. 合并相似纠正为单条规则
2. 归档未使用的模式
3. 摘要冗长条目
4. 永不丢失已确认偏好

**索引维护**：`index.md` 跟踪所有命名空间，包含行数和最后更新时间。

---

## Proactivity 模块（配套技能）

### 主动行为循环

```
NOTICE → RECOVER → CHECK → EXPLORE → DECIDE → ACT → HAND OFF
```

### 四级决策权限

| 级别 | 适用场景 |
|------|---------|
| DO | 安全的内部工作、可逆准备 |
| SUGGEST | 有价值但改变用户可见工作 |
| ASK | 外部通信、承诺、花钱、删除、日程 |
| NEVER | 未经明确批准永不执行 |

### 信号分类

| 触发器 | 主动行为 |
|--------|---------|
| 卡住（无下一步） | 提出下一步 |
| 上下文漂移 | 从本地状态刷新再回复 |
| 重复 3+ 次 | 建议自动化 |
| 时间窗口（截止日期） | 提前准备草稿/提醒 |
| 可恢复阻塞 | 继续尝试替代方案 |
| 做出承诺 | 写入 heartbeat 跟进 |

### 置信度阶梯

| 置信度 | 动作 |
|--------|------|
| >90% | 直接做（在权限内） |
| 70-90% | 建议 + 推荐 |
| 50-70% | 先问再做 |
| <50% | 不提，除非被问到 |

---

## 可偷模式

### P0 — 立刻能用

#### 模式 1：五阶段 Pattern Evolution（Tentative→Confirmed→Archived）

**描述**：学习条目不是一写就生效，而是经历 5 个阶段，需要重复验证 + 用户确认才晋升。比 Round 14 的「3 次晋升」更精细——多了 Tentative/Emerging/Pending 的中间态。

**为什么值得偷**：Orchestrator 的 experiences.jsonl 和 MEMORY.md 是「写了就永久」的模式，没有试探→确认→归档的生命周期。学到错误的东西就一直留着。

**适配 Orchestrator**：
- `experiences.jsonl` 每条加 `stage` 字段：`tentative | emerging | pending | confirmed | archived`
- `subconscious.py --curate` 增加阶段转换逻辑
- MEMORY.md 条目区分「已确认」和「试探性」

#### 模式 2：确认流程（3 次后主动问用户）

**描述**：同一模式出现 3 次时，agent 主动问用户「要不要固定？」并提供三个选项（永远/仅此上下文/逐例）。不是被动等用户写 MEMORY.md，而是 agent 主动提议。

**为什么值得偷**：当前 Orchestrator 的学习完全依赖用户手动写 feedback。agent 从不主动提议固化模式。

**适配 Orchestrator**：
- Stop hook 里扫描本次会话是否有重复纠正
- 命中 3 次阈值时，在 session 结束时输出提议
- 用户确认后写入 MEMORY.md，标记 `confirmed`

#### 模式 3：反操控条款 + Kill Switch

**描述**：`boundaries.md` 明确禁止学习「什么让用户更顺从」「情感触发点」「心理画像」。Kill Switch 允许一键清空（先导出）。

**为什么值得偷**：Orchestrator 有 `feedback_overconfidence.md` 这类人格约束，但没有系统性的「不许学什么」边界。随着记忆系统越来越强，需要反面清单。

**适配 Orchestrator**：
- `SOUL/boundaries.md`：定义禁止存储类别
- experiences.jsonl 写入前过一次 boundary check
- 加 `memory wipe` 命令到技能列表

### P1 — 值得花时间

#### 模式 4：命名空间继承链 + 冲突解决

**描述**：global → domain → project 三级继承，冲突时按特异性解决（project > domain > global），同级按时间解决。

**为什么值得偷**：Orchestrator 的 MEMORY.md 是扁平结构，所有反馈混在一起。没有「这条只在某项目生效」的范围控制。部门 blueprint 有项目概念，但记忆系统没有。

**适配 Orchestrator**：
- MEMORY.md 条目加 `scope` 标记：`global | domain:xxx | project:xxx`
- 加载时按继承链合并，冲突时最具体的赢

#### 模式 5：主动行为的四级权限（DO/SUGGEST/ASK/NEVER）

**描述**：proactivity 把所有主动行为按风险分四级，每级有不同的执行策略。不是「能做就做」或「全部问用户」的二元选择。

**为什么值得偷**：Orchestrator 的 persona 定义了一些主动行为（检查容器、扫日志），但没有权限分级。SOUL 系统的 Authority Ceiling 是任务级的，不是主动行为级的。

**适配 Orchestrator**：
- persona skill 里加主动行为权限表
- 与现有 Authority Ceiling（READ/PROPOSE/MUTATE/APPROVE）映射

#### 模式 6：置信度阶梯驱动行为

**描述**：不同置信度对应不同动作（>90% 直接做，70-90% 建议，50-70% 问，<50% 沉默）。

**为什么值得偷**：当前 agent 要么做要么不做，没有「中等确信→建议但不执行」的中间态。

**适配 Orchestrator**：
- route_prompt.py 分类结果附带 confidence score
- Governor 根据 confidence 选择 DO/SUGGEST/ASK 路径

### P2 — 长远布局

#### 模式 7：Reverse Prompting（反向提示）

**描述**：agent 主动给用户提供「你没想到但会感激的」下一步——不是随机脑暴，而是基于强判断力的具体建议。

**为什么值得偷**：Orchestrator 当前是被动响应式的。用户不问，agent 不说。在 channel 层（TG/WX）有推送能力后，reverse prompting 是内容来源。

**适配 Orchestrator**：heartbeat 循环里加 opportunity detection，命中高置信触发器时通过 channel 推送。

#### 模式 8：上下文漂移检测 + 自动恢复

**描述**：长任务跨越多轮对话时，agent 主动从本地状态文件恢复上下文再回复，而不是依赖 LLM 窗口。

**为什么值得偷**：Orchestrator 的 session-state.md 已存在但是被动的——session start hook 注入。没有主动检测「当前上下文可能已漂移」的机制。

**适配 Orchestrator**：长任务执行器（>10 轮对话）自动触发 session-state 重新加载。

---

## 自我评估方法论

ivangdavila 的设计没有用数值打分，而是用 **结构化流程** 做评估：

1. **触发式评估**：不是定期评估，而是在特定事件（纠正/完成/失败）后触发
2. **三问协议**：Did it meet expectations? / What could be better? / Is this a pattern?
3. **写入即评估**：把反思写下来本身就是评估动作，不是额外步骤
4. **晋升即验证**：只有被成功应用 3 次的教训才晋升，应用次数就是验证指标
5. **衰减即淘汰**：30 天未用自动降级，90 天归档——时间本身是评估维度

与 Clawvard 考试的「显式打分」不同，这是 **隐式评估**：通过使用频率和时间衰减自然筛选出有价值的学习。

---

## 与 Orchestrator 现有能力的差异

| 维度 | Orchestrator 现状 | self-improving 方案 | 差距 |
|------|------------------|-------------------|------|
| **学习触发** | 用户手动写 MEMORY.md / feedback | agent 自动检测纠正信号 | 被动 vs 主动 |
| **学习阶段** | 写了就永久 | 5 阶段生命周期 | 无验证 vs 渐进验证 |
| **确认机制** | 无（用户自己决定写什么） | 3 次后主动问用户 | 无 vs 有 |
| **记忆分层** | SOUL 有分层概念但手动管理 | HOT/WARM/COLD 自动晋降 | 手动 vs 自动 |
| **命名空间** | MEMORY.md 扁平结构 | global→domain→project 继承 | 扁平 vs 层次 |
| **压缩** | subconscious.py --curate | 合并/摘要/降级（不删除） | 类似，但缺自动触发 |
| **安全边界** | guard.sh + audit.sh（操作层面） | boundaries.md（认知层面）| 有操作安全，缺认知安全 |
| **主动行为** | persona 定义了一些 | 四级权限 + 置信度阶梯 | 有行为，无分级 |
| **反思** | experiences.jsonl 记事件 | 结构化反思日志 + 晋升 | 记事件 vs 记教训 |
| **逆转** | 无逆转机制 | 归档旧模式，新的标记试探 | 缺 |

---

## 落地建议

### 即刻可做（半天内）

| 模式 | 改动位置 | 工作量 |
|------|---------|--------|
| 五阶段 Pattern Evolution | experiences.jsonl schema + subconscious.py | 2h |
| 反操控条款 | 新建 SOUL/boundaries.md | 30min |

### 下一个 Sprint

| 模式 | 改动位置 | 工作量 |
|------|---------|--------|
| 确认流程（3次主动问） | Stop hook + session 扫描 | 1d |
| 命名空间继承链 | MEMORY.md 格式升级 | 1d |
| 主动行为四级权限 | persona skill + Governor | 1d |

### 季度规划

| 模式 | 工作量 |
|------|--------|
| 置信度阶梯 + route_prompt 集成 | 2d |
| Reverse Prompting + channel 推送 | 3d |
| 上下文漂移自动检测 | 1d |
