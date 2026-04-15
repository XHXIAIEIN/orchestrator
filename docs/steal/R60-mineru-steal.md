# R60 — MinerU Steal Report

**Source**: https://github.com/opendatalab/MinerU | **Stars**: 59.7K | **License**: AGPL-3.0
**Date**: 2026-04-14 | **Category**: Complete Framework

## TL;DR

MinerU 是一个工业级文档解析引擎（PDF/Word/PPT → Markdown/JSON），问题空间是"非结构化文档 → LLM-ready 结构化数据"。值得偷师的不是它的 ML 模型，而是它在**多后端路由、VRAM 自适应批处理、任务装箱调度、流式回调管线**上的工程模式——这些模式直接映射到 Orchestrator 的多通道执行和资源管理场景。

## Architecture Overview

```
Layer 4: CLI / REST API / Router (负载均衡)
  ├── client.py       — 装箱调度 + 异步worker池
  ├── fast_api.py     — AsyncTaskManager + 信号量并发控制
  └── router.py       — WorkerPool + 最低负载路由

Layer 3: Backend Selection (3引擎可切换)
  ├── pipeline/       — 传统多模型流水线 (Layout→MFR→Table→OCR)
  ├── vlm/            — 单VLM模型直接输出结构化块
  └── hybrid/         — VLM布局 + Pipeline OCR/公式补充

Layer 2: Model Layer (无统一ABC，鸭子类型)
  ├── layout/         — RT-DETR + 阅读顺序Transformer
  ├── table/          — 分类(有线/无线) → 重建(UNet/SLANet)
  ├── mfr/            — UnimerNet / PP-FormulaNet (面积自适应动态batch)
  ├── ocr/            — PaddleOCR PyTorch移植 (109语言,脚本族路由)
  └── ori_cls/        — 两阶段方向检测 (廉价筛→昂贵分类)

Layer 1: Data / IO / Config
  ├── data_reader_writer/ — 两层IO抽象 (传输层 + 应用层)
  ├── config_reader.py    — JSON配置 + 环境变量覆盖
  └── output_paths.py     — 结构化输出目录
```

## Steal Sheet

### P0 — Must Steal (5 patterns)

| Pattern | Mechanism | Our Current State | Adaptation | Effort |
|---------|-----------|------------------|------------|--------|
| VRAM自适应批量比 | 探测GPU显存(6/8/16/32GB)→设batch_ratio(1~16x)，各子模型按比例缩放batch size | 无，所有并发硬编码 | `src/channels/session_pool.py` + 未来GPU任务的通用资源探测 | ~1.5h |
| 装箱调度器 | FFD(First-Fit-Decreasing)按任务大小装箱到窗口，大任务独占，小任务合并 | scheduler.py用简单队列 | `src/scheduler.py` 任务批处理 | ~2h |
| 双事件等待模式 | `asyncio.wait({task_event, manager_wakeup})` 让shutdown立即唤醒所有同步阻塞者 | 无，关闭时等超时 | `src/channels/session_pool.py` 的优雅关闭 | ~1h |
| 两阶段渐进检测 | 廉价探测(文本检测统计)过滤90%负样本→只对可疑样本跑昂贵分类器 | 无此模式 | `src/analysis/burst_detector.py` 异常检测可用廉价统计先筛 | ~1.5h |
| 流式回调管线 | `doc_analyze_streaming(on_doc_ready=callback)` — 分析完一个文档立即回调写入，不等全部完成 | 同步处理，全部完成后才输出 | `src/channels/block_streamer.py` 块级流式 | ~2h |

### P1 — Worth Doing (6 patterns)

| Pattern | Mechanism | Adaptation | Effort |
|---------|-----------|------------|--------|
| 最低负载路由 | `(queued+processing+pending_assignments)/max_concurrent_requests` 归一化评分，同分随机打散 | `src/channels/channel_router.py` 多通道负载均衡 | ~3h |
| 面积排序动态batch | 公式识别按像素面积排序→大面积减半batch size防OOM，小面积打满batch | GPU推理任务通用模式 | ~2h |
| tqdm空闲时间扣除 | 调整`progress_bar.start_t`扣除模型加载时间，速度统计更准确 | 进度报告场景 | ~0.5h |
| 14路shutdown探测 | 循环尝试`shutdown/close/stop/terminate/destroy`及嵌套路径清理推理运行时 | VLM/外部进程管理 | ~1h |
| LiveAware日志协调 | 自定义loguru sink，log输出前clear live display，写完后re-render | terminal_display.py已有类似需求 | ~1.5h |
| 范围读URL参数编码 | S3路径嵌入`?bytes=start,end`实现range-read，不改接口签名 | DataReader接口扩展 | ~1h |

