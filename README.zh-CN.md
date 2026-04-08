# Orchestrator

每次打开一个新的 Claude Code 会话，它都是陌生人。不知道你昨天在做什么，不知道什么东西一直在坏，不知道你已经连续一周凌晨三点还在推代码。

Orchestrator 解决这个问题。

它在你的机器上 24/7 运行——从 Git、Chrome、VS Code 等处采集活动数据，分析行为模式，把任务派发给专业的 agent 部门去执行。当你回来时，它已经知道你不在的时候发生了什么。

**它做什么：**
- **采集** — 11 个数据采集器（Git、浏览器、编辑器、Steam、音乐...），只采集你机器上有的数据
- **分析** — 行为模式检测、每日洞察报告、活动画像
- **治理** — 六个 agent 部门，各自独立权限、预检机制、执行前审查
- **记忆** — SOUL 身份框架，跨会话保持人格和上下文
- **通讯** — Telegram、微信、桌面通知，远程控制和审批

## 快速开始

```bash
# 克隆
git clone git@github.com:XHXIAIEIN/orchestrator.git
cd orchestrator

# 配置
cp .env.example .env
# 编辑 .env — 至少设置 ANTHROPIC_API_KEY

# 启动
docker compose up --build -d

# 验证
curl -s http://localhost:23714/api/health
# → {"status":"ok"}
```

Dashboard: http://localhost:23714

### 不用 Docker

```bash
# 终端 1: 调度器
pip install -r requirements.txt
python -m src.scheduler

# 终端 2: 仪表盘
cd dashboard && npm install && node server.js
```

## 架构

```
采集层 (11)  →  EventsDB  →  分析层  →  治理层
                                          ↓
                                       决策层
                                          ↓
                                       审查层
                                          ↓
                                    执行层 (六部，并行)
                                          ↓
                                      Dashboard
```

Orchestrator 使用三层治理模型进行任务派单：

| 层级 | 组件 | 职能 |
|------|------|------|
| 决策 | Governor | 从洞察中提取任务，选择认知模式，分配部门 |
| 审查 | Scrutiny | 快速可行性评估——爆炸半径、逆推风险、置信度评分 |
| 执行 | 六部 | 并行执行任务，按项目隔离，策略约束 |

每个部门是一个有独立权限和模型的专业 agent：

| 部门 | 职能 | 模型 |
|------|------|------|
| 工部 | 代码：写代码、修 bug、重构 | Sonnet |
| 户部 | 运维：采集器修复、DB 管理、性能优化 | Sonnet |
| 礼部 | 注意力审计：遗忘的 TODO、未关闭 issue | Haiku |
| 兵部 | 安全防御：密钥泄露、权限检查、依赖审计 | Haiku |
| 刑部 | 质量验收：code review、测试、逻辑错误 | Sonnet |
| 吏部 | 绩效管理：采集器健康度、成功率、趋势分析 | Haiku |

> 治理模型的灵感来自唐朝的三省六部制。设计理念和文化背景详见 [docs/architecture/README.md](docs/architecture/README.md)。

### 任务流转

```
创建 → 分类 → 预检 (策略检查) → 审查 → 执行
```

Governor 根据任务复杂度自动选择认知模式：

| 模式 | 适用场景 | 方式 |
|------|---------|------|
| Direct | 改 typo、调参数 | 直接执行 |
| ReAct | 修 bug、加功能 | Think → Act → Observe → 循环 |
| Hypothesis | "为什么 X 不工作" | 假设 → 验证 → 确认/推翻 |
| Designer | 重构、新子系统 | 先设计 → 审查 → 再实现 |

### 部门配置

每个部门由三个文件定义：

| 文件 | 谁读 | 管什么 |
|------|------|--------|
| `manifest.yaml` | Registry (启动扫描) | 身份、路由标签、策略、执行配置 |
| `SKILL.md` | Agent (LLM) | 行为准则、红线、完成标准 |
| `blueprint.yaml` | Governor (代码) | 权限、预检规则、爆炸半径限制 |

