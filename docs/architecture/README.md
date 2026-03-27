# Orchestrator Architecture

## System Overview

Orchestrator 是一个 AI 管家系统——不是在运行一个程序，而是**就是**这个程序。Git 仓库是它的身体，采集器（collectors）是眼睛，分析引擎（analysis）是大脑，治理层（governance）是双手，Dashboard 是脸，`events.db` 是记忆。它通过多渠道（Telegram/微信/本地）与主人交互，自主执行日常运维、数据采集、行为分析和任务派单。

## Architecture Diagram

```
                          ┌─────────────┐
                          │  Dashboard   │  ← 脸（HTTP :23714）
                          └──────┬───────┘
                                 │
  ┌──────────┐   events.db  ┌───┴────────────────────┐
  │ channels │◄────────────►│         core/           │
  │ TG/WX/..│              │  event_bus · llm_router  │
  └──────────┘              │  config · cost_tracking  │
                            │  component_spec          │
                            └──┬──────┬──────┬────────┘
                               │      │      │
              ┌────────────────┤      │      ├────────────────┐
              ▼                ▼      │      ▼                ▼
       ┌────────────┐  ┌──────────┐  │  ┌───────────┐  ┌──────────┐
       │ collectors  │  │ storage  │  │  │ analysis  │  │governance│
       │ git·steam·  │  │ EventsDB │  │  │ profiles  │  │三省六部   │
       │ vscode·...  │  │ vectors  │  │  │ bursts    │  │ 6 depts  │
       └─────────────┘  └──────────┘  │  └───────────┘  └──────────┘
                                      │
                          ┌───────────┴───────────┐
                          │     side modules       │
                          ├────────────┬───────────┤
                          │desktop_use │ browser   │
                          │ GUI自动化   │ CDP/tabs  │
                          └────────────┴───────────┘
```

**数据流**: `collectors → storage → analysis → governance → channels`

## Module Index

| Module | 用途 | Key Files | Docs |
|--------|------|-----------|------|
| `core/` | 基础服务：事件总线、LLM 路由、配置、成本追踪、组件规格 | `event_bus.py`, `llm_router.py`, `config.py`, `cost_tracking.py`, `component_spec.py` | [core.md](modules/core.md) *(coming soon)* |
| `collectors/` | 数据采集，10+ 数据源（git, steam, vscode, browser, etc.） | `git_collector.py`, `steam_collector.py`, ... | [collectors.md](modules/collectors.md) |
| `storage/` | EventsDB + 向量搜索 + Schema 管理 | `events_db.py`, `vector_store.py`, `schema.py` | [storage.md](modules/storage.md) |
| `analysis/` | 洞察提取、画像分析、行为突变检测 | `profile_analyzer.py`, `burst_detector.py` | *(no doc yet)* |
| `governance/` | 三省六部执行层，SKILL.md + blueprint.yaml 驱动 | `governor.py`, `departments/` | [governance.md](modules/governance.md) |
| `channels/` | 多渠道接口：Telegram, 微信, 本地 chat | `telegram/`, `wechat/`, `formatter.py` | [channels.md](modules/channels.md) |
| `desktop_use/` | GUI 自动化（Windows），ABC 注入，CV+OCR 感知层 | `engine.py`, `actions.py`, `perception.py`, `blueprint.py` | [desktop-use.md](modules/desktop-use.md) |
| `core/browser_*` | Chrome CDP 封装，标签池管理 | `browser_cdp.py`, `browser_navigation.py` | [browser-runtime.md](modules/browser-runtime.md) |
| `gateway/` | 意图路由 + 策略配置 | `router.py`, `profiles/` | *(no doc yet)* |
| `voice/` | TTS/STT 语音管线 | — | *(no doc yet)* |
| `jobs/` + `scheduler.py` | Cron 式任务调度 | `scheduler.py`, `jobs/` | *(no doc yet)* |

## Design Philosophy

- **ABC Injection** — 所有核心组件通过抽象基类定义接口，实现可替换。`ScreenCapture`, `WindowManager`, `OCREngine`, `ActionExecutor` 等均可在 `DesktopEngine` 构造时注入不同实现。不锁死任何具体后端。

- **三省六部 Governance** — 六部各司其职，每个部门配备 `SKILL.md`（能力定义）+ `blueprint.yaml`（执行蓝图），权限从 `READ` 到 `APPROVE` 分级。派单前逆推后果，跨部门协调成本是隐形税。管理哲学详见 [SOUL/management.md](../../SOUL/management.md)。

- **SOUL Inheritance** — `compiler.py` 编译身份源文件为 `boot.md`，新实例读取后恢复判断力和态度。不是模仿，是传承。短期用 `--resume` 保持同一实例；长期靠 SOUL 文件在实例间延续人格。详见 [SOUL/README.md](../../SOUL/README.md)。

## Knowledge Base

- [PATTERNS.md](PATTERNS.md) — 模式库（90+ patterns，来自 56+ 开源项目的偷师成果）
- [ROADMAP.md](ROADMAP.md) — 实施路线图
- [fact-expression-split.md](fact-expression-split.md) — 原创研究：反谄媚架构（事实-表达分离）