### P2 — Reference Only (4 patterns)

| Pattern | Mechanism | Why ref-only |
|---------|-----------|-------------|
| 鸭子类型模型层 | 无ABC无Protocol，全靠约定`predict/batch_predict` | 我们用ABC更严格，不退化 |
| In-place结果回填 | batch方法直接写入输入dict而非返回新结构 | 耦合过紧，不适合我们的消息传递模式 |
| 单文件e2e测试+20%覆盖率 | 唯一测试是跑真实PDF对比模糊匹配 | 我们测试策略已更成熟 |
| config_version字符串比较 | `< '1.3.1'` 字典序判断是否需要升级配置 | 脆弱，semver解析才正确 |

## Comparison Matrix (P0 Patterns)

### VRAM自适应批量比

| Capability | Their impl | Our impl | Gap size | Action |
|-----------|-----------|---------|----------|--------|
| GPU显存探测 | `get_vram()` → 4级阈值→batch_ratio | 无 | Large | Steal |
| 各子任务按比例缩放 | base_batch_size * batch_ratio | 硬编码并发数 | Large | Steal |
| 虚拟显存覆盖(测试用) | `MINERU_VIRTUAL_VRAM_SIZE` env var | 无 | Medium | Steal |
| 多GPU族支持 | CUDA/MPS/NPU/GCU/MUSA/MLU/SDAA | N/A（我们不跑模型） | None | Skip |

### 装箱调度器

| Capability | Their impl | Our impl | Gap size | Action |
|-----------|-----------|---------|----------|--------|
| 任务大小估计 | PDF页数 | 无（任务无大小概念） | Large | Steal |
| FFD装箱 | 按页数降序→最小负载箱优先 | 简单FIFO队列 | Large | Steal |
| 大任务独占 | 超窗口大小自动独立task | 无 | Medium | Steal |
| 窗口大小可配 | `PROCESSING_WINDOW_SIZE` env var | 无 | Medium | Steal |

### 双事件等待模式

| Capability | Their impl | Our impl | Gap size | Action |
|-----------|-----------|---------|----------|--------|
| 任务完成事件 | `asyncio.Event` per task | 有 | None | Skip |
| 全局唤醒事件 | `manager_wakeup` broadcast | 无 | Medium | Steal |
| shutdown广播 | `wait({task_event, wakeup})` | 超时等待 | Medium | Steal |

### 两阶段渐进检测

| Capability | Their impl | Our impl | Gap size | Action |
|-----------|-----------|---------|----------|--------|
| 廉价预筛 | 文本框纵横比统计→28%阈值 | 无，所有样本跑完整流程 | Large | Steal |
| 昂贵分类只跑阳性 | ONNX分类器只对flagged图片运行 | N/A | Large | Steal |
| 阈值可配 | 硬编码28%+3框 | N/A | N/A | 适配时参数化 |

### 流式回调管线

| Capability | Their impl | Our impl | Gap size | Action |
|-----------|-----------|---------|----------|--------|
| 文档级流式回调 | `on_doc_ready` callback → ThreadPoolExecutor | 同步批处理 | Large | Steal |
| 写入不阻塞分析 | IO在独立线程池(max_workers=1) | 串行 | Medium | Steal |
| 进度更新 | 每文档完成更新tqdm | 全部完成后报告 | Medium | Enhance |

## Triple Validation Gate (P0 Patterns)

| Pattern | Cross-domain | Generative | Exclusivity | Score |
|---------|-------------|-----------|-------------|-------|
| VRAM自适应批量比 | ✅ vLLM/TGI等推理框架均有VRAM自适应 | ✅ 给定新GPU可预测batch_ratio | ✅ 阶梯式而非线性，有特定阈值 | 3/3 |
| 装箱调度器 | ✅ Kubernetes bin-packing, 批处理系统 | ✅ 新任务集可预测分箱结果 | ✅ FFD+页数估计+窗口约束组合 | 3/3 |
| 双事件等待模式 | ✅ Go context.Done+select, Erlang monitors | ✅ 任何需要优雅关闭的场景适用 | ⚠️ 接近通用模式，但dual-event组合有特色 | 2/3 |
| 两阶段渐进检测 | ✅ 级联分类器(Viola-Jones), 漏斗分析 | ✅ 给定新检测任务可设计廉价预筛 | ✅ 文本框统计→分类器的具体组合独特 | 3/3 |
| 流式回调管线 | ✅ 流处理系统(Flink/Kafka Streams) | ✅ 任何批→流转换场景适用 | ⚠️ callback+单线程写入是常见模式 | 2/3 |

