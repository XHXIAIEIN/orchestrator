# Firecrawl 深度偷师分析 (98K Stars)

> 仓库: https://github.com/mendableai/firecrawl
> 语言: TypeScript (API/Worker) + Go (HTML-to-Markdown) + Rust (后处理)
> 架构: Monorepo，多进程 harness 编排
> 日期: 2026-03-26

---

## 一、整体架构

```
┌─────────────────────────────────────────────────────────┐
│                    harness.ts                           │
│  (进程编排器 — 启动 API / Worker / NuQ / Extract 等)     │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  API Server ──► Queue (NuQ/BullMQ + Redis + RabbitMQ)   │
│                          │                              │
│              ┌───────────┼───────────┐                  │
│              ▼           ▼           ▼                  │
│         NuQ Worker  Queue Worker  Extract Worker        │
│              │           │           │                  │
│         scrapeURL    deepResearch   extract             │
│              │                                          │
│     ┌────────┼────────┐                                │
│     ▼        ▼        ▼                                │
│  Engine   Engine   Engine                              │
│  (CDP)   (TLS)   (Fetch/Playwright/PDF/Wikipedia)      │
│     │                                                   │
│     ▼                                                   │
│  Transformer Pipeline                                   │
│  (HTML→MD→LLM Extract→Screenshot→Index→...)            │
│     │                                                   │
│     ▼                                                   │
│  Billing → Webhook → Response                          │
└─────────────────────────────────────────────────────────┘
```

### 关键文件路径

| 模块 | 路径 |
|------|------|
| 进程编排 | `apps/api/src/harness.ts` |
| 队列服务 | `apps/api/src/services/queue-service.ts` |
| 队列任务 | `apps/api/src/services/queue-jobs.ts` |
| Worker (BullMQ) | `apps/api/src/services/queue-worker.ts` |
| Worker (NuQ) | `apps/api/src/services/worker/nuq-worker.ts` |
| NuQ 队列 (Postgres+RabbitMQ) | `apps/api/src/services/worker/nuq.ts` |
| Scrape 核心 | `apps/api/src/scraper/scrapeURL/index.ts` |
| 引擎注册 | `apps/api/src/scraper/scrapeURL/engines/index.ts` |
| Transformer 流水线 | `apps/api/src/scraper/scrapeURL/transformers/index.ts` |
| 并发控制 | `apps/api/src/lib/concurrency-limit.ts` |
| Team 信号量 | `apps/api/src/services/worker/team-semaphore.ts` |
| 速率限制 | `apps/api/src/services/rate-limiter.ts` |
| 费用追踪 | `apps/api/src/lib/cost-tracking.ts` |
| 计费逻辑 | `apps/api/src/lib/scrape-billing.ts` |
| 系统监控 | `apps/api/src/services/system-monitor.ts` |
| 重试工具 | `apps/api/src/lib/retry-utils.ts` |
| 分布式锁 | `apps/api/src/services/redlock.ts` |
| HTML→MD | `apps/api/src/lib/html-to-markdown.ts` |
| LLM 提取 | `apps/api/src/scraper/scrapeURL/transformers/llmExtract.ts` |

---

## 二、可偷模式 (按优先级)

### P0 — 立即可偷

#### 1. Engine Waterfall (引擎瀑布流)

**核心思想**: 不是选一个引擎跑到死，而是同时启动多个引擎，谁先返回合格结果谁赢。

```
engines/index.ts — buildFallbackList():
1. 根据 featureFlags 计算每个引擎的 supportScore
2. 按 quality + supportScore 排序
3. 依次启动引擎，用 Promise.race + 超时机制
4. 超时后自动 waterfall 到下一个引擎
5. 中途某个引擎成功 → snipeAbort 取消其他引擎
```

**偷法**: Orchestrator 的 LLM 调用可以用类似模式 — 先发快模型，超时后 waterfall 到大模型。或者浏览器操作：先试轻量方案（fetch），不行再升级到 Playwright/CDP。

```typescript
// Firecrawl 的核心 race 逻辑 (scrapeURL/index.ts:589-625)
result = await Promise.race([
  ...enginePromises.map(x => x.promise),
  // 如果还有后续引擎，设置 waterfall 超时
  ...(remainingEngines.length > 0
    ? [new Promise((_, reject) => {
        setTimeout(() => reject(new WaterfallNextEngineSignal()), waitUntilWaterfall);
      })]
    : []),
  // 全局超时
  new Promise((_, reject) => {
    setTimeout(() => reject(new ScrapeJobTimeoutError()), meta.abort.scrapeTimeout() ?? 300000);
  }),
]);
```

