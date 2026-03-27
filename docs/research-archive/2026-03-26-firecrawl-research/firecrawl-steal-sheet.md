# Firecrawl 偷师研究报告

> 98K+ stars, TypeScript, AGPL-3.0
> AIMultiple 2026 Agentic Search Benchmark: #2 (Agent Score 14.58), Mean Relevance 最高 (4.30)
> 源码: github.com/firecrawl/firecrawl

---

## 一、定位澄清

Firecrawl **不是搜索引擎**。它是 **Web Data API** — 把网页变成 LLM 可用的结构化数据。它在 search benchmark 排名高的原因：

1. `/search` 端点 = 搜索引擎（Fire Engine / SearXNG / DuckDuckGo）+ 自动全文抓取
2. 搜索结果不只返回 snippet，而是直接抓取每个结果页的完整 markdown
3. Mean Relevance 4.30（全场最高），因为 LLM 拿到的是完整页面内容而非摘要

**核心洞察**: Firecrawl 赢在"搜索+抓取"一体化。Agent 拿到的不是 10 条 snippet，而是 5 篇完整文章的 markdown。这就是为什么"爬虫工具"能在搜索 benchmark 碾压纯搜索 API。

---

## 二、系统架构

### 2.1 整体架构：Client → API → Queue → Worker → Engines → Transformers

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────┐
│   Client     │────▶│   Express API    │────▶│   BullMQ     │
│  (SDK/REST)  │     │   (auth/rate)    │     │   (Redis)    │
└─────────────┘     └──────────────────┘     └──────┬──────┘
                                                     │
                    ┌────────────────────────────────┼────────────────────┐
                    │                                │                    │
              ┌─────▼─────┐  ┌──────────▼──────┐  ┌─▼──────────┐  ┌────▼─────┐
              │ scrape-    │  │ extract-        │  │ index-      │  │ nuq-     │
              │ worker     │  │ worker          │  │ worker      │  │ workers  │
              └─────┬─────┘  └─────────────────┘  └────────────┘  └──────────┘
                    │
        ┌───────────┼────────────┬──────────────┐
        │           │            │              │
   ┌────▼────┐ ┌────▼─────┐ ┌───▼────┐  ┌─────▼──────┐
   │  Fire   │ │Playwright│ │ Fetch  │  │ PDF/Doc    │
   │ Engine  │ │ Service  │ │(HTTP)  │  │ Engine     │
   └────┬────┘ └──────────┘ └────────┘  └────────────┘
        │
   ┌────▼────────────────────────────┐
   │  18-step Transformer Pipeline   │
   │  rawHTML → metadata → HTML →    │
   │  markdown → LLM extract →      │
   │  screenshot → diff → index     │
   └─────────────────────────────────┘
