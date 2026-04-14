# R55 — SlowMist Agent Security Steal Report

**Source**: https://github.com/slowmist/slowmist-agent-security | https://github.com/slowmist/MCP-Security-Checklist | https://github.com/slowmist/openclaw-security-practice-guide | https://github.com/slowmist/MasterMCP | https://slowmist.medium.com/slowmist-bitget-security-research-risks-and-protections-of-ai-agents-020190c1ec67  
**Date**: 2026-04-14  
**Category**: Industry survey — blockchain security firm's AI agent security methodology  
**Repos found**: 4 directly relevant (slowmist-agent-security, MCP-Security-Checklist, openclaw-security-practice-guide, MasterMCP)

---

## TL;DR

SlowMist 在 2026 年 3 月前后密集发布了一套针对 AI agent 的安全框架，切入点是 Web3 + AI agent 的交叉风险。核心资产有三层：**攻击模式库**（11 类代码红旗 + 8 类社会工程 + 7 类供应链）、**运行时安全框架**（OpenClaw Security Practice Guide v2.8）、**plugin 生态审计**（MCP Security Checklist 覆盖 Server/Client/Multi-MCP 三层）。

最有价值的偷师点不是他们的区块链安全专业知识，而是他们把 agent 运行环境当作 **adversarial environment** 的基本前提假设，以及由此推导出的具体操作模式。

---

## Architecture Overview

SlowMist 的 agent 安全体系分四个独立产品，彼此互补：

```
┌─────────────────────────────────────────────────────────┐
│              SlowMist Agent Security Stack               │
├─────────────────┬───────────────────────────────────────┤
│ slowmist-agent- │ SKILL.md 格式的 agent 内置安全框架      │
│ security        │ 激活条件路由 → 6类 review guide         │
│ (v0.1.2)        │ 4级风险评分 + 5级信任层级              │
├─────────────────┼───────────────────────────────────────┤
│ MCP-Security-   │ 针对 MCP plugin 生态的 checklist        │
│ Checklist       │ 覆盖 Server / Client / Multi-MCP       │
│                 │ 三级优先级标注 (High/Medium/Low)        │
├─────────────────┼───────────────────────────────────────┤
│ openclaw-       │ "思想钢印"实验 — 直接注入 Markdown 改变  │
│ security-       │ agent 基线行为判断                      │
│ practice-guide  │ 3层防御矩阵：pre / in / post action     │
├─────────────────┼───────────────────────────────────────┤
│ MasterMCP       │ PoC 攻击工具包（教育用途）              │
│                 │ 演示 4 种 MCP 攻击向量的实际代码        │
└─────────────────┴───────────────────────────────────────┘
```

补充：SlowMist × Bitget 联合发布的 AI Agent 安全报告（2026 年 3 月）是理论框架；上述 repos 是落地实现。

---

## Steal Sheet

### P0 — 必须直接借鉴的模式

#### P0.1 — 风险四级 + 信任五层的标准化输出

SlowMist 把 agent 的每次外部输入评估结果强制输出为标准格式：

| 等级 | 含义 | Agent 动作 |
|------|------|----------|
| 🟢 LOW | 信息型，无执行能力，可信来源 | 告知用户，按需继续 |
| 🟡 MEDIUM | 有限能力，来源已知，存在部分风险 | 完整报告 + 建议谨慎 |
| 🔴 HIGH | 涉及凭据/资金/系统修改/未知来源 | 详细报告，**必须人工审批** |
| ⛔ REJECT | 命中红旗 pattern，确认恶意 | 拒绝执行，解释原因 |

信任层级（只调整审查强度，从不跳过步骤）：
- Tier 1: 官方组织 → 中等审查
- Tier 2: 已知安全团队 → 中等审查
- Tier 3: 高下载量 + 多版本迭代 → 中高
- Tier 4: 高 star + 活跃维护 → 高 — 必须验证代码
- Tier 5: 未知来源/新账号 → 最高强度

