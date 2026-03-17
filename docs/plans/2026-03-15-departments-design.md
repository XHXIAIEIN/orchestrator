# 六部建制设计 — 2026-03-15

## 目标

把 Governor 的尚书省从"一个通才 `claude --print`"拆成可路由的专业部门。
不是一次建六个——先建路由机制 + 工部（代码工程），其他部门按需追加。

## 实施状态

| 里程碑 | 状态 | 日期 |
|--------|------|------|
| 路由机制 + DEPARTMENTS 路由表 | ✅ 已实现 | 2026-03-15 |
| 六部 prompt_prefix 一句话版 | ✅ 已实现 | 2026-03-15 |
| 门下省审查（scrutiny） | ✅ 已实现 | 2026-03-15 |
| 六部 prompt 升级为完整手册 | ✅ 已实现 | 2026-03-17 |
| Agent SDK 替换 `claude --print` | ⬚ 未开始 | — |

## 架构

### 三省

| 省 | 对应模块 | 职责 |
|----|---------|------|
| **尚书省** | `Governor.execute_task()` | 执行——派单到六部 |
| **门下省** | `Governor.scrutinize()` | 审查——用 Haiku 快速判断任务是否值得执行 |
| **中书省** | `InsightEngine` | 决策——分析数据、生成 recommendation |

### 六部路由表

```
InsightEngine(中书省) → recommendation.department → Governor(尚书省) → DEPARTMENTS[dept] → sub-agent
                                                          ↓
                                                   scrutinize(门下省)
```

### 六部职责与权限

| 部 | key | 职责 | 权限 | tools |
|----|-----|------|------|-------|
| 工部 | `engineering` | 代码工程：写代码、改 bug、加功能、重构 | 读写 | Bash,Read,Edit,Write,Glob,Grep |
| 户部 | `operations` | 系统运维：修采集器、管 DB、优化性能 | 读写 | Bash,Read,Edit,Write,Glob,Grep |
| 礼部 | `protocol` | 注意力审计：扫 TODO、追遗留、查过时文档 | 只读 | Read,Glob,Grep |
| 兵部 | `security` | 安全防御：查密钥泄露、权限、备份完整性 | 只读+Bash | Bash,Read,Glob,Grep |
| 刑部 | `quality` | 质量验收：跑测试、review 代码、查逻辑错误 | 只读+Bash | Bash,Read,Glob,Grep |
| 吏部 | `personnel` | 绩效管理：监控组件健康度、执行效率 | 只读 | Read,Glob,Grep |

**分权制衡**：只有工部和户部有写权限，其余四部只能报告不能修改。

## Prompt 手册设计（2026-03-17 升级）

### 设计决策

参考 [agency-agents](https://github.com/msitarzewski/agency-agents)（49k+ stars）的 agent 模板结构，
从其六层设计（Identity / Mission / Critical Rules / Deliverables / Success Metrics / Communication Style）中
提炼出对 sub-agent 执行质量影响最大的三个维度，形成统一的四段式手册：

```
【身份】一句话定位
【行为准则】正面指导——怎么干活（← Critical Rules + Workflow）
【红线】负面约束——什么绝对不能做（← Security-First / Safety）
【完成标准】自我验收——做到什么算完（← Success Metrics / Deliverables）
```

### 为什么不照搬 agency-agents 全部维度

| agency-agents 维度 | 取舍 | 原因 |
|-------------------|------|------|
| Identity | ✅ 保留（精简为一句话） | sub-agent 需要知道自己的角色 |
| Core Mission | ✅ 融入行为准则 | 拆成可执行的具体指令 |
| Critical Rules | ✅ 拆为行为准则 + 红线 | 正面/负面约束分开更清晰 |
| Deliverables | ✅ 融入完成标准 | sub-agent 需要知道"做完了"是什么样 |
| Success Metrics | ✅ 融入完成标准 | 量化标准让 agent 自我验收 |
| Personality/Voice | ❌ 不要 | sub-agent 是无状态执行器，不面向人类交互 |
| Communication Style | ❌ 不要 | 同上，输出格式由 TASK_PROMPT_TEMPLATE 统一控制 |
| Memory | ❌ 不要 | sub-agent 无跨任务记忆，记忆在 events.db |

### 与 agency-agents 的本质区别

| | Orchestrator 六部 | agency-agents |
|---|---|---|
| **本质** | 运行时治理架构（自动路由+审查+执行） | 静态 prompt 模板库（人工选择） |
| **调度** | InsightEngine 分析 → 自动标注 department → Governor 派单 | 用户手动说 "activate XXX mode" |
| **状态** | 有状态：task spec、执行结果、git status、视觉验证 | 无状态：纯 prompt |
| **分权** | 六部权限隔离，只读/读写分明 | 每个 agent 全能，无权限约束 |
| **审查** | 门下省（Haiku）自动审查每个任务 | 无审查机制 |

## Task spec 字段

```python
spec = {
    "department": "engineering",      # 目标部门（六部之一）
    "project": "orchestrator",        # 目标项目
    "cwd": "/path/to/project",        # 工作目录（可选，由 project_registry 解析）
    "problem": "...",
    "behavior_chain": "...",
    "observation": "...",
    "expected": "...",
    "summary": "...",
    "importance": "...",
}
```

## 待做

- Agent SDK 替换 `claude --print`：解锁工具调用能力，六部 prompt 才能真正发挥作用
- 部门间协作协议：工部改完 → 自动触发刑部验收 → 验收不过打回工部
- 吏部定时报告：每日生成组件绩效报告写入 dashboard
