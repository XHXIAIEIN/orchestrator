"""
三级记忆系统 — hot / warm / cold（R14 upgrade from 2-tier to 3-tier）。

Artemis 启发：hot memory（~70 行，每次加载）+ extended memory（按需加载）。
workflow-orchestration 启发：条件式 prompt 注入，不一股脑加载所有 system prompt。
R14 ClawHub elite-longterm-memory 启发：三层自动晋降 + per-agent namespace。

Hot memory: 编入 boot.md，每个实例启动时自动加载（≤100 lines, ~2000 tokens）
Warm memory: 按任务/部门/项目按需注入到 agent prompt（≤200 lines）
Cold memory: 归档，仅通过显式搜索加载

Memory 分类规则：
  - hot: 身份、关系、性格、核心规则（~2000 tokens 预算）
  - warm: 项目细节、近期偷师笔记（按需加载）
  - cold: 参考资料、归档项目、历史偷师笔记

与 SOUL compiler 的关系：
  compiler 从源文件编译 boot.md（hot memory 的载体）
  这个模块在运行时做 warm/cold memory 的按需加载
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# ── Hotness-based tier classification (stolen from OpenViking) ──
try:
    from src.storage.hotness import score_hotness, classify_tier as _hotness_classify
    _HOTNESS_AVAILABLE = True
except ImportError:
    _HOTNESS_AVAILABLE = False

# Token 预算（字符数估算，1 token ≈ 4 chars）
HOT_BUDGET_CHARS = 8000    # ~2000 tokens
EXTENDED_MAX_CHARS = 4000  # 单次注入上限 ~1000 tokens

# ── Three-tier auto-promotion/demotion (R14 steal) ──
# HOT: ≤100 lines, loaded every session via boot.md (~2000 tokens)
# WARM: ≤200 lines, loaded on-demand per department/task
# COLD: archived, only loaded via explicit search
TIER_HOT = "hot"
TIER_WARM = "warm"
TIER_COLD = "cold"

# Promotion rules
PROMOTE_TO_HOT_THRESHOLD = 3      # applied 3+ times → promote to hot
PROMOTE_TO_WARM_THRESHOLD = 1     # applied 1+ time → promote to warm
PROMOTE_TIME_DAYS = 7             # OR: referenced within 7 days → promote

# Demotion rules
DEMOTE_TO_WARM_DAYS = 14          # hot → warm if unused for 14 days
DEMOTE_TO_COLD_DAYS = 30          # warm → cold if unused for 30 days

_REPO_ROOT = Path(__file__).resolve().parent
while _REPO_ROOT != _REPO_ROOT.parent and not ((_REPO_ROOT / "departments").is_dir() and (_REPO_ROOT / "src").is_dir()):
    _REPO_ROOT = _REPO_ROOT.parent


@dataclass
class MemoryEntry:
    """单条记忆，支持 L0/L1/L2 三层加载（stolen from OpenViking）。

    R14 additions: apply_count, last_accessed, created_at for auto-promotion/demotion.
    """
    name: str
    content: str           # L2: full content
    tier: str              # "hot" | "warm" | "cold"
    tags: list = field(default_factory=list)
    l0: str = ""           # ~100 tokens: one-line summary for search ranking
    l1: str = ""           # ~1000 tokens: structural overview for navigation
    apply_count: int = 0        # how many times this memory was applied (R14)
    last_accessed: str = ""     # ISO date of last access (R14)
    created_at: str = ""        # ISO date of creation (R14)

    @property
    def char_count(self) -> int:
        return len(self.content)

    @property
    def token_estimate(self) -> int:
        return self.char_count // 4


def _parse_frontmatter(content: str) -> dict:
    """Parse YAML frontmatter, extracting l0, l1, name, description, type."""
    if not content.startswith("---"):
        return {}
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}
    meta = {}
    for line in parts[1].strip().split("\n"):
        if ":" in line:
            key, val = line.split(":", 1)
            meta[key.strip()] = val.strip()
    return meta


def _body_without_frontmatter(content: str) -> str:
    """Return content after frontmatter block."""
    if not content.startswith("---"):
        return content
    parts = content.split("---", 2)
    return parts[2].strip() if len(parts) >= 3 else content


def _generate_l0(name: str, content: str, meta: dict) -> str:
    """Generate L0 (one-line summary) from description or first line."""
    if meta.get("l0"):
        return meta["l0"]
    if meta.get("description"):
        return meta["description"][:200]
    # Fallback: first non-empty line of body
    body = _body_without_frontmatter(content)
    for line in body.split("\n"):
        line = line.strip().lstrip("#").strip()
        if line and len(line) > 10:
            return line[:200]
    return name


def _generate_l1(content: str, meta: dict, max_chars: int = 4000) -> str:
    """Generate L1 (structural overview) from l1 field or first ~1000 tokens."""
    if meta.get("l1"):
        return meta["l1"]
    body = _body_without_frontmatter(content)
    # Take first max_chars of body as L1 approximation
    if len(body) <= max_chars:
        return body
    # Try to cut at a paragraph boundary
    cut = body[:max_chars]
    last_para = cut.rfind("\n\n")
    if last_para > max_chars // 2:
        return cut[:last_para].strip()
    return cut.strip()


# ── Extended Memory Tags ──
# 按标签匹配：任务 spec 中的关键词 → 加载对应的 extended memory

EXTENDED_TAG_RULES: dict[str, list[str]] = {
    # 部门标签
    "engineering": ["engineering", "code", "refactor", "工部"],
    "operations": ["operations", "collector", "docker", "户部"],
    "security": ["security", "vulnerability", "兵部"],
    "quality": ["quality", "test", "review", "刑部"],

    # 项目标签
    "construct3-rag": ["construct3", "rag", "embedding", "lora"],
    "orchestrator": ["orchestrator", "governor", "三省六部", "soul"],

    # 话题标签
    "steal-sheet": ["偷师", "steal", "upgrade", "升级"],
    "gstack": ["gstack", "axe"],
}


def load_extended_memory(tags: list[str], memory_dir: Path = None,
                         load_level: int = 1) -> list[MemoryEntry]:
    """按标签加载 extended memory 文件，支持 L0/L1/L2 三级加载。

    load_level:
      0 — L0: one-line summary only (~100 tokens each)
      1 — L1: structural overview (~1000 tokens each)
      2 — L2: full content

    扫描 memory 目录中的 .md 文件，读取 frontmatter 的 type 和 description，
    匹配标签后加载内容。
    """
    if memory_dir is None:
        # 尝试自动发现 memory 目录
        memory_dir = _find_memory_dir()

    if not memory_dir or not memory_dir.exists():
        return []

    entries = []
    total_chars = 0

    for md_file in sorted(memory_dir.glob("*.md")):
        if md_file.name == "MEMORY.md":
            continue

        try:
            content = md_file.read_text(encoding="utf-8")
        except Exception:
            continue

        # Parse frontmatter for L0/L1
        meta = _parse_frontmatter(content)
        name_lower = md_file.stem.lower()
        l0 = _generate_l0(md_file.stem, content, meta)
        l1 = _generate_l1(content, meta)

        # Tag matching: check l0 + l1 + name (cheaper than full content)
        search_text = f"{name_lower} {l0.lower()} {l1[:500].lower()}"
        matched = False
        for tag in tags:
            tag_lower = tag.lower()
            if tag_lower in name_lower or tag_lower in search_text:
                matched = True
                break

        if not matched:
            continue

        # Progressive loading based on load_level
        if load_level == 0:
            entry_content = l0
        elif load_level == 1:
            entry_content = l1
        else:
            entry_content = content  # L2: full content

        # Token budget control
        if total_chars + len(entry_content) > EXTENDED_MAX_CHARS * 3:
            break

        entries.append(MemoryEntry(
            name=md_file.stem,
            content=entry_content,
            tier="extended",
            tags=tags,
            l0=l0,
            l1=l1 if load_level >= 1 else "",
        ))
        total_chars += len(entry_content)

    log.info(f"memory_tier: loaded {len(entries)} extended memories "
             f"(L{load_level}, {total_chars} chars) for tags {tags}")
    return entries


def escalate_to_l2(entry: MemoryEntry, memory_dir: Path = None) -> MemoryEntry:
    """Load full L2 content for a previously L1-loaded entry."""
    if memory_dir is None:
        memory_dir = _find_memory_dir()
    if not memory_dir:
        return entry

    file_path = memory_dir / f"{entry.name}.md"
    if not file_path.exists():
        return entry

    try:
        full_content = file_path.read_text(encoding="utf-8")
        entry.content = full_content
        return entry
    except Exception:
        return entry


def resolve_tags_from_spec(spec: dict) -> list[str]:
    """从任务 spec 中提取标签，用于加载 extended memory。"""
    tags = []

    # 部门
    dept = spec.get("department", "")
    if dept:
        tags.append(dept)

    # 项目
    project = spec.get("project", "")
    if project:
        tags.append(project)

    # 从 problem/action 中提取关键词
    text = f"{spec.get('problem', '')} {spec.get('summary', '')}".lower()
    for tag, keywords in EXTENDED_TAG_RULES.items():
        if any(kw in text for kw in keywords):
            tags.append(tag)

    return list(set(tags))


def format_extended_for_prompt(entries: list[MemoryEntry]) -> str:
    """格式化 extended memory 为 prompt 注入格式。"""
    if not entries:
        return ""

    lines = ["## Extended Memory（按需加载，L1 概览）"]
    for entry in entries:
        # 截断过长的内容
        content = entry.content
        if len(content) > EXTENDED_MAX_CHARS:
            content = content[:EXTENDED_MAX_CHARS] + "\n\n(... 截断，完整内容见文件)"

        lines.append(f"\n### {entry.name}")
        if entry.l0:
            lines.append(f"*{entry.l0}*")
        lines.append(content)

    return "\n".join(lines)


def classify_learning_tier(hit_count: int, last_hit_at: str | None,
                           created_at: str | None = None) -> str:
    """Classify a learning into hot/warm/cold using hotness scoring.

    Falls back to simple hit_count heuristic if hotness module is unavailable.
    Used by memory_tier to decide which learnings get loaded as hot memory
    vs. extended memory.
    """
    if _HOTNESS_AVAILABLE:
        try:
            score = score_hotness(hit_count, last_hit_at, created_at)
            return _hotness_classify(score)
        except Exception:
            pass
    # Fallback: simple heuristic
    if hit_count >= 5:
        return "hot"
    elif hit_count >= 1:
        return "warm"
    return "cold"


# ── Three-tier auto-promotion/demotion (R14 steal) ──────────────────────


def _days_since(iso_date: str) -> int:
    """Return days since an ISO date string. Returns 9999 on parse failure."""
    if not iso_date:
        return 9999
    try:
        dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        # Make dt offset-aware if naive
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, (now - dt).days)
    except (ValueError, TypeError):
        return 9999


def classify_tier(entry: MemoryEntry) -> str:
    """Determine tier based on apply_count + last_accessed (R14).

    - apply_count >= 3 OR accessed within 7 days → hot
    - apply_count >= 1 OR accessed within 14 days → warm
    - otherwise → cold
    """
    days = _days_since(entry.last_accessed)

    if entry.apply_count >= PROMOTE_TO_HOT_THRESHOLD or days <= PROMOTE_TIME_DAYS:
        return TIER_HOT
    if entry.apply_count >= PROMOTE_TO_WARM_THRESHOLD or days <= DEMOTE_TO_WARM_DAYS:
        return TIER_WARM
    return TIER_COLD


def auto_promote_demote(
    entries: list[MemoryEntry],
) -> list[tuple[MemoryEntry, str, str]]:
    """Return list of (entry, old_tier, new_tier) for entries whose tier changed.

    Does NOT modify entries in place — caller decides whether to apply.
    """
    changes: list[tuple[MemoryEntry, str, str]] = []
    for entry in entries:
        new_tier = classify_tier(entry)
        if new_tier != entry.tier:
            changes.append((entry, entry.tier, new_tier))
    if changes:
        log.info("memory_tier: %d tier changes detected", len(changes))
    return changes


def record_access(entry: MemoryEntry) -> None:
    """Increment apply_count and update last_accessed to today (R14)."""
    entry.apply_count += 1
    entry.last_accessed = datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ── Per-Agent Memory Isolation (R29 steal — DeerFlow) ────────────────────


@dataclass
class AgentMemoryNamespace:
    """Independent memory namespace for a specific agent/department."""
    agent_name: str
    entries: list[MemoryEntry] = field(default_factory=list)
    token_budget: int = 2000


def get_agent_memory(
    agent_name: str,
    all_entries: list[MemoryEntry],
) -> list[MemoryEntry]:
    """Filter entries by tag matching agent_name.

    If no agent-specific entries found, return shared/global entries
    (those with no agent-specific tag).
    """
    agent_lower = agent_name.lower()
    agent_specific = [
        e for e in all_entries
        if any(t.lower() == agent_lower for t in e.tags)
    ]
    if agent_specific:
        return agent_specific

    # Fallback: return global entries (no tags or generic tags only)
    return [e for e in all_entries if not e.tags]


def partition_by_agent(
    entries: list[MemoryEntry],
) -> dict[str, list[MemoryEntry]]:
    """Group entries by their first tag. Untagged entries go to '_global'."""
    partitions: dict[str, list[MemoryEntry]] = {}
    for entry in entries:
        key = entry.tags[0] if entry.tags else "_global"
        partitions.setdefault(key, []).append(entry)
    return partitions


def _find_memory_dir() -> Optional[Path]:
    """自动发现 Claude 的 memory 目录。"""
    projects_root = Path.home() / ".claude" / "projects"
    if not projects_root.exists():
        return None

    repo_dir = _REPO_ROOT.resolve()
    # 编码路径
    encoded = str(repo_dir).replace("\\", "-").replace(":", "-").replace("/", "-")

    candidate = projects_root / encoded / "memory"
    if candidate.exists():
        return candidate

    # Fuzzy search
    for d in projects_root.iterdir():
        if not d.is_dir():
            continue
        mem = d / "memory" / "MEMORY.md"
        if mem.exists() and "orchestrator" in d.name.lower():
            return d / "memory"

    return None
