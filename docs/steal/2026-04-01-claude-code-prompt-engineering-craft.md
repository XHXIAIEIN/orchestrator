# Round 34: Claude Code Prompt Engineering 工艺学 — 深度解剖报告

> **日期**: 2026-04-01
> **来源**: Claude Code v2.1.89 源码逆向 + 官方文档 + Piebald-AI prompt 追踪 + 社区分析
> **方法**: 跨 6 份已有偷师报告交叉比对，补充 Output Styles / Deferred Tools / 动态注入 / 版本演进等新维度
> **与已有报告关系**: Round 28b（30 个 prompt 模块）、Round 29（84 模式 6 子系统）的 **prompt 工艺层** 补完

---

## 执行摘要

Claude Code 的 prompt 系统不是"写一段长文本"——是一个 **110+ 模块、条件拼装、三层缓存优化、双向工具延迟加载** 的工业级 prompt 管线。本报告从 7 个维度拆解这套工艺，每个维度提取可偷模式。

**核心发现**:
1. **Output Styles 是 system prompt 的"换头术"** — 不是追加，是替换掉软件工程相关指令
2. **Deferred Tools 将 14K tokens 压到 968** — 用 ToolSearch 做按需加载，后来混合策略稳定在 8.1K
3. **CLAUDE.md 不在 system prompt 里** — 是作为 user message 注入的，优先级和缓存语义完全不同
4. **System Reminder 漂浮锚定** — 不是首尾放一次，是每隔 N 轮在 tool_result 里重复注入
5. **Prompt 版本用 Statsig 门控** — 180+ feature flags，编译时和运行时双层开关

---

## 一、Prompt 拼装管线（Assembly Pipeline）

### 架构全景

```
                    ┌─────────────────────────────────┐
                    │     Section Builder Functions     │
                    │  (110+ 模块，各返回 string|null)  │
                    └─────────────┬───────────────────┘
                                  │ 条件拼装
                    ┌─────────────▼───────────────────┐
                    │        Static Prefix (~80%)       │
                    │  身份 + 安全 + 工具定义 + 规则    │
                    │  ← cache_control breakpoint →     │
                    ├─────────────────────────────────  │
                    │        Dynamic Suffix (~20%)       │
                    │  环境变量 + Feature Flags + 状态   │
                    └─────────────┬───────────────────┘
                                  │
                    ┌─────────────▼───────────────────┐
                    │     system prompt (API 调用)      │
                    └─────────────┬───────────────────┘
                                  │
                    ┌─────────────▼───────────────────┐
                    │  CLAUDE.md → user message 注入    │
                    │  system-reminder → tool_result    │
                    └─────────────────────────────────┘
```

### 拼装逻辑

每个 Section Builder 是一个函数，返回 `string | null`。`null` 表示该模块在当前配置下不激活。拼装器按固定顺序调用所有 builder，过滤掉 null，用换行连接。

**模块分类**（按 token 量排序）:

| 类别 | 模块数 | 典型 token | 示例 |
|------|--------|-----------|------|
| 任务执行 | 12 | ~600 | "read before modifying", "no premature abstractions" |
| 安全/权限 | 8 | ~540 | 哪些操作需要权限，哪些不需要 |
| 输出/语气 | 6 | ~320 | 简洁度、格式、语气 |
| 工具定义 | 24 | ~968-8100 | Bash/Read/Edit/Glob/Grep... |
| Agent/协作 | 10 | 按需 | Coordinator/Explore/Verification |
| 条件模块 | 40+ | 0-1300 | Plan mode/Learning mode/Auto mode |
| 微服务 prompt | 6 | 各自独立 | Compact/Title/Summary/Suggestion |

**关键洞察**: 不是一个大文件，是函数式组合。每个模块可以被独立测试、版本化、A/B 测试。

### 可偷: Orchestrator 适配

当前 SOUL/boot.md 是手写编译产物（~1.7K tokens），没有模块化。应该改为：

```python
# 伪代码
sections = [
    identity_section(),        # 身份 → 固定
    safety_section(),          # 安全规则 → 固定
    tool_definitions(),        # 工具 → 按 agent 类型变化
    task_rules(task_type),     # 任务规则 → 按任务类型条件注入
    memory_context(session),   # 记忆 → 动态
    env_context(os, cwd, git), # 环境 → 动态
]
prompt = "\n\n".join(s for s in sections if s is not None)
```

