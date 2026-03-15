"""
项目注册表 — 管理 Orchestrator 可调度的项目清单。

自动扫描 /git-repos 下的 git 仓库，支持手动配置覆盖。
提供 project_name → container_path 映射，供 Governor 路由任务。
"""
import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

GIT_REPOS_ROOT = os.environ.get("GIT_REPOS_ROOT", "/git-repos")
ORCHESTRATOR_ROOT = os.environ.get("ORCHESTRATOR_ROOT", "/orchestrator")
REGISTRY_FILE = Path(ORCHESTRATOR_ROOT) / "project_registry.json"


def _claude_dir_to_project(dirname: str) -> str:
    """从 Claude projects 目录名提取项目名。
    e.g. "D--Users-Administrator-Documents-GitHub-Construct3-RAG" → "Construct3-RAG"

    Claude Code 的目录名格式：盘符--路径各段用-连接。
    无法区分路径分隔符和目录名中的 -，所以用 "GitHub-" 作为锚点。
    """
    # 找 "GitHub-" 锚点（大小写不敏感），取后面的部分
    lower = dirname.lower()
    anchor = lower.find("github-")
    if anchor >= 0:
        return dirname[anchor + 7:]  # len("GitHub-") == 7

    # 没有 GitHub 锚点时（如 Desktop 项目），取 -- 后最后一段有意义的部分
    if "--" in dirname:
        after_drive = dirname.split("--", 1)[1]
        # 取 Desktop- 或 Documents- 之后的部分
        for marker in ("Desktop-", "Documents-"):
            idx = after_drive.find(marker)
            if idx >= 0:
                return after_drive[idx + len(marker):]
        return after_drive

    return dirname


def scan_repos() -> dict[str, dict]:
    """扫描 /git-repos 下所有目录，返回 {project_name: {path, is_git, has_claude_md}}。"""
    root = Path(GIT_REPOS_ROOT)
    if not root.exists():
        log.warning(f"ProjectRegistry: {GIT_REPOS_ROOT} not found")
        return {}

    projects = {}
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        projects[d.name] = {
            "path": str(d),
            "is_git": (d / ".git").exists(),
            "has_claude_md": (d / "CLAUDE.md").exists(),
        }

    # orchestrator 自身
    projects["orchestrator"] = {
        "path": ORCHESTRATOR_ROOT,
        "is_git": True,
        "has_claude_md": True,
    }

    return projects


def load_registry() -> dict[str, dict]:
    """加载注册表：合并自动扫描 + 手动配置。手动配置优先。"""
    auto = scan_repos()

    manual = {}
    if REGISTRY_FILE.exists():
        try:
            manual = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning(f"ProjectRegistry: failed to load {REGISTRY_FILE}: {e}")

    return {**auto, **manual}


def save_manual_config(overrides: dict):
    """保存手动配置覆盖。"""
    REGISTRY_FILE.write_text(
        json.dumps(overrides, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def resolve_project(project_name: str) -> str | None:
    """根据项目名返回容器内路径。支持精确、大小写不敏感、部分匹配。"""
    registry = load_registry()

    # 精确匹配
    if project_name in registry:
        return registry[project_name]["path"]

    # 大小写不敏感
    lower = project_name.lower()
    for name, info in registry.items():
        if name.lower() == lower:
            return info["path"]

    # 部分匹配
    for name, info in registry.items():
        if lower in name.lower():
            return info["path"]

    return None


def get_project_for_claude_dir(claude_dir_name: str) -> tuple[str, str] | None:
    """从 Claude projects 目录名推断项目名和路径。
    返回 (project_name, container_path) 或 None。"""
    project_name = _claude_dir_to_project(claude_dir_name)
    path = resolve_project(project_name)
    if path:
        return project_name, path
    return None
