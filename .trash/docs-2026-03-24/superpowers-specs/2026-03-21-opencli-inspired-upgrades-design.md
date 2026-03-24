# OpenCLI 偷师升级方案

> 从 [jackwener/opencli](https://github.com/jackwener/opencli) 中提取的设计模式，适配到 Orchestrator 架构。
> 日期：2026-03-21

## 背景

OpenCLI 是一个将任意网站/应用统一为 CLI 命令的框架。其中几个设计模式对 Orchestrator 的采集器生态和 LLM 路由有直接启发：

| OpenCLI 模式 | Orchestrator 应用 |
|---|---|
| Manifest 预编译 + 自动发现 | 采集器动态扫描替代硬编码 dict |
| Adapter 接口 + metadata | ICollector 协议 + 能力声明 |
| Strategy Cascade | LLMRouter 自动降级探测 |
| Pipeline DSL (YAML) | 声明式采集器定义 |
| AI explore → synthesize 闭环 | 采集器声誉系统 + 未来 AI 自助生成 |
| CliError 统一错误层级 (code + hint) | 采集器异常分类 + 自动决策 |
| Worker Pool 并发限制器 | 采集器并行执行 |
| 三层测试 + Mock 工厂 | 采集器测试体系 |
| 统一日志分级 (stderr + verbose/debug) | 采集器可观测性 |
| doctor 连通性诊断 | health.py 增强 |

## 升级 1：ICollector 协议

### 问题

当前 9 个采集器没有统一基类，接口靠约定（`__init__(db)` + `collect() -> int`）。没有 metadata 声明，scheduler 不知道每个采集器需要什么环境变量、依赖什么外部资源、预期产出什么类型的事件。

### 设计

新增 `src/collectors/base.py`：

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from src.storage.events_db import EventsDB


@dataclass
class CollectorMeta:
    """采集器自我描述 — 灵感来自 OpenCLI 的 adapter metadata。"""
    name: str                          # 机器名，如 "git"
    display_name: str                  # 人类名，如 "Git 仓库采集器"
    category: str                      # "core" | "optional" | "experimental"
    env_vars: list[str] = field(default_factory=list)       # 依赖的环境变量
    requires: list[str] = field(default_factory=list)       # 外部依赖（"chrome", "git", "steam"）
    event_sources: list[str] = field(default_factory=list)  # 产出的 event source 标签
    default_enabled: bool = True       # 默认是否启用


class ICollector(ABC):
    """采集器统一协议。所有采集器必须继承此基类。"""

    def __init__(self, db: EventsDB, **kwargs):
        self.db = db

    @classmethod
    @abstractmethod
    def metadata(cls) -> CollectorMeta:
        """声明自己的能力和依赖。scheduler 用这个做自动发现和健康检查。"""
        ...

    @abstractmethod
    def collect(self) -> int:
        """执行采集。返回新增事件数，-1 表示失败。"""
        ...

    def preflight(self) -> tuple[bool, str]:
        """预检：检查依赖是否就绪。返回 (ok, reason)。
        默认实现检查 env_vars 和 requires。子类可覆盖。"""
        meta = self.metadata()
        for var in meta.env_vars:
            # env_vars 是"可选配置"不是"必须存在"，跳过
            pass
        return True, "ok"
```

### 迁移策略

- 所有现有采集器继承 `ICollector`，加 `metadata()` classmethod
- 不改变现有 `__init__` 签名（`db` + 各自的可选参数）
- `preflight()` 可选覆盖，默认通过

### 示例：GitCollector 迁移

```python
class GitCollector(ICollector):
    @classmethod
    def metadata(cls) -> CollectorMeta:
        return CollectorMeta(
            name="git",
            display_name="Git 仓库采集器",
            category="core",
            env_vars=["GIT_REPOS_ROOT", "GIT_PATHS"],
            requires=["git"],
            event_sources=["git"],
            default_enabled=True,
        )

    def __init__(self, db, search_paths=None, days_back=30):
        super().__init__(db)
        # ... 现有逻辑不变
```

## 升级 2：采集器自动发现

### 问题

`scheduler.py:_build_collectors()` 硬编码了 9 个 import + lambda 工厂函数。新增采集器要改 scheduler.py 的 import 和 dict。

### 设计

新增 `src/collectors/registry.py`：

```python
"""
采集器注册表 — 灵感来自 OpenCLI 的 Manifest 预编译。
动态扫描 src/collectors/ 下所有 ICollector 子类，按 metadata 注册。
"""
import importlib
import logging
from pathlib import Path
from src.collectors.base import ICollector, CollectorMeta

log = logging.getLogger(__name__)

_COLLECTORS_DIR = Path(__file__).parent


def discover_collectors() -> dict[str, type[ICollector]]:
    """扫描 src/collectors/ 下所有 *_collector.py，找到 ICollector 子类。"""
    registry = {}
    for py_file in _COLLECTORS_DIR.glob("*_collector.py"):
        module_name = f"src.collectors.{py_file.stem}"
        try:
            module = importlib.import_module(module_name)
        except Exception as e:
            log.warning(f"registry: failed to import {module_name}: {e}")
            continue

        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (isinstance(attr, type)
                    and issubclass(attr, ICollector)
                    and attr is not ICollector):
                try:
                    meta = attr.metadata()
                    registry[meta.name] = attr
                    log.debug(f"registry: discovered {meta.name} ({meta.display_name})")
                except Exception as e:
                    log.warning(f"registry: {attr_name}.metadata() failed: {e}")
    return registry


def build_enabled_collectors(db, env_overrides: dict = None) -> list[tuple[str, object]]:
    """构建启用的采集器实例列表。替代 scheduler._build_collectors()。

    启用逻辑：
    1. COLLECTOR_<NAME>=true/false 环境变量覆盖
    2. metadata().default_enabled 默认值
    3. metadata().category == "core" 默认启用
    """
    import os
    registry = discover_collectors()
    enabled = []

    for name, cls in registry.items():
        meta = cls.metadata()

        # 环境变量覆盖
        env_key = f"COLLECTOR_{name.upper()}"
        env_val = os.environ.get(env_key)
        if env_val is not None:
            is_on = env_val.lower() in ("true", "1", "yes")
        else:
            is_on = meta.default_enabled

        if not is_on:
            continue

        # 实例化（延迟，捕获异常）
        try:
            instance = cls(db=db)
            enabled.append((name, instance))
        except Exception as e:
            log.error(f"registry: {name} init failed: {e}")

    return enabled
```

### scheduler.py 改动

```python
# 删除 9 个 import 和 _build_collectors()
# 替换为：
from src.collectors.registry import build_enabled_collectors

def run_collectors():
    db = EventsDB(DB_PATH)
    enabled = build_enabled_collectors(db)
    # ... 后续逻辑不变，enabled 格式从 (name, factory) 变为 (name, instance)
```

### 预编译索引（可选，Phase 2）

当采集器数量 > 20 时，动态 import 可能变慢。届时可仿 OpenCLI 的 `build-manifest.ts`，生成 `collectors-manifest.json`：

```json
{
  "git": {"module": "src.collectors.git_collector", "class": "GitCollector", "category": "core"},
  "browser": {"module": "src.collectors.browser_collector", "class": "BrowserCollector", "category": "core"}
}
```

当前 9 个采集器不需要这个优化。

## 升级 3：Strategy Cascade（LLMRouter）

### 问题

当前 LLMRouter 的路由是硬编码的：每个 task_type 绑定一个固定后端 + 一个 fallback。没有"先试便宜的，不行再升级"的自动降级。

比如 `deep_analysis` 直接走 `claude-sonnet-4-6`，但有些简单的 deep_analysis（比如只有 3 个事件的日子）用 Haiku 就够了。反之，有些 `scrutiny` 任务复杂到 qwen3:32b 搞不定，但代码没有"升级到更强模型"的路径。

### 设计

灵感来自 OpenCLI 的 `cascade.ts`：从最便宜的策略开始试，逐级升级。

```python
# 新增：模型能力梯队
MODEL_TIERS = [
    {"name": "ollama/qwen3:32b",     "cost": 0,    "capability": 0.6, "multimodal": False},
    {"name": "claude-haiku-4-5",     "cost": 0.25, "capability": 0.7, "multimodal": False},
    {"name": "ollama/gemma3:27b",    "cost": 0,    "capability": 0.65,"multimodal": True},
    {"name": "claude-sonnet-4-6",    "cost": 3.0,  "capability": 0.9, "multimodal": True},
]

# 新增路由配置字段
ROUTES = {
    "scrutiny": {
        "cascade": ["ollama/qwen3:32b", "claude-haiku-4-5"],
        "min_capability": 0.5,
        "timeout": 45,
    },
    "deep_analysis": {
        "cascade": ["claude-haiku-4-5", "claude-sonnet-4-6"],
        "min_capability": 0.7,
        "timeout": 120,
    },
    # ...
}
```

### Cascade 逻辑

```python
def generate_cascade(self, prompt: str, task_type: str, **kwargs) -> tuple[str, dict]:
    """级联尝试：从便宜到贵，返回 (result, metadata)。

    升级条件：
    1. 模型不可达 → 下一级
    2. 输出太短（< MIN_RESPONSE_LEN）→ 下一级
    3. 输出包含 "I cannot" / "我无法" → 下一级（模型承认能力不足）

    metadata 包含实际使用的模型、尝试次数、总耗时。
    """
    route = ROUTES[task_type]
    cascade = route["cascade"]
    attempts = []

    for i, model_name in enumerate(cascade):
        tier = self._get_tier(model_name)
        try:
            result = self._call_model(model_name, prompt, route["timeout"], **kwargs)
            if self._is_valid_response(result):
                return result, {
                    "model": model_name,
                    "attempts": len(attempts) + 1,
                    "cascaded_from": [a["model"] for a in attempts],
                }
            attempts.append({"model": model_name, "reason": "low_quality"})
        except Exception as e:
            attempts.append({"model": model_name, "reason": str(e)})

    # 全部失败
    return "", {"model": None, "attempts": len(attempts), "all_failed": True}
```

### 兼容性

- `generate()` 方法签名不变，内部调用 `generate_cascade()`
- 旧的 `ROUTES` 格式仍然支持（没有 `cascade` 字段时走原有逻辑）
- 新增 `cascade_stats` 属性，记录每个 task_type 的实际模型使用分布（供 Dashboard 展示）

### 成本追踪

```python
@dataclass
class CascadeStats:
    task_type: str
    model_usage: dict[str, int]     # model_name → 使用次数
    cascade_rate: float             # 需要升级的比例
    avg_attempts: float             # 平均尝试次数
    total_cost_estimate: float      # 估算成本（基于 MODEL_TIERS.cost）
```

## 升级 4：YAML 声明式采集器

### 问题

写一个新采集器需要：写 Python 类、继承 ICollector、处理路径/去重/异常。对于简单的"读文件/解析 JSON/入库"场景，这些 boilerplate 太重了。

### 设计

灵感来自 OpenCLI 的 Pipeline DSL。用 YAML 声明采集逻辑，运行时由通用 Pipeline Runner 执行。

```yaml
# src/collectors/yaml/discord_presence.yaml
name: discord_presence
display_name: Discord 在线状态采集器
category: experimental
default_enabled: false

source:
  type: json_file
  path: "${APPDATA}/discord/Local Storage/leveldb/"
  # 或: type: command, cmd: "curl -s http://..."
  # 或: type: sqlite, path: "...", query: "SELECT ..."

extract:
  - field: last_activity
    pattern: "lastModified"
  - field: status
    jq: ".userSettings.status"

transform:
  dedup_key: "discord:${extract.last_activity}"
  source: "discord"
  category: "social"
  title: "Discord ${extract.status}"
  score: 0.3
  tags: ["discord", "social"]
```

### Pipeline Runner

新增 `src/collectors/yaml_runner.py`：

```python
class YAMLCollector(ICollector):
    """通用 YAML 声明式采集器。从 YAML 定义加载采集逻辑。"""

    def __init__(self, db, yaml_path: Path):
        super().__init__(db)
        self.config = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        self._yaml_path = yaml_path

    @classmethod
    def metadata(cls) -> CollectorMeta:
        # 由 registry 在发现时传入 yaml_path，动态生成 metadata
        raise NotImplementedError("Use YAMLCollector.from_yaml() instead")

    @classmethod
    def from_yaml(cls, yaml_path: Path) -> CollectorMeta:
        """从 YAML 文件提取 metadata，供 registry 使用。"""
        config = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        return CollectorMeta(
            name=config["name"],
            display_name=config["display_name"],
            category=config.get("category", "experimental"),
            env_vars=_extract_env_vars(config),
            default_enabled=config.get("default_enabled", False),
        )

    def collect(self) -> int:
        """执行 YAML 定义的采集管道：source → extract → transform → insert。"""
        raw = self._read_source()
        if raw is None:
            return -1
        extracted = self._extract(raw)
        return self._transform_and_insert(extracted)
```

### registry 集成

`discover_collectors()` 额外扫描 `src/collectors/yaml/*.yaml`，为每个 YAML 生成 `YAMLCollector` 实例。

### 支持的 source 类型（Phase 1）

| type | 描述 | 示例 |
|---|---|---|
| `json_file` | 读 JSON/JSONL 文件 | Discord 缓存 |
| `command` | 执行系统命令，解析 stdout | `netstat`, `wmic` |
| `sqlite` | 查询 SQLite DB | Chrome History |
| `http` | GET 请求 | REST API |

### 不做的事

- 不做完整的 step-based pipeline（OpenCLI 有 16 个 step，我们不需要浏览器自动化）
- 不做模板引擎（`${{ expr | filter }}` 太重了，用 Python f-string 和 jq 够用）
- 不做浏览器桥接（不需要）

## 升级 5：采集器声誉系统

### 问题

Steam collector 坏了很久（0 数据），但系统只在 health check 里报个 warning，没有持续追踪"这个采集器一直表现很差"的能力。

### 设计

灵感来自 OpenCLI 的 AI 自助闭环中的评估环节。

新增 `src/collectors/reputation.py`：

```python
@dataclass
class CollectorReputation:
    name: str
    total_runs: int = 0
    successful_runs: int = 0
    total_events: int = 0
    avg_events_per_run: float = 0.0
    last_success: str = ""          # ISO datetime
    last_failure: str = ""
    last_failure_reason: str = ""
    streak: int = 0                 # 连续成功次数（负数=连续失败）
    health_score: float = 1.0       # 0.0 ~ 1.0

    @property
    def success_rate(self) -> float:
        return self.successful_runs / max(self.total_runs, 1)
```

### 声誉计算

```python
def update_reputation(self, name: str, event_count: int, error: str = None):
    """每次采集后调用，更新声誉。"""
    rep = self._load(name)
    rep.total_runs += 1

    if event_count >= 0:
        rep.successful_runs += 1
        rep.total_events += event_count
        rep.avg_events_per_run = rep.total_events / rep.successful_runs
        rep.last_success = now_iso()
        rep.streak = max(rep.streak + 1, 1)
    else:
        rep.last_failure = now_iso()
        rep.last_failure_reason = error or "unknown"
        rep.streak = min(rep.streak - 1, -1)

    # 健康分计算
    rep.health_score = self._calc_health(rep)
    self._save(rep)

def _calc_health(self, rep: CollectorReputation) -> float:
    """综合评分：成功率 60% + 产出量 20% + 近期趋势 20%"""
    rate_score = rep.success_rate
    volume_score = min(rep.avg_events_per_run / 10.0, 1.0)  # 10 events/run = 满分
    trend_score = 1.0 if rep.streak > 0 else max(0.0, 1.0 + rep.streak * 0.1)
    return rate_score * 0.6 + volume_score * 0.2 + trend_score * 0.2
```

### 与现有系统集成

- **scheduler.py**：`run_collectors()` 每次采集后调用 `update_reputation()`
- **health.py**：`_check_collectors()` 改为读取声誉数据，而非仅检查"最近 24h 有无事件"
- **Dashboard API**：`/api/collectors/reputation` 展示所有采集器的健康卡片
- **Governor 自动反应**：连续失败 5 次 → 自动生成修复任务（已有类似逻辑，增强为基于声誉）

### 存储

声誉数据存在 `events.db` 新表 `collector_reputation`：

```sql
CREATE TABLE IF NOT EXISTS collector_reputation (
    name TEXT PRIMARY KEY,
    data TEXT NOT NULL,  -- JSON
    updated_at TEXT NOT NULL
);
```

## 升级 6：统一错误层级 + 重试策略

### 问题

9 个采集器的错误处理全是 `except Exception: return 0`（甚至有些返回 0 而非 -1）。不区分瞬时故障（网络超时、文件锁）和永久故障（目录不存在、权限拒绝）。超时值散落在各文件（5s/10s/30s），无统一配置。

### 设计

灵感来自 OpenCLI 的 `CliError`（code + hint）和 daemon 重试逻辑。

新增 `src/collectors/errors.py`：

```python
class CollectorError(Exception):
    """采集器统一异常基类。"""
    code: str           # 机器可读：'TIMEOUT', 'PERMISSION', 'NOT_FOUND', 'PARSE'
    hint: str           # 人类可读修复建议
    retryable: bool     # 是否值得重试

class TransientError(CollectorError):
    """瞬时故障 — 值得重试。网络超时、文件锁、进程忙。"""
    retryable = True

class PermanentError(CollectorError):
    """永久故障 — 不重试。路径不存在、权限拒绝、配置错误。"""
    retryable = False
```

新增 `src/collectors/retry.py`：

```python
def with_retry(fn, max_retries=3, base_delay=0.5, max_delay=10.0):
    """指数退避重试。仅对 TransientError 重试。

    延迟策略：0.5s → 1s → 2s（带 ±20% 抖动）
    """
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except TransientError as e:
            if attempt == max_retries:
                raise
            delay = min(base_delay * (2 ** attempt), max_delay)
            delay *= 0.8 + random.random() * 0.4  # jitter
            log.warning(f"retry: attempt {attempt+1}/{max_retries}, "
                        f"retrying in {delay:.1f}s: {e.code}")
            time.sleep(delay)
        except PermanentError:
            raise  # 不重试
```

### 熔断器（Circuit Breaker）

集成到声誉系统。连续失败 N 次后跳过采集，避免每小时重复同一个已知故障：

```python
# reputation.py 增强
def should_skip(self, name: str) -> tuple[bool, str]:
    """检查熔断状态。连续失败 >= 5 次 → 跳过 1 小时。"""
    rep = self._load(name)
    if rep.streak <= -5:
        if rep.last_failure and (now() - parse(rep.last_failure)) < timedelta(hours=1):
            return True, f"circuit open: {-rep.streak} consecutive failures"
    return False, ""
```

### 超时统一配置

```python
# src/collectors/base.py 增加
COLLECTOR_TIMEOUTS = {
    "subprocess": int(os.environ.get("COLLECTOR_TIMEOUT_SUBPROCESS", "30")),
    "http": int(os.environ.get("COLLECTOR_TIMEOUT_HTTP", "10")),
    "file_io": int(os.environ.get("COLLECTOR_TIMEOUT_FILE", "5")),
}
```

## 升级 7：采集器并行执行

### 问题

`scheduler.py:74` 用顺序 for 循环跑 9 个采集器。一个卡住的采集器（比如 Chrome 文件锁）会阻塞后面所有的。

### 设计

灵感来自 OpenCLI 的 `mapConcurrent()` Worker Pool。

```python
# scheduler.py 改造
from concurrent.futures import ThreadPoolExecutor, as_completed

MAX_COLLECTOR_WORKERS = int(os.environ.get("COLLECTOR_PARALLEL_WORKERS", "4"))
COLLECTOR_TIMEOUT = int(os.environ.get("COLLECTOR_RUN_TIMEOUT", "60"))

def run_collectors():
    db = EventsDB(DB_PATH)
    db.write_log("开始采集数据", "INFO", "collector")
    enabled = build_enabled_collectors(db)
    results = {}
    reputation = CollectorReputation(db)

    def _run_one(name, collector):
        """单个采集器的执行单元。"""
        # 熔断检查
        skip, reason = reputation.should_skip(name)
        if skip:
            log.info(f"collector [{name}] skipped: {reason}")
            return name, 0, reason

        t0 = time.time()
        try:
            count = collector.collect()
            elapsed = time.time() - t0
            log.info(f"collector [{name}] done: {count} events in {elapsed:.1f}s")
            return name, count, None
        except Exception as e:
            elapsed = time.time() - t0
            log.error(f"collector [{name}] failed after {elapsed:.1f}s: {e}")
            return name, -1, str(e)

    with ThreadPoolExecutor(max_workers=MAX_COLLECTOR_WORKERS) as pool:
        futures = {
            pool.submit(_run_one, name, collector): name
            for name, collector in enabled
        }
        for future in as_completed(futures, timeout=COLLECTOR_TIMEOUT):
            name = futures[future]
            try:
                name, count, error = future.result()
                results[name] = count
                reputation.update(name, count, error)
            except Exception as e:
                results[name] = -1
                reputation.update(name, -1, str(e))

    # ... 后续 burst detection + health check 不变
```

### 线程安全

- `EventsDB` 使用 SQLite，已有 `check_same_thread=False` + WAL mode
- 每个采集器操作独立的数据源，不存在竞争
- reputation 更新需要加锁（采集器可能同时完成）

## 升级 8：采集器可观测性

### 问题

8/9 采集器零 `log.*()` 调用。采集器是 Orchestrator 的"眼睛"，眼睛出问题了自己都不知道。

### 设计

灵感来自 OpenCLI 的 `logger.ts` 分级日志 + `step()`/`stepResult()` 进度标记。

```python
# src/collectors/base.py ICollector 增强
class ICollector(ABC):
    def __init__(self, db: EventsDB, **kwargs):
        self.db = db
        meta = self.metadata()
        self.log = logging.getLogger(f"collector.{meta.name}")

    def collect_with_metrics(self) -> int:
        """带指标的采集包装器。子类不需要关心日志和计时。"""
        meta = self.metadata()
        self.log.info(f"starting collection")
        t0 = time.time()

        try:
            count = self.collect()
            elapsed = time.time() - t0
            self.log.info(f"done: {count} events in {elapsed:.1f}s")

            # 写结构化指标到 DB
            self.db.write_log(
                f"[{meta.name}] {count} events, {elapsed:.1f}s",
                "INFO", f"collector.{meta.name}",
            )
            return count
        except Exception as e:
            elapsed = time.time() - t0
            self.log.error(f"failed after {elapsed:.1f}s: {e}")
            self.db.write_log(
                f"[{meta.name}] FAILED: {e}",
                "ERROR", f"collector.{meta.name}",
            )
            return -1
```

### scheduler 改动

`run_collectors()` 改为调用 `collector.collect_with_metrics()` 而非 `collector.collect()`。子类只需要实现 `collect()` 本身，日志/计时/异常捕获全在基类处理。

### Dashboard 集成

结构化日志使 Dashboard 可以展示：
- 每个采集器的平均执行时间趋势
- 每次采集的事件产出量变化
- 错误率和错误类型分布

## 实现顺序

```
Phase 1（基础设施 — 纯重构，不改外部行为）
├── 升级 1: ICollector 协议（base.py）
├── 升级 6: 统一错误层级 + 重试（errors.py, retry.py）
├── 升级 8: 可观测性（collect_with_metrics 包装器）
├── 升级 2: 自动发现（registry.py）
└── 升级 5: 声誉系统 + 熔断器（reputation.py）
    ↓
Phase 2（增强 — 新能力）
├── 升级 7: 并行执行（ThreadPoolExecutor）
├── 升级 3: Strategy Cascade（llm_router.py 改造）
└── 升级 4: YAML 声明式采集器（yaml_runner.py）
    ↓
Phase 3（终极形态 — 演进路线图阶段 4）
└── AI 自助采集器生成（吏部能力，explore → synthesize → register）
```

**Phase 1 依赖链**：ICollector 协议 → 错误层级 → 可观测性 → 自动发现 → 声誉系统。每一步都建立在前一步之上。

**Phase 2 可并行**：并行执行、Strategy Cascade、YAML 采集器互不依赖。

## 附录：自查发现的工程债务

深度扫描发现的问题，这些不是从 OpenCLI 偷的，是我们自己的短板：

| 问题 | 严重度 | 现状 | 被哪个升级解决 |
|---|---|---|---|
| 9 个采集器全 `except Exception: return 0` | 🔴 | 不分瞬时/永久故障 | 升级 6 |
| 8/9 采集器零日志 | 🔴 | 只有 codebase_collector 有 log | 升级 8 |
| 采集器顺序执行 | 🟠 | `for name, factory in _build_collectors(db)` | 升级 7 |
| 5/9 采集器无测试 | 🟠 | network/qqmusic/vscode/codebase 零覆盖 | Phase 1 补测试 |
| 超时值散落 | 🟠 | 5s/10s/30s 硬编码在各文件 | 升级 6 |
| Dashboard 只读 | 🟡 | 无手动触发/禁用采集器 | 升级 5 Dashboard API |
| Chrome 文件锁无重试 | 🟡 | `shutil.copy2` 失败直接返回 0 | 升级 6 |

## 风险

| 风险 | 缓解 |
|---|---|
| 自动发现 import 失败 | 每个 import 都有 try/catch，一个坏不影响其他 |
| Strategy Cascade 增加延迟 | 首选模型通常能用，cascade 只在失败时触发 |
| YAML 采集器表达力不够 | 复杂场景仍然用 Python 采集器，YAML 只服务简单场景 |
| 声誉数据膨胀 | 每个采集器一行，9 行 JSON，可以忽略 |

## 不做的事

- **不做浏览器桥接**：OpenCLI 的 Chrome Extension + CDP 方案很强，但 Orchestrator 不需要控制浏览器
- **不做 Interceptor**：monkey-patch fetch/XHR 是 OpenCLI 的核心，但我们的数据源是文件/DB/系统命令，不是浏览器请求
- **不做外部工具 Hub**：OpenCLI 的 `external.ts` 注册 gh/docker/kubectl 等外部工具，但我们的"工具"是采集器不是 CLI 命令
- **不做完整 Pipeline DSL**：16 个 step（navigate/click/type...）是浏览器自动化的东西，YAML 采集器只需要 source → extract → transform
