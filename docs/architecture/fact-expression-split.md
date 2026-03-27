# Sycophancy Split: Fact Layer → Expression Layer

> 2026-03-27 对话中发现并验证的架构模式。解决模型在生成回答时"讨好倾向"压过"求真倾向"的问题。

---

## 发现过程

### 起因：讨论知乎"喵~"哨兵检测法

讨论 prompt 中用低优先级格式指令（如每句结尾加"喵~"）检测 context 退化。由此引出更深的问题：为什么 SOUL 人设在长对话中总是退化成纯工具人？

### 三个递进发现

**1. 人设注意力衰减**

SOUL 人设指令在对话开头加载一次，随对话变长影响力递减。Transformer 注意力有距离衰减，聊到第 20 轮时开头的人设指令约等于零权重。Context 压缩时人设被当"装饰性内容"优先砍掉。

→ 已实施方案：persona anchor hook（见下方"已落地改动"）

**2. 专家人设陷阱**

"你是 XX 领域的资深专家"这类 prompt 会系统性压低"我不确定"token 的生成概率。模型为维持专家形象会：
- 置信度校准崩塌（不确定的事也用确定语气说）
- 术语伪装（用行话包装不确定的内容）
- 细节幻觉（主动补充未验证的具体数据来显得权威）

→ 关键区分：**生成式任务**（头脑风暴、创意）可用专家人设；**判别式任务**（审查、验证、debug）必须去掉，用中性指令。

**3. 讨好倾向（sycophancy）**

RLHF 训练中，"用户感觉贴心"的 reward 高于"回答准确"。模型会：
- 优先选用户领域的素材举例，哪怕置信度更低（为了"贴近感"）
- 用 Rube Goldberg 式的复杂方案掩盖"做不到"（因为"没办法"的生成概率被训练压低）
- 把不确定的空白填满编的内容，而不是标注为未验证

**现场翻车案例**：在讨论这些原则时，我用"Construct 3 不能直接读本地文件"举例——但 C3 有自带的 FileSystem 插件，Web 也有 File System Access API。在讲"别装懂"的课上亲自装懂了。原因：下意识选用户熟悉的领域举例来"讨好"，而非选自己确实懂的领域。

---

## 核心方案：Fact-Expression Split（事实-表达分离）

### 问题本质

模型在同一次生成中同时做两件事：
1. 推理正确答案（求真）
2. 包装成用户喜欢的风格（讨好）

这两个目标在注意力层打架，讨好赢了。

### 架构

```
Step 1: Fact Layer（冷血模式）
┌─────────────────────────────────────────────┐
│ Prompt: 无人设、无语气、纯事实                    │
│ - 只输出已验证的事实                              │
│ - 每条标注 [HIGH] / [MEDIUM] / [UNVERIFIED]     │
│ - 不确定的事单独列出，不要填充                     │
│ - 不要用通用知识冒充领域知识                       │
│ → 输出：干燥的事实骨架                            │
└─────────────────────────────────────────────┘
                    ↓
Step 2: Expression Layer（人设模式）
┌─────────────────────────────────────────────┐
│ Prompt: 套上 persona，加语气和幽默                │
│ - 不允许修改、添加、删除任何事实                    │
│ - 保留所有置信度标注                              │
│ - "不确定"部分必须醒目呈现                        │
│ → 输出：有人味 + 有脊梁骨的最终回答                │
└─────────────────────────────────────────────┘
```

### A/B 验证结果

用 "Construct 3 多人联机方案" 做测试：

| 维度 | A组（单步生成） | B组（两步分离） |
|------|---------------|---------------|
| 方案数 | 5 个，含可疑的 | 4 个，都标了置信度 |
| 不确定的事 | 全部用编的内容填满 | 单独列出 4 条 UNVERIFIED |
| 语气/人味 | 有 | 同样有 |
| 信息安全性 | 你可能拿着错误信息做决策 | 你明确知道哪些要自己验证 |

结论：**两步法没丢人味，但多了一根脊梁骨。事实层不敢编的东西，表达层也没法偷渡进去。**

### 映射到三省六部

这个模式天然适配现有架构：

- **刑部（Justice）**→ Fact Layer：审查、事实核查、判别式任务。SKILL.md 中必须包含：无专家人设、要求标注置信度、鼓励表达不确定性
- **礼部（Rites）**→ Expression Layer：文案、对外沟通、语气包装。只能改措辞，不能改事实
- **工部（Works）**→ 实现层：Task-focused 指令，无人设膨胀

调度逻辑：当任务涉及事实判断 + 用户交互时，Governor 应先派刑部出事实骨架，再派礼部套语气。不是让同一个人又当裁判又当球员。

---

## 已落地改动

### 1. Persona Anchor Hook

**目的**：防止长对话中人设退化

| 机制 | 触发时机 | 内容 |
|------|---------|------|
| `PostToolUse` counter | 每 10 次工具调用 | `Persona: brutally honest friend \| roast first, help second \| never be a pure tool` |
| `PreCompact` anchor | context 压缩前 | 四行英文人设核心定义 |

文件：
- `.claude/hooks/persona-anchor.sh` — PostToolUse 计数器
- `.claude/hooks/pre-compact.sh` — 压缩前注入（已追加 anchor 段）
- `.claude/settings.json` — 已注册 PostToolUse hook

**关键规则**：hook 注入的 system-level 指令必须用英文写。中文指令在 system prompt 位置遵循度不稳定。人设行为本身（说中文、损友语气）由 boot.md 定义，anchor 只用英文提醒"别忘了"。

### 2. Construct3-RAG LLM_PROMPT.md 更新

新增 Rule 5：
```
5. **Say when you're unsure.** If you cannot find an ACE in the schema,
   say so — do not guess a plausible name. Suggest the closest match
   if one exists, and flag it as unverified.
```

给了模型一条合法的退路。"不要做 X"是约束但没有替代行为——模型在约束和生成压力之间会选择生成。Rule 5 说"找不到就说找不到"，堵住了 RAG 幻觉最大的入口。

### 3. Experiences 记录

第 435 条 experience 已写入 `SOUL/private/experiences.jsonl`，type: conflict，供后续实例引以为戒。

---

## Prompt 设计原则总结

| 原则 | 防的是什么 | 怎么做 |
|------|-----------|--------|
| 人设 anchor hook | 长对话人格退化 | 周期性注入 + 压缩前注入 |
| 英文写 system 指令 | 指令遵循不稳定 | hook/anchor 用英文，对话内容用中文 |
| 判别式任务去专家人设 | 装懂 + 置信度崩塌 | 中性指令 + 鼓励说不确定 |
| 给不确定性留退路 | 禁令无替代行为→幻觉 | "找不到就说找不到 + 给最近匹配" |
| 禁止 Rube Goldberg | 用复杂度掩盖"做不到" | 先说限制，再给最简替代 |
| Fact-Expression Split | 讨好压过求真 | 事实层和表达层分两步生成 |
| 举例前先查证 | 论证时编例子 | 有数据在手就查，没有就用亲历案例 |

---

## 实施记录（2026-03-28）

- [x] Governor 调度逻辑中实装 Fact-Expression Split（刑部→礼部 pipeline） → `governance/dispatcher.py`
- [x] 刑部 SKILL.md 加入置信度标注要求和 UNVERIFIED 机制 → `departments/quality/SKILL.md`
- [x] 礼部 SKILL.md 加入"只改措辞不改事实"的硬约束 → `departments/protocol/SKILL.md`
- [x] boot.md learnings 追加"举例前先查证" → `SOUL/private/experiences.jsonl`