#### 2. Feature Flag 驱动的引擎选择

**核心思想**: 每个引擎声明自己支持哪些 feature，请求带 featureFlags，系统自动匹配最佳引擎。

```typescript
// 每个引擎声明 feature 支持矩阵
engineOptions["fire-engine;chrome-cdp"] = {
  features: {
    actions: true,      // 支持点击/输入等操作
    screenshot: true,   // 支持截图
    pdf: false,         // 不支持 PDF
    stealthProxy: false, // 无隐身代理
    branding: true,     // 支持品牌提取
    // ...
  },
  quality: 50,  // 质量分
};

// featureFlag 有优先级权重
featureFlagOptions = {
  actions: { priority: 20 },
  pdf: { priority: 100 },    // PDF 最高优先
  screenshot: { priority: 10 },
  // ...
};
```

**偷法**: Orchestrator 的工具/模型选择可以用同样模式 — 每个工具声明能力矩阵，任务带 feature 需求，自动匹配最优工具。

#### 3. 双层并发控制 (Team + Crawl)

**核心思想**: 并发限制分两层 — team 级别全局限制 + crawl 级别单任务限制。超限任务不丢弃，进入 concurrency queue 排队。

```
concurrency-limit.ts:
├── Team 并发限制 (Redis Sorted Set, score=过期时间)
│   ├── pushConcurrencyLimitActiveJob() — 占槽
│   ├── removeConcurrencyLimitActiveJob() — 释放
│   └── cleanOldConcurrencyLimitEntries() — 清理过期
├── Crawl 并发限制 (同样机制, 按 crawl_id)
│   └── 支持 delay 配置 (每次爬取间隔)
└── 并发等待队列 (Redis Sorted Set)
    ├── pushConcurrencyLimitedJob() — 入队
    └── getNextConcurrentJob() — ZPOPMIN 原子出队
```

**关键**: `concurrentJobDone()` 完成时自动 promote 队列中的下一个任务，形成流水线。

**偷法**: Orchestrator 的任务执行可以用 Redis Sorted Set 做并发槽管理，比简单的 semaphore 更灵活（可以设过期、可查可清理）。

#### 4. System Monitor 背压控制

```typescript
// system-monitor.ts
class SystemMonitor {
  async acceptConnection() {
    const cpuUsage = await this.checkCpuUsage();
    const memoryUsage = await this.checkMemoryUsage();
    return cpuUsage < MAX_CPU && memoryUsage < MAX_RAM;
  }
}

// queue-worker.ts — worker 循环
while (true) {
  const canAcceptConnection = await monitor.acceptConnection();
  if (!canAcceptConnection) {
    cantAcceptConnectionCount++;
    isWorkerStalled = cantAcceptConnectionCount >= 25; // 25次拒绝 = 卡死报警
    await sleep(cantAcceptConnectionInterval);
    continue;
  }
  const job = await worker.getNextJob(token);
  // ...
}
```

**偷法**: Orchestrator 的 Agent SDK 执行前检查系统资源，避免在高负载时启动新任务。简单但有效。

#### 5. Transformer Pipeline (变换流水线)

```typescript
// transformers/index.ts
const transformerStack: Transformer[] = [
  deriveHTMLFromRawHTML,      // 1. 清理 HTML
  deriveMarkdownFromHTML,      // 2. HTML → Markdown
  performCleanContent,         // 3. 清理内容
  deriveLinksFromHTML,         // 4. 提取链接
  deriveImagesFromHTML,        // 5. 提取图片
  deriveBrandingFromActions,   // 6. 品牌提取
  deriveMetadataFromRawHTML,   // 7. 元数据
  uploadScreenshot,            // 8. 截图上传
  sendDocumentToIndex,         // 9. 发送到索引
  performLLMExtract,           // 10. LLM 结构化提取
  performSummary,              // 11. 摘要
  performQuery,                // 12. 问答
  performAttributes,           // 13. 属性提取
  performAgent,                // 14. Agent 模式
  deriveDiff,                  // 15. 变更追踪
  fetchAudio,                  // 16. 音频
  coerceFieldsToFormats,       // 17. 格式裁剪
  removeBase64Images,          // 18. 清理 base64 图片
];

// 执行器 — 按序执行，记录每步耗时
async function executeTransformers(meta, document) {
  const executions: [string, number][] = [];
  for (const transformer of transformerStack) {
    const start = Date.now();
    document = await transformer(meta, document);
    executions.push([transformer.name, Date.now() - start]);
  }
  meta.logger.debug("Executed transformers.", { executions });
  return document;
}
```