## Knowledge Irreplaceability

| Pattern | Pitfall | Judgment | Relationship | Hidden Context | Failure | Behavioral | Score |
|---------|---------|----------|-------------|---------------|---------|-----------|-------|
| VRAM自适应批量比 | ✅ 6GB阈值从OOM调出 | ✅ 阶梯比线性好 | | ✅ 不同子模型base不同 | ✅ OOM级联 | | 4/6 |
| 装箱调度器 | | ✅ 大任务必须独占 | | ✅ 窗口64是经验值 | | ✅ FFD优于FIFO | 3/6 |
| 双事件等待模式 | ✅ 不broadcast→僵尸等待 | | | | ✅ shutdown卡死 | | 2/6 |
| 两阶段渐进检测 | | ✅ 28%是调参结果 | | ✅ 纵横比<0.8=竖排 | | ✅ 90%节省 | 3/6 |
| 流式回调管线 | ✅ 多线程写入会乱序 | ✅ max_workers=1串行化 | | | | ✅ 分析不等IO | 3/6 |

## Gaps Identified

| Dimension | Their Coverage | Our Coverage | Gap |
|-----------|---------------|-------------|-----|
| **Security/Governance** | 薄弱 — 无权限模型，无审计，无沙箱。PDF分类失败静默降级为OCR | 较强 — attack pattern库、hook守卫、audit log | 我们领先 |
| **Memory/Learning** | 无 — 无持久化学习，无配置自适应 | 有 — memory系统、evidence tier | 我们领先 |
| **Execution/Orchestration** | 强 — 装箱调度、3引擎路由、流式回调、WorkerPool负载均衡 | 中 — 简单队列、同步处理 | **主要差距** |
| **Context/Budget** | 中 — VRAM探测+batch_ratio，窗口化分页处理 | 弱 — 无资源感知调度 | **主要差距** |
| **Failure/Recovery** | 弱 — 无失败分类体系，静默降级+warn日志，无检查点/恢复 | 中 — 有错误分类但不完整 | 互有长短 |
| **Quality/Review** | 弱 — 单文件e2e测试、20%覆盖率、fuzzywuzzy模糊匹配 | 中 — verification gate | 我们领先 |

## Adjacent Discoveries

1. **`magika` 库** (Google出品) — 基于内容的文件类型检测，比扩展名判断准确得多。MinerU 用它做 `guess_suffix_by_bytes()`。我们的媒体处理 (`src/channels/media.py`) 可以直接用。

2. **`json-repair` 库** — 修复LLM输出的畸形JSON（缺引号、多余逗号等）。MinerU依赖它解析VLM输出。我们解析agent输出时可能有同样需求。

3. **`fast-langdetect`** — 快速语言检测，MinerU用于OCR语言路由。可用于我们多语言消息路由。

4. **pdfium线程安全守卫** (`pdfium_guard.py`) — 所有pdfium调用包裹在`threading.RLock()`中。这是一个通用模式：外部C库非线程安全时用锁守卫而非每次创建新进程。

5. **ProcessPoolExecutor恢复模式** — BrokenProcessPool时 SIGTERM→等0.1s→SIGKILL→回收。比我们简单重启更健壮。

6. **RT-DETR + Reading Order Transformer** — 布局检测后用独立的阅读顺序Transformer（基于LayoutLMv3空间编码+RoPE 2D位置关系）确定阅读序。这种"检测→排序"分离架构可以迁移到我们的UI分析模块 (`/analyze-ui`)。

## Path Dependency Assessment

**锁定决策:**
- **PaddleOCR PyTorch移植**：深度绑定PaddlePaddle的Backbone-Neck-Head架构，迁移到其他OCR栈(如EasyOCR/Tesseract)代价极高
- **中间JSON格式("middle_json")**：三个后端都必须输出同一schema，新后端必须适配此格式
- **鸭子类型模型层**：无ABC = 新模型集成只能靠读现有实现猜接口，但也意味着低耦合

