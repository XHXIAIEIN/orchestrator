# Round 23：stock-analysis @udiedrichsen（ClawHub 偷师）

**日期**: 2026-03-31
**来源**: https://clawhub.ai/udiedrichsen/stock-analysis
**版本**: 6.2.0 | Stars: 193 | Installs: 456
**源码**: 未公开（无 GitHub 仓库），分析基于 ClawHub 页面元数据 + 脚本文件清单

---

## 概述

Claude Code 股票/加密货币分析技能，核心卖点是 **8 维加权评分系统** + **多脚本分工架构**（analyze / dividend / watchlist / portfolio / hot_scanner / rumor_scanner）。数据源覆盖 Yahoo Finance、CoinGecko、Google News、SEC EDGAR。

## 核心机制

### 8 维股票评分体系

| 维度 | 权重 | 数据源 | 量化指标 |
|------|------|--------|----------|
| Earnings Surprise | 30% | Yahoo Finance | EPS beat/miss 幅度 |
| Fundamentals | 20% | Yahoo Finance | P/E, margins, revenue growth |
| Analyst Sentiment | 20% | Yahoo Finance | 评级分布, target price vs current |
| Momentum | 15% | Yahoo Finance | RSI, 52-week range position |
| Sector | 15% | Yahoo Finance | 相对板块强度 |
| Historical | 10% | Yahoo Finance | 历史财报反应模式 |
| Market Context | 10% | Yahoo Finance | VIX, SPY/QQQ 趋势 |
| Sentiment | 10% | 多源 | Fear/Greed Index, short interest, insider trades |

**注意**: 权重总和 = 130%，说明不是简单加权平均，可能是归一化后的相对权重，或者某些维度有重叠计算。

**加密货币简化版**: 3 维 — Market Cap/Category, BTC Correlation (30d), Momentum (RSI/range)

### 多脚本分工架构

| 脚本 | 大小 | 职责 |
|------|------|------|
| `analyze_stock.py` | 88 KB | 主分析引擎，8维评分 |
| `hot_scanner.py` | 24 KB | 病毒式趋势检测 |
| `portfolio.py` | 18 KB | 组合管理 CRUD |
| `dividends.py` | 13 KB | 股息分析 |
| `watchlist.py` | 11 KB | 监控列表 + 告警 |
| `rumor_scanner.py` | 11 KB | M&A / 内幕活动信号 |

### 数据持久化

```
~/.clawdbot/skills/stock-analysis/
├── portfolios.json    # 组合数据
└── watchlist.json     # 监控列表 + 告警阈值
```

### 告警三类型

- **Target Hit**: price >= target
- **Stop Hit**: price <= stop
- **Signal Change**: BUY/HOLD/SELL 状态跃迁

---

## 可偷模式

### P0 — 高价值，直接适配

#### 1. Multi-Dimension Weighted Scoring（多维加权评分框架）

**描述**: 将复杂评估拆解为 N 个独立维度，每个维度有明确的数据源、量化指标和权重，最终聚合为单一分数。

**为什么值得偷**: Orchestrator 当前的 Clawvard 考试评分、agent 绩效评估、偷师模式优先级排序都是拍脑袋的。一个结构化的多维评分框架可以统一所有评估场景。

**如何适配 Orchestrator**:
- **Agent 绩效评分**: 8维 → 定义 agent 表现维度（任务完成率 30% / 代码质量 20% / 响应速度 15% / 上下文利用率 15% / 自主性 10% / 错误恢复 10%）
- **偷师价值评分**: 对新发现的项目做 P0/P1/P2 分级时，用维度评分替代直觉判断（新颖性 / 可实施性 / 与现有架构契合度 / 预期 ROI）
- **实现**: `SOUL/evaluation/scoring.py` — 通用 `DimensionScorer` 类，接受维度定义 dict，输出加权总分 + 各维度明细

#### 2. Scanner-as-Separate-Script（扫描器独立脚本模式）

**描述**: 每种数据采集/分析逻辑独立为一个脚本文件，通过 CLI 接口互不耦合，由上层 skill 编排调用。

**为什么值得偷**: Orchestrator 的数据采集目前全塞在 collector 里。stock-analysis 用 6 个独立脚本覆盖 6 种分析场景，每个脚本可以独立开发、测试、替换。

**如何适配 Orchestrator**:
- QQ 音乐采集器、Telegram 消息采集、GitHub 活动采集 → 各自独立脚本
- 统一 CLI 接口：`python scripts/collect_<source>.py [--fast] [--json] [--notify]`
- 编排层只关心脚本入口和输出格式，不关心内部实现

#### 3. Threshold-Alert State Machine（阈值告警状态机）

**描述**: 监控列表的三种告警类型（Target Hit / Stop Hit / Signal Change）本质是一个状态机——每个 watchlist item 有当前状态，价格变动触发状态跃迁。

**为什么值得偷**: Orchestrator 需要监控多种信号（容器健康、agent 性能退化、数据新鲜度），目前都是 ad-hoc 检查。统一的阈值告警状态机可以覆盖所有监控场景。

**如何适配 Orchestrator**:
- 定义通用 `WatchItem`：`{target, metric_fn, thresholds: {warn, critical}, state: NORMAL|WARN|CRITICAL, last_check}`
- 状态跃迁触发 hook（Telegram 通知 / 自动修复 / 日志记录）
- 复用现有 Telegram bot 作为通知通道

### P1 — 有价值，需要适配

#### 4. Domain-Specific Dimension Reduction（领域特化维度压缩）

