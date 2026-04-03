"""
Memory Supersede — 新记忆自动替代旧记忆。

Lucentia 启发：新记忆与旧记忆相似度 > 0.90 → 旧的标记 superseded。
半衰期 90 天。

使用 SequenceMatcher 做相似度比较。
"""
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

SUPERSEDE_THRESHOLD = 0.90   # 相似度阈值
HALF_LIFE_DAYS = 90          # 半衰期（天）


@dataclass
class SupersedeResult:
    """替代检查结果。"""
    should_supersede: bool
    old_file: str = ""
    similarity: float = 0.0
    reason: str = ""


def check_supersede(new_content: str, memory_dir: Path,
                     exclude_file: str = "") -> SupersedeResult:
    """检查新记忆是否应该替代某个旧记忆。

    扫描 memory 目录中的所有 .md 文件，找到最相似的，
    如果相似度 > 阈值则建议替代。
    """
    if not memory_dir or not memory_dir.exists():
        return SupersedeResult(should_supersede=False)

    best_match = ""
    best_similarity = 0.0

    for md_file in memory_dir.glob("*.md"):
        if md_file.name == "MEMORY.md" or md_file.name == exclude_file:
            continue

        try:
            old_content = md_file.read_text(encoding="utf-8")
        except Exception:
            continue

        similarity = _compute_similarity(new_content, old_content)

        if similarity > best_similarity:
            best_similarity = similarity
            best_match = md_file.name

    if best_similarity >= SUPERSEDE_THRESHOLD and best_match:
        return SupersedeResult(
            should_supersede=True,
            old_file=best_match,
            similarity=best_similarity,
            reason=f"与 {best_match} 相似度 {best_similarity:.0%}，建议更新而非新建",
        )

    return SupersedeResult(
        should_supersede=False,
        old_file=best_match,
        similarity=best_similarity,
    )


def _compute_similarity(text_a: str, text_b: str) -> float:
    """计算两段文本的相似度。"""
    return SequenceMatcher(None, text_a[:2000], text_b[:2000]).ratio()


def apply_half_life(memory_dir: Path, dry_run: bool = True) -> list[dict]:
    """扫描过期记忆（超过半衰期）。

    不自动删除，只标记。返回过期记忆列表。
    """
    if not memory_dir or not memory_dir.exists():
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=HALF_LIFE_DAYS)
    expired = []

    for md_file in memory_dir.glob("*.md"):
        if md_file.name == "MEMORY.md":
            continue

        try:
            # 从文件修改时间判断（不完美但简单）
            mtime = datetime.fromtimestamp(md_file.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                expired.append({
                    "file": md_file.name,
                    "last_modified": mtime.isoformat(),
                    "age_days": (datetime.now(timezone.utc) - mtime).days,
                })
        except Exception:
            continue

    if expired and not dry_run:
        log.info(f"memory_supersede: {len(expired)} memories past half-life")

    return expired
