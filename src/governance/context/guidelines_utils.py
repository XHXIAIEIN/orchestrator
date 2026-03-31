"""
Guideline matching and shared knowledge utilities.

Extracted from context_assembler.py so that Providers can use these
without depending on the deprecated assembler module.
"""
import re
from pathlib import Path


def extract_trigger_keywords(guideline_content: str) -> list[str]:
    """从 guideline 文件中提取触发条件关键词。"""
    keywords = []
    in_trigger = False
    for line in guideline_content.splitlines():
        if line.strip().lower().startswith("## 触发条件"):
            in_trigger = True
            continue
        if in_trigger:
            if line.strip().startswith("##"):
                break
            # 解析 "关键词: a, b, c" 格式
            if "关键词" in line or "keywords" in line.lower():
                parts = line.split(":", 1)
                if len(parts) > 1:
                    kws = [k.strip().lower() for k in parts[1].split(",") if k.strip()]
                    keywords.extend(kws)
    return keywords


def match_guidelines(department: str, task_description: str) -> list[str]:
    """匹配任务相关的 guidelines，返回匹配到的 guideline 内容列表。"""
    guidelines_dir = Path("departments") / department / "guidelines"
    if not guidelines_dir.exists():
        return []

    task_lower = task_description.lower()
    matched = []

    for gfile in sorted(guidelines_dir.glob("*.md")):
        try:
            content = gfile.read_text(encoding="utf-8")
            keywords = extract_trigger_keywords(content)
            if any(kw in task_lower for kw in keywords):
                # 提取 ## 规则 section 的内容（不需要触发条件部分）
                rules_section = _extract_rules_section(content)
                if rules_section:
                    matched.append(f"【{gfile.stem} 规则】\n{rules_section}")
        except Exception:
            continue

    return matched


def _extract_rules_section(content: str) -> str:
    """从 guideline 中提取 ## 规则 section。"""
    lines = content.splitlines()
    in_rules = False
    rules = []
    for line in lines:
        if line.strip().startswith("## 规则"):
            in_rules = True
            continue
        if in_rules:
            if line.strip().startswith("## "):
                break
            rules.append(line)
    return "\n".join(rules).strip()


def load_shared_knowledge(task_description: str) -> str:
    """加载 departments/shared/ 中与任务相关的共享知识。"""
    shared_dir = Path("departments") / "shared"
    if not shared_dir.exists():
        return ""

    # 简单策略：如果任务提到代码/文件/项目结构，加载 codebase-map
    # 如果提到 bug/issue/问题，加载 known-issues
    parts = []
    task_lower = task_description.lower()

    for name, keywords in [
        ("codebase-map.md", ["代码", "文件", "结构", "路径", "code", "file", "structure"]),
        ("known-issues.md", ["bug", "issue", "问题", "错误", "error", "失败", "fail"]),
        ("recent-changes.md", ["最近", "recent", "上次", "之前", "last"]),
    ]:
        fpath = shared_dir / name
        if fpath.exists() and any(k in task_lower for k in keywords):
            try:
                content = fpath.read_text(encoding="utf-8").strip()
                if content:
                    parts.append(f"【共享知识: {name}】\n{content}")
            except Exception:
                continue

    return "\n\n".join(parts)