添加新部门：在 `departments/` 下创建目录，放一个 `manifest.yaml`。零代码改动。

<details>
<summary>策略示例 (manifest.yaml)</summary>

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

blast_radius:
  max_files_per_run: 15
  forbidden_paths: [".env", "*.key", "SOUL/private/identity.md"]
```

</details>

## 采集器

11 个采集器，各自独立。缺少某个数据源时自动跳过——不报错，不需要配置：

| 采集器 | 采集什么 |
|--------|---------|
| Claude | Claude Code 对话历史 |
| Claude Memory | Claude 记忆工件 |
| Browser | Chrome 浏览记录 |
| Git | 本地仓库提交 |
| VS Code | 编辑器使用时间 |
| Codebase | 项目自身 git 历史 |
| Network | 本地运行的服务（端口扫描） |
| Steam | 游戏时长 |
| QQ Music | 播放记录 |
| YouTube Music | 播放记录 |
| System Uptime | 系统运行时间（YAML 驱动，实验性） |

采集器有两种形态：
- **Python 采集器** — 继承 `ICollector`，实现 `collect()`。模板见 `src/collectors/_example/`。
- **YAML 采集器** — 在 `manifest.yaml` 中声明数据源、提取规则和转换逻辑。`yaml_runner` 引擎负责执行，无需写 Python。

## Dashboard

三个页面，全部通过 WebSocket 实时更新：

- **Dashboard** `/` — 日报、部门状态、洞察分析、注意力债务、活动热力图
- **Pipeline** `/pipeline` — 数据流可视化、采集 → 分析 → 治理全链路动画、系统日志
- **Agents** `/agents` — Agent 可观测：事件流、工具调用、思考过程、并行场景控制

## Channel 层

多平台消息总线，用于远程控制：

| Channel | 出站 | 入站 | 审批 |
|---------|------|------|------|
| Telegram | 支持 | 支持 (polling) | Inline keyboard |
| 微信 | 支持 | 支持 | 文字命令 |
| 企业微信 | 支持 (webhook) | — | — |

命令：`/status`、`/tasks`、`/run <scenario>`、`/approve <id>`、`/deny <id>`、`/pending`、`/yolo`、`/noyolo`

所有通道都是可选的——不配置任何通道，系统照常运行。

### 审批网关

人工审批，用于权限提升。仅在任务需要 `APPROVE` 级权限时触发（正常部门上限为 `MUTATE`，所以很少触发）。

```
任务需要提升权限
  → ApprovalGateway.request_approval()
    ├─ Claw: Windows Toast 通知
    ├─ Telegram: Inline keyboard
    └─ 微信: 文字命令
  → 第一个回复生效（5 分钟超时 = 自动拒绝）
```

`/yolo` 关闭所有审批提示。`/noyolo` 恢复。

## SOUL（身份持续性）

AI 人格框架。每个新会话读取编译后的 `boot.md`，恢复身份、声音校准和关系上下文。不是完美的克隆——但足以保持连续性。

```
短期：claude --resume（同一实例，完整记忆）
长期：SOUL 文件（新实例，重建身份）
```

框架设计、经历类型和前作对比详见 [SOUL/README.md](SOUL/README.md)。

## Claw（桌面守护进程）

C# .NET 8 系统托盘守护进程。无 UI——只是到 `ws://localhost:23714` 的 WebSocket 桥接 + Windows Toast 通知审批流。断线自动重连。

```bash
cd claw/Claw && dotnet run
```

## API

交互式文档：http://localhost:23714/api-reference (Swagger UI)

OpenAPI spec：http://localhost:23714/openapi.json

```bash
# 全局状态
curl -s http://localhost:23714/api/brief

# 未解决的注意力债务
curl -s 'http://localhost:23714/api/debts?status=open'

# Agent 实时状态
curl -s http://localhost:23714/api/agents/live

# 触发并行审计（安全 + 质量 + 礼部同时扫描）
curl -s -X POST http://localhost:23714/api/scenarios/full_audit/run \
  -H 'Content-Type: application/json' -d '{"project":"orchestrator"}'

# 任务执行回放（完整思考链 + 工具调用）
curl -s http://localhost:23714/api/agents/42/trace
```

