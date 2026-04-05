# src/governance/context/artifact_store.py
"""
Artifact Store — 大型工具输出外部化存储 (R39 PraisonAI steal).

当工具输出超过阈值 (默认 32KB) 时，自动存储到磁盘，
context 中只保留 ArtifactRef (summary + checksum + path)。
支持 grep/tail/chunk 操作按需取回部分内容。

灵感: PraisonAI context/artifacts.py
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

# 默认阈值: 32KB 字符 (~8K tokens)
DEFAULT_THRESHOLD_CHARS = 32_768
# 摘要截取长度
SUMMARY_HEAD_CHARS = 300
SUMMARY_TAIL_CHARS = 100
# Artifact 存储目录
DEFAULT_STORE_DIR = "data/artifacts"


@dataclass(frozen=True)
class ArtifactRef:
    """Context 中工具输出的轻量替身。

    Attributes:
        artifact_id: 唯一 ID (基于内容 SHA256 前 12 位)
        path: 磁盘存储路径
        tool_name: 产生该输出的工具名
        char_count: 原始字符数
        line_count: 原始行数
        checksum: SHA256 全量校验
        summary: 头部 + 尾部摘要
        created_at: Unix timestamp
    """
    artifact_id: str
    path: str
    tool_name: str
    char_count: int
    line_count: int
    checksum: str
    summary: str
    created_at: float

    def to_context_str(self) -> str:
        """生成放入 LLM context 的替代文本。"""
        return (
            f"[ArtifactRef: {self.artifact_id}]\n"
            f"  tool: {self.tool_name}\n"
            f"  size: {self.char_count:,} chars / {self.line_count:,} lines\n"
            f"  checksum: {self.checksum[:16]}...\n"
            f"  path: {self.path}\n"
            f"  ---\n"
            f"  {self.summary}\n"
            f"  ---\n"
            f"  Use artifact_store.load/grep/tail to retrieve content."
        )


class ArtifactStore:
    """管理大型工具输出的外部化存储。

    Usage:
        store = ArtifactStore()
        result = store.maybe_externalize(tool_output, tool_name="Bash")
        # result 是 str: 如果未超阈值, 返回原文; 超阈值, 返回 ArtifactRef.to_context_str()
    """

    def __init__(
        self,
        store_dir: str | Path | None = None,
        threshold_chars: int = DEFAULT_THRESHOLD_CHARS,
    ):
        self._store_dir = Path(store_dir or DEFAULT_STORE_DIR)
        self._threshold = threshold_chars
        self._refs: dict[str, ArtifactRef] = {}  # artifact_id → ref
        self._store_dir.mkdir(parents=True, exist_ok=True)

    @property
    def threshold(self) -> int:
        return self._threshold

    @property
    def refs(self) -> dict[str, ArtifactRef]:
        return dict(self._refs)

    # ── Core API ──────────────────────────────────────────────

    def maybe_externalize(self, output: str, tool_name: str = "") -> str:
        """如果 output 超阈值, 存储到磁盘并返回 ArtifactRef 文本; 否则原样返回。"""
        if len(output) <= self._threshold:
            return output

        ref = self.store(output, tool_name)
        log.info(
            f"ArtifactStore: externalized '{tool_name}' output "
            f"({ref.char_count:,} chars) → {ref.artifact_id}"
        )
        return ref.to_context_str()

    def store(self, content: str, tool_name: str = "") -> ArtifactRef:
        """强制存储内容, 返回 ArtifactRef。"""
        checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
        artifact_id = checksum[:12]

        # 避免重复存储
        if artifact_id in self._refs:
            return self._refs[artifact_id]

        # 写磁盘
        file_path = self._store_dir / f"{artifact_id}.txt"
        file_path.write_text(content, encoding="utf-8")

        # 生成摘要
        summary = self._make_summary(content)
        lines = content.count("\n") + 1

        ref = ArtifactRef(
            artifact_id=artifact_id,
            path=str(file_path),
            tool_name=tool_name,
            char_count=len(content),
            line_count=lines,
            checksum=checksum,
            summary=summary,
            created_at=time.time(),
        )
        self._refs[artifact_id] = ref
        return ref

    def load(self, artifact_id: str) -> str:
        """加载完整内容。"""
        ref = self._get_ref(artifact_id)
        return Path(ref.path).read_text(encoding="utf-8")

    def tail(self, artifact_id: str, lines: int = 50) -> str:
        """返回最后 N 行。"""
        content = self.load(artifact_id)
        all_lines = content.splitlines()
        tail_lines = all_lines[-lines:]
        header = f"[tail {lines} of {len(all_lines)} lines from {artifact_id}]\n"
        return header + "\n".join(tail_lines)

    def head(self, artifact_id: str, lines: int = 50) -> str:
        """返回前 N 行。"""
        content = self.load(artifact_id)
        all_lines = content.splitlines()
        head_lines = all_lines[:lines]
        footer = f"\n[head {lines} of {len(all_lines)} lines from {artifact_id}]"
        return "\n".join(head_lines) + footer

    def grep(self, artifact_id: str, pattern: str, context_lines: int = 2) -> str:
        """在 artifact 内容中正则搜索, 返回匹配行及上下文。"""
        content = self.load(artifact_id)
        all_lines = content.splitlines()
        regex = re.compile(pattern, re.IGNORECASE)

        matches: list[str] = []
        matched_indices: set[int] = set()

        for i, line in enumerate(all_lines):
            if regex.search(line):
                matched_indices.add(i)
                # 加上下文行
                for j in range(max(0, i - context_lines), min(len(all_lines), i + context_lines + 1)):
                    matched_indices.add(j)

        if not matched_indices:
            return f"[grep '{pattern}' in {artifact_id}: no matches]"

        sorted_indices = sorted(matched_indices)
        result_lines: list[str] = []
        prev_idx = -2
        for idx in sorted_indices:
            if idx > prev_idx + 1:
                result_lines.append("---")
            prefix = ">>>" if regex.search(all_lines[idx]) else "   "
            result_lines.append(f"{prefix} {idx + 1:>5}: {all_lines[idx]}")
            prev_idx = idx

        header = f"[grep '{pattern}' in {artifact_id}: {len([i for i in sorted_indices if regex.search(all_lines[i])])} matches]\n"
        return header + "\n".join(result_lines)

    def chunk(self, artifact_id: str, start_line: int = 1, end_line: int = 100) -> str:
        """返回指定行范围 [start_line, end_line] (1-indexed)。"""
        content = self.load(artifact_id)
        all_lines = content.splitlines()
        # 转 0-indexed
        s = max(0, start_line - 1)
        e = min(len(all_lines), end_line)
        chunk_lines = all_lines[s:e]
        header = f"[chunk {start_line}-{end_line} of {len(all_lines)} lines from {artifact_id}]\n"
        numbered = [f"{i + start_line:>5}: {line}" for i, line in enumerate(chunk_lines)]
        return header + "\n".join(numbered)

    def cleanup(self, max_age_hours: float = 24.0) -> int:
        """清理超过 max_age 的旧 artifact。返回清理数量。"""
        cutoff = time.time() - (max_age_hours * 3600)
        removed = 0
        stale_ids = [
            aid for aid, ref in self._refs.items()
            if ref.created_at < cutoff
        ]
        for aid in stale_ids:
            ref = self._refs.pop(aid)
            try:
                Path(ref.path).unlink(missing_ok=True)
                removed += 1
            except OSError as e:
                log.warning(f"ArtifactStore: failed to remove {ref.path}: {e}")
        if removed:
            log.info(f"ArtifactStore: cleaned up {removed} stale artifacts")
        return removed

    # ── Internal ──────────────────────────────────────────────

    def _get_ref(self, artifact_id: str) -> ArtifactRef:
        """查找 ArtifactRef, 不存在则抛 KeyError。"""
        if artifact_id not in self._refs:
            raise KeyError(f"Unknown artifact: {artifact_id}")
        return self._refs[artifact_id]

    @staticmethod
    def _make_summary(content: str) -> str:
        """提取头 + 尾摘要。"""
        head = content[:SUMMARY_HEAD_CHARS].rstrip()
        tail = content[-SUMMARY_TAIL_CHARS:].lstrip() if len(content) > SUMMARY_HEAD_CHARS + SUMMARY_TAIL_CHARS else ""
        if tail:
            return f"{head}\n  [...{len(content) - SUMMARY_HEAD_CHARS - SUMMARY_TAIL_CHARS:,} chars omitted...]\n  {tail}"
        return head