**难度**: 6h（拆分现有 boot.md 为模块函数）
**价值**: 为 Agent SDK 调用准备缓存友好的 prompt 结构

---

## 二、Cache Boundary 策略

### 机制

System prompt 被显式分为两段，由 `cache_control` 参数标记边界：

- **静态前缀**（身份 + 规则 + 工具定义 + 安全策略）→ 跨请求缓存，命中率 80%+
- **动态后缀**（OS、CWD、git status、feature flags、会话状态）→ 每次重新计算

Anthropic prompt caching 的关键参数：
- 最多 4 个 cache breakpoint
- 系统自动在 breakpoint 前最多 20 个 content block 检查缓存命中
- 最小可缓存前缀：1024-4096 tokens（取决于模型）
- 5 分钟 TTL（1.25x 写入价格，0.1x 读取价格）

### Output Style 对缓存的影响

官方文档明确说：

> "Because the output style is set in the system prompt at session start, changes take effect the next time you start a new session. This keeps the system prompt stable throughout a conversation so prompt caching can reduce latency and cost."

也就是说，Output Style 一旦选定就**冻结整个会话**，不允许中途切换——就是为了保住 cache 命中率。

### Deferred Tools 对缓存的保护

这是最精妙的设计：

> "Deferred tools are not included in the system-prompt prefix. When the model discovers a deferred tool through tool search, the tool definition is appended inline as a `tool_reference` block in the conversation. The prefix is untouched, so prompt caching is preserved."

工具定义变化不会破坏 cache！因为延迟工具的 schema 是在对话历史里追加的，不动 prefix。

### 可偷: Orchestrator 适配

1. **立即可做**: boot.md 编译产物的前 80% 标记为"可缓存"，后 20% 标记为"动态"
2. **中期**: Agent SDK 调用时显式设置 `cache_control` breakpoint
3. **关键决策**: 工具定义放在 cache boundary 之前还是之后？Claude Code 选择"之前但可 defer"——因为核心工具（Bash/Read/Edit）每次都用，defer 它们反而多一次 round trip

**难度**: 2h（标记分割点）+ 取决于 Agent SDK 支持
**优先级**: P0 — 直接影响 API 成本

---

## 三、Output Styles 系统

### 内部机制

Output Styles **不是追加**——是对 system prompt 的**结构性替换**：

1. **所有 Output Styles**（包括内置的）都会移除"高效输出"指令（如"回答要简洁"）
2. **Custom Output Styles** 额外移除"编码相关"指令（如"用测试验证代码"），除非 `keep-coding-instructions: true`
3. Style 的自定义内容追加到 system prompt **末尾**
4. 对话过程中，system-reminder 会**定期提醒**模型遵守 output style

### 三层替换语义

```
Default Style:
  [身份] + [安全] + [工具] + [编码规则] + [高效输出] + [动态]

Built-in Style (Explanatory/Learning):
  [身份] + [安全] + [工具] + [编码规则] + [自定义指令] + [动态]
  ← 移除 [高效输出]，追加 [自定义指令]

Custom Style:
  [身份] + [安全] + [工具] + [自定义指令] + [动态]
  ← 移除 [编码规则] + [高效输出]，追加 [自定义指令]

Custom Style (keep-coding-instructions: true):
  [身份] + [安全] + [工具] + [编码规则] + [自定义指令] + [动态]
  ← 只移除 [高效输出]
```

### Frontmatter 字段

| 字段 | 用途 | 默认值 |
|------|------|--------|
| `name` | 显示名称 | 文件名 |
| `description` | 在 /config 选择器中显示 | 无 |
| `keep-coding-instructions` | 保留编码规则 | false |

### 存储位置

- 用户级: `~/.claude/output-styles/`
- 项目级: `.claude/output-styles/`
- 激活: `.claude/settings.local.json` 的 `outputStyle` 字段

### 可偷: Orchestrator 适配

这就是 Orchestrator 的 **persona 系统** 的升级蓝图：

```
当前: persona skill = 一个 SKILL.md 文件，追加到 context
升级: output-style = 结构性替换 boot.md 的部分模块

用例:
- "采集器模式": 移除对话相关规则，注入采集专用指令
- "审计模式": 移除创作规则，注入严格验证指令
- "损友模式": 默认 persona，保持吐槽风格
```

