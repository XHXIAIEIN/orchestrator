#!/usr/bin/env python3
"""Collector scaffolding tool — generate new collector boilerplate.

Usage:
    python -m src.collectors.scaffold <name> [--display "Display Name"] [--category core|optional|experimental]

Creates:
    src/collectors/<name>/
    ├── __init__.py
    ├── manifest.yaml
    └── collector.py       (with ICollector boilerplate)

The registry auto-discovers it on next scheduler tick.
"""
import argparse
import sys
from pathlib import Path

_COLLECTORS_DIR = Path(__file__).resolve().parent

MANIFEST_TEMPLATE = """\
name: {name}
display_name: {display_name}
category: {category}
enabled: {enabled}
env_vars: []
requires: []
event_sources:
- {name}
"""

COLLECTOR_TEMPLATE = '''\
"""
{display_name} Collector — TODO: describe what this collector does.
"""
import logging

from src.collectors.base import ICollector, CollectorMeta
from src.storage.events_db import EventsDB

log = logging.getLogger(__name__)


class {class_name}(ICollector):

    @classmethod
    def metadata(cls) -> CollectorMeta:
        return CollectorMeta(
            name="{name}",
            display_name="{display_name}",
            category="{category}",
            default_enabled={enabled},
            event_sources=["{name}"],
        )

    def collect(self) -> int:
        """Run collection. Returns number of events collected."""
        # TODO: implement collection logic
        log.info(f"{{self._name}}: collection started")
        count = 0

        # Example:
        # events = self._fetch_data()
        # for event in events:
        #     self.db.insert_event(
        #         source="{name}",
        #         category="TODO",
        #         title=event["title"],
        #         duration_minutes=0,
        #         score=0.5,
        #         tags=[],
        #         metadata={{}},
        #     )
        #     count += 1

        log.info(f"{{self._name}}: collected {{count}} events")
        return count
'''

INIT_TEMPLATE = "from .collector import *\n"


def scaffold(name: str, display_name: str = "", category: str = "optional",
             enabled: bool = False) -> Path:
    """Create a new collector directory with boilerplate files."""
    if not display_name:
        display_name = name.replace("_", " ").title()

    class_name = "".join(w.capitalize() for w in name.split("_")) + "Collector"
    target = _COLLECTORS_DIR / name

    if target.exists():
        print(f"Error: {target} already exists", file=sys.stderr)
        sys.exit(1)

    target.mkdir(parents=True)

    (target / "manifest.yaml").write_text(
        MANIFEST_TEMPLATE.format(name=name, display_name=display_name,
                                 category=category, enabled=str(enabled).lower()),
        encoding="utf-8",
    )

    (target / "collector.py").write_text(
        COLLECTOR_TEMPLATE.format(name=name, display_name=display_name,
                                  class_name=class_name, category=category,
                                  enabled=enabled),
        encoding="utf-8",
    )

    (target / "__init__.py").write_text(INIT_TEMPLATE, encoding="utf-8")

    print(f"Created collector: {target}/")
    print(f"  manifest.yaml  — edit to configure")
    print(f"  collector.py   — implement collect()")
    print(f"  __init__.py")
    print(f"\nNext: implement collect() in {target}/collector.py")

    return target


def main():
    parser = argparse.ArgumentParser(description="Scaffold a new collector")
    parser.add_argument("name", help="Collector name (snake_case)")
    parser.add_argument("--display", default="", help="Display name")
    parser.add_argument("--category", default="optional", choices=["core", "optional", "experimental"])
    parser.add_argument("--enabled", action="store_true", help="Enable by default")
    args = parser.parse_args()
    scaffold(args.name, args.display, args.category, args.enabled)


if __name__ == "__main__":
    main()
