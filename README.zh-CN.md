# Orchestrator

一个 24/7 自主运行的 AI 管家系统 —— 采集数据、分析行为、自动派单、执行任务、自我改善。

## 架构

```
采集层 (8 collectors)  →  EventsDB  →  分析层  →  治理层 (Governor)
                                                      ↓
                                                 预检 (Blueprint)
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
| 尚书省 | Six Depts | 执行：六部并行处理，按项目隔离，Blueprint 策略约束 |

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

### Blueprint 系统

每个部门有三层配置文件：

| 文件 | 谁读 | 管什么 |
|------|------|--------|
| `manifest.yaml` | Registry (启动时扫描) | 身份、语义标签、意图路由、策略、执行配置 —— 单一注册源 |
| `SKILL.md` | Agent (LLM) | 身份、行为准则、红线、完成标准 |
| `blueprint.yaml` | Governor (代码) | 策略、权限、预检规则、生命周期配置 |

添加新部门只需要一个目录 + `manifest.yaml`，零代码改动。

任务派单五阶段生命周期（借鉴 NemoClaw）：

```
Create → Classify → Preflight(Blueprint) → Scrutinize(门下省) → Execute
```

Blueprint 声明式策略示例：

```yaml
policy:
  allowed_tools: [Bash, Read, Edit, Write, Glob, Grep]
  denied_paths: [".env", "*.key", "data/events.db"]
  can_commit: true
  read_only: false

preflight:
  - check: cwd_exists
  - check: skill_exists
  - check: disk_space
    target: "100"
```

## 目录结构

```
orchestrator/
├── src/
│   ├── core/           # 基础设施：config, agent, LLM 路由, 工具
│   ├── governance/     # 治理层：Governor, 债务扫描, 技能进化
│   ├── analysis/       # 分析层：日报, 洞察, 画像, 绩效
│   ├── collectors/     # 采集层：Claude, Browser, Git, Steam, etc.
│   ├── channels/       # Channel 层：Telegram, WeChat, 企业微信适配器
│   ├── storage/        # 存储层：EventsDB, VectorDB
│   ├── voice/          # 语音：TTS, 声音选择
│   ├── scheduler.py    # 调度入口
│   └── cli.py          # CLI 入口
├── claw/               # 桌面守护进程 (C# .NET 8，系统托盘 + Toast 审批)
├── dashboard/          # 前端 (Express + WebSocket)
│   └── public/         # 三个页面：Dashboard / Pipeline / Agents
├── departments/        # 六部配置 (manifest.yaml + SKILL.md + blueprint.yaml + run-log)
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
# 编辑 .env：
#   - ANTHROPIC_API_KEY: 你的 Anthropic API key
#   - 其余路径根据你的操作系统调整（.env.example 里有 Windows/macOS/Linux 示例）

# 3. 创建数据目录
mkdir -p data SOUL/private

# 4. 启动 (Docker)
docker compose up --build -d

# 5. 验证
curl -s http://localhost:23714/api/health
# 返回 {"status":"ok"} 表示启动成功

# 6. 访问
# Dashboard:     http://localhost:23714
# Pipeline:      http://localhost:23714/pipeline
# Agents:        http://localhost:23714/agents
# API Reference: http://localhost:23714/api-reference
# OpenAPI Spec:  http://localhost:23714/openapi.json
```

### 不用 Docker

```bash
# 终端 1: Python 调度器
pip install -r requirements.txt
python -m src.scheduler

# 终端 2: Node 仪表盘
cd dashboard && npm install && node server.js
```

### 在其他项目中集成

在你的其他项目的 `CLAUDE.md` 里加入：

```markdown
## Orchestrator

