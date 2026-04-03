# Round 36c: aresbit/skillsfather (= blader/Claudeception) — 自萃取 Meta-Skill

> 来源: https://github.com/blader/Claudeception (2196 stars) / https://github.com/aresbit/skillsfather (零改动 fork)
> 日期: 2026-04-03
> 分类: Claude Code Tooling / Skill Lifecycle / Meta-Learning
> 语言: 无代码（纯 Prompt Engineering，15KB SKILL.md）

---

## 一句话

教 Claude "如何从调试过程中自动萃取可复用 skill" 的 meta-skill——用 hook 强制每次交互后自检，绕过 Claude Code 被动语义匹配的局限。

---

## 它解决什么问题

AI agent 每次会话从零开始，反复踩同样的坑。Claudeception 的回答：**把调试过程中的非显性发现自动萃取为 Claude Code Skill**，下次遇到类似情况自动加载。

---

## 架构（极简，无代码）

```
├── SKILL.md                           # 主技能定义（15KB）—— 萃取引擎
├── .claude/skills/continuous-learning/SKILL.md  # 内嵌子技能（精简版）
├── scripts/claudeception-activator.sh # Hook 脚本（1.7KB）
├── resources/
│   ├── research-references.md         # 学术引用（Voyager/CASCADE/SEAgent/Reflexion/EvoFSM）
│   └── skill-template.md             # 技能模板
└── examples/                          # 3 个示例技能
    ├── nextjs-server-side-error-debugging/
    ├── prisma-connection-pool-exhaustion/
    └── typescript-circular-dependency/
```

**关键发现：整个项目没有一行实际代码。** 全部是 prompt 指令 + 一个 bash hook + markdown 模板。

---

## 核心机制

### 1. Hook 强制自检（P0 — 最有价值）

`claudeception-activator.sh` 注册为 PreToolUse/PostToolUse hook，每次交互注入：

```
🧠 MANDATORY SKILL EVALUATION REQUIRED
After completing this user request, you MUST evaluate whether
it produced extractable knowledge using the claudeception skill.
```

**为什么有效**：Claude Code 用 description 字段做语义匹配来决定是否加载技能——匹配率低。Hook 绕过被动匹配，**在每次交互后强制 Claude 自检是否有可萃取知识**。是 "prompt injection 式" 的持久提醒。

### 2. 萃取流程（5 步）

| 步骤 | 做什么 | 关键细节 |
|------|--------|----------|
| Step 1 | 检查已有技能 | `rg --files -g 'SKILL.md'` 扫描所有技能目录，决策矩阵（更新 vs 新建 vs 关联） |
| Step 2 | 识别知识 | 自问：非显性在哪？触发条件是什么？ |
| Step 3 | WebSearch 研究 | 搜索最新实践，防止写入过时知识 |
| Step 4 | 结构化写入 | YAML frontmatter + 7 段式 markdown |
| Step 5 | 优化描述 | description 字段决定未来语义匹配能否命中 |

### 3. 去重决策矩阵（P0 — 直接可用）

| 场景 | 动作 |
|------|------|
| 无相关 | 新建 |
| 同触发 + 同修复 | 更新版本（patch/minor） |
| 同触发 + 不同根因 | 新建 + 双向 `See also` |
| 部分重叠 | 更新已有，加 "Variant" 子节 |
| 同领域不同问题 | 新建 + `See also` |
| 已过时 | 标 deprecated + 替代链接 |

### 4. 质量门（防止垃圾技能）

四个硬标准——不满足就不萃取：
- **Reusable**：不是一次性方案
- **Non-trivial**：不是文档能查到的
- **Specific**：有精确触发条件
- **Verified**：实际验证过有效

### 5. 描述优化（语义匹配的关键）

```yaml
# 差——永远匹配不到
description: "Helps with database problems"

# 好——精确命中
description: |
  Fix for "ENOENT: no such file or directory" errors when running npm scripts
  in monorepos. Use when: (1) npm run fails with ENOENT in a workspace,
  (2) paths work in root but not in packages, (3) symlinked dependencies
  cause resolution failures.
```

利用 Claude Code 内部机制：只读 frontmatter description (~100 token) 做语义匹配，匹配到才加载全文。

### 6. 自省 5 问

工作中持续自问：
1. "我刚学到了什么非显性的东西？"
2. "再遇到同样问题我希望知道什么？"
3. "什么错误信息/症状把我引到这里？"
4. "这个模式是项目特有的还是通用的？"
5. "我会怎么告诉同事？"

---

## 学术基础

| 论文 | 贡献 |
|------|------|
| **Voyager** (Wang 2023) | 技能库架构——可增长、可组合、可检索 |
| **CASCADE** (2024) | Meta-skill——"学会学习"的技能 |
| **SEAgent** (Sun 2025) | 从失败和成功中双向学习 |
| **Reflexion** (Shinn 2023) | 语言反馈替代数值奖励 |
| **EvoFSM** (2024) | 经验池蒸馏 + 热启动 |

---

## 值得偷的模式

### P0: Hook 强制自检

我们的 hook 体系已经成熟，可以加 post-task 自检 hook。不是被动等语义匹配，而是每次任务完成后主动评估是否有可萃取知识。

**Orchestrator 可偷**: 在 SessionEnd 或 Stop hook 中注入自检提示，自动将有价值的发现写入 experiences.jsonl 或 memory。

### P0: 去重决策矩阵

6 种场景 6 种策略，防止技能库膨胀。

**Orchestrator 可偷**: 直接应用于 SOUL/public/skills 管理和 memory 文件管理。我们目前的 memory 系统缺乏系统性去重。

### P1: 描述即检索键

description 决定技能能否被发现。好的 description 包含：具体错误信息、触发条件列表、使用场景。

**Orchestrator 可偷**: 审计所有现有 skill 的 description 字段，用这个标准优化。

### P1: 4 重质量门

Reusable / Non-trivial / Specific / Verified。

**Orchestrator 可偷**: 融入 prompt-linter 的技能评分维度，或加到 skill-reviewer agent 的检查项。

### P2: 技能生命周期

Creation → Refinement → Deprecation → Archival。

**Orchestrator 可偷**: SOUL 系统目前缺这层管理——skill 只增不减。

---

## 相关项目

- **markdav-is/Skiller**: Claudeception 的跨平台 fork，新增 GitHub Copilot + Cursor 支持，三层渐进加载（名称/描述 → 完整指令 → 辅助文件）

---

## 局限性

1. **纯 prompt，无自动化测试** — 不知道萃取出的技能质量如何
2. **Hook 开销** — 每次交互都评估，token 成本不低
3. **示例太窄** — 全是 Next.js/Prisma/TypeScript
4. **无版本控制** — 技能更新没有 changelog 或 diff
