"""
CAFI File Index — 为每个文件生成 routing hint。

claude-prove 启发：agent 查索引后再 Glob/Grep，减少盲目搜索。

为代码库中的每个文件生成：
  - routing_hint: 一句话描述文件职责（由 LLM 或规则生成）
  - tags: 关联的部门/话题标签
  - embedding: 可选的向量表示

存储在 events.db 的 file_index 表中。
"""
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent
while _REPO_ROOT != _REPO_ROOT.parent and not ((_REPO_ROOT / "departments").is_dir() and (_REPO_ROOT / "src").is_dir()):
    _REPO_ROOT = _REPO_ROOT.parent

# 路径 → routing hint 的规则映射（零 LLM 成本）
_ROUTING_RULES: list[tuple[str, str, list[str]]] = [
    # (path pattern, hint, tags)
    ("src/collectors/", "采集器：从外部系统采集数据", ["operations", "collector"]),
    ("src/governance/governor", "Governor：任务调度和执行引擎", ["engineering", "governance"]),
    ("src/governance/blueprint", "Blueprint：部门声明式配置", ["engineering", "governance"]),
    ("src/governance/run_logger", "Run Logger：哈希链执行日志", ["operations", "logging"]),
    ("src/governance/eval_loop", "EVAL Loop：质量闭环控制", ["quality", "governance"]),
    ("src/governance/token_budget", "TokenAccountant：预算降级", ["operations", "budget"]),
    ("src/governance/scout", "Scout：轻量侦察 agent", ["protocol", "governance"]),
    ("src/governance/doom_loop", "Doom Loop：agent 死循环检测", ["quality", "governance"]),
    ("src/governance/scratchpad", "Scratchpad：文件传递协议", ["engineering", "governance"]),
    ("src/governance/verify_gate", "Verify Gate：质量门控", ["quality", "governance"]),
    ("src/governance/novelty_policy", "Novelty Policy：防重复失败", ["quality", "governance"]),
    ("src/governance/deslop", "Deslop：AI 臭味检测", ["quality"]),
    ("src/governance/prompt_canary", "Canary：prompt A/B 测试", ["engineering", "governance"]),
    ("src/governance/memory_tier", "Memory Tier：hot/extended 记忆分层", ["engineering", "memory"]),
    ("src/governance/learn_from_edit", "Learn from Edit：人工修正反馈", ["quality", "memory"]),
    ("src/governance/stage_pipeline", "Stage Pipeline：可配置执行阶段", ["engineering", "governance"]),
    ("src/governance/task_lifecycle", "Task Lifecycle：状态机", ["engineering", "governance"]),
    ("src/gateway/", "Gateway：请求分类和路由", ["engineering", "gateway"]),
    ("src/storage/events_db", "EventsDB：中央数据库", ["operations", "storage"]),
    ("src/storage/qdrant_store", "QdrantStore：Qdrant 向量记忆层", ["engineering", "storage"]),
    ("src/core/llm_router", "LLM Router：模型选择和级联", ["operations", "llm"]),
    ("src/core/event_bus", "Event Bus：事件总线", ["operations", "events"]),
    ("src/analysis/", "Analysis：数据分析引擎", ["protocol", "analysis"]),
    ("src/scheduler", "Scheduler：定时任务调度", ["operations"]),
    ("dashboard/", "Dashboard：前端可视化", ["engineering", "dashboard"]),
    ("departments/", "Departments：六部配置和技能", ["governance"]),
    ("SOUL/", "SOUL：身份和记忆系统", ["engineering", "soul"]),
    ("tests/", "Tests：测试用例", ["quality", "testing"]),
    ("docker", "Docker：容器化配置", ["operations", "docker"]),
]


def build_index(db=None) -> dict:
    """扫描代码库，为每个文件生成 routing hint 并写入 DB。

    Returns: {"indexed": int, "skipped": int}
    """
    indexed = 0
    skipped = 0

    # 扫描所有代码文件
    extensions = {".py", ".js", ".ts", ".yaml", ".yml", ".md", ".json"}
    skip_dirs = {".git", "__pycache__", "node_modules", ".trash", "tmp", "data", ".claude"}

    for root, dirs, files in os.walk(str(_REPO_ROOT)):
        # 跳过不需要的目录
        dirs[:] = [d for d in dirs if d not in skip_dirs]

        for fname in files:
            ext = Path(fname).suffix
            if ext not in extensions:
                skipped += 1
                continue

            full_path = Path(root) / fname
            rel_path = str(full_path.relative_to(_REPO_ROOT)).replace("\\", "/")

            hint, tags = _get_routing_hint(rel_path)

            if db:
                try:
                    db.upsert_file_index(rel_path, hint, tags)
                except Exception:
                    pass

            indexed += 1

    log.info(f"cafi_index: indexed {indexed} files, skipped {skipped}")
    return {"indexed": indexed, "skipped": skipped}


def _get_routing_hint(rel_path: str) -> tuple[str, list[str]]:
    """根据路径规则生成 routing hint 和 tags。"""
    for pattern, hint, tags in _ROUTING_RULES:
        if pattern in rel_path:
            return hint, tags

    # 默认 hint
    if rel_path.endswith(".py"):
        return "Python 模块", ["engineering"]
    elif rel_path.endswith(".js"):
        return "JavaScript 模块", ["engineering", "dashboard"]
    elif rel_path.endswith(".md"):
        return "Markdown 文档", ["documentation"]
    elif rel_path.endswith((".yaml", ".yml")):
        return "YAML 配置", ["operations"]

    return "文件", []


def lookup_files(query: str, db=None) -> list[dict]:
    """根据查询词查找相关文件。"""
    if not db:
        return []

    # 从查询词中提取可能的 tags
    tag_map = {
        "采集": ["collector"], "收集": ["collector"],
        "治理": ["governance"], "调度": ["governance"],
        "质量": ["quality"], "测试": ["testing", "quality"],
        "安全": ["security"], "部署": ["docker", "operations"],
        "前端": ["dashboard"], "分析": ["analysis"],
        "记忆": ["memory", "soul"], "预算": ["budget"],
        "事件": ["events"],
    }

    tags = []
    for keyword, mapped_tags in tag_map.items():
        if keyword in query:
            tags.extend(mapped_tags)

    if not tags:
        tags = ["engineering"]  # 默认

    return db.query_file_index(tags=tags, limit=10)
