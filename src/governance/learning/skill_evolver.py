"""
Skill Evolution: 分析部门 run-log，发现重复模式，生成 SKILL.md 改善建议。
不自动修改 SKILL.md —— 所有建议写入 data/suggestions/{dept}/skill-suggestions.md 等待审批。
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from src.core.llm_router import get_router

log = logging.getLogger(__name__)

ANALYSIS_PROMPT = """你是 Orchestrator 吏部的绩效分析师。分析以下部门的执行记录，找出可以改善的模式。

部门：{department}
当前 SKILL.md 内容：
{skill_content}

最近执行记录（{run_count} 条）：
{runs_text}

分析维度：
1. **重复失败**：同类任务反复失败？原因可能是什么？SKILL.md 是否缺少相关指导？
2. **耗时异常**：哪些任务耗时远高于平均？是否可以通过更好的指令减少探索时间？
3. **经验沉淀**：有没有多次成功处理的任务类型，其中的经验可以固化到 SKILL.md？
4. **认知模式匹配**：任务使用的认知模式（direct/react/hypothesis/designer）是否合适？
5. **高频文件**：如果某些文件反复被改动，是否应该在 SKILL.md 里加入这些文件的上下文说明？

输出格式（严格遵循）：

## 发现

### 模式 1: [模式名称]
- 证据: [具体的 run-log 条目引用]
- 建议: [具体的 SKILL.md 改动建议]
- 优先级: HIGH / MEDIUM / LOW

### 模式 2: [模式名称]
...

## 统计
- 总执行次数: N
- 成功率: X%
- 平均耗时: Ys
- 最常改动的文件: [列表]

如果执行记录太少（< 5 条）或没有明显模式，直接输出"记录不足，暂无建议。"
"""


def analyze_department(department: str) -> str | None:
    """分析单个部门的 run-log，返回分析结果文本。"""
    dept_dir = Path("departments") / department
    run_log_path = dept_dir / "run-log.jsonl"
    skill_path = dept_dir / "SKILL.md"

    if not run_log_path.exists():
        log.info(f"SkillEvolver: no run-log for {department}, skipping")
        return None

    # 读取 run-log
    runs = []
    try:
        for line in run_log_path.read_text(encoding="utf-8").strip().split("\n"):
            if line.strip():
                runs.append(json.loads(line))
    except Exception as e:
        log.warning(f"SkillEvolver: failed to read run-log for {department}: {e}")
        return None

    if len(runs) < 5:
        log.info(f"SkillEvolver: {department} has only {len(runs)} runs, need 5+")
        return None

    # 读取当前 SKILL.md
    skill_content = ""
    if skill_path.exists():
        try:
            skill_content = skill_path.read_text(encoding="utf-8")
        except Exception:
            pass

    # 格式化 runs 为文本
    runs_text = "\n".join(
        f"- [{r.get('ts','')}] mode={r.get('mode','?')} status={r.get('status','?')} "
        f"duration={r.get('duration_s',0)}s summary={r.get('summary','')} "
        f"files={r.get('files_changed',[])} notes={r.get('notes','')}"
        for r in runs[-30:]  # 最多分析最近 30 条
    )

    prompt = ANALYSIS_PROMPT.format(
        department=department,
        skill_content=skill_content[:2000],
        run_count=len(runs),
        runs_text=runs_text,
    )

    try:
        result = get_router().generate(prompt, task_type="analysis")
        return result
    except Exception as e:
        log.error(f"SkillEvolver: LLM analysis failed for {department}: {e}")
        return None


def run_evolution():
    """分析所有部门，生成改善建议。"""
    departments_dir = Path("departments")
    if not departments_dir.exists():
        log.warning("SkillEvolver: departments/ directory not found")
        return

    results = {}
    for dept_dir in sorted(departments_dir.iterdir()):
        if not dept_dir.is_dir() or dept_dir.name == "shared":
            continue

        log.info(f"SkillEvolver: analyzing {dept_dir.name}...")
        analysis = analyze_department(dept_dir.name)

        if analysis and "暂无建议" not in analysis:
            # 写入 data/suggestions/{dept}/skill-suggestions.md
            suggestions_dir = Path("data") / "suggestions" / dept_dir.name
            suggestions_dir.mkdir(parents=True, exist_ok=True)
            suggestions_path = suggestions_dir / "skill-suggestions.md"
            header = f"# Skill 改善建议 — {dept_dir.name}\n"
            header += f"生成时间: {datetime.now(timezone.utc).isoformat()}\n"
            header += f"状态: 待审核\n\n"

            try:
                suggestions_path.write_text(header + analysis, encoding="utf-8")
                results[dept_dir.name] = "suggestions generated"
                log.info(f"SkillEvolver: wrote suggestions for {dept_dir.name}")
            except Exception as e:
                log.error(f"SkillEvolver: failed to write suggestions for {dept_dir.name}: {e}")
                results[dept_dir.name] = f"write failed: {e}"
        else:
            results[dept_dir.name] = "no patterns found" if analysis else "skipped (no data)"

    return results
