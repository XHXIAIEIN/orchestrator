"""
两级记忆系统 — hot / extended。

Artemis 启发：hot memory（~70 行，每次加载）+ extended memory（按需加载）。
workflow-orchestration 启发：条件式 prompt 注入，不一股脑加载所有 system prompt。

Hot memory: 编入 boot.md，每个实例启动时自动加载
Extended memory: 按任务/部门/项目按需注入到 agent prompt

Memory 分类规则：
  - hot: 身份、关系、性格、核心规则（~2000 tokens 预算）
  - extended: 项目细节、参考资料、历史偷师笔记、归档项目

与 SOUL compiler 的关系：
  compiler 从源文件编译 boot.md（hot memory 的载体）
  这个模块在运行时做 extended memory 的按需加载
"""
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Token 预算（字符数估算，1 token ≈ 4 chars）
HOT_BUDGET_CHARS = 8000    # ~2000 tokens
EXTENDED_MAX_CHARS = 4000  # 单次注入上限 ~1000 tokens

_REPO_ROOT = Path(__file__).resolve().parent
while _REPO_ROOT != _REPO_ROOT.parent and not ((_REPO_ROOT / "departments").is_dir() and (_REPO_ROOT / "src").is_dir()):
    _REPO_ROOT = _REPO_ROOT.parent


@dataclass
class MemoryEntry:
    """单条记忆。"""
    name: str
    content: str
    tier: str       # "hot" | "extended"
    tags: list = field(default_factory=list)  # 关联标签（部门/项目/话题）

    @property
    def char_count(self) -> int:
        return len(self.content)

    @property
    def token_estimate(self) -> int:
        return self.char_count // 4


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


def load_extended_memory(tags: list[str], memory_dir: Path = None) -> list[MemoryEntry]:
    """按标签加载 extended memory 文件。

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

        # 检查标签匹配
        content_lower = content.lower()
        name_lower = md_file.stem.lower()
        matched = False

        for tag in tags:
            tag_lower = tag.lower()
            if tag_lower in name_lower or tag_lower in content_lower[:500]:
                matched = True
                break

        if not matched:
            continue

        # Token 预算控制
        if total_chars + len(content) > EXTENDED_MAX_CHARS * 3:  # 最多 3 个 extended 文件
            break

        entries.append(MemoryEntry(
            name=md_file.stem,
            content=content,
            tier="extended",
            tags=tags,
        ))
        total_chars += len(content)

    log.info(f"memory_tier: loaded {len(entries)} extended memories "
             f"({total_chars} chars) for tags {tags}")
    return entries


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

    lines = ["## Extended Memory（按需加载）"]
    for entry in entries:
        # 截断过长的内容
        content = entry.content
        if len(content) > EXTENDED_MAX_CHARS:
            content = content[:EXTENDED_MAX_CHARS] + "\n\n(... 截断，完整内容见文件)"

        lines.append(f"\n### {entry.name}")
        lines.append(content)

    return "\n".join(lines)


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