**偷法**: Orchestrator 已有 stage 概念 (cvui)，但 Firecrawl 的做法更优雅 — 每个 transformer 是纯函数 `(meta, doc) => doc`，按序执行、自动计时。可以直接搬到我们的处理流水线。

### P1 — 短期可偷

#### 6. CostTracking 运行时计费

```typescript
// cost-tracking.ts — 每次 LLM 调用累加成本
class CostTracking {
  calls: { type: string; cost: number; model: string; tokens?: {...}; stack: string; }[] = [];
  limit: number | null = null;

  addCall(call) {
    this.calls.push({ ...call, stack: new Error().stack! }); // 带调用栈！
    if (this.limit !== null && this.toJSON().totalCost > this.limit) {
      throw new CostLimitExceededError(); // 超限直接中断
    }
  }
}

// scrape-billing.ts — 按操作类型阶梯计费
// 基础抓取: 1 credit
// JSON 提取: 5 credits
// 隐身代理: +4 credits
// PDF 多页: +1 credit/page
// 零数据保留: +1 credit
// fire-1 模型: ceil(totalCost * 1800) — 按实际 LLM 消耗
```

**偷法**: Orchestrator 需要 Agent SDK 调用成本追踪。Firecrawl 的做法是**每个请求创建一个 CostTracking 实例，贯穿整个处理流水线**，任何 LLM 调用都往里加。带 stack trace 方便调试。

#### 7. NuQ — 自建队列 (PostgreSQL + RabbitMQ)

**核心发现**: Firecrawl 没有只用 BullMQ！他们建了自己的队列系统 NuQ。

```
NuQ 架构:
├── PostgreSQL — 任务持久化、状态管理
├── RabbitMQ — 任务通知（LISTEN/NOTIFY 替代品）
├── Redis — 信号量、并发控制、锁续期
└── GCS — 大结果存储（job result 太大放 GCS）
```

为什么不只用 BullMQ？
- BullMQ 的 job data 存在 Redis 里，大结果会撑爆内存
- 需要按 team/crawl 分组管理任务
- 需要 backlog 机制（任务先进等待区，不占 worker 资源）
- 需要可靠的 LISTEN/NOTIFY（BullMQ 的事件不够可靠）

**偷法**: Orchestrator 现在用 SQLite，如果要 scale 可以考虑类似架构 — SQLite/Postgres 做持久化，Redis 做并发控制，RabbitMQ 做通知。但目前单机场景 SQLite 够用，先偷概念不偷实现。

#### 8. Harness 进程编排

```typescript
// harness.ts — 一个 master 进程管理所有子进程
interface Services {
  api?: ProcessResult;           // API 服务器
  worker?: ProcessResult;         // BullMQ worker
  nuqWorkers: ProcessResult[];    // NuQ worker (多实例)
  nuqPrefetchWorker?: ProcessResult;
  nuqReconcilerWorker?: ProcessResult;
  extractWorker?: ProcessResult;  // 提取专用 worker
  indexWorker?: ProcessResult;    // 索引 worker
  nuqPostgres?: { containerName, containerRuntime }; // Docker 管理
  nuqRabbitMQ?: { containerName, containerRuntime };
}
```

特点:
- `--start-docker` 参数自动拉起 Postgres/RabbitMQ 容器
- 子进程崩溃自动重启
- SIGINT/SIGTERM 优雅关闭
- 彩色日志区分不同服务

**偷法**: Orchestrator 的 docker-compose 已经做了类似的事，但 harness 模式更适合开发/单机部署。可以考虑加一个 `orchestrator harness` 命令。

#### 9. Team Semaphore (Redis Lua 脚本实现)

```typescript
// team-semaphore.ts
async function withSemaphore<T>(teamId, holderId, limit, signal, timeoutMs, func) {
  if (isSelfHosted()) return await func(false); // 自部署跳过限制

  const { limited } = await acquireBlocking(teamId, holderId, limit, {
    base_delay_ms: 25,
    max_delay_ms: 250,
    timeout_ms: timeoutMs,
    signal,
  });

  const hb = startHeartbeat(teamId, holderId, SEMAPHORE_TTL / 2);
  try {
    return await Promise.race([func(limited), hb.promise]);
  } finally {
    hb.stop();
    await release(teamId, holderId);
  }
}
```