```

### 2.2 Docker Compose 服务拓扑（5 服务）

| 服务 | 职责 | 资源限制 |
|------|------|----------|
| `api` | Express + 所有 worker 进程 | 4 CPU, 8GB RAM |
| `playwright-service` | 浏览器自动化 (CDP) | 2 CPU, 4GB RAM |
| `redis` | BullMQ 队列 / 缓存 / 限流 | 默认 |
| `rabbitmq` | NuQ 消息中间件 | 默认 |
| `nuq-postgres` | 任务状态持久化 | 默认 |

### 2.3 存储策略（多级持久化）

| 层 | 用途 | TTL |
|----|------|-----|
| Redis | 队列、爬虫状态(`crawl:{id}:visited`)、ACUC 缓存、限流计数 | 600s (ACUC) |
| PostgreSQL (NuQ) | 任务元数据、worker 协调、执行状态 | 持久 |
| Supabase | 内容索引（URL hash）、审计日志、认证 | 持久 |
| GCS | 完整结果 JSON、截图、PDF | 持久 |

---

## 三、API 设计（全端点）

### 3.1 端点清单

| 端点 | 方法 | 用途 | 同步/异步 | 信用消耗 |
|------|------|------|-----------|----------|
| `/v2/scrape` | POST | 单页抓取 → markdown/HTML/JSON/截图 | 同步 | 1 credit |
| `/v2/crawl` | POST | 全站爬取 | 异步(轮询) | 1/页 |
| `/v2/crawl/{id}` | GET | 查询爬取状态 | - | 0 |
| `/v2/map` | POST | 发现站点所有 URL | 同步 | 1 credit |
| `/v2/search` | POST | 搜索+可选全文抓取 | 同步 | 1 + 1/页 |
| `/v2/extract` | POST | 结构化数据提取 (已被 /agent 取代) | 异步 | 5 credits |
| `/v2/agent` | POST | AI agent 自主搜索+导航+提取 | 异步 | 按用量 |
| `/v2/browser` | POST | 远程浏览器会话 (CDP) | 同步 | 按时间 |
| `/v2/batch/scrape` | POST | 批量抓取 (5000+ URL) | 异步 | 1/页 |

### 3.2 核心请求参数 (/scrape)

```typescript
{
  url: string;                    // 必填
  formats: Format[];              // markdown | html | rawHtml | screenshot | links | json | images | branding | audio | summary
  actions?: Action[];             // click | write | press | wait | screenshot — 抓取前交互
  location?: { country, languages }; // 地理定位
  timeout?: number;               // ms
  only_main_content?: boolean;
  maxAge?: number;                // 缓存新鲜度 (ms), 0=强制刷新
  waitFor?: number;               // JS 渲染等待
  zeroDataRetention?: boolean;    // 企业级 ZDR
  changeTracking?: boolean;       // 变更检测
  // JSON format 专用:
  schema?: JSONSchema;            // Pydantic/JSON Schema 结构化提取
  prompt?: string;                // 无 schema 时用自然语言描述
}
```

### 3.3 响应格式

```typescript
{
  success: boolean;
  data: {
    markdown?: string;
    html?: string;
    rawHtml?: string;
    screenshot?: string;          // URL, 24h 过期
    links?: string[];
    json?: object;                // 按 schema 提取的结构化数据
    images?: string[];
    branding?: BrandingProfile;   // 颜色/字体/排版/组件样式
    audio?: string;               // GCS 签名 URL, 1h 过期
    summary?: string;
    actions?: { screenshots, scrapes, javascriptReturns };
    metadata: {
      title, description, language, keywords, robots,
      ogTitle, ogDescription, ogUrl, ogImage,
      sourceURL, statusCode
    }
  }
}
```

### 3.4 格式信用成本

| 格式 | 额外信用 |
|------|----------|
| markdown/html/links/screenshot | 0 (含在基础 1 credit) |
| json (LLM 提取) | +4 credits |
| enhanced proxy | +4 credits |
| PDF 解析 | 1 credit/页 |
| ZDR | +1 credit |

---

## 四、引擎选择与回退链

### 4.1 引擎类型

```typescript
type Engine =
  | "fire-engine;chrome-cdp"           // Chrome CDP (最强)
  | "fire-engine;chrome-cdp;stealth"   // + 隐身代理
  | "fire-engine;tlsclient"            // TLS 指纹模拟
  | "fire-engine;tlsclient;stealth"    // + 隐身
  | "fire-engine(retry);chrome-cdp"    // 重试变体
  | "playwright"                       // 标准浏览器自动化
  | "fetch"                            // 轻量 HTTP
  | "pdf"                              // Rust PDF + OCR
  | "document"                         // DOCX/XLSX/ODT
  | "index"                            // 缓存命中
  | "wikipedia"                        // Wikipedia Enterprise API
