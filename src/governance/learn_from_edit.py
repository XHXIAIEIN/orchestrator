"""
Learn-from-edit — 从人工修正中提取通用教训。

Artemis 启发：人工修正 agent 产出 → diff 分析 → 提取通用教训 → 追加到 lessons。

当人类在 agent 完成后手动修改文件时，分析 diff，提取模式性错误，
写入 departments/{dept}/learned-skills.md 供未来的 agent 参考。

集成点：
  - Git hook 或定时扫描检测人工修正
  - Governor _finalize_task 后检查是否有人工改动
"""
import logging
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class EditLesson:
    """从人工修正中提取的教训。"""
    file: str
    what_agent_did: str     # agent 原来写了什么
    what_human_changed: str  # 人类改成了什么
    lesson: str             # 通用化的教训
    category: str           # 分类：style/logic/missing/over-engineering/naming
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


# ── Diff Analysis ──

def analyze_human_edits(task_commit: str, department: str,
                        cwd: str = None) -> list[EditLesson]:
    """分析 agent commit 之后的人工修改。

    比较 task_commit 和当前 HEAD，找出人工修正的 diff，
    提取可学习的模式。

    Args:
        task_commit: agent 任务产生的 commit hash
        department: 执行任务的部门
        cwd: 工作目录
    """
    work_dir = cwd or str(_REPO_ROOT)

    try:
        # 获取 agent commit 之后的 diff
        result = subprocess.run(
            ["git", "diff", f"{task_commit}..HEAD", "--", "*.py", "*.js", "*.ts", "*.yaml", "*.yml"],
            cwd=work_dir, capture_output=True, text=True, timeout=10,
        )
        if not result.stdout.strip():
            return []

        return _parse_diff_for_lessons(result.stdout, department)
    except Exception as e:
        log.warning(f"learn_from_edit: failed to analyze edits: {e}")
        return []


def _parse_diff_for_lessons(diff_text: str, department: str) -> list[EditLesson]:
    """从 git diff 输出中提取教训。"""
    lessons = []
    current_file = ""

    # 分析 diff 中的模式
    for line in diff_text.splitlines():
        # 文件头
        if line.startswith("diff --git"):
            m = re.search(r'b/(.+)$', line)
            if m:
                current_file = m.group(1)
            continue

        if not current_file:
            continue

        # 删除的行（agent 写的）和添加的行（人类改的）
        if line.startswith("-") and not line.startswith("---"):
            old_line = line[1:].strip()
            # 检测常见的修正模式
            lesson = _detect_pattern(old_line, current_file)
            if lesson:
                lessons.append(lesson)

    return lessons[:10]  # 最多 10 条


def _detect_pattern(removed_line: str, file: str) -> EditLesson | None:
    """检测常见的被修正模式。"""
    # 过度注释
    if removed_line.startswith("#") and len(removed_line) > 50:
        comment_text = removed_line.lstrip("# ")
        if any(w in comment_text.lower() for w in ["this function", "这个函数", "note:", "注意"]):
            return EditLesson(
                file=file,
                what_agent_did=f"添加了冗长注释: {removed_line[:60]}",
                what_human_changed="删除了不必要的注释",
                lesson="不要添加解释显而易见代码的注释。只在逻辑不自明时加注释。",
                category="style",
            )

    # 不必要的 try/except
    if "try:" in removed_line or "except Exception" in removed_line:
        return None  # 需要上下文，单行不足以判断

    # 过度防御性编程
    if "if " in removed_line and ("is not None" in removed_line or "!= None" in removed_line):
        if removed_line.count("is not None") >= 2:
            return EditLesson(
                file=file,
                what_agent_did=f"过度空值检查: {removed_line[:60]}",
                what_human_changed="简化条件判断",
                lesson="不要对不可能为 None 的内部变量做空值检查。只在系统边界验证。",
                category="over-engineering",
            )

    return None


# ── Lesson Storage ──

def save_lessons(department: str, lessons: list[EditLesson]):
    """将教训追加到部门的 learned-skills.md。"""
    if not lessons:
        return

    learned_path = _REPO_ROOT / "departments" / department / "learned-skills.md"

    # 读取现有内容
    existing = ""
    if learned_path.exists():
        existing = learned_path.read_text(encoding="utf-8")

    # 追加新教训
    new_section = f"\n\n## 教训 ({datetime.now(timezone.utc).strftime('%Y-%m-%d')})\n"
    for lesson in lessons:
        new_section += (
            f"\n### [{lesson.category}] {lesson.file}\n"
            f"- Agent 做了: {lesson.what_agent_did}\n"
            f"- 人类改为: {lesson.what_human_changed}\n"
            f"- **教训**: {lesson.lesson}\n"
        )

    # 去重：如果相同的 lesson 已存在，跳过
    for lesson in lessons:
        if lesson.lesson in existing:
            log.info(f"learn_from_edit: skipping duplicate lesson: {lesson.lesson[:50]}")
            continue

    learned_path.write_text(existing + new_section, encoding="utf-8")
    log.info(f"learn_from_edit: saved {len(lessons)} lessons to {learned_path}")


def get_lessons(department: str, n: int = 10) -> list[str]:
    """读取部门最近的教训列表。"""
    learned_path = _REPO_ROOT / "departments" / department / "learned-skills.md"
    if not learned_path.exists():
        return []

    content = learned_path.read_text(encoding="utf-8")
    lessons = re.findall(r'\*\*教训\*\*:\s*(.+)', content)
    return lessons[-n:]
