# Headroom 偷师报告

**仓库**: https://github.com/chopratejas/headroom
**作者**: [@chopratejas](https://github.com/chopratejas) (Tejas Chopra)
**定位**: AI Agent 上下文压缩中间层——减少 50-90% token 消耗不掉准确率
**技术栈**: Python (tree-sitter + tiktoken + Magika + sentence-transformers) + FastAPI proxy + TypeScript SDK
**日期**: 2026-04-01

---

## 项目概述

Headroom 是一个 token 优化层，夹在 Agent 和 LLM Provider 之间。核心洞察：**每次 tool call、DB 查询、文件读取、RAG 检索返回的内容 70-95% 是样板垃圾**。Headroom 在请求到达 LLM 前把这些垃圾干掉。

实测数据：
- 代码搜索（100 结果）：92% token 缩减
- SRE 事故调试：92% 缩减
- GitHub issue 分流：73% 缩减
- GSM8K benchmark：保持 87% 准确率；TruthfulQA：53% → 56%（压缩后反而提升）

### 核心架构

```
Agent/Application → Headroom Pipeline → LLM Provider
                         │
         ┌───────────────┼───────────────┐
         │               │               │
   ContentRouter   CacheAligner   ContextManager
    (分类路由)     (前缀稳定)     (语义评分+丢弃)
         │
    ┌────┴────┬────────┬──────────┬──────────┐
    │         │        │          │          │
 SmartCrusher CodeAware  LogComp  SearchComp  KompressComp
  (JSON统计)  (AST感知) (日志提取) (搜索格式)  (ML文本压缩)
```

### 部署模式（6 种）

| 模式 | 改动量 | 适用场景 |
|------|--------|---------|
| Proxy Server | 零代码，改环境变量 | 任何语言/框架 |
| Python SDK | `compress()` 函数调用 | Python 项目 |
| TypeScript SDK | Node.js 集成 | TS/JS 项目 |
| Framework 集成 | LangChain/LiteLLM/Agno/Strands 钩子 | 框架用户 |
| ASGI Middleware | 现有 FastAPI 服务 | Python Web |
| MCP Tools | Claude Code / Cursor | AI 编辑器 |

---

## 可偷模式清单

### 1. ContentRouter — 内容类型感知路由（Content-Aware Compression Router）

**优先级**: P0

**描述**: 不同类型的内容需要完全不同的压缩策略。Headroom 用 Magika（Google 的 ML 分类器，5ms 延迟，100+ 类型）做第一遍检测，fallback 到正则匹配，然后把内容路由到专用压缩器：

| 内容类型 | 路由目标 | 压缩策略 |
|----------|---------|---------|
| 源代码 | CodeAwareCompressor | AST 保留签名+类型，折叠函数体 |
| JSON 数组 | SmartCrusher | 统计分析，保留异常值 |
| 构建/测试日志 | LogCompressor | 只提取 error/warning |
| 搜索结果 | SearchCompressor | 格式化输出，去重 |
| 纯文本 | KompressCompressor | ML 压缩（33万输出训练） |
| HTML | HTMLExtractor | 内容提取，去标签 |
| Git Diff | DiffCompressor | Diff 专用 |

**关键创新 — 混合内容处理**：当一个消息块包含多种类型时（比如 Markdown 里嵌着代码块和 JSON），ContentRouter 先切分成类型片段，分别路由压缩，再重组。

**代码证据**:

```python
# 检测管线：ML → 正则 → 混合切分
class ContentRouter:
    def route(self, content: str) -> CompressedResult:
        # 1. Magika ML 检测（5ms）
        content_type = self.magika.detect(content)
        # 2. 正则 fallback
        if content_type == UNKNOWN:
            content_type = self.regex_detect(content)
        # 3. 混合内容 → 切分+分别路由
        if self.is_mixed(content):
            sections = self.split_typed_sections(content)
            return self.compress_and_reassemble(sections)
        # 4. 路由到专用压缩器
        return self.compressors[content_type].compress(content)
```

**偷法**: Orchestrator 的 compaction 目前是一刀切——所有内容用同一个 9 段模板压缩。但 tool call 返回的 JSON、代码片段、日志、纯文本需要完全不同的处理。可以在 compact hook 里加一层内容分类路由：

```
compact 前 → 检测每段内容类型 → 分别用最合适的策略压缩 → 重组
```

特别是 agent 执行日志（大量重复模式）和 tool call 返回的 JSON（70%+ 样板字段），分类压缩比统一模板有效得多。

---

### 2. SmartCrusher — 统计驱动的 JSON 智能压缩（Statistical JSON Compression）

**优先级**: P0

**描述**: 传统 JSON 压缩靠字段名匹配（硬编码删 "id"、"timestamp" 等），SmartCrusher 靠统计分析——不看字段名，看数据特征：

**多信号检测**：
| 信号 | 检测方式 | 决策 |
|------|---------|------|
| ID 字段 | 唯一性 >0.95 + UUID/顺序模式 | 可采样 |
| 评分字段 | 有界范围 (0-1, 0-100) + 降序排列 | Top-N 保留 |
| 时间字段 | ISO 8601 / Unix timestamp 范围 | 变化点检测 |
| 错误项 | 关键词 'error'/'exception'/'failed'/'critical' | **永远保留** |
| 结构异常 | 罕见字段、异常状态 | **永远保留** |
| 数值异常 | >2σ 偏差 | **永远保留** |

**可压缩性框架**：

```
低唯一性 (<0.3)         → 安全采样
高唯一性 (>0.8) + ID + 无信号 → 不压缩
高唯一性 + 有信号       → 按信号策略压缩
中等唯一性 + 无信号     → 保守处理
```

**4 种压缩策略**：
- `TIME_SERIES`: 方差变化点检测（只保留转折点）
- `CLUSTER_SAMPLE`: 相似项去重
- `TOP_N`: 排名选择（搜索结果模式）
- `SMART_SAMPLE`: 自适应统计采样

**安全保证**：所有错误项、结构异常、数值异常永远不压缩——这是硬规则不是启发式。

**偷法**: 我们的 Governor 执行结果经常包含大量 JSON（API 响应、数据库查询结果、采集器输出）。现在直接塞进 context，或者被 compaction 粗暴截断。可以在结果进入 context 前套一层 SmartCrusher 逻辑：

1. 分析 JSON 数组的字段唯一性分布
2. 用统计信号（而不是字段名）决定保留策略
3. 永远保留错误项和异常值——这些是 agent 最需要看到的

---

### 3. CacheAligner — 前缀稳定化利用 Provider 缓存折扣（Prefix Stabilization for Cache Economics）

**优先级**: P0

**描述**: Claude 的 prompt caching 给 90% 的读取折扣——但前提是前缀完全匹配。动态内容（UUID、时间戳、trace ID）每次请求都变，导致缓存命中率暴跌。CacheAligner 专门解决这个问题：

**两阶段处理**：

1. **DynamicContentDetector**（33KB 实现）：
   - 15+ 模式类型：UUID、API key、JWT token、Unix 时间戳、request/trace ID、日期时间格式
   - 提取并单独存储这些动态部分

2. **Normalization**：
   - 动态内容 → 占位符（存储映射关系）
   - 统一空白字符（行尾、多余空行）
   - 只对静态内容做 hash

**核心洞察**: 同样的指令 + 不同的 UUID/时间戳 → 归一化后 hash 相同 → 命中 90% 读取折扣。

**代码证据**:

```python
class CacheAligner:
    def align(self, messages):
        for msg in messages:
            # 1. 检测并提取动态内容
            dynamics = self.detector.extract(msg.content)
            # 2. 替换为稳定占位符
            stable = self.normalize(msg.content, dynamics)
            # 3. hash 稳定后的内容
            msg.cache_key = hash(stable)
            # 4. 动态内容单独存储，模型仍可访问
            msg.metadata['dynamics'] = dynamics
```

**偷法**: 我们目前每次 Agent SDK 调用都从头算 token，没有利用 Anthropic 的 prompt caching。Orchestrator 的系统 prompt（boot.md + context packs）在一个 session 内基本不变，但每次 tool call 返回带时间戳、ID 的内容会破坏前缀匹配。可以：

1. 在 Agent SDK 调用前加 CacheAligner 层
2. 系统 prompt + 静态上下文 → 标记为 cacheable
3. Tool call 返回的动态内容 → 提取变量部分，稳定化前缀
4. 预估每月能省 30-50% 的 API 成本（系统 prompt 占比大时更明显）

---

### 4. CodeAwareCompressor — AST 感知的代码压缩（AST-Preserving Code Compression）

**优先级**: P1

**描述**: 用 tree-sitter 做跨 8 种语言（Python/JS/TS/Go/Rust/Java/C/C++）的 AST 级代码压缩。不是简单截断——保留签名、类型、装饰器，智能折叠函数体。

**符号重要性评分**（归一化到 0.0-1.0）：

| 因子 | 权重 | 含义 |
|------|------|------|
| 引用计数 | 高 | 被调用越多越重要 |
| Fan-out | 中 | 调用越多外部函数越是核心 |
| 命名约定 | 中 | Python `__dunder__`、Go 大写导出 |
| 上下文匹配 | 高 | 与用户查询的相关度 |

**压缩输出示例**:

```python
def process_data(items: List[str]) -> List[str]:
    """Process a list of items."""
    # [10 lines omitted; calls: validate_item, process_item]
    pass
```

**安全规则**：
- 永远保留：imports、签名、类型注解、装饰器
- 选择性压缩：函数体、注释
- 绝不破坏语法（检查 AST 的 ERROR/MISSING 节点）

**偷法**: 当 Orchestrator agent 读取代码文件（比如偷师时扫源码），原文可能几百行但 agent 只需要结构和关键函数。可以在 file read 结果进入 context 前做 AST 压缩——保留接口定义，折叠实现细节。对我们的偷师 agent 特别有价值：读 100 个文件的结构比读 10 个文件的全文更有信息密度。

---

### 5. CCR — 压缩-缓存-检索的可逆压缩（Compress-Cache-Retrieve）

**优先级**: P0

**描述**: 最精妙的设计。压缩不是永久丢弃——是"先藏起来，需要时再取"：

1. **Compress**: 大内容 → 压缩摘要
2. **Cache**: 原文存入线程安全存储（TTL 自动过期）
3. **Retrieve**: 注入检索标记，告诉模型怎么取回完整数据

```
<headroom:dropped_context size="87 items" status_summary="87 passed, 2 failed, 1 error">
  To see full details, call headroom_retrieve(context_id="abc123")
</headroom:dropped_context>
```

**学习闭环**: 追踪哪些压缩内容被模型主动检索 → 反馈给 TOIN（Tool Output Intelligence Network）→ 改进未来的压缩决策。被频繁检索的内容 → 下次少压缩。从不被检索的内容 → 下次更激进压缩。

**偷法**: 这个模式对 Orchestrator 的 compaction 是范式级升级。现在 compaction 是不可逆的——压缩后细节永远丢失。可以改为：

1. Compaction 时把完整历史存到 events.db 或临时存储
2. 压缩摘要里注入检索标记
3. Agent 需要细节时可以"回忆"完整内容
4. 追踪检索模式 → 优化未来的 compaction 策略

这解决了 compaction 最大的痛点：**你永远不知道模型什么时候需要被压缩掉的细节**。CCR 说：那就别猜，让模型自己决定。

---

### 6. TOIN — 工具输出智能网络（Tool Output Intelligence Network）

**优先级**: P1

**描述**: 跨用户、跨会话的压缩学习系统：

**学习维度**：
| 维度 | 内容 | 应用 |
|------|------|------|
| 字段语义 | 哪些字段真正重要 | SmartCrusher 压缩决策 |
| 检索模式 | 什么内容会被请求回来 | CCR 压缩力度 |
| 压缩效果 | 哪些摘要有效 | 未来摘要质量 |
| 错误指标 | 失败模式特征 | 错误保留策略 |

**反馈回路**:

```
Tool 输出 → 压缩 → 模型使用 → 检索/不检索
                                    ↓
                              TOIN 记录
                                    ↓
                         下次压缩决策更精准
```

**偷法**: 我们的三省六部已经有经验积累（learnings.md），但没有量化的压缩效果反馈。可以在 Governor 执行后追踪：

1. 哪些 context 内容 agent 真正用到了（通过分析输出引用）
2. 哪些内容从未被引用（浪费的 token）
3. 用这个数据训练 compaction 策略——不是靠规则，靠数据

---

### 7. IntelligentContextManager — 六因子语义评分丢弃（Multi-Factor Semantic Scoring）

**优先级**: P1

**描述**: 超越位置顺序的上下文管理。每条消息用 6 个加权因子评分：

| 因子 | 权重 | 计算方式 |
|------|------|---------|
| 时效性 | 高 | 指数衰减 e^(-λ × position) |
| 语义相似度 | 高 | 与最近 3 条消息的 embedding 余弦相似度 |
| TOIN 重要性 | 中 | 跨用户学习的检索模式 |
| 错误检测 | 高 | TOIN 字段语义（不是关键词） |
| 前向引用 | 中 | 被后续消息引用的次数 |
| Token 密度 | 低 | 信息浓度（unique/total tokens） |

**三档丢弃策略**：
- 超 <10% → `COMPRESS_FIRST`（先压缩再说）
- 超 <25% → `SUMMARIZE`（生成锚定摘要）
- 超 >25% → `DROP_BY_SCORE`（按评分丢弃最低的）

**保护规则**：
- 系统消息、最近 N 轮：永远保护
- Tool call/response 对：原子操作，不拆分
- 已冻结消息（在 provider KV cache 里的）：不动

**偷法**: 我们的 compaction hook 目前是按位置截断的——老消息先删。但一条早期的错误诊断消息可能比最近 5 条 "OK" 确认更重要。可以给每条消息加语义评分，compaction 时按评分而不是位置决定保留什么。

---

### 8. Hook-Based Extensibility — 三钩子扩展点（Pre/Post/Bias Hooks）

**优先级**: P2

**描述**: 不修改核心代码就能定制压缩行为的三个钩子：

```python
class CompressionHooks:
    def pre_compress(self, messages) -> messages      # 压缩前修改
    def compute_biases(self, context) -> {idx: float}  # 注入重要性偏置
    def post_compress(self, metrics) -> None           # 压缩后观测
```

**`compute_biases` 最精妙**: 外部系统可以给特定消息注入重要性偏置（-1.0 到 +1.0），影响但不覆盖内部评分。比如：用户手动标记的消息 → bias +0.8，已知无用的自动回复 → bias -0.5。

**偷法**: 我们的 hook 系统（pre-compact、post-tool 等）已经有事件机制，但没有 bias 注入的概念。可以加一个 `compute_biases` 钩子，让外部规则（比如三省六部的策略）影响 compaction 决策——哪些 context 更值得保留。

---

### 9. Bounded Data Structures — 全链路有界数据结构（Production Memory Management）

**优先级**: P2

**描述**: 整个项目从头到尾用有界数据结构，不存在无限增长的容器：

| 组件 | 数据结构 | 上限 |
|------|---------|------|
| 语义缓存 | `OrderedDict` LRU | maxlen 配置 |
| 成本历史 | `deque` | 100K 条 + 24h 保留 |
| 请求日志 | `deque` | 10K max |
| Session 缓存 | 超 500 session → 淘汰最旧 25% | 500 session |
| CCR 存储 | TTL 自动过期 | 按时间回收 |

**偷法**: Orchestrator 的 events.db 已经在膨胀（15M），部分内存数据结构没有上限。可以系统性排查所有容器，加上 max-size + 淘汰策略。不是性能优化——是生产稳定性保障。

---

### 10. Adaptive Pressure — 压力自适应压缩（Context-Pressure-Driven Compression）

**优先级**: P2

**描述**: 压缩力度不是固定的——随 context 接近 token 上限动态调整：

```
Context 使用率 30%  → 轻度压缩（保留更多细节）
Context 使用率 60%  → 中度压缩
Context 使用率 85%  → 激进压缩（只保留核心）
Context 使用率 95%  → 紧急模式（DROP_BY_SCORE）
```

**偷法**: 我们的 pre-compact hook 在固定时机触发（context 快满时）。可以改为渐进式——context 使用率越高，每次 tool call 返回的结果压缩越激进。这比"满了才压缩"平滑得多，避免突然大量丢失上下文。

---

## 架构级洞察

### 洞察 1: 压缩是分类问题，不是字符串操作

Headroom 最大的创新不是某个具体压缩算法——是**意识到不同内容需要不同策略**这件事。JSON 数组要统计分析，代码要 AST 解析，日志要错误提取，纯文本要 ML 压缩。一刀切的 truncation 或 summarization 是在用一把锤子对付所有钉子。

我们的 compaction 模板用的就是这把锤子。

### 洞察 2: 可逆压缩 > 不可逆压缩

CCR 模式（压缩-缓存-检索）是对"压缩必然有损"假设的挑战。不是所有压缩都需要是永久的——只要原文还在某个地方，压缩就是可逆的。这把压缩从"信息损失"变成"信息分层"：
- 第一层：压缩摘要（always in context）
- 第二层：完整内容（on-demand retrieval）

### 洞察 3: Provider 经济学决定技术架构

CacheAligner 不是技术驱动的——是经济驱动的。Anthropic 给 90% 缓存读取折扣，所以值得花工程量来稳定前缀。如果折扣变了，策略也该变。这提醒我们：**最优架构不止看技术约束，还要看定价模型**。

### 洞察 4: 学习闭环比算法重要

TOIN 不是最聪明的算法——但它能学习。一个能从使用数据中改进的笨算法，长期比一个固定的聪明算法强。我们的三省六部有经验积累的框架，但 compaction/context 管理没有——这是一个结构性缺口。

---

## 实施优先级

| 编号 | 模式 | 优先级 | 预估工作量 | 依赖 |
|------|------|--------|-----------|------|
| 1 | ContentRouter 内容分类路由 | P0 | 2-3 天 | 无 |
| 2 | SmartCrusher JSON 统计压缩 | P0 | 3-4 天 | #1 |
| 3 | CacheAligner 前缀稳定化 | P0 | 2 天 | Agent SDK 调用层 |
| 5 | CCR 可逆压缩 | P0 | 3-4 天 | events.db |
| 4 | CodeAwareCompressor AST 压缩 | P1 | 2-3 天 | tree-sitter |
| 6 | TOIN 学习网络 | P1 | 4-5 天 | #5 |
| 7 | IntelligentContextManager 语义评分 | P1 | 3 天 | embedding 模型 |
| 8 | Hook-Based Bias 注入 | P2 | 1 天 | hook 系统 |
| 9 | Bounded Data Structures | P2 | 1 天 | 无 |
| 10 | Adaptive Pressure | P2 | 1 天 | compaction hook |

**Phase 1**（立即可做）: #1 + #3 + #9 + #10 — 内容分类 + 缓存优化 + 防御加固
**Phase 2**（需要基础设施）: #2 + #5 — JSON 压缩 + 可逆压缩
**Phase 3**（长期投资）: #4 + #6 + #7 + #8 — AST 压缩 + 学习闭环 + 语义管理

---

## 与现有偷师的交叉引用

| 已有模式 | Headroom 对应 | 增量价值 |
|---------|-------------|---------|
| Round 28b 九段压缩 | ContentRouter + SmartCrusher | 从"模板压缩"升级到"分类感知压缩" |
| Round 28e hindsight 记忆 | TOIN 学习网络 | 从"存储"升级到"学习哪些值得存储" |
| Round 30 yoyo-evolve Checkpoint | CCR 可逆压缩 | 从"检查点回退"升级到"按需检索" |
| Round 28a Gate Chain | Adaptive Pressure | 从"固定门控"升级到"压力自适应" |
| Round 22 Review Swarm 过滤协议 | SmartCrusher 安全保证 | 从"过滤输出"升级到"统计驱动的保留策略" |

---

## 总结

Headroom 是一个**被严重低估的项目**。表面是 token 压缩工具，底层是一套完整的**信息分层与智能路由系统**。

对 Orchestrator 最有价值的 3 个偷法：

1. **CCR 可逆压缩** — 解决 compaction 最大痛点（不可逆信息损失）
2. **ContentRouter 分类路由** — 让 compaction 从一刀切变成精准手术
3. **CacheAligner 前缀稳定化** — 直接省钱，每月 API 成本预估降 30-50%

10 个模式，4 个 P0，3 个 P1，3 个 P2。其中 P0 的 CacheAligner 和 Adaptive Pressure 几乎可以立即实施，不需要额外依赖。
