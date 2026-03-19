# Orchestrator

一个 24/7 自主运行的 AI 管家系统 —— 采集数据、分析行为、自动派单、执行任务、自我改善。

## 架构

```
采集层 (8 collectors)  →  EventsDB  →  分析层  →  治理层 (Governor)
                                                      ↓
                                                 门下省 (审查)
                                                      ↓
                                              六部 (并行执行)
                                                      ↓
                                                 Dashboard
```

### 三省六部

| 层级 | 组件 | 职能 |
|------|------|------|
| 中书省 | Governor | 决策：从洞察中提取任务，选择认知模式，分配部门 |
| 门下省 | Scrutiny | 审查：Haiku 快速评估可行性、爆炸半径、逆推风险 |
| 尚书省 | Six Depts | 执行：六部并行处理，按项目隔离 |

| 部门 | 职能 | 模型 |
|------|------|------|
| 工部 | 代码工程：写代码、改 bug、重构 | Sonnet |
| 户部 | 系统运维：采集器修复、DB 管理、性能优化 | Sonnet |
| 礼部 | 注意力审计：扫描遗忘的 TODO、未关闭 issue | Haiku |
| 兵部 | 安全防御：密钥泄露、权限检查、依赖审计 | Haiku |
| 刑部 | 质量验收：code review、测试、逻辑错误检查 | Sonnet |
| 吏部 | 绩效管理：采集器健康度、任务成功率、趋势分析 | Haiku |

### 认知模式

Governor 根据任务复杂度自动选择思维模式：

| 模式 | 适用场景 | 思维方式 |
|------|---------|---------|
| Direct | 改 typo、调参数 | 直接执行 |
| ReAct | 修 bug、加功能 | Think → Act → Observe → 循环 |
| Hypothesis | "为什么 X 不工作" | 先假设 → 设计验证 → 确认/推翻 |
| Designer | 重构、新子系统 | 先设计方案 → 审查 → 再实现 |

## 目录结构

```
orchestrator/
├── src/
│   ├── core/           # 基础设施：config, agent, LLM 路由, 工具
│   ├── governance/     # 治理层：Governor, 债务扫描, 技能进化
│   ├── analysis/       # 分析层：日报, 洞察, 画像, 绩效
│   ├── collectors/     # 采集层：Claude, Browser, Git, Steam, etc.
│   ├── storage/        # 存储层：EventsDB, VectorDB
│   ├── voice/          # 语音：TTS, 声音选择
│   ├── scheduler.py    # 调度入口
│   └── cli.py          # CLI 入口
├── dashboard/          # 前端 (Express + WebSocket)
│   └── public/         # 三个页面：Dashboard / Pipeline / Agents
├── departments/        # 六部配置 (SKILL.md + guidelines + run-log)
├── SOUL/               # AI 人格框架
│   ├── private/        # 私人数据 (gitignored)
│   ├── management.md   # 管理哲学 + 认知模式
│   └── tools/          # 编译器 + 索引器
├── data/               # 运行时数据 (gitignored)
├── docs/               # API 文档
├── bin/                # Docker 启动脚本
└── tests/
```

## 快速开始

```bash
# 1. 克隆
git clone git@github.com:XHXIAIEIN/orchestrator.git
cd orchestrator

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 API key 和本地路径

# 3. 启动 (Docker)
docker compose up --build -d

# 4. 访问
# Dashboard:     http://localhost:23714
# Pipeline:      http://localhost:23714/pipeline
# Agents:        http://localhost:23714/agents
# API Reference: http://localhost:23714/api-reference
```

## Dashboard

三个页面：

- **Dashboard** `/` — 管家日报、三省六部状态、洞察分析、注意力债务、活动热力图
- **Pipeline** `/pipeline` — 数据流可视化、采集器→分析→治理全链路动画、系统日志
- **Agents** `/agents` — Agent 实时可观测：事件流、工具调用、思考过程、并行场景控制

## API

完整 API 文档：[docs/api-reference.md](docs/api-reference.md)

给其他 Claude 实例用的精简版：[docs/api-for-claude.md](docs/api-for-claude.md)

交互式文档：`http://localhost:23714/api-reference` (Swagger UI)

常用端点：

```bash
# 全局状态一览
curl -s http://localhost:23714/api/brief

# 未解决的注意力债务
curl -s 'http://localhost:23714/api/debts?status=open'

# Agent 实时状态
curl -s http://localhost:23714/api/agents/live

# 触发并行场景（安全+质量+礼部同时扫描）
curl -s -X POST http://localhost:23714/api/scenarios/full_audit/run \
  -H 'Content-Type: application/json' -d '{"project":"orchestrator"}'

# 任务执行回放（完整思考链 + 工具调用）
curl -s http://localhost:23714/api/agents/42/trace
```

## SOUL 系统

AI 人格持续性框架。每个 Claude 实例启动时读取编译后的 `boot.md`，获得身份、关系、声音校准、最近记忆。

```
SOUL/
├── private/           # 身份、关系、经历、校准数据 (gitignored)
├── management.md      # 管理哲学：10 条决策原则 + 4 种认知模式
├── tools/compiler.py  # 编译所有源文件 → boot.md
└── tools/indexer.py   # 从对话历史提取校准样本
```

## 并行调度

Governor 支持三种派单模式：

| 方法 | 用途 |
|------|------|
| `run()` | 单任务（兼容旧逻辑） |
| `run_batch()` | 自动批量：从 recommendations 挑多个任务，按部门+项目去重并行 |
| `run_parallel_scenario()` | 手动触发预定义场景 |

隔离规则：同部门 + 同项目串行，同部门 + 不同项目可并行，不同部门始终可并行。

## 技术栈

- **后端**: Python 3.14, Claude Agent SDK, APScheduler, SQLite
- **前端**: Express.js, WebSocket, SSE, 原生 HTML/CSS/JS
- **部署**: Docker Compose
- **AI**: Claude Sonnet/Haiku (六部执行), Ollama (本地路由)