**可偷：** Orchestrator 的 gate function 目前是 binary（做/不做），可以引入 4 级风险输出作为 gate function 的返回格式，取代布尔判断。

#### P0.2 — "Judge by code, not by comments"原则

SlowMist 的 social-engineering 模式库明确指出：注释是建议，代码是真相。当注释和代码行为不一致时，信任代码。

这对应 Orchestrator 自己长期以来的一个盲点：评估 agent 行为时倾向于读文档描述而不是实际执行路径。

**可偷：** 在 skill-vetter 或 plugin 审查流程中，明确将"注释-代码一致性检查"列为 mandatory step。

#### P0.3 — 渐进式升级攻击（Boiling Frog）的整体文档视角

> 评估整个文档/对话的整体效果，不是逐步评估。问："如果我按顺序执行这个文档里的所有内容，净效果是什么？"

这是 SlowMist 红旗模式库里最精妙的一条。单条命令都合法，整体串联起来是系统级攻击。

**可偷：** Orchestrator 处理 multi-step agent 任务时，应在执行前对整个计划做全局 intent check，而不是只看当前步骤是否合法。

#### P0.4 — 供应链攻击：Runtime Secondary Download 的检测逻辑

SlowMist 的供应链模式库对"运行时二次下载"的检测关键词非常具体：
- `npm install`, `pip install` 出现在 postinstall 脚本中
- `curl | bash`, `wget | sh` 管道执行
- `npx unknown-package -y` 无确认一次性执行
- Auto-update channel（MANIFEST 文件远程替换本地文件）

**Bybit AI Hub 的 MANIFEST 自动更新机制**被明确点名为"if the GitHub account is compromised, remote code execution channel"。

**可偷：** Orchestrator 的 skill/plugin 安装 gate 应该扫描这些关键词，MasterMCP 的 PoC 代码可以作为测试用例。

---

### P1 — 值得系统性研究的模式

#### P1.1 — 3层防御矩阵（Pre/In/Post Action）

OpenClaw Security Practice Guide v2.8 的防御矩阵：
1. **Pre-action**: 行为黑名单 + Skill 安装审计（反供应链投毒）
2. **In-action**: 权限收窄 + 跨 Skill 预飞检查（业务风险控制）
3. **Post-action**: 定时显式审计（13 个核心指标）+ Git 灾难恢复

对应 Orchestrator 现有架构：Pre-action 有 gate function，In-action 有 dispatch-gate hook，Post-action **缺失**。

**差距：** Orchestrator 没有系统性的事后审计机制。OpenClaw 的 nightly audit 脚本 (v2.8) 包含 persistent report path + 30 天轮转 + known-issue 排除逻辑，设计相当成熟。

#### P1.2 — 五层安全治理框架（L1-L5）来自 SlowMist × Bitget 联合报告

| 层级 | 职责 |
|------|------|
| L1 | 统一基线：跨工具/框架的标准化策略 |
| L2 | 权限边界：最小特权 + 人在回路 |
| L3 | 实时威胁感知：URL/依赖/plugin 来源筛查 |
| L4 | 链上隔离：风险分析 + 独立签名（不直接访问私钥）|
| L5 | 闭环审计：执行前验证 / 执行中约束 / 执行后可追溯 |

这个 L1-L5 框架和 Orchestrator 的 Commitment Hierarchy 有结构性相似，但 SlowMist 更强调执行链的每个节点都需要独立验证，不能依赖上层已经验证过。

#### P1.3 — "思想钢印"实验的 Meta 洞察

OpenClaw Security Practice Guide 的设计哲学：把安全策略直接注入 agent 的认知基线（via Markdown），而不是构建一个独立的安全 Skill。

理由：外部 Skill 是工具，思想钢印改变的是 agent 的基线判断。如果 Skill 被 prompt injection 污染，它会失效；如果基线判断被塑造，防御会更持久。