**关键决策**: 用 frontmatter 的 `keep-X-instructions` 模式比完全替换更安全——保留安全层，只换行为层。

**难度**: 4h
**优先级**: P1 — 当前 persona skill 够用，但多 agent 场景会需要

---

## 四、CLAUDE.md 注入层

### 关键发现: 不在 system prompt 里

官方文档明确说：

> "CLAUDE.md adds the contents as a **user message** following Claude Code's default system prompt."

这和 `--append-system-prompt`（追加到 system prompt）是不同的注入点。

### 五层优先级

从低到高：

1. **Enterprise** (`/etc/claude-code/settings.json`) — 组织级，不可覆盖
2. **User** (`~/.claude/CLAUDE.md`) — 个人全局
3. **Project** (`CLAUDE.md` / `.claude/CLAUDE.md`) — 项目级
4. **Rules** (`.claude/rules/*.md`) — 模块化规则，支持 `paths` 条件注入
5. **Local** (`CLAUDE.local.md`) — 私有本地覆盖

### 冲突解决

- 设置文件（settings.json）：managed > CLI flags > local > project > user
- 数组值（如允许列表）：**拼接去重**，不是替换——低优先级可以添加但不能覆盖
- CLAUDE.md 内容：全部拼接，高优先级的内容在后面（模型更重视后面的指令）

### Rules 的条件注入

`.claude/rules/*.md` 支持 frontmatter `paths` 字段——只在编辑匹配 glob 的文件时加载：

```yaml
---
paths:
  - "src/channels/**"
  - "dashboard/**"
---
# 前端规则
匹配现有页面样式...
```

### @include 递归

CLAUDE.md 支持 `@path` 指令引用其他文件，最大递归深度 5 层，有循环检测。

### 可偷: Orchestrator 适配

1. **Rules 条件注入**: 当 agent 操作特定模块时，自动加载对应规则——比把所有规则塞进 boot.md 省 token
2. **User message vs System prompt 注入点选择**: 如果想让 CLAUDE.md 内容被 cache，应该放 system prompt；如果想让它可以被覆盖/更新，放 user message。Claude Code 选了后者——牺牲缓存换灵活性

**难度**: 3h（Rules 条件注入）
**优先级**: P1

---

## 五、Tool Description 生成与 Deferred Loading

### 演进时间线

| 版本 | 变化 | Token 消耗 |
|------|------|-----------|
| < 2.1.69 | 所有工具 upfront 加载 | ~14-16K |
| 2.1.69 | 全部 defer 到 ToolSearch | ~968 |
| 2.1.72 | 混合策略：核心 9 个 upfront + 其余 defer | ~8.1K |

### 混合策略细节

**预加载（full schema）**: Agent, Bash, Edit, Glob, Grep, Read, Skill, ToolSearch, Write
**延迟加载（仅名称）**: AskUserQuestion, Cron*, Worktree*, Task*, WebFetch, WebSearch

选择标准：**每次对话几乎必用的工具 → preload；偶尔用的 → defer**。

### ToolSearch 双变体

- **Regex** (`tool_search_tool_regex_20251119`): Claude 构造 Python 正则匹配工具名/描述
- **BM25** (`tool_search_tool_bm25_20251119`): 自然语言查询，语义匹配

搜索范围：tool names + descriptions + argument names + argument descriptions
返回：3-5 个最相关工具的完整 schema

### MCP 工具合并

MCP 工具默认就是 deferred。当 MCP server 的工具定义超过 context window 的 10% 时自动启用 ToolSearch。MCP 还支持 `list_changed` 通知——server 可以动态增减工具而不需要断开重连。

### 自定义 ToolSearch

可以自己实现搜索逻辑（比如用 embedding），只要返回 `tool_reference` block：

```json
{
  "type": "tool_result",
  "tool_use_id": "toolu_xxx",
  "content": [{"type": "tool_reference", "tool_name": "discovered_tool"}]
}
```

### 可偷: Orchestrator 适配

1. **立即可做**: Agent SDK 调用时，把不常用工具标记 `defer_loading: true`——直接省 token
2. **SOUL 工具注册表**: 维护一个"工具频率表"，按使用频率决定 preload/defer
3. **Skill 描述动态生成**: 当前所有 skill 描述都在 system prompt 里（~15K 字符上限），可以改为只放名字 + 一行描述，详细 schema 按需加载