**错过的分岔:**
- 未在早期引入统一模型接口(ABC/Protocol)，现在22+模型类各自为政
- 无检查点/恢复机制 — 100页PDF处理到第99页失败，必须全部重来
- 无失败分类体系 — 所有错误都是`except Exception as e: logger.warning`

**自强化:**
- 59.7K stars → 社区贡献围绕现有架构 → 重构代价指数增长
- 10+国产芯片适配 → 每个新芯片都是在现有抽象上打补丁
- middle_json schema已成为生态契约(LangChain/Dify集成依赖它)

**对我们的启示:**
- 学他们的**执行层模式**(装箱调度、流式回调、VRAM自适应)，而非他们的架构选择
- 避免他们的路径锁定：我们的模型层(如果扩展)应从一开始就用Protocol定义接口
- middle_json的教训：中间表示一旦成为生态契约就无法改，所以**schema要早定、要版本化**

## Meta Insights

1. **工程模式跨域迁移的黄金案例**：MinerU是文档解析引擎，Orchestrator是AI代理系统，看似毫无关系。但"装箱调度器"、"VRAM自适应批量"、"流式回调管线"这些模式完全不关心你处理的是PDF还是消息——它们解决的是**资源约束下的批处理调度**这个通用问题。这验证了偷师的核心假设：结构可迁移。

2. **"无ABC"是个警告信号，不是美德**：MinerU 22+模型类全靠鸭子类型，新贡献者只能靠读代码猜接口。这在59.7K stars的项目中居然没有引起重构，说明一旦生态建立，技术债的偿还成本会指数增长。对我们的启示：现在给`src/channels/base.py`的Channel Protocol加严比以后任何时候都便宜。

3. **渐进检测是被严重低估的优化模式**：MinerU的两阶段方向检测（廉价统计筛掉90%→昂贵分类器只跑10%）不是什么高深算法，但它省了9倍的推理成本。同样的模式可以用在：异常检测先跑统计指标→只对异常窗口跑ML模型；消息分类先做关键词匹配→只对模糊case调LLM。

4. **Hybrid不是"两者都跑" — 而是"谁擅长什么就谁来"**：MinerU的hybrid后端不是简单的ensemble。它用VLM理解布局结构（VLM擅长），用pipeline做OCR文本识别（传统模型更快更准）。这种"按能力路由"模式比"按配置选后端"高级一个维度——它假设不同组件在不同子任务上有不同的comparative advantage。这直接映射到我们的多Agent协作：不是"选一个Agent跑全部"，而是"让每个Agent做它最擅长的那部分"。

5. **shutdown是被忽视的工程难题**：MinerU花了70行代码（14路方法探测）只为了干净关闭VLM运行时。这不是过度工程——不干净的关闭意味着GPU内存泄漏、僵尸进程、端口占用。我们的`session_pool.py`和外部进程管理同样需要这种防御性关闭。

## Implementation Status

All 5 P0 patterns implemented in commit `2b876b4`:
- `src/jobs/__init__.py`: JobBatcher (FFD bin-packing) + run_job on_complete callback
- `src/channels/session_pool.py`: dual-event shutdown + resource-adaptive max_sessions
- `src/analysis/burst_detector.py`: two-stage progressive detection with SQL pre-filter

All 6 P1 patterns implemented:
- P1-1 最低负载路由: `src/channels/channel_router.py` — ChannelLoadState + select_least_loaded (score-based, random tie-break, optimistic pending_assignments)
- P1-2 面积排序动态batch: `src/jobs/__init__.py` — _pack_ffd now sorts ascending, computes baseline mean weight, halves bin capacity at 4x ratio thresholds
- P1-3 空闲时间扣除: `src/jobs/__init__.py` — exclude_idle_time() + run_job idle_since param, flush tracks inter-job idle gaps
- P1-4 多路shutdown探测: `src/channels/agent_bridge.py` — ACPBridge.close() tries JSON-RPC shutdown first, then _graceful_kill with process tree cleanup
- P1-5 LiveAware日志协调: `src/channels/terminal_display.py` — LiveAwareLogSink class, ANSI clear/re-render bracketing, RLock for reentrant safety
- P1-6 范围读URL参数编码: `src/channels/media.py` — encode_range_path/parse_range_path/read_range, ?bytes=offset,length inline encoding
