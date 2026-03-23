"""
ACB Intent Manifest — agent 执行时声明意图。

claude-prove 启发：agent commit 时声明意图，按意图分组审查。
Classification: explicit/inferred/speculative

每个任务执行结束后，从 agent 输出中提取意图清单，
帮助刑部按意图分组审查而非逐行看 diff。
"""
import logging
import re
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


class IntentType:
    EXPLICIT = "explicit"        # 明确在 action 中描述的
    INFERRED = "inferred"       # 从代码改动推断的
    SPECULATIVE = "speculative"  # agent 自行判断需要的额外改动


@dataclass
class IntentEntry:
    """单条意图声明。"""
    description: str
    type: str = IntentType.EXPLICIT
    files: list[str] = field(default_factory=list)
    confidence: float = 1.0


@dataclass
class IntentManifest:
    """完整的意图清单。"""
    task_id: int
    action: str
    intents: list[IntentEntry] = field(default_factory=list)

    def to_review_prompt(self) -> str:
        """格式化为刑部审查 prompt。"""
        lines = [
            "## 意图清单（Intent Manifest）",
            f"任务 #{self.task_id}: {self.action}",
            "",
        ]

        by_type = {}
        for intent in self.intents:
            by_type.setdefault(intent.type, []).append(intent)

        for itype, label in [
            (IntentType.EXPLICIT, "明确意图（任务要求做的）"),
            (IntentType.INFERRED, "推断意图（从改动推断的）"),
            (IntentType.SPECULATIVE, "推测意图（agent 额外做的）"),
        ]:
            items = by_type.get(itype, [])
            if not items:
                continue
            lines.append(f"### {label}")
            for item in items:
                files = ", ".join(item.files[:5]) if item.files else "N/A"
                lines.append(f"- {item.description}")
                lines.append(f"  文件: {files} | 信心: {item.confidence:.0%}")
            lines.append("")

        lines.append("请按意图分组审查，重点关注 SPECULATIVE 类别的改动是否必要。")
        return "\n".join(lines)


def build_manifest(task: dict) -> IntentManifest:
    """从任务数据构建意图清单。"""
    task_id = task.get("id", 0)
    action = task.get("action", "")
    spec = task.get("spec", {})
    output = task.get("output", "")

    intents = []

    # 1. Explicit：直接从 action/spec 提取
    intents.append(IntentEntry(
        description=action,
        type=IntentType.EXPLICIT,
        confidence=1.0,
    ))

    if spec.get("expected"):
        intents.append(IntentEntry(
            description=f"预期结果: {spec['expected']}",
            type=IntentType.EXPLICIT,
            confidence=1.0,
        ))

    # 2. Inferred：从输出中提取文件改动
    file_changes = re.findall(
        r'(?:modified|created|edited|wrote|changed)\s+[`"]?([^\s`"]+\.\w+)',
        output, re.IGNORECASE
    )
    if file_changes:
        intents.append(IntentEntry(
            description=f"修改了 {len(set(file_changes))} 个文件",
            type=IntentType.INFERRED,
            files=list(set(file_changes))[:10],
            confidence=0.9,
        ))

    # 3. Speculative：检测 agent 做了但没被要求的事
    speculative_patterns = [
        (r'(?:also|另外|顺便|while at it)\s+(.+)', "额外改动"),
        (r'(?:refactored?|重构了?)\s+(.+)', "顺手重构"),
        (r'(?:added? (?:test|测试))\s*(.*)', "添加测试"),
        (r'(?:updated? (?:doc|文档|comment|注释))\s*(.*)', "更新文档"),
    ]

    for pattern, label in speculative_patterns:
        matches = re.findall(pattern, output, re.IGNORECASE)
        for match in matches:
            intents.append(IntentEntry(
                description=f"{label}: {match[:80]}",
                type=IntentType.SPECULATIVE,
                confidence=0.6,
            ))

    return IntentManifest(task_id=task_id, action=action, intents=intents)
