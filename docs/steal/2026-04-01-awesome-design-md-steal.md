# Round 35: VoltAgent/awesome-design-md — 设计系统的 Prompt 编译

> **源**: https://github.com/VoltAgent/awesome-design-md
> **性质**: 30+ 品牌的 DESIGN.md 标准化模板集（Claude/Linear/Vercel/Stripe/Apple 等）
> **核心洞察**: 把视觉设计系统编译成 AI agent 可直接消费的结构化 prompt

---

## 一句话

Google Stitch 提出 DESIGN.md 概念（类比 AGENTS.md 告诉 agent 怎么构建项目，DESIGN.md 告诉 agent 怎么构建 UI），这个仓库是目前最完整的实现。

---

## 仓库结构

```
awesome-design-md/
├── README.md                    # 分类目录表
├── CONTRIBUTING.md              # 质量门控 checklist
└── design-md/
    ├── claude/                  # 每个品牌一个目录
    │   ├── DESIGN.md            # 核心：~1500 行结构化设计规范
    │   ├── README.md            # 品牌简介
    │   ├── preview.html         # 自包含视觉目录（light）
    │   └── preview-dark.html    # dark 版
    ├── linear.app/
    ├── vercel/
    ├── stripe/
    └── ... (31 个品牌)
```

---

## P0 模式（可直接偷）

### 1. 九段式文档骨架（Canonical Section Order）

每个 DESIGN.md 严格遵循 9 个 section，顺序固定：

```markdown
## 1. Visual Theme & Atmosphere    # 散文体大气氛（隐喻化，不是 "clean and modern"）
## 2. Color Palette & Roles        # 语义名(hex): 功能角色 + 设计意图
## 3. Typography Rules             # 完整层级表（必含 letter-spacing）
## 4. Component Stylings           # 按钮/卡片/输入（含 hover/focus 状态 + transition timing）
## 5. Layout Principles            # 间距比例 + grid + 留白哲学
## 6. Depth & Elevation            # 阴影层级表（Level 0-5，带语义名）
## 7. Do's and Don'ts              # 每条带具体数值，不模糊
## 8. Responsive Behavior          # 断点 + 触摸目标 + 折叠策略
## 9. Agent Prompt Guide           # 快速色彩查阅 + 即用提示词模板
```

**偷法**: 我们的 CLAUDE.md / boot.md 缺少类似的固定 section 骨架。Agent 读取文档时，固定顺序 = 可预期的信息位置 = 更快的检索。

**迁移目标**: boot.md 编译器可以强制输出 section 顺序。

---

### 2. 散文体大气氛描述（Prose Atmosphere）

每个设计系统的开篇不是列表，是**隐喻化散文**：

| 品牌 | 大气氛描述 |
|------|-----------|
| Claude | "a literary salon reimagined as a product page — warm, unhurried, quietly intellectual" |
| Linear | "content emerges from darkness like starlight" |
| Vercel | "minimalism as engineering principle. Geist treats the interface like a compiler treats code" |
| Stripe | "simultaneously technical and luxurious, precise and warm" |
| VoltAgent | "a deep-space command terminal for the AI age" |

**质量门控**: "clean and modern" 这类通用描述直接 BANNED。

**偷法**: SOUL 身份描述、persona 描述用散文隐喻替代列表。一个好的 atmosphere 描述应该能让 agent 在没读任何具体规则前就建立整体画像。

---

### 3. 颜色三元组标注（Color Triple Annotation）

```markdown
- **Anthropic Near Black** (`#141413`): Primary text — not pure black but warm,
  olive-tinted dark that's gentler on the eyes.
```

格式：`语义名 (hex): 功能角色 + 为什么选它`

不只标注"什么颜色"，还要说"为什么是这个颜色"。

**偷法**: 任何配置项都可以用三元组标注：`名称 (值): 功能 + 原因`。我们的 CLAUDE.md 规则可以加 "Why" 行（部分已有，但不一致）。

---

### 4. 命名你的架构决策（Named Design Decisions）

每个系统给核心技术选择起名字：

| 品牌 | 命名 | 含义 |
|------|------|------|
| Vercel | "shadow-as-border philosophy" | 用 box-shadow 模拟 border |
| Linear | "luminance stacking model" | 用背景透明度表达层级 |
| Claude | "ring-based shadow system" | ring shadow 替代 drop shadow |
| Stripe | "blue-tinted shadow" | `rgba(50,50,93,0.25)` 带品牌色阴影 |
| Cursor | "oklab-space borders" | 感知均匀颜色空间边框 |

**偷法**: 给 Orchestrator 的架构模式起名字。当 agent 有一个概念锚点时，不需要每次描述完整机制。
- "三省六部" ✅ 已有
- boot.md 编译流 → 可以叫 "Soul Compiler"
- 偷师流程 → 可以叫 "Pattern Extraction Pipeline"

---

### 5. Section 9: Agent 即用提示词（Agent Prompt Guide）

每个 DESIGN.md 最后一节直接"编译"成可复制的 prompt 片段：

```markdown
## 9. Agent Prompt Guide

### Quick Color Reference
- Brand CTA: "Terracotta Brand (#c96442)"

### Example Component Prompts
- "Create a hero section on Parchment (#f5f4ed) with headline at 64px
   Anthropic Serif weight 500, line-height 1.10. Add Terracotta CTA."

