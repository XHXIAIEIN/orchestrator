"""
Example Collector — 最小可运行的采集器模板。

复制此目录，改名为你的采集器名（如 douyin/），然后：
1. 改 manifest.yaml 里的 name、display_name、enabled
2. 实现 collect() 方法
3. Registry 自动发现，无需注册

脚手架工具也可以生成这个结构：
    python -m src.collectors.scaffold <name>
"""
import logging
from datetime import datetime, timezone

from src.collectors.base import ICollector, CollectorMeta
from src.storage.events_db import EventsDB

log = logging.getLogger(__name__)


class ExampleCollector(ICollector):
    """采集器模板 — 实现 metadata() 和 collect() 即可。"""

    @classmethod
    def metadata(cls) -> CollectorMeta:
        return CollectorMeta(
            name="example",
            display_name="Example Collector",
            category="experimental",
            default_enabled=False,
            event_sources=["example"],
        )

    def __init__(self, db: EventsDB):
        super().__init__(db)
        # 在这里初始化你需要的资源（API client、文件路径等）

    def collect(self) -> int:
        """执行一次采集，返回采集到的事件数量。

        这个方法会被 scheduler 每小时调用一次。
        用 self.db.insert_event() 写入事件。
        用 dedup_key 防止重复插入。
        """
        now = datetime.now(timezone.utc)
        count = 0

        # ── 1. 获取数据 ──
        # items = self._fetch_from_api()
        # items = self._read_from_file()
        items = [
            {"title": "示例事件", "category": "demo", "score": 0.5},
        ]

        # ── 2. 写入事件 ──
        for item in items:
            # dedup_key 确保同一条数据不会重复写入
            import hashlib
            dedup_key = hashlib.md5(
                f"example:{item['title']}:{now.strftime('%Y-%m-%d')}".encode()
            ).hexdigest()

            inserted = self.db.insert_event(
                source="example",                    # 对应 manifest.event_sources
                category=item["category"],           # 事件分类
                title=item["title"],                 # 事件标题
                duration_minutes=0,                  # 持续时间（无则 0）
                score=item["score"],                 # 重要度 0.0-1.0
                tags=["example"],                    # 标签列表
                metadata={"raw": item},              # 任意附加数据
                dedup_key=dedup_key,                 # 去重键
                occurred_at=now.isoformat(),         # 事件发生时间
            )
            if inserted:
                count += 1

        log.info(f"{self._name}: collected {count} events")
        return count
