"""
Scratchpad — 文件传递协议，替代 stdout 传文本。

Agent 间不传文本传文件路径，彻底杜绝 context 膨胀。
协议：agent 完成后输出包含 DONE|{path}，下游 agent 读文件获取完整结果。

workflow-orchestration 启发：文件系统即通信通道。
"""
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent
while _REPO_ROOT != _REPO_ROOT.parent and not ((_REPO_ROOT / "departments").is_dir() and (_REPO_ROOT / "src").is_dir()):
    _REPO_ROOT = _REPO_ROOT.parent
SCRATCHPAD_DIR = _REPO_ROOT / "tmp" / "scratchpad"


def get_scratchpad_path(task_id: int, department: str = "") -> Path:
    """获取任务的 scratchpad 文件路径。"""
    SCRATCHPAD_DIR.mkdir(parents=True, exist_ok=True)
    prefix = f"{department}-" if department else ""
    return SCRATCHPAD_DIR / f"{prefix}task-{task_id}.md"


def write_scratchpad(task_id: int, department: str, content: str,
                     metadata: dict = None) -> Path:
    """将任务输出写入 scratchpad 文件。返回文件路径。"""
    path = get_scratchpad_path(task_id, department)

    header = (
        f"# Task #{task_id} — {department}\n"
        f"<!-- ts: {datetime.now(timezone.utc).isoformat()} -->\n"
    )
    if metadata:
        for k, v in metadata.items():
            header += f"<!-- {k}: {v} -->\n"
    header += "\n"

    path.write_text(header + content, encoding="utf-8")
    log.info(f"scratchpad: wrote {len(content)} chars to {path}")
    return path


def read_scratchpad(task_id: int, department: str = "") -> str:
    """读取 scratchpad 文件内容。优先精确匹配，fallback 到模糊搜索。"""
    # 精确匹配
    path = get_scratchpad_path(task_id, department)
    if path.exists():
        return path.read_text(encoding="utf-8")

    # Fallback: 搜索任意部门的 scratchpad
    if SCRATCHPAD_DIR.exists():
        for f in SCRATCHPAD_DIR.glob(f"*task-{task_id}.md"):
            return f.read_text(encoding="utf-8")

    return ""


def parse_done_signal(output: str) -> tuple[str | None, str]:
    """从 agent 输出中解析 DONE|{path} 信号。

    Returns: (scratchpad_path or None, remaining_output)
    """
    match = re.search(r'DONE\|(.+?)(?:\s|$)', output)
    if match:
        path = match.group(1).strip()
        remaining = output[:match.start()] + output[match.end():]
        return path, remaining.strip()
    return None, output


def build_handoff_prompt(task_id: int, department: str,
                         summary: str, scratchpad_path: str) -> str:
    """构建跨部门交接 prompt，引用 scratchpad 而非内联文本。"""
    return (
        f"## 上游任务交接\n"
        f"- 任务 ID: #{task_id}\n"
        f"- 执行部门: {department}\n"
        f"- 执行摘要: {summary}\n"
        f"- 完整结果: 请读取文件 `{scratchpad_path}`\n\n"
        f"请先用 Read 工具读取上述文件获取完整执行结果，再开始你的工作。"
    )