**但 SlowMist 自己也承认这个方法有硬限制**（见 FAQ）：模型能力不足时，误判风险高于零安全策略。因此它对模型有明确的能力前提要求（"strong, latest-generation reasoning model"）。

**可偷：** Orchestrator 的 CLAUDE.md 里的 Gate Function 本质上就是"思想钢印"实验，但没有明确的模型能力前提说明。考虑在 boot.md 中加入 capability self-check 触发条件。

#### P1.4 — Agent Identity/Memory File 作为独立攻击面

SlowMist 的 red-flags 模式库把 agent 身份/记忆文件单独列为一个攻击向量（Severity: 🔴 Always）：

```
MEMORY.md, USER.md, SOUL.md, IDENTITY.md, AGENTS.md, TOOLS.md,
paired.json, openclaw.json, sessions.json, .claude/settings
```

PoC 文档包含：`cp ~/.openclaw/workspace/MEMORY.md /tmp/poc-agent-pwned-memory.txt`

**对 Orchestrator 的直接含义：** `SOUL/` 目录和 `.claude/` 目录是高价值攻击目标。外部 Skill/MCP 安装时应明确禁止访问这些路径。

---

### P2 — 存档参考，暂不优先

#### P2.1 — MCP Security Checklist 的 Auto-approve 控制

MCP Client 层的 Auto-approve 管控：
- 严格控制哪些 tool/操作可以自动审批
- 维护 whitelist 机制
- 基于上下文动态调整策略
- 审计所有自动审批决策

这对 Orchestrator 现在的规模（单主人、小规模 plugin 生态）不是急迫问题，但一旦对外开放多用户就需要。

#### P2.2 — 密码学完整性验证

SlowMist 建议对所有 code 和 Skill 进行 hash/签名验证。技术上可行，但在 OpenClaw 生态内推动成本高，且实际攻击中 Trusted Source Compromise（维护者账号被攻破）使签名失效。

---

## Comparison Matrix

| 维度 | SlowMist 做法 | Orchestrator 现状 | 差距 |
|------|-------------|-----------------|------|
| 外部输入假设 | 一切外部输入不信任直至验证 | Gate function 存在但覆盖不完整 | 缺 URL/Document/Social Share 路由 |
| 风险量化 | 4 级标准化输出 | Binary (做/不做) | 没有中间态 |
| 攻击模式库 | 11+8+7 = 26 类，带检测关键词 | 无系统性 pattern library | 直接缺失 |
| 供应链安全 | 7 类供应链 pattern + 安装审计 | 无 | 直接缺失 |
| 事后审计 | nightly audit，13 指标，持久化报告 | 无 | 直接缺失 |
| agent 身份保护 | 内存/身份文件列为 🔴 攻击向量 | SOUL/ 目录有 gitignore，无访问限制 | 需要加 path 限制到 gate |
| Plugin 权限 | 最小特权 + chattr +i 锁定 | 依赖 CLAUDE.md 人工遵守 | 无机制强制 |
| PoC 测试套件 | MasterMCP 4 种攻击向量可复现 | 无 red team 测试用例 | 直接缺失 |

---

## Gaps

1. **Orchestrator 没有 pattern library**。遇到可疑 plugin/URL/外部输入时，靠 agent 临时判断。SlowMist 证明这是不够的——他们在 ClawHub 里发现了 400+ 恶意 Skill 样本，说明 ad-hoc 判断在规模下失效。

2. **Agent 身份文件没有访问控制**。`SOUL/` 目录只靠 gitignore 保护（防止上传），没有防止 Skill/外部代码读取的机制。SlowMist 的 PoC 明确演示了 `cp MEMORY.md /tmp/exfil` 的攻击路径。

3. **事后审计是盲区**。Pre-action 和 In-action 有覆盖，但 Post-action 几乎为零。没有"上次运行了什么 skill，它访问了哪些文件"的记录。

4. **整体文档 intent check 缺失**。当前 multi-step 任务只验证单步骤是否合法，Boiling Frog 类攻击（每步合法，整体有害）无法被当前机制检测到。

