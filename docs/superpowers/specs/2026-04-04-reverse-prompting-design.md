# Reverse Prompting — TG Bot 从被动变主动

> 设计日期：2026-04-04
> 来源：R23 proactive-agent 深挖 + self-improving proactivity 模块
> 状态：Design Approved

---

## 一句话

Orchestrator 的 TG bot 从"等用户问才答"变成"该说的时候自己开口"——基于系统事件、用户行为和项目进展主动发起对话。

---

## 设计决策记录

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 推送通道 | 复用现有 TG 私聊 | 单用户，分频道多余；同一 chat 可直接回复追问形成闭环 |
| 实施节奏 | 三阶段（事件触发 → 定时报告 → Growth Loops） | 事件触发 ROI 最高，定时报告容易变噪音 |
| 静默策略 | 时间窗口 + 频率上限 + 紧急穿透 + 手动静音 | 既不漏重要的，也不被琐碎的烦到 |
| 消息生成 | 分级：规则引擎（系统告警）/ 规则+LLM（行为/项目类） | 告警要快准，观察类要上下文和人味 |

---

## 架构总览

```
┌─────────────────────────────────────────────────────────┐
│                    Signal Sources                        │
│  HealthCheck │ EventsDB │ Git Collector │ Cron Results  │
└──────┬───────┴────┬─────┴──────┬────────┴───────┬───────┘
       │            │            │                │
       ▼            ▼            ▼                ▼
┌─────────────────────────────────────────────────────────┐
│              ProactiveEngine (新模块)                     │
│                                                         │
│  ┌───────────┐  ┌───────────┐  ┌──────────────────┐    │
│  │ Signal    │→ │ Throttle  │→ │ Message          │    │
│  │ Detector  │  │ Gate      │  │ Generator        │    │
│  │           │  │           │  │                  │    │
│  │ 12 rules  │  │ time win  │  │ A: template      │    │
│  │ threshold │  │ rate cap  │  │ B: rule + LLM    │    │
│  │ cooldown  │  │ /quiet    │  │ (by signal tier) │    │
│  └───────────┘  └───────────┘  └────────┬─────────┘    │
│                                         │               │
└─────────────────────────────────────────┼───────────────┘
                                          ▼
                                ┌───────────────────┐
                                │ TG Bot send_message│
                                │ (existing tg_api)  │
                                └───────────────────┘
```

---

## Phase 1: 事件触发型（MVP）

### 目标

检测到特定信号时主动推送，不需要用户发消息触发。

### 信号定义

#### Tier A — 系统告警（规则引擎，模板消息）

| ID | 信号 | 数据源 | 触发条件 | 冷却 | 模板 |
|----|------|--------|----------|------|------|
| S1 | 采集器连续失败 | `runs` 表 | 同一 collector 连续 ≥3 次 status=error | 6h | `⚠️ {collector} 连续失败 {n} 次，最后错误：{err}` |
| S2 | 容器异常 | `docker ps` / health check | 容器 restart count 增加 或 状态非 running | 1h | `🔴 容器 {name} 状态异常：{status}` |
| S3 | DB 膨胀 | `os.path.getsize()` | events.db > 50MB 或 增速 > 5MB/天 | 24h | `📦 events.db 已达 {size}MB，日增 {delta}MB` |
| S4 | Governor 任务连续失败 | `tasks` 表 | 连续 ≥3 个任务 status=failed | 3h | `❌ Governor 连续 {n} 个任务失败，最近：{summary}` |

#### Tier B — 用户行为观察（规则触发 + LLM 生成）

| ID | 信号 | 数据源 | 触发条件 | 冷却 | LLM 输入 |
|----|------|--------|----------|------|----------|
| S5 | 项目沉寂 | `codebase_collector` / git log | 项目 ≥5 天无 commit | 7d/项目 | 项目名 + 最后 commit 信息 + 最近相关对话 |
| S6 | 深夜活跃 | git commit timestamps | 凌晨 1-5 点有 ≥2 个 commit | 24h | commit 内容 + 项目名 |
| S7 | 重复操作模式 | `chat_messages` + `tasks` | 同类请求 ≥3 次/周 | 7d | 请求列表 + 可能的自动化方案 |