关键设计:
- **Blocking acquire with backoff**: 25ms 起步，1.5x 递增，上限 250ms，加 jitter
- **Heartbeat**: TTL/2 间隔续期，心跳失败 = 任务中断
- **Self-hosted bypass**: 自部署直接跳过所有并发限制

#### 10. LLM 提取的智能模型选择

```typescript
// llmExtract.ts
function selectModelForSchema(schema?: any) {
  if (!schema) return { modelName: "gpt-4o-mini", reason: "no_schema" };

  const isRecursive = detectRecursiveSchema(schema);
  if (isRecursive) {
    return { modelName: "gpt-4.1", reason: "recursive_schema_detected" };
  }
  return { modelName: "gpt-4o-mini", reason: "simple_schema" };
}
```

**偷法**: 根据任务复杂度自动选模型。简单的用小模型省钱，复杂的（递归 schema）才上大模型。Orchestrator 的 llm_router 可以加入类似逻辑。

### P2 — 长期参考

#### 11. A/B 测试框架

```
services/ab-test.ts — 对引擎/URL 做 A/B 测试
config: FIRE_ENGINE_AB_URL, FIRE_ENGINE_AB_RATE, FIRE_ENGINE_AB_MODE ("mirror"|"split")
```

#### 12. Engpicker — 基于历史数据的引擎选择

```
lib/engpicker.ts — 查询某个域名该用哪个引擎
queryEngpickerVerdict(hostname) → "TlsClientOk" | null
```

根据历史成功率动态调整引擎优先级。

#### 13. Index Cache 层

```
engines/index/ — 从缓存索引中读取已爬过的页面
quality: 1000 (最高优先级)
条件: 无自定义 headers/actions，maxAge 未设为 0
```

#### 14. 零数据保留 (ZDR)

```
贯穿整个代码的 zeroDataRetention 标志:
- 日志中不记录内容
- GCS 中处理完立即删除
- 禁止截图/PDF action
- Sentry 不上报内容
- 额外计费 (+1 credit)
```

---

## 三、98K Stars 的秘密

1. **解决真实痛点**: 把网页变成 LLM 可用数据，这是 AI 时代的基础设施需求
2. **工程质量极高**: 引擎瀑布流、双层并发控制、成本追踪 — 每个系统都做到了生产级
3. **多语言混合**: Go (Markdown 转换) + Rust (后处理) + TypeScript (业务逻辑) — 每个环节用最适合的语言
4. **API 设计简洁**: 一个 URL 进，markdown/JSON/screenshot 出。开发者友好
5. **自建队列 NuQ**: 不满足于 BullMQ 的限制，自建 Postgres+RabbitMQ 队列 — 这种"不将就"的态度
6. **完整的变换流水线**: 18 步 transformer，每步可独立测试、独立计时
7. **MCP Server + CLI**: 及时拥抱 AI 编码工具生态

---

## 四、Orchestrator 可直接应用的模式

| # | 模式 | 应用方式 | 优先级 |
|---|------|---------|--------|
| 1 | Engine Waterfall | LLM 调用: 快模型先发，超时 waterfall 到大模型 | P0 |
| 2 | Feature Flag 引擎选择 | 工具注册能力矩阵，任务自动匹配最优工具 | P0 |
| 3 | Redis Sorted Set 并发槽 | 替换现有简单信号量，支持 TTL 自动清理 | P0 |
| 4 | System Monitor 背压 | Agent 执行前检查 CPU/RAM，高负载延迟执行 | P0 |
| 5 | Transformer Pipeline | 统一处理流水线: `(meta, doc) => doc` 纯函数模式 | P0 |
| 6 | CostTracking | 每个请求一个实例，贯穿全链路，带 stack trace | P1 |
| 7 | Smart Model Selection | 根据任务复杂度自动选模型 (llm_router 增强) | P1 |
| 8 | Heartbeat + Lock Renewal | 长任务定期续锁，心跳失败 = 中断 | P1 |
| 9 | Backpressure via canAcceptConnection | Worker 循环中的资源检查门控 | P1 |
| 10 | Concurrency Queue Promotion | 任务完成后自动 promote 等待队列中的下一个 | P2 |