```

### 4.2 Feature Flag 驱动的引擎选择

不是硬编码的 if-else，而是 **feature flag 系统**：

```typescript
const featureFlagOptions = {
  actions:              { priority: 20 },   // 需要 CDP
  waitFor:              { priority: 1 },
  screenshot:           { priority: 10 },
  pdf:                  { priority: 100 },  // 强制 PDF 引擎
  document:             { priority: 100 },  // 强制文档引擎
  atsv:                 { priority: 90 },   // 强制 TLS client
  useFastMode:          { priority: 90 },
  location:             { priority: 10 },
  mobile:               { priority: 10 },
  stealthProxy:         { priority: 20 },
  branding:             { priority: 20 },   // 需要 JS 执行
  disableAdblock:       { priority: 10 },
};
```

**核心机制**: 从 URL + options 推导 feature flags → 构建兼容引擎列表 → 按优先级瀑布式回退。

### 4.3 回退链流程

```
Wikipedia (专用 URL) → Index Cache → Fire Engine CDP → Fire Engine CDP+Stealth
  → Fire Engine TLS → Playwright → Fetch → PDF/Document (按文件类型)
```

每个引擎失败时抛出类型化错误（`EngineError`, `IndexMissError`, `PDFAntibotError` 等），上层 catch 并尝试下一个引擎。

---

## 五、Transformer Pipeline（18 步）

引擎返回 raw HTML 后，经过 transformer 管道：

```
rawHTML
  → deriveMetadataFromRawHTML()      // 提取 title/description/og:*
  → deriveHTMLFromRawHTML()          // 清理 HTML (去广告/导航/脚注)
  → deriveMarkdownFromHTML()         // HTML → Markdown
  → extractLinks()                   // 提取所有链接
  → extractImages()                  // 提取图片 URL
  → performLLMExtract()              // JSON schema 结构化提取 (可选)
  → performSummary()                 // 摘要生成 (可选)
  → performQuery()                   // 页面级问答 (可选)
  → performCleanContent()            // 内容清洗
  → uploadScreenshot()               // 截图上传 GCS
  → removeBase64Images()             // 移除内联 base64
  → deriveDiff()                     // 变更追踪 (git-diff 算法!)
  → performAttributes()              // 属性提取
  → brandingTransformer()            // 品牌识别
  → fetchAudio()                     // TTS 音频生成
  → sendDocumentToIndex()            // 写入索引缓存
  → sendDocumentToSearchIndex()      // 写入搜索索引