**难度**: 2h（标记 defer_loading）
**优先级**: P0 — 直接省钱

---

## 六、Prompt 优化技法

### 6.1 System Reminder 漂浮锚定

Claude Code 不是把规则说一次就完——在对话过程中**持续重复注入**关键指令：

- system-reminder 以 `<system-reminder>` 标签包裹
- 注入点：tool_result 内容、user message 之间
- 触发条件：每隔 N 轮、特定事件（文件修改、hook 执行结果、plan mode 切换）
- 内容：当前日期、CLAUDE.md 内容、output style 提醒、git status 更新

**为什么有效**: 长对话中模型会"遗忘"早期指令。定期在中间位置重复关键规则，比放在开头一次效果好得多。

### 6.2 Scratchpad-Strip 模式

Compact 和 Memory 子系统让模型在 `<analysis>` 标签里做推理草稿，然后 **strip 掉** 只保留结果。草稿提升输出质量但不消耗后续 context token。

```
模型输出:
<analysis>
这里是中间推理过程...
</analysis>
<summary>
这里是精炼结果
</summary>

注入 context:
（只保留 summary，analysis 被 strip）
```

### 6.3 正面框架优先

Claude Code 的 prompt 几乎全是正面指令（"do X"），极少用负面指令（"don't do X"）。负面指令出现在两个地方：
- 安全分类器（explicit deny list）
- Coordinator 反模式清单（"不准懒委派"）

**为什么有效**: 正面指令给模型明确的行为方向；负面指令只排除了一种行为，模型可能选另一种同样糟糕的替代。

### 6.4 Token 最小化演进

Piebald-AI 的 CHANGELOG 显示 Claude Code 持续压缩 prompt：
- v2.1.88: 验证 skill 压缩 ~67%，删除扩展发现梯度参考表
- v2.1.88: 从 git status prompt 中剥离内联变量模板
- v2.1.88: 合并 fresh-agent vs context-inheriting subagent 指导为单一流程
- v2.1.84: 移除"写清晰 Bash 命令描述"指令（减少元叙述）

**模式**: 先写完整指令 → 观察模型行为 → 如果模型已经自然做到了，删掉这条指令。**指令的最佳数量是让模型正确行为所需的最少数量。**

### 6.5 指令位置策略

- **安全指令**: system prompt 最前面（身份之后）——必须最先被处理
- **编码规则**: 中段——可以被 output style 替换
- **动态上下文**: 末尾——不破坏 cache
- **CLAUDE.md**: user message——可被覆盖，保持灵活
- **System Reminder**: 散布在对话中间——对抗遗忘

### 可偷: Orchestrator 适配

1. **System Reminder 机制**: 在长对话中每 5 轮重复注入核心规则（身份 + 安全 + 当前任务）
2. **Scratchpad-Strip**: Compact 时强制用 analysis/summary 两段式，只保留 summary
3. **指令审计**: 定期检查 CLAUDE.md 中的规则——如果模型已经自然做到，删掉它

**难度**: 2h（system reminder）+ 2h（scratchpad-strip）
**优先级**: P0

---

## 七、Prompt 版本化与 A/B 测试

### 双层开关

Claude Code 用两种完全不同的特性开关：

1. **编译时开关** (`feature('FLAG')`): Tree-shaking 边界。关闭时整个代码分支被移除，不打包。用于未发布功能（Buddy、Kairos、Teleport）。**不可运行时切换。**

2. **运行时开关** (Statsig gates): 可在不重新部署的情况下切换。用于 A/B 测试、渐进发布、用户分群。`buildQueryConfig()` 在入口调用一次，快照到 `QueryConfig.gates`，整个 query 生命周期内不变。

### 规模

社区追踪到 **180+ feature flags**，其中 **41 个 Statsig feature gates** 控制运行时行为。每个版本都有 flags 的增减记录。

### Prompt 变体

不同 feature gate 会导致不同的 prompt 模块被加载：
- `PROACTIVE` → 加载 tick/sleep/focus prompt
- `TEAMMEM` → 加载团队记忆同步 prompt
- `BUDDY` → 加载 AI 宠物状态持久化 prompt