### Iteration Guide
1. Reference specific color names — "use Olive Gray (#5e5d59)" not "make it gray"
2. Always specify warm-toned variants — no cool grays
```

**偷法**: CLAUDE.md 或 boot.md 加 "Quick Reference" 块，把最常用的命令、路径、格式列为可直接使用的片段，降低 agent 的检索成本。

---

### 6. 精确化 Do's/Don'ts（Quantified Guardrails）

不写模糊的禁忌，每条带具体值：

```markdown
### Don't
- Don't use cool blue-grays — palette is exclusively warm-toned
- Don't use bold (700+) on Anthropic Serif — weight 500 is ceiling
- Don't use pure white (#ffffff) as background — Parchment (#f5f4ed) always warmer
- Don't reduce body line-height below 1.40
```

**对比我们现有的**:
- 我们: "match existing style" ← 模糊
- 他们: "don't use weight 700+ on this font" ← 精确

**偷法**: CLAUDE.md 的 Do's/Don'ts 需要一轮精确化 pass。

---

### 7. 自包含 Preview HTML（Self-Contained Visual Catalog）

preview.html 是完全自包含的单页（inline CSS，仅引 Google Fonts），展示：
- 颜色色板 + 字体比例 + 按钮变体 + 卡片样例 + 表单元素 + 间距比例 + 圆角系统 + 阴影层级

质量要求：
- 无 logo 或 emoji 图标（nav 纯文字）
- 无 Do's/Don'ts 文字（只展示渲染效果）
- 必须移动端可用

**偷法**: Dashboard DESIGN.md + preview.html，作为前端改动的设计锚点。

---

## P1 模式（有价值但非紧急）

### 8. CONTRIBUTING.md 的质量门控

不是简单的"如何提 PR"，而是详细的文档质量标准：

```markdown
### Common Issues to Watch For
- Hex values that don't match live site
- Missing hover/focus states
- Generic atmosphere descriptions (BANNED)
- Incomplete typography tables

### Writing Standards
- Atmosphere: Evocative and specific, never "clean and modern"
- Components: Include hover/focus states AND transition timing
- Why, not just what
```

**偷法**: 偷师报告、文档本身也可以有类似的质量 checklist。

### 9. 品牌视觉签名一句话鉴别

| 品牌 | 视觉签名 |
|------|----------|
| Claude | 羊皮纸底 `#f5f4ed` + 赤陶 CTA `#c96442` + 衬线 headline + ring shadow |
| Linear | 近黑底 + Inter 510 weight + 负 tracking + 半透明白 border |
| Vercel | 纯白 + Geist 超压缩字 + shadow-as-border + 三色 accent |
| Stripe | 深海军蓝 heading + sohne weight 300 + 蓝调阴影 |
| Apple | 交替黑/浅灰 section + SF Pro 光学尺寸 + 980px pill CTA |
| Notion | 暖白 + 近黑 `rgba(0,0,0,0.95)` + whisper border |
| Ollama | 纯黑白零色彩零阴影，全 pill 圆角 |

### 10. Typography 隐藏变量：letter-spacing

最被低估的设计变量：
- Vercel: -2.4px 到 -2.88px（最激进压缩）
- Linear: 510 weight（Inter variable 非标准权重 = 专属身份）
- Stripe: weight 300 做 headline（反直觉的轻量权威感）
- VoltAgent: +0.5px overline（少见的正向 tracking）

---

## 迁移地图

| # | 模式 | 迁移目标 | 优先级 | 状态 |
|---|------|---------|--------|------|
| 1 | 九段式骨架 | boot.md compiler / CLAUDE.md section 标准化 | P0 | 待定 |
| 2 | 散文体大气氛 | SOUL identity 描述 | P0 | 待定 |
| 3 | 颜色三元组 | CLAUDE.md 规则加 "Why" 行 | P0 | 部分已有 |
| 4 | 命名架构决策 | Orchestrator 架构概念命名 | P0 | 部分已有 |
| 5 | Agent Prompt Guide | boot.md "Quick Reference" 块 | P0 | 待定 |
| 6 | 精确化 Do's/Don'ts | CLAUDE.md 规则精确化 pass | P0 | 待定 |
| 7 | Self-Contained Preview | Dashboard DESIGN.md + preview.html | P1 | 待定 |
| 8 | 质量门控 CONTRIBUTING | 偷师报告质量 checklist | P1 | 待定 |
| 9 | 一句话鉴别 | - | P2 | 参考 |
| 10 | letter-spacing 技法 | - | P2 | 参考 |

---

## 核心认知

这个仓库的真正价值不在于"收集了 31 个品牌的设计"，而在于**证明了一个命题**：

> 任何领域的专业知识都可以被"编译"成 AI agent 可消费的结构化文档，关键是找到正确的 section 骨架 + 精确化程度。

DESIGN.md 对设计系统做的事，和我们的 CLAUDE.md 对编码规范做的事，本质上是同一件事。差距在于：
1. **固定骨架** — 他们有九段式模板，我们的 CLAUDE.md 是自然增长的
2. **精确化程度** — 他们每条规则带具体值，我们有些还是模糊的
3. **最后一英里** — 他们有 Section 9 把文档"编译"成即用 prompt，我们没有这一步
