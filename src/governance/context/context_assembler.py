"""
# DEPRECATED: use ContextEngine instead. Will be removed.
#
# All functionality has been migrated:
#   - match_guidelines, load_shared_knowledge → guidelines_utils.py
#   - assemble_context → ContextEngine.default().assemble()
#   - HOT/WARM/COLD layering → Provider priorities + PriorityProcessor + TruncateProcessor
#
# This file is kept only for backward compatibility.
# Import from guidelines_utils.py or use ContextEngine directly.

动态上下文组装器：根据任务描述匹配相关的 department guidelines。
Parlant-inspired: 不全量注入，只注入任务相关的规则。
"""
import warnings as _warnings
_warnings.warn(
    "context_assembler is deprecated. Use ContextEngine or guidelines_utils instead.",
    DeprecationWarning,
    stacklevel=2,
)

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


def assemble_context(department: str, task: dict) -> str:
    """组装完整的动态上下文。返回应该追加到 prompt 后面的额外上下文字符串。"""
    task_text = f"{task.get('action', '')} {task.get('spec', {}).get('problem', '')} {task.get('spec', {}).get('summary', '')}"

    # ── HOT/WARM/COLD attention tiers (claude-cognitive inspired) ──
    # HOT: always kept, never compressed — learnings + recent run context
    # WARM: kept if space allows — matched guidelines + shared knowledge
    # COLD: first to be dropped — extended memory + learned skills
    hot_parts = []
    warm_parts = []
    cold_parts = []

    # 1. Matched guidelines → WARM
    guidelines = match_guidelines(department, task_text)
    if guidelines:
        warm_parts.extend(guidelines)

    # 2. Shared knowledge → WARM
    shared = load_shared_knowledge(task_text)
    if shared:
        warm_parts.append(shared)

    # 3. Learned skills → COLD (historical, less urgent)
    learned_path = Path("departments") / department / "learned-skills.md"
    if learned_path.exists():
        try:
            learned = learned_path.read_text(encoding="utf-8").strip()
            if learned:
                cold_parts.append(f"[Learned Skills]\n{learned}")
        except Exception:
            pass

    # 4. Extended Memory → COLD
    try:
        from src.governance.context.memory_tier import (
            resolve_tags_from_spec, load_extended_memory, format_extended_for_prompt,
        )
        spec = task.get("spec", {})
        tags = resolve_tags_from_spec(spec)
        if tags:
            extended = load_extended_memory(tags)
            if extended:
                formatted = format_extended_for_prompt(extended)
                if formatted:
                    cold_parts.append(formatted)
    except Exception:
        pass

    # 5. Learnings → HOT (past mistakes, must never be dropped)
    spec = task.get("spec", {}) if isinstance(task.get("spec"), dict) else {}
    learnings = spec.get("learnings", [])
    if learnings:
        hot_parts.append("[Learnings] Rules from past mistakes. Violating these will likely cause the same failures:\n" + "\n".join(learnings))

    if not hot_parts and not warm_parts and not cold_parts:
        return ""

    # ── Assemble with tier-aware compression ──
    MAX_CONTEXT_CHARS = 12000  # ~3400 tokens

    # HOT always included
    hot_text = "\n\n---\n\n".join(hot_parts) if hot_parts else ""
    remaining_budget = MAX_CONTEXT_CHARS - len(hot_text)

    # WARM: include if budget allows
    warm_text = "\n\n---\n\n".join(warm_parts) if warm_parts else ""
    if len(warm_text) > remaining_budget > 0:
        warm_text = warm_text[:remaining_budget] + "\n\n[...warm context truncated...]"
    remaining_budget -= len(warm_text)

    # COLD: include only if budget remains
    cold_text = ""
    if remaining_budget > 500 and cold_parts:  # need at least 500 chars to be useful
        cold_text = "\n\n---\n\n".join(cold_parts)
        if len(cold_text) > remaining_budget:
            cold_text = cold_text[:remaining_budget] + "\n\n[...cold context truncated...]"

    parts = [p for p in [hot_text, warm_text, cold_text] if p]
    return "\n\n---\n\n".join(parts)
