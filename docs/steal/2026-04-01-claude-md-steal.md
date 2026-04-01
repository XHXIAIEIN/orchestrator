# Steal Report: iamfakeguru/claude-md + Obuchowski 架构分析

- **日期**: 2026-04-01
- **来源**:
  - Repo: https://github.com/iamfakeguru/claude-md (361 star, 13KB, MIT)
  - 推文: https://x.com/iamfakeguru/status/2038965567269249484 (118万浏览, 7627赞)
  - 推文: https://x.com/AlexObuchowski/status/2038938582912586225 (1万浏览, 61赞)
- **背景**: Claude Code 源码泄露后，两位作者从不同角度分析。fakeguru 做 workaround 指南（用户视角），Obuchowski 做架构还原（工程视角）。
- **Round**: 34

---

## 事实校验

fakeguru 的推文以"Anthropic 员工专属功能"为卖点，需要拉警报：

| 声称 | 验证 |
|------|------|
| `process.env.USER_TYPE === 'ant'` 员工验证门控 | **无法验证，高度可疑**。Round 28a-29 源码审计未发现此 env var。当前系统提示已含 verification 指令 |
| compaction ~167K tokens 触发 | 基本属实，数字可能不精确 |
| 系统提示含 "try the simplest approach" | 完全属实，可直接观察 |
| sub-agent 无 MAX_WORKERS 限制 | 属实，Agent tool 文档公开 |
| 文件读取上限 2000 行 | 属实，Read tool 描述明确写着 |
| 工具结果截断 | 合理，具体阈值无法验证 |
| grep 不是 AST | 显然，工具描述写的就是 ripgrep |

**结论**: 7 条中 5 条是已知公开行为，1 条基本属实，1 条（员工门控）不可验证。推文的传播力来自阴谋叙事包装，不是技术深度。

Obuchowski 的文章更扎实——5 个架构模式都有代码引用和设计原理分析，无夸大成分。

---

## 提取模式

### P0 — 立即写入系统

#### 1. Context Decay Hard Rule
- **来源**: fakeguru §6 / CLAUDE.md §4
- **内容**: 10+ 消息后编辑文件前必须 re-read。auto-compaction 会静默销毁文件上下文，编辑 stale state 导致无声破坏
- **我们的现状**: learnings 有 breadth-first 规则但没有 re-read 硬规则
- **写入位置**: boot.md learnings

#### 2. Tool Truncation Awareness
- **来源**: fakeguru §8 / CLAUDE.md §4
- **内容**: 工具结果超大时被静默截断。搜索结果疑似过少时，声明怀疑截断并缩小范围重跑
- **我们的现状**: 完全没有此防御
- **写入位置**: boot.md learnings

#### 3. Edit Read-After-Write
- **来源**: fakeguru §9 / CLAUDE.md §6
- **内容**: 编辑后立即重读确认变更生效。Edit tool 在 old_string 不匹配时静默失败。同一文件不超过 3 次编辑不验证读
- **我们的现状**: Gate 体系覆盖删除/重置/配置，但普通编辑无 post-write verification
- **写入位置**: CLAUDE.md Surgical Changes

#### 4. Delete Before Rebuild
- **来源**: fakeguru §1 / CLAUDE.md §2
- **内容**: >300 LOC 文件结构重构前，先删除死代码（unused exports/imports/props/debug logs），单独提交，再做真正的重构
- **我们的现状**: 有"清理自己造成的孤儿"，但没有重构前主动清理的规则
- **写入位置**: CLAUDE.md Planning Discipline

#### 5. Three-Tier Context Compaction（架构认知）
- **来源**: Obuchowski §1
- **内容**: 三层压缩策略：微压缩（AFK 清旧结果）→ 缓存感知压缩（cache_edits API 保持缓存前缀）→ 全量压缩（session summary）。700 行 promptCacheBreakDetection.ts 监控缓存命中，3 次失败熔断
- **我们的现状**: boot.md 编译器管 token 预算，但无运行时多层策略
- **关联**: Round 33 Headroom 偷师的 CacheAligner 模式的实际实现
- **写入位置**: learnings（架构认知，指导 compaction 策略设计）