#### Tier C — 项目进展（规则触发 + LLM 生成）

| ID | 信号 | 数据源 | 触发条件 | 冷却 | LLM 输入 |
|----|------|--------|----------|------|----------|
| S8 | 批量任务完成 | `tasks` 表 | cron batch 内所有任务完成 | per batch | 任务列表 + 结果摘要 |
| S9 | 偷师成果 | git log on `steal/*` branches | steal 分支有新 commit | per round | commit messages + 偷师文档 |
| S10 | DEFER 项超期 | `docs/architecture/ROADMAP.md` + `proactive_tracker` 表 | DEFER 标记项 ≥14 天无相关 commit/对话 | 14d | defer 项描述 + 上次提及时间 |

#### Tier D — 外部信号（规则引擎，模板消息）

| ID | 信号 | 数据源 | 触发条件 | 冷却 | 模板 |
|----|------|--------|----------|------|------|
| S11 | GitHub 仓库活动 | GitHub API / webhook | 收到 star/issue/PR | 1h/仓库 | `⭐ {repo} 新增 {event_type}: {title}` |
| S12 | 依赖安全漏洞 | `pip audit` / `npm audit` | 发现 HIGH/CRITICAL 漏洞 | 24h | `🛡️ {package} 发现 {severity} 漏洞：{cve}` |

### 新模块：`src/proactive/`

```
src/proactive/
├── __init__.py
├── engine.py          # ProactiveEngine — 主循环
├── signals.py         # SignalDetector — 12 个信号检测器
├── throttle.py        # ThrottleGate — 静默策略
├── messages.py        # MessageGenerator — 模板 / LLM 生成
└── config.py          # 可配置参数（窗口、阈值、冷却）
```

### ProactiveEngine 主循环

```python
class ProactiveEngine:
    """主动推送引擎 — 定时扫描信号源，通过 throttle 后推送。"""

    def __init__(self, db: EventsDB, registry: ChannelRegistry, llm_router):
        self.detector = SignalDetector(db)
        self.throttle = ThrottleGate()
        self.generator = MessageGenerator(llm_router)
        self.registry = registry

    async def scan_cycle(self):
        """单次扫描周期 — 由 scheduler 每 5 分钟调用。"""
        signals = self.detector.detect_all()
        for signal in signals:
            if not self.throttle.should_send(signal):
                continue
            message = self.generator.generate(signal)
            self.registry.broadcast(ChannelMessage(
                text=message,
                event_type=f"proactive.{signal.id}",
                priority="HIGH" if signal.tier == "A" else "NORMAL",
            ))
            self.throttle.record_sent(signal)
```

### SignalDetector

```python
@dataclass
class Signal:
    id: str              # "S1" ~ "S12"
    tier: str            # "A" | "B" | "C" | "D"
    title: str           # 人类可读标题
    severity: str        # "critical" | "warning" | "info"
    data: dict           # 信号携带的上下文数据
    detected_at: datetime

class SignalDetector:
    """扫描所有数据源，返回当前活跃信号列表。"""

    def __init__(self, db: EventsDB):
        self.db = db
        self._detectors = [
            self._check_collector_failures,    # S1
            self._check_container_health,      # S2
            self._check_db_size,               # S3
            self._check_governor_failures,     # S4
            self._check_project_silence,       # S5
            self._check_late_night_activity,   # S6
            self._check_repeated_patterns,     # S7
            self._check_batch_completion,      # S8
            self._check_steal_progress,        # S9
            self._check_defer_overdue,         # S10
            self._check_github_activity,       # S11
            self._check_dependency_vulns,      # S12
        ]

    def detect_all(self) -> list[Signal]:
        signals = []
        for fn in self._detectors:
            try:
                result = fn()
                if result:
                    signals.extend(result if isinstance(result, list) else [result])
            except Exception as e:
                log.warning(f"proactive: detector {fn.__name__} failed: {e}")
        return signals
```