查全局状态：`curl -s http://localhost:23714/api/brief`
查未解决债务：`curl -s http://localhost:23714/api/debts?status=open`
Agent 实时状态：`curl -s http://localhost:23714/api/agents/live`
完整 API：见 http://localhost:23714/api-reference
```

## Dashboard

三个页面：

- **Dashboard** `/` — 管家日报、三省六部状态、洞察分析、注意力债务、活动热力图
- **Pipeline** `/pipeline` — 数据流可视化、采集器→分析→治理全链路动画、系统日志
- **Agents** `/agents` — Agent 实时可观测：事件流、工具调用、思考过程、并行场景控制

## Channel 层

多平台消息总线。通过统一的 `ChannelMessage` 接口实现出站事件和入站命令。

| Channel | 出站 | 入站 | 审批按钮 |
|---------|------|------|---------|
| Telegram | ✓ | ✓ (polling) | Inline keyboard |
| WeChat | ✓ | ✓ | 文字命令 |
| 企业微信 | ✓ (webhook) | — | — |

命令：`/status`、`/tasks`、`/run <scenario>`、`/approve <id>`、`/deny <id>`、`/pending`、`/yolo`、`/noyolo`

## 审批网关

多通道人工审批，用于权限提升。仅在 `blueprint.authority >= APPROVE` 或任务标记 `requires_approval: true` 时触发。正常运行中所有部门权限上限为 MUTATE，不会触发审批。

```
执行层需要 APPROVE 权限
  → ApprovalGateway.request_approval()
    ├─ Claw: Windows Toast（批准/拒绝按钮）
    ├─ Telegram: Inline keyboard（批准/拒绝）
    └─ WeChat: 文字命令
  → 第一个回复生效（5 分钟超时 = 自动拒绝）
  → 执行层继续或中止
```

- `/yolo` — 关闭所有审批提示，自动批准一切
- `/noyolo` — 恢复审批流程
- 所有组件可选（通过 `try/except ImportError` 解耦）

## Claw（桌面守护进程）

C# .NET 8 系统托盘守护进程 — 无 UI，纯 WebSocket 桥接 + Windows Toast 通知。连接 `ws://localhost:23714`，断线自动重连。

```bash
cd claw/Claw && dotnet run
```

## API

交互式文档：`http://localhost:23714/api-reference` (Swagger UI)

OpenAPI spec：`http://localhost:23714/openapi.json`

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

Governor 支持两种派单模式：

| 方法 | 用途 |
|------|------|
| `run_batch()` | 自动批量：从 recommendations 挑多个任务，按部门+项目去重并行 |
| `run_parallel_scenario()` | 手动触发预定义场景 |

隔离规则：同部门 + 同项目串行，同部门 + 不同项目可并行，不同部门始终可并行。

## 前置要求

只需要三样东西：

- **Python 3.10+**
- **Node.js 18+**
- **Claude Code**（[安装指南](https://docs.anthropic.com/en/docs/claude-code)）

数据库用 SQLite（Python 内置），不需要额外安装。Docker 可选。

### 可选组件

以下组件不是必须的，系统会自动适配：

| 组件 | 有的话 | 没有的话 |
|------|--------|---------|
| **Docker** | 一键 `docker compose up` 启动 | 手动 `python -m src.scheduler` + `node server.js` |
| **Ollama** | 门下省审查、债务扫描走本地模型，省 token | 自动走 Claude API |
| **Fish Speech** | Dashboard 管家日报可以语音播放 | 语音按钮不可用，不影响其他功能 |

### 采集器

8 个采集器各自独立，只采集你机器上有的数据。缺少某个数据源时该采集器自动跳过，不报错：

| 采集器 | 采集什么 |
|--------|---------|
| Claude | Claude Code 对话历史 |
| Browser | Chrome 浏览记录 |
| Git | 本地 Git 仓库提交 |
| VS Code | 编辑器使用时间 |
| Steam | 游戏时长 |
| QQ Music | 播放记录 |
| Network | 本地运行的服务（端口扫描） |
| Codebase | 项目自身的 git 历史 |

## 设计参考

100+ 开源项目、44 轮偷师的模式研究。217 个模式（194 个已实现）。完整模式库见 [docs/architecture/PATTERNS.md](docs/architecture/PATTERNS.md)。

核心来源：

| 来源 | 贡献 |
|------|------|
| [autonomous-claude](https://github.com/matthewbergvinson/autonomous-claude) | 24/7 自主运行的根基 |
| [edict](https://github.com/cft0808/edict) / [danghuangshang](https://github.com/wanikua/danghuangshang) | 三省六部治理模型 |
| [soul.md](https://github.com/aaronjmars/soul.md) | SOUL 身份系统 |
| [NVIDIA G-Assist](https://github.com/NVIDIA/g-assist) | Manifest 驱动的部门自发现 |
| [OpenHands](https://github.com/All-Hands-AI/OpenHands) | 上下文压缩 + 卡死检测 |
| [OpenClaw](https://github.com/openclaw/openclaw) | Channel 层（Telegram / WeChat） |
| [Agent-S](https://github.com/simular-ai/Agent-S) / [UI-TARS](https://github.com/bytedance/UI-TARS) | GUI 桌面控制引擎 |
| [Fish Speech](https://github.com/fishaudio/fish-speech) | 语音系统（TTS + 情感标签） |
