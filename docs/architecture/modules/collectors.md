# Collectors

> 数据采集层 — manifest 驱动的自动发现，统一 ABC 协议。

## Key Files

| File | Purpose |
|------|---------|
| `base.py` | `ICollector` ABC + `CollectorMeta` 自描述数据类 |
| `registry.py` | manifest 驱动的自动发现，扫描 `{name}/manifest.yaml` |
| `reputation.py` | 采集器信誉追踪（成功率、延迟） |
| `retry.py` | 重试策略 |
| `errors.py` | 统一异常类型 |
| `yaml_runner.py` | YAML 声明式采集执行器 |

## Collector List

| Collector | Category | What it collects |
|-----------|----------|-----------------|
| `browser/` | core | 浏览器历史/标签 |
| `claude/` | core | Claude 对话记录 |
| `claude_memory/` | core | Claude 记忆文件 |
| `codebase/` | core | 代码仓库活动 |
| `git/` | core | Git commit/diff |
| `network/` | optional | 网络活动 |
| `qqmusic/` | optional | QQ 音乐听歌记录 |
| `steam/` | optional | Steam 游戏时间 |
| `system_uptime/` | core | 系统运行时间 |
| `vscode/` | optional | VS Code 使用数据 |
| `youtube_music/` | optional | YouTube Music 历史 |

## ICollector ABC

```python
class ICollector(ABC):
    def __init__(self, db: EventsDB, **kwargs): ...
    @classmethod
    @abstractmethod
    def metadata(cls) -> CollectorMeta: ...  # 名称、分类、环境变量、依赖
    @abstractmethod
    def collect(self) -> int: ...            # 返回采集条目数
```

每个采集器通过 `collect_with_metrics()` 包装执行，自动追踪 run_id、耗时、异常。

## How to Add a New Collector

1. 创建目录 `src/collectors/{name}/`
2. 写 `manifest.yaml`：声明名称、分类、环境变量、enabled
3. 写 `collector.py`：继承 `ICollector`，实现 `metadata()` + `collect()`
4. 完成。`registry.discover_collectors()` 会自动发现。

优先级：`env COLLECTOR_{NAME}` > `manifest.yaml enabled` > 默认 `true`。

## Related

- Example collector: `src/collectors/_example/`
- Collector timeouts: `base.py` — subprocess 30s, http 10s, file 5s