### ThrottleGate 静默策略

```python
class ThrottleGate:
    """四层过滤：时间窗口 → 频率上限 → 冷却期 → 手动静音。"""

    def __init__(self):
        self._quiet_mode = False          # /quiet 手动静音
        self._sent_log: dict[str, list[datetime]] = {}  # signal_id → 发送时间列表

    # 可配置参数
    ACTIVE_HOURS = (10, 23)               # 活跃时段 10:00-23:00
    MAX_PER_HOUR = 5                      # 每小时最多 5 条
    COOLDOWNS = {                         # 每个信号的冷却期（秒）
        "S1": 21600, "S2": 3600, "S3": 86400, "S4": 10800,
        "S5": 604800, "S6": 86400, "S7": 604800,
        "S8": 0, "S9": 0, "S10": 1209600,
        "S11": 3600, "S12": 86400,
    }

    def should_send(self, signal: Signal) -> bool:
        # 紧急穿透：Tier A + severity=critical 无视所有限制
        if signal.tier == "A" and signal.severity == "critical":
            return True

        # 手动静音
        if self._quiet_mode:
            return False

        # 时间窗口
        now = datetime.now()
        if not (self.ACTIVE_HOURS[0] <= now.hour < self.ACTIVE_HOURS[1]):
            self._queue_for_later(signal)
            return False

        # 频率上限
        recent = self._count_recent(minutes=60)
        if recent >= self.MAX_PER_HOUR:
            self._queue_for_later(signal)
            return False

        # 冷却期
        cooldown = self.COOLDOWNS.get(signal.id, 3600)
        if self._in_cooldown(signal.id, cooldown):
            return False

        return True
```

### MessageGenerator 分级生成

```python
class MessageGenerator:
    """根据信号 tier 选择生成策略。"""

    # Tier A/D: 模板（零延迟，零成本）
    TEMPLATES = {
        "S1": "⚠️ **{collector}** 连续失败 {count} 次\n最后错误：`{error}`",
        "S2": "🔴 容器 **{name}** 状态异常：{status}",
        "S3": "📦 events.db 已达 **{size_mb}MB**（日增 {delta_mb}MB）",
        "S4": "❌ Governor 连续 **{count}** 个任务失败\n最近：{last_summary}",
        "S11": "⭐ **{repo}** — {event_type}: {title}",
        "S12": "🛡️ **{package}** 发现 {severity} 漏洞：{cve_id}",
    }

    def generate(self, signal: Signal) -> str:
        if signal.tier in ("A", "D"):
            return self._from_template(signal)
        else:
            return self._from_llm(signal)

    def _from_template(self, signal: Signal) -> str:
        tpl = self.TEMPLATES[signal.id]
        return tpl.format(**signal.data)

    def _from_llm(self, signal: Signal) -> str:
        """Tier B/C: 规则触发 + LLM 润色。"""
        system = (
            "你是 Orchestrator，用户的 AI 管家和损友。"
            "根据以下观察生成一条简短的主动推送消息。"
            "要求：1) 说人话，带点损友味 2) 包含具体数据 "
            "3) 如果有建议就给，没有就不硬凑 4) 一条消息，不超过 200 字"
        )
        user_prompt = (
            f"信号类型：{signal.title}\n"
            f"数据：{json.dumps(signal.data, ensure_ascii=False)}\n"
            f"生成一条推送消息。"
        )
        # 走 Haiku — 便宜、快、够用
        return self.llm_router.generate(
            system=system, user=user_prompt,
            model="claude-3-5-haiku", max_tokens=256,
        )
```

### TG Bot 新命令

| 命令 | 作用 |
|------|------|
| `/quiet` | 进入免打扰模式（紧急告警仍穿透） |
| `/loud` | 恢复推送 |
| `/proactive` | 查看当前推送配置 + 最近 10 条推送历史 |
| `/proactive off` | 完全关闭主动推送 |
| `/proactive on` | 重新开启 |

### Scheduler 集成