**描述**: 股票用 8 维，加密货币只用 3 维。不是简单砍维度，而是根据领域特性选择最有区分度的维度子集。

**为什么值得偷**: 不同类型的 agent 任务（代码生成 vs 信息检索 vs 创意写作）需要不同的评估维度组合。一刀切的评分不如按领域特化。

**适配**: 在 DimensionScorer 中支持 `profile` 参数，不同任务类型加载不同的维度配置。

#### 5. Fast-Mode Flag（快速模式跳过昂贵维度）

**描述**: `--fast` flag 跳过 insider/news 等耗时数据源，只算核心维度。权衡速度和精度。

**为什么值得偷**: Orchestrator 在高频场景（实时监控、批量评估）中需要快速模式。

**适配**: 评分器支持 `fast=True`，跳过需要外部 API 调用的维度，用缓存或默认值填充。

#### 6. Rumor Scanner Pattern（弱信号早期检测）

**描述**: 独立的 rumor_scanner 专门检测 M&A、内幕交易等弱信号，与主分析流程解耦。

**为什么值得偷**: Orchestrator 缺乏"弱信号检测"能力——比如某个 GitHub 项目突然活跃、某个技术栈的讨论量异常上升。

**适配**: 独立的 `signal_scanner.py`，定期扫描 GitHub trending / HN / Twitter，检测与 Orchestrator 关注领域相关的异常信号。

### P2 — 有启发，低优先级

#### 7. Dividend Safety Score（复合安全评分）

**描述**: 股息安全评分（0-100）综合 payout ratio / 5年 CAGR / 连续增长年数，给出分类标签。

**启发**: 任何需要"这个东西靠不靠谱"判断的场景都可以用类似的复合安全评分——比如评估一个新 MCP server 的可靠性。

#### 8. Hot Scanner（趋势检测）

**描述**: 独立脚本检测"病毒式"趋势，数据源包括 CoinGecko trending / Google News。

**启发**: 偷师任务的目标发现可以自动化——定期扫描 ClawHub / GitHub trending / ProductHunt，自动生成候选偷师列表。

---

## 8 维评分体系深度分析

### 设计优点

1. **权重反映信息价值**: Earnings Surprise 30% 最高——因为这是最难预测、最有 alpha 的维度。Fundamentals 和 Analyst Sentiment 各 20%，这两个最稳定但也最公开（priced in）。
2. **维度独立性**: 每个维度有独立数据源和计算逻辑，不会互相污染。
3. **加密货币的维度压缩合理**: 加密没有 earnings/dividends/analysts，压缩到 3 维是正确的。

### 设计疑点

1. **权重总和 130%**: 不是标准归一化，可能有 bug 或者刻意的 over-weighting。
2. **没有置信度**: 某些维度数据缺失时（比如新 IPO 没有 Historical），分数怎么处理？缺乏 fallback 策略的说明。
3. **静态权重**: 不同市场环境（牛市/熊市/震荡市）可能需要动态调整权重，但看不到这种机制。

---

## 数据采集策略分析

### API 调用模式

- **主数据源**: Yahoo Finance（免费，无需 API key，通过 yfinance 库）
- **辅助源**: CoinGecko（trending）、Google News（sentiment）、SEC EDGAR（insider）
- **可选源**: Twitter/X（需 `bird` CLI + cookie 提取 — 安全红旗）

### 推测的缓存策略

基于脚本大小和 `--fast` flag 的存在，推测：
- 88KB 的 analyze_stock.py 大概率包含本地缓存逻辑
- `--fast` 跳过的不是计算而是 I/O（网络请求）
- 数据持久化在 `~/.clawdbot/` 下，可能有 TTL 缓存

### 对 Orchestrator 数据采集的参考价值

1. **yfinance 模式可复制**: 免费、无 key、Python 原生，适合 Orchestrator 的数据采集层
2. **多源聚合但主次分明**: Yahoo Finance 是主干，其他是补充——不要试图平等对待所有数据源
3. **`--fast` 模式必须有**: 任何采集脚本都应该支持跳过非核心数据源的快速模式

---

## 安全观察

此技能被 VirusTotal 和 OpenClaw 标记为可疑：
- 要求提取浏览器 cookie（AUTH_TOKEN, CT0）
- 请求 macOS Terminal Full Disk Access
- 未声明的环境变量
- uv 二进制依赖来源不明

**偷师结论**: 偷模式，不偷实现。安全红旗说明即使在 ClawHub 生态中，skill 的安全审计也是必要的——这反过来验证了 Orchestrator 的 guard.sh 拦截机制的价值。

---

## 总结

| 优先级 | 模式 | 适配场景 |
|--------|------|----------|
| P0 | Multi-Dimension Weighted Scoring | Agent 绩效 / 偷师价值 / 任务评估 |
| P0 | Scanner-as-Separate-Script | 数据采集脚本化 |
| P0 | Threshold-Alert State Machine | 统一监控告警 |
| P1 | Domain-Specific Dimension Reduction | 按任务类型特化评估 |
| P1 | Fast-Mode Flag | 高频场景快速评估 |
| P1 | Rumor Scanner Pattern | 弱信号早期检测 |
| P2 | Dividend Safety Score | 复合可靠性评分 |
| P2 | Hot Scanner | 自动化偷师目标发现 |

**核心收获**: 8 维评分框架是这个技能最值得偷的设计。不是偷具体的 8 个维度（那是金融领域的），而是偷"将复杂评估拆解为加权独立维度"这个元模式。Orchestrator 的 agent 评估、偷师分级、任务优先级排序都可以统一到这个框架下。