#### 6. Fork Agent Cache Sharing
- **来源**: Obuchowski §5
- **内容**: 所有后台操作（记忆提取/dream/压缩/推测）作为 fork agent 共享父会话 prompt cache。CacheSafeParams 快照确保字节一致。fork 复制父级 content replacement state。90%+ cache read rate
- **我们的现状**: 三省六部每个 sub-agent 从头构建上下文，完全没利用 cache sharing
- **写入位置**: learnings + 三省六部优化方向

### P1 — 有价值但需适配

#### 7. Dream Agent（自动记忆整理）
- **来源**: Obuchowski §2
- **内容**: 会话间后台 agent 整理 memory：合并重复、修正过时信息、相对日期转绝对日期、清理死指针
- **我们的现状**: memory 手动维护，Round 29c 记过 DreamTask 但未实施
- **评估**: 需要评估是否值得自建。当前 memory 量级下手动可控

#### 8. Forced Verification（项目特定检查）
- **来源**: fakeguru §4 / CLAUDE.md §3
- **内容**: 完成前必须跑 tsc + eslint + 测试
- **我们的现状**: verification-gate 五步链更通用，但缺项目特定检查命令
- **评估**: 可以在 verification-gate 里加项目感知——TS 项目自动 tsc，Python 项目自动 pytest

#### 9. Bug Autopsy
- **来源**: CLAUDE.md §8
- **内容**: 修完 bug 后解释为什么发生、如何预防同类
- **我们的现状**: feedback_bug_report.md 要求写最小复现 + issue，但缺事后分析
- **评估**: 补充到 bug 修复流程

### P2 — 已有更好方案

| 模式 | 我们为什么更好 |
|------|--------------|
| Sub-Agent Swarming | 三省六部 + Governor 协作链 > "5-8 文件一个 agent" |
| File System as State | SOUL + memory 分类 + experiences.jsonl > gotchas.md |
| Session Continuity | remember skill + core-memories + boot.md > `--continue` |
| Phased Execution | planning discipline + 原子步骤 + 依赖声明 > "每 phase ≤5 文件" |
| Prompt Cache Awareness | boot.md 编译器 > "别中途换模型" |
| Senior Dev Override | 与 Surgical Changes 冲突，适合个人项目全权重构，不适合多 agent 协作 |
| Speculative Execution | Claude Code 内部机制，用户侧无法复制。boundary 概念与 Gate 体系同构 |
| Bash Approval Classifier | Claude Code 内部机制。设计思想（speculative classifier + 短超时）值得记录 |

### 不偷

| 模式 | 理由 |
|------|------|
| 员工门控叙事 | 不可验证，更像 content marketing 包装 |
| "One-Word Mode" | 我们的 CLAUDE.md 已有"他说'是的'通常意味着别废话了快做" |
| "Write Human Code" | 我们已有 Surgical Changes + 匹配现有风格 |
| gotchas.md | memory feedback 类型功能等价且更结构化 |
| Two-Perspective Review | 优先级低，当前工作流不需要 |

---

## 关键洞察

1. **fakeguru 的核心贡献是"对抗默认行为"** — 不是教写代码，而是修补 Claude Code 系统性盲点的 workaround。这些是平台级 bug 的用户侧补丁
2. **Obuchowski 的核心贡献是"架构可偷性"** — 三层压缩、cache sharing、speculative execution 是 Claude Code 内部的精巧工程，对我们设计 sub-agent 系统有直接参考价值
3. **我们在"身份/记忆/协作"维度远超两者，但在"防御性编辑"维度有盲点** — P0 的 1-4 条都是我们缺失的硬防御规则
4. **偷师要分清"洞察"和"叙事"** — 洞察是可验证的技术事实，叙事是传播包装。偷洞察不偷叙事

---

## 统计

- 提取: 9 模式（6 P0 + 3 P1）
- 已有更好方案: 8 模式
- 不偷: 5 模式
- 待实施: 6 P0（写入 boot.md learnings + CLAUDE.md）