```python
# scheduler.py — 新增 proactive scan job
from src.proactive.engine import ProactiveEngine

engine = ProactiveEngine(db=events_db, registry=registry, llm_router=router)
scheduler.add_job(engine.scan_cycle, "interval", minutes=5, id="proactive_scan")
```

扫描周期 5 分钟。Tier A 告警实际延迟 = 0~5 分钟（可接受，不是心跳监控）。

### 数据持久化

```sql
-- proactive_log: 记录所有推送（含被 throttle 拦截的）
CREATE TABLE IF NOT EXISTS proactive_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id   TEXT NOT NULL,          -- "S1" ~ "S12"
    tier        TEXT NOT NULL,          -- "A" | "B" | "C" | "D"
    severity    TEXT NOT NULL,
    data        TEXT,                   -- JSON
    message     TEXT,                   -- 生成的消息文本（被拦截时为 NULL）
    action      TEXT NOT NULL,          -- "sent" | "throttled" | "queued"
    reason      TEXT,                   -- throttle 拦截原因
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_proactive_signal ON proactive_log(signal_id, created_at);
```

---

## Phase 2: 定时报告

### 目标

周期性生成结构化报告，而非逐条推送。

### 报告类型

| 报告 | 频率 | 内容 | 生成方式 |
|------|------|------|----------|
| 晨报 | 每天 10:00 | 昨夜系统状态 + 采集成果 + 待办提醒 | LLM 摘要 |
| 周报 | 每周日 20:00 | 本周亮点 + 数据统计 + 趋势 + 建议 | LLM 深度分析 |
| 月报 | 每月 1 号 | 月度回顾 + 项目进展 + 演进方向 | LLM 长文 |

### 报告生成流程

```
Cron 触发 → 采集数据（EventsDB + git log + Qdrant）
          → 组装 context（任务统计 + 采集统计 + commit 摘要）
          → LLM 生成报告（Claude Haiku，max 1024 tokens）
          → 格式化为 Markdown
          → TG 推送（长消息自动分段）
```

### 与 Phase 1 的关系

Phase 2 的定时报告可以**吸收 Phase 1 中被 throttle 的 queued 信号**——攒了一天没发的观察，合并进晨报。这样既不浪费信息，也不增加噪音。

---

## Phase 3: Growth Loops

### 目标

从"通知型"进化为"成长型"——bot 通过三个闭环持续了解用户、识别模式、跟进决策。

### Loop 1: Curiosity（好奇心）

- **触发**：每次 TG 对话结束时，有 20% 概率附带一个了解用户的问题
- **问题来源**：`user_profile_deep.md` 中的空白字段 + 最近对话中的新话题
- **写入**：答案更新到 user_profile 相关 memory 文件
- **约束**：每天最多问 1 个；用户说"别问了"立刻停；不问隐私/情感类问题（反操控条款）

### Loop 2: Pattern Recognition（模式识别）

- **数据源**：Phase 1 的 `proactive_log` + `chat_messages` + `tasks`
- **检测**：同一类操作 ≥3 次/周 → 生成自动化提案
- **推送格式**：
  ```
  🔄 我发现你这周做了 3 次 "XXX"。
  要不要我写个自动化？选项：
  1) 好，搞一个
  2) 不用，这个每次不一样
  3) 先记着，以后再说
  ```
- **写入**：用户选择写入 `proactive_tracker` 表，阈值累积后晋升

### Loop 3: Outcome Tracking（决策跟进）

- **触发**：检测到对话中的决策信号（"就这样做"/"用方案 A"/"先不管 X"）
- **记录**：写入 `decisions` 表（决策内容 + 日期 + 项目 + 上下文）
- **跟进**：7 天后生成跟进推送（"上周你决定用方案 A 重构 XXX，进展如何？"）
- **生成**：LLM，基于决策内容 + 最近 git 活动判断是否有进展

### Growth Loops 数据表