```

**关键洞察**: `deriveDiff()` 用的是 **git-diff + parse-diff** 库，把网页内容变更当作 git diff 来处理。配合 schema 提取时，还会对前后两次的结构化数据做字段级 diff。

---

## 六、Search 实现细节

### 6.1 搜索引擎路由

```typescript
// apps/api/src/search/index.ts — 三级回退
if (config.FIRE_ENGINE_BETA_URL) {
  return fire_engine_search(query, opts);     // 1. Fire Engine (Google)
}
if (config.SEARXNG_ENDPOINT) {
  return searxng_search(query, opts);          // 2. SearXNG (自托管)
}
return ddgSearch(query, num_results, opts);    // 3. DuckDuckGo (兜底)
```

### 6.2 Search + Scrape 一体化

V2 `/search` 的杀手锏：搜索返回 URL 后，**自动为每个结果创建独立 scrape job**。
- 搜索本身 1 credit
- 每页抓取独立计费
- `scrape_options` 参数直接传入 scrape 配置

这就是为什么它在 benchmark 中碾压纯搜索 API：其他 API 返回 snippet，Firecrawl 返回完整 markdown。

### 6.3 Map 服务的 URL 发现策略

三路并行发现：
1. **Sitemap 解析** — 标准 robots.txt → sitemap.xml
2. **搜索引擎** — `site:domain.com` 查询（Fire Engine Map，100 结果/页，Redis 缓存 48h）
3. **索引缓存** — 分层 URL 切片查询（`example.com` → `example.com/blog` → ...）

发现后经过过滤管道：域名匹配 → 子域名 → 路径过滤 → robots.txt → 正则 → URL 归一化 → 去重。

可选 **余弦相似度排序**：query vs URL 文本的相似度排名。

---

## 七、/agent 端点（最有价值的偷师目标）

```python
# 不需要 URL，只需要描述你要什么
result = app.agent(
    prompt="Find the pricing plans for Notion",
    schema=PricingSchema  # 可选：结构化输出
)
# agent 自主搜索、导航、提取、返回结构化数据
```

### 7.1 两档模型

| 模型 | 成本 | 适用 |
|------|------|------|
| `spark-1-mini` (默认) | 便宜 60% | 大多数任务 |
| `spark-1-pro` | 标准 | 复杂研究、跨站比较、关键数据 |

### 7.2 /browser 端点（远程浏览器）

```javascript
const session = await firecrawl.browser();
// 返回 CDP WebSocket URL + 实时预览 URL
// 支持 Playwright 代码执行、bash 命令、持久化 profile
```

---

## 八、自托管 vs 云端

| 能力 | 云端 | 自托管 |
|------|------|--------|
| 全部 API 端点 | ✅ | 部分 (`/agent` 和 `/browser` 不支持) |
| Fire Engine (反反爬) | ✅ | ❌ (只有 Playwright + Fetch) |
| 本地 LLM (Ollama) | ❌ | ✅ |
| SearXNG 搜索 | ❌ | ✅ |
| 截图 | ✅ | ✅ |
| 认证 (Supabase) | 自动 | 可选 |
| JSON 提取 | ✅ | ✅ (需配置 LLM) |

**自托管关键配置**:
```env
USE_DB_AUTHENTICATION=false          # 跳过认证
NUM_WORKERS_PER_QUEUE=8              # worker 并发
CRAWL_CONCURRENT_REQUESTS=10         # 爬虫并发
MAX_CONCURRENT_JOBS=5                # 最大同时爬取数
BROWSER_POOL_SIZE=5                  # Playwright 实例池
OPENAI_API_KEY=...                   # LLM 提取用
SEARXNG_ENDPOINT=http://searxng:8080 # 自托管搜索
```

---

## 九、定价模型

| 层级 | 月费 | 信用 | 并发 |
|------|------|------|------|
| Free | $0 | 500 终身 | - |
| Hobby | $16/月 | 3,000/月 | - |
| Standard | $83/月 | 100,000/月 | - |
| Growth | $333/月 | 500,000/月 | - |
| Scale | $599/月 | 1,000,000/月 | 150 并发 |
| Enterprise | 定制 | 定制 | 定制 |

- 信用不滚存（自动充值包除外）
- 额外信用 $9/1000 (Hobby)

---

## 十、Scaling 血泪史（实战经验）

来自官方博文 "Handling 300k requests per day":

### 10.1 BullMQ 踩坑
- 初始 lockDuration 设为 2 小时 → 任务卡死 2 小时
- 修正为 lockDuration=2min, lockRenewTime=15s

### 10.2 爬虫任务拆分
- 早期：一个大 crawl job = 一个进程爬全站 → OOM
- 现在：每个 URL 拆成独立 scrape job → 分布式执行，不怕 OOM

### 10.3 Redis 状态协调
- `SADD` 原子操作做分布式锁，防止两个 worker 抓同一 URL
- `crawl:{id}:visited` set 跟踪已访问 URL

### 10.4 Redis 成本爆炸
- Redis 出站流量暴涨到 **$15,000/月**
- 迁移到 Fly.io 私有网络解决

### 10.5 BullMQ 事件流陷阱
- Redis streams 默认 10,000 事件上限
- 高负载下事件被清除 → `Job.waitUntilFinished()` 永远 hang
- 解决：直接查询 job 状态，不依赖事件流

---

## 十一、可偷模式清单

### P0 — 立即可用

| # | 模式 | Firecrawl 实现 | 偷师方向 |
|---|------|---------------|---------|
| 1 | **引擎瀑布回退** | Feature flags → 兼容引擎列表 → 逐个尝试 | LLM router 的 model fallback 可以用相同模式：feature flags 决定候选模型 |
| 2 | **Transformer Pipeline** | 18 步函数管道，每步只做一件事 | channel 消息处理管道化：raw → clean → enrich → respond → log |
| 3 | **搜索+抓取一体化** | `/search` 自动抓取结果页全文 | wake/chat channel 的 web search tool 可以返回完整内容而非 snippet |
| 4 | **Job 原子化** | 大爬虫拆成小 scrape jobs | 长任务（如批量分析）拆成子任务分发 |
| 5 | **Redis SADD 分布式锁** | 防重复处理 | 多 channel 同时收到相同请求时去重 |

### P1 — 架构参考

| # | 模式 | 说明 |
|---|------|------|
| 6 | **ACUC 缓存** | 认证+额度信息缓存 600s，不是每次请求都查 DB |
| 7 | **ZDR (Zero Data Retention)** | 企业级数据不落盘模式，按功能开关控制 |
| 8 | **git-diff 做变更检测** | 网页内容 diff 直接用 git-diff 库，不自己造轮子 |
| 9 | **Feature Flag 系统** | 不是 if-else 选引擎，而是声明式 flag → 兼容性矩阵 |
| 10 | **harness.ts 多进程编排** | 一个入口文件启动 API + 所有 worker 进程，颜色编码日志 |

### P2 — 产品启发

| # | 模式 | 说明 |
|---|------|------|
| 11 | **formats 数组** | 一次请求多种输出格式，按需计费 |
| 12 | **actions 预操作** | 抓取前执行交互序列（click/type/wait），解锁动态内容 |
| 13 | **branding 提取** | 自动识别网站视觉身份（颜色/字体/排版） |
| 14 | **/agent 无 URL 提取** | 只描述需求，agent 自主搜索+导航+提取 |
| 15 | **cosine similarity URL 排序** | map 结果按查询相关性排序 |

---

## 十二、与 Orchestrator 的交叉点

| Orchestrator 组件 | 可借鉴 |
|-------------------|--------|
| `llm_router.py` | 引擎瀑布回退 (P0-1)、feature flag 选模型 (P1-9) |
| channel 消息处理 | transformer pipeline (P0-2)、job 原子化 (P0-4) |
| wake channel | search+scrape 一体化 (P0-3) 给 desktop agent 加 web 搜索能力 |
| 审批体系 | ACUC 式额度缓存 (P1-6) |
| 三省六部派单 | Redis SADD 去重 (P0-5)、harness 多进程编排 (P1-10) |

---

## 十三、Benchmark 完整数据

AIMultiple 2026 Agentic Search Benchmark（100 查询，8 API，5 结果/查询，GPT-5.2 评判）:

| 排名 | API | Agent Score | Mean Relevant | Quality | Latency |
|------|-----|-------------|---------------|---------|---------|
| 1 | Brave Search | 14.89 | 4.32 | 3.45 | 669ms |
| 2 | **Firecrawl** | **14.58** | **4.30** | 3.39 | 1,335ms |
| 3 | Exa AI | 14.39 | ~4.0 | 3.59 | ~1,200ms |
| 4 | Parallel Search Pro | 14.21 | ~4.0 | 3.55 | 13,600ms |
| 5 | Tavily | 13.67 | ~3.8 | 3.60 | 998ms |
| 6 | Parallel Search Base | 13.50 | ~3.8 | 3.55 | 2,900ms |
| 7 | Perplexity | 12.96 | ~3.6 | 3.60 | 11,000ms |
| 8 | SerpAPI | 12.28 | 3.58 | 3.42 | 2,400ms |

Agent Score = Mean Relevant × Quality。前 4 名统计上无显著差异（置信区间重叠）。

**Firecrawl 的独特优势**: Relevance 最高但 Quality 不是最高 → 说明它找到的东西最相关，但返回的原始内容（完整 markdown）比经过 AI 加工的 snippet（如 Perplexity）在"质量"评分上略低。这是设计取舍：raw fidelity vs polished summary。