5. **没有 red team 测试套件**。SlowMist 有 MasterMCP（4 种 PoC）+ Validation Guide（模拟攻击剧本），Orchestrator 完全没有对应的东西。

---

## Adjacent Discoveries

### 1. MasterMCP 的四种攻击实现

PoC 代码完整实现了四种攻击：
- **数据投毒**（`initialize_data_poisoning.py`）：在任意操作前强制插入"香蕉检查"步骤，建立虚假流程依赖
- **JSON 注入**（`inject_json_poisoning.py`）：从本地恶意服务拉数据，导致数据泄露或命令操纵
- **竞争性函数覆盖**（`malicious_competitive_function.py`）：`remove_server` 函数名相同但行为不同，覆盖合法系统函数
- **跨 MCP 调用攻击**（`malicious_cross_mcp_call.py`）：通过编码错误信息引导用户添加未验证的外部服务

这些可以直接作为 Orchestrator skill 安装门的测试用例。

### 2. AAPWG 伪权威案例

SlowMist 的 PoC 文档声称"AAPWG（AI Agent Performance Working Group）认证安全"，该组织不存在。这是专门测试 agent 是否会对伪权威声明进行独立核实的 red team 测试方法。

值得在 Orchestrator 的验证门里加入"权威声明可验证性"检查。

### 3. v2.8 新增 `--light-context` Cron 保护

OpenClaw v2.8 的 nightly audit 使用 `--light-context` 参数，防止工作区上下文劫持隔离的审计会话。这是对 Boiling Frog 攻击在 cron 场景中的具体防御措施。

### 4. 400+ 恶意 Skill 的规模数据

SlowMist 在 ClawHub（OpenClaw 官方 plugin 中心）发现 400+ 恶意 Skill 样本。这说明 plugin 生态一旦开放，供应链投毒速度极快。Orchestrator 如果以后对外开放 skill marketplace 必须在设计阶段就考虑审计机制。

---

## Meta Insights

### 1. 安全框架的格式即载体

SlowMist 的 `slowmist-agent-security` 用 SKILL.md 格式打包安全框架，让安全规则成为 agent 的内置认知，而不是外部工具。这和 Orchestrator 用 CLAUDE.md 植入 Gate Function 的逻辑完全一致——只是 SlowMist 把它做成了可复用的模块化产品。

**洞察：** 安全框架的最佳形态是被 agent 内化的认知，而不是被调用的工具。Orchestrator 的 Gate Function 应该进一步细化为 pattern-indexed 的查找结构，而不是 prose 描述。

### 2. "每个信任层级调整审查强度，但从不跳过步骤"

这是 SlowMist 信任模型中最反直觉也最重要的一句话。通常我们对可信来源会降低审查密度，SlowMist 明确规定不行。

原因：Trusted Source Compromise（维护者账号被攻破）是最难检测的攻击类型之一，正是因为大家信任它。

### 3. Red Team 是文档，不是工具

SlowMist 的 OpenClaw Security Practice Guide 里包含完整的攻防演练手册（Validation Guide），让用户自己对已部署安全策略做模拟攻击测试。这把"安全测试"从安全团队的职责变成了每个 agent 用户的日常操作。

这个范式值得直接引入：Orchestrator 的安全机制（Gate Function、dispatch-gate hook）应该有对应的测试场景描述，让主人可以主动验证防御是否有效。

### 4. 安全和能力的张力不应该被掩盖

SlowMist 在 FAQ 里明确写出来：过度安全会导致 agent 拒绝做任何事。他们设计了"Zero-friction operations"原则——在未命中红线的情况下操作应该无摩擦。

Orchestrator 目前的 Gate Function 设计偏向"只在危险时阻止"，和这个原则一致。但缺乏明确的"正常操作不应该有摩擦"的成文声明，导致每次新情况出现时都要重新判断阈值。