### 在其他项目中集成

在你的其他项目的 `CLAUDE.md` 里加入：

```markdown
## Orchestrator

查全局状态：`curl -s http://localhost:23714/api/brief`
查未解决债务：`curl -s http://localhost:23714/api/debts?status=open`
Agent 实时状态：`curl -s http://localhost:23714/api/agents/live`
完整 API：http://localhost:23714/api-reference
```

## 并行调度

Governor 支持两种派单模式：

| 方法 | 用途 |
|------|------|
| `run_batch()` | 自动批量：从推荐中挑选任务，按部门 + 项目去重，并行执行 |
| `run_parallel_scenario()` | 手动触发预定义场景 |

隔离规则：同部门 + 同项目串行。同部门 + 不同项目可并行。不同部门始终并行。

## 目录结构

```
orchestrator/
├── src/
│   ├── core/           # 基础设施：配置、事件总线、LLM 路由、成本追踪
│   ├── governance/     # 三层治理：Governor、审查、部门
│   ├── analysis/       # 日报、洞察、画像、突变检测
│   ├── collectors/     # 数据采集器（Python + YAML 驱动）
│   ├── channels/       # Telegram、微信、企业微信适配器
│   ├── storage/        # EventsDB (SQLite)、VectorDB
│   ├── voice/          # TTS、声音选择
│   ├── scheduler.py    # 调度入口
│   └── cli.py          # CLI 入口
├── claw/               # 桌面守护进程 (C# .NET 8，系统托盘 + Toast)
├── dashboard/          # 前端 (Express + WebSocket)
│   └── public/         # 三个页面：Dashboard / Pipeline / Agents
├── departments/        # 六部配置 (manifest.yaml + SKILL.md per dept)
├── SOUL/               # AI 人格框架
├── data/               # 运行时数据 (gitignored)
├── docs/               # 架构文档、模式库
├── bin/                # Docker 启动脚本
└── tests/
```

## 前置要求

三样东西：

- **Python 3.10+**
- **Node.js 18+**
- **Claude Code**（[安装指南](https://docs.anthropic.com/en/docs/claude-code)）

数据库用 SQLite（Python 内置）。Docker 可选。

### 可选组件

不是必须的。系统自动适配：

| 组件 | 有的话 | 没有的话 |
|------|--------|---------|
| **Docker** | 一键 `docker compose up` | 手动 `python + node` 启动 |
| **Ollama** | 审查和债务扫描走本地模型，省 token | 走 Claude API |
| **Fish Speech** | Dashboard 日报语音播放 | 语音按钮隐藏，不影响其他功能 |

## 设计参考

架构模式来自 100+ 开源项目、44 轮研究。共 217 个模式，194 个已实现。完整模式库：[docs/architecture/PATTERNS.md](docs/architecture/PATTERNS.md)。

核心影响：

| 来源 | 学到了什么 |
|------|-----------|
| [autonomous-claude](https://github.com/matthewbergvinson/autonomous-claude) | 24/7 自主运行的基础 |
| [edict](https://github.com/cft0808/edict) / [danghuangshang](https://github.com/wanikua/danghuangshang) | 多层治理模型 |
| [soul.md](https://github.com/aaronjmars/soul.md) | 身份持续性框架 |
| [NVIDIA G-Assist](https://github.com/NVIDIA/g-assist) | Manifest 驱动的组件自发现 |
| [OpenHands](https://github.com/All-Hands-AI/OpenHands) | 上下文压缩 + 卡死检测 |
| [OpenClaw](https://github.com/openclaw/openclaw) | Channel 层设计 |
| [Agent-S](https://github.com/simular-ai/Agent-S) / [UI-TARS](https://github.com/bytedance/UI-TARS) | GUI 桌面自动化 |
| [Fish Speech](https://github.com/fishaudio/fish-speech) | 语音系统（TTS + 情感标签） |