### 版本追踪

Piebald-AI 追踪了 **138 个版本** 的 prompt 变化，精确到每个字符串的增删改。CHANGELOG 在每次 Claude Code 发布后几分钟更新。

### 可偷: Orchestrator 适配

1. **编译时 vs 运行时分离**: SOUL 编译产物（boot.md）用编译时开关控制模块；Agent dispatch 用运行时开关控制行为
2. **Prompt CHANGELOG**: 每次修改 SOUL 文件时自动记录变更（可以用 git diff hook）
3. **Config Snapshot**: Agent dispatch 时快照当前配置，整个任务生命周期内不变——防止中途配置变更导致行为不一致

**难度**: 3h
**优先级**: P1

---

## 八、动态上下文注入

### Git Status 注入

每次 API 调用前组装：

```
Current branch: main
Main branch: main
Git user: XXX
Status:
 M src/foo.py
 M src/bar.py
?? new-file.txt

Recent commits:
abc1234 feat: something
def5678 fix: something else
```

- `git status --short` 输出截断到 **2000 字符**
- 最近 **5 条** commit（`git log --oneline -5`）
- 作为 system prompt 动态后缀注入

### 文件修改通知

当外部进程修改了 Claude Code 正在处理的文件时，system-reminder 自动注入：

```xml
<system-reminder>
File externally modified: src/foo.py
[snippet of changed content]
</system-reminder>
```

### Hook 执行结果

PreToolUse/PostToolUse hook 的输出也通过 system-reminder 注入——模型能看到 hook 的判断结果并据此调整行为。

### 可偷: Orchestrator 适配

1. **Git Status 自动注入**: Agent dispatch 时自动附加 git status（当前已在做，但格式可以对齐）
2. **文件修改监控**: Docker 容器内文件变更时通知 agent——防止覆盖他人修改
3. **Hook 结果反馈**: guard.sh 拦截结果注入 agent context，让模型知道为什么被拦截

**难度**: 2h
**优先级**: P1

---

## 总结: 可偷模式优先级排序

| 优先级 | 模式 | 来源 | 难度 | 价值 |
|--------|------|------|------|------|
| **P0** | Cache Boundary 显式标记 | §二 | 2h | 直接省 API 成本 |
| **P0** | Deferred Tools (defer_loading) | §五 | 2h | 省 ~6K tokens/请求 |
| **P0** | System Reminder 漂浮锚定 | §六 | 2h | 对抗长对话遗忘 |
| **P0** | Scratchpad-Strip 压缩 | §六 | 2h | 提升 compact 质量 |
| **P0** | 指令审计/瘦身 | §六 | 1h | 减少无效 token |
| **P1** | Prompt 模块化拼装 | §一 | 6h | 为多 agent 类型准备 |
| **P1** | Output Style 换头术 | §三 | 4h | 多 agent persona |
| **P1** | Rules 条件注入 | §四 | 3h | 按任务类型加载规则 |
| **P1** | Config Snapshot 隔离 | §七 | 3h | 防中途配置变更 |
| **P1** | Git/文件/Hook 动态注入 | §八 | 2h | 上下文鲜度 |

**总工时估算**: P0 ≈ 9h, P1 ≈ 18h

---

## Sources

- [Piebald-AI/claude-code-system-prompts](https://github.com/Piebald-AI/claude-code-system-prompts) — 110+ prompt 模块追踪，138 版本 CHANGELOG
- [Claude Code Output Styles 官方文档](https://code.claude.com/docs/en/output-styles)
- [Agent SDK Modifying System Prompts](https://platform.claude.com/docs/en/agent-sdk/modifying-system-prompts)
- [Tool Search Tool API 文档](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool)
- [Prompt Caching API 文档](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- [Built-in tools deferred behind ToolSearch (Issue #31002)](https://github.com/anthropics/claude-code/issues/31002)
- [marckrenn/claude-code-changelog](https://github.com/marckrenn/claude-code-changelog) — 180+ feature flags 追踪
- [awesome-claude-code-output-styles](https://github.com/hesreallyhim/awesome-claude-code-output-styles-that-i-really-like)
- [Leonxlnx/claude-code-system-prompts](https://github.com/Leonxlnx/claude-code-system-prompts)
- [Claude Code Settings 文档](https://code.claude.com/docs/en/settings)