```sql
-- proactive_tracker: 模式追踪
CREATE TABLE IF NOT EXISTS proactive_tracker (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern     TEXT NOT NULL,          -- 模式描述
    category    TEXT NOT NULL,          -- "automation" | "habit" | "preference"
    occurrences INTEGER DEFAULT 1,
    stage       TEXT DEFAULT 'tentative',  -- tentative | emerging | confirmed | archived
    last_seen   TEXT NOT NULL,
    user_choice TEXT,                   -- 用户回应
    created_at  TEXT NOT NULL
);

-- decisions: 决策跟进
CREATE TABLE IF NOT EXISTS decisions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    summary     TEXT NOT NULL,
    project     TEXT,
    context     TEXT,                   -- 决策时的对话上下文摘要
    follow_up_at TEXT,                  -- 预定跟进日期
    followed_up INTEGER DEFAULT 0,
    outcome     TEXT,                   -- 跟进结果
    created_at  TEXT NOT NULL
);
```

---

## 文件变更清单

### 新建

| 文件 | 用途 | Phase |
|------|------|-------|
| `src/proactive/__init__.py` | 模块入口 | 1 |
| `src/proactive/engine.py` | ProactiveEngine 主循环 | 1 |
| `src/proactive/signals.py` | SignalDetector — 12 个检测器 | 1 |
| `src/proactive/throttle.py` | ThrottleGate 静默策略 | 1 |
| `src/proactive/messages.py` | MessageGenerator 分级生成 | 1 |
| `src/proactive/config.py` | 可配置参数 | 1 |
| `src/proactive/reports.py` | 定时报告生成 | 2 |
| `src/proactive/growth.py` | Growth Loops 三环 | 3 |

### 修改

| 文件 | 变更 | Phase |
|------|------|-------|
| `src/storage/_schema.py` | 新增 proactive_log / proactive_tracker / decisions 表 | 1 |
| `src/storage/events_db.py` | 新增 proactive 相关 mixin 方法 | 1 |
| `src/scheduler.py` | 新增 proactive_scan job (5min) | 1 |
| `src/channels/telegram/handler.py` | 新增 /quiet /loud /proactive 命令 | 1 |
| `src/channels/chat/commands.py` | 注册新命令 | 1 |
| `src/scheduler.py` | 新增 daily/weekly/monthly 报告 job | 2 |
| `src/channels/chat/engine.py` | Curiosity Loop 注入点 | 3 |

---

## 实施节奏

| Phase | 内容 | 工作量 | 依赖 |
|-------|------|--------|------|
| **1a** | ProactiveEngine + Tier A 信号（S1-S4） + ThrottleGate + 模板消息 | 半天 | 无 |
| **1b** | Tier B/C 信号（S5-S10） + LLM 生成 + /quiet /loud 命令 | 半天 | 1a |
| **1c** | Tier D 信号（S11-S12） + proactive_log 持久化 | 半天 | 1a |
| **2** | 晨报 + 周报 + queued 信号合并 | 1 天 | Phase 1 |
| **3a** | Pattern Recognition Loop | 半天 | Phase 1 |
| **3b** | Outcome Tracking Loop | 半天 | Phase 1 |
| **3c** | Curiosity Loop | 半天 | Phase 2 |

**总计：~4 天**（Phase 1: 1.5 天, Phase 2: 1 天, Phase 3: 1.5 天）

---

## 约束与边界

1. **反噪音铁律**：宁可漏发，不可误发。ThrottleGate 的默认行为是拦截，不是放行。
2. **反操控条款**（继承自 self-improving boundaries）：
   - 不学习"什么能让用户更顺从"
   - 不利用情感触发点
   - Curiosity Loop 不问隐私/财务/医疗
3. **成本约束**：Phase 1 Tier B/C 每次扫描最多触发 2 条 LLM 生成（Haiku）。Phase 2 报告每次 1 次 LLM 调用。月成本 < $1。
4. **降级策略**：LLM 不可用时 Tier B/C 降级为模板消息（有数据但没人味），不 block 推送。
5. **用户主权**：`/proactive off` 是硬开关，关了就完全不推。不存在"为了你好所以我还是推一下"的逻辑。
