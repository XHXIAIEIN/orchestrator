"""Review Dispatch — quality review dispatch and rework loop logic."""
import logging
import re
from typing import Callable

from src.storage.events_db import EventsDB
from src.governance.pipeline.eval_loop import parse_eval_output, format_eval_for_rework, MAX_EVAL_ITERATIONS

# Optional imports
try:
    from src.governance.pipeline.scratchpad import build_handoff_prompt
except ImportError:
    build_handoff_prompt = None

try:
    from src.governance.policy.tiered_review import determine_review_tier, get_review_config
except ImportError:
    determine_review_tier = None
    get_review_config = None

try:
    from src.governance.context.intent_manifest import build_manifest
except ImportError:
    build_manifest = None

log = logging.getLogger(__name__)


def _extract_artifact(task: dict) -> dict:
    """Extract structured handoff artifact from completed task."""
    try:
        output = task.get("output") or ""

        commit_match = re.search(r'(?:commit|committed|提交)[:\s]*([0-9a-f]{7,40})', output, re.IGNORECASE)
        commit = commit_match.group(1) if commit_match else ""

        file_patterns = re.findall(r'(?:src|departments|SOUL|dashboard|tests|data|docs|bin)/[\w/.-]+\.\w+', output)
        files_changed = list(set(file_patterns))[:10]

        done_match = re.search(r'DONE:\s*(.+)', output)
        summary = done_match.group(1).strip() if done_match else task.get("action", "")[:100]

        remaining = re.findall(r'(?:TODO|FIXME|remaining|still need|未完成)[:\s]*(.+)', output, re.IGNORECASE)
        remaining = [r.strip()[:100] for r in remaining[:5]]

        found = []
        for pattern in [r'(?:found|discovered|noticed|发现)[:\s]*(.+)',
                       r'(?:note|warning|注意)[:\s]*(.+)']:
            found.extend(re.findall(pattern, output, re.IGNORECASE))
        found = [f.strip()[:100] for f in found[:5]]

        return {
            "task_id": task.get("id", 0),
            "status": task.get("status", ""),
            "done": summary,
            "found": found,
            "remaining": remaining,
            "files_changed": files_changed,
            "commit": commit,
        }
    except Exception:
        return {
            "task_id": task.get("id", 0),
            "status": task.get("status", ""),
            "done": task.get("action", "")[:100],
            "found": [],
            "remaining": [],
            "files_changed": [],
            "commit": "",
        }


class ReviewDispatcher:
    """Handles quality review dispatch and rework loop logic."""

    MAX_REWORK = MAX_EVAL_ITERATIONS - 1

    def __init__(self, db: EventsDB, on_execute: Callable[[int], None] | None = None):
        self.db = db
        self.on_execute = on_execute

    def dispatch_quality_review(self, parent_id: int, parent_task: dict, task_cwd: str, project_name: str):
        """工部完成任务后，自动创建刑部验收任务。跳过门下省审查（验收本身就是审查）。"""
        parent_spec = parent_task.get("spec", {})
        parent_action = parent_task.get("action", "")
        if parent_spec.get("department") == "quality":
            return

        artifact = _extract_artifact(parent_task)
        files_str = ", ".join(artifact["files_changed"]) if artifact["files_changed"] else "未检测到"
        commit_str = artifact["commit"] or "未检测到"

        # Scratchpad 交接：引用文件路径而非内联全文
        scratchpad = parent_spec.get("scratchpad", "")
        if scratchpad and build_handoff_prompt:
            observation = build_handoff_prompt(
                task_id=parent_id, department="engineering",
                summary=artifact["done"],
                scratchpad_path=scratchpad,
            )
            observation += (
                f"\n\n改动文件：{files_str}\n"
                f"Commit: {commit_str}\n"
            )
        elif artifact["commit"]:
            observation = (
                f"工部执行摘要：{artifact['done']}\n"
                f"改动文件：{files_str}\n"
                f"Commit: {commit_str}\n\n"
                f"请自行运行 git diff {artifact['commit']}~1..{artifact['commit']} 查看实际代码改动，不要依赖上述摘要做判断。"
            )
        else:
            observation = (
                f"工部执行摘要：{artifact['done']}\n"
                f"改动文件：{files_str}\n"
                f"Commit: {commit_str}\n\n"
                f"未检测到 commit hash，请运行 git log --oneline -3 查看最近提交，然后用 git diff 查看实际改动。"
            )

        # ── Tiered Review: 根据任务复杂度选择审查深度 ──
        review_tier = determine_review_tier(parent_task) if determine_review_tier else "quick"
        review_cfg = get_review_config(review_tier) if get_review_config else {"instructions": ""}
        log.info(f"ReviewManager: quality review for #{parent_id}: tier={review_tier}")

        # ── Intent Manifest: 按意图分组审查 ──
        if build_manifest:
            manifest = build_manifest(parent_task)
            manifest_prompt = manifest.to_review_prompt()
            observation += f"\n\n{manifest_prompt}"

        observation += f"\n\n{review_cfg['instructions']}"

        review_spec = {
            "department": "quality",
            "intent": "quality_review" if review_tier == "quick" else "quality_regression",
            "project": project_name,
            "cwd": task_cwd,
            "problem": f"验收工部任务 #{parent_id} 的执行结果",
            "observation": observation,
            "expected": parent_spec.get("expected", "任务正确完成，无引入新问题"),
            "summary": f"刑部验收：{parent_action[:40]}",
            "review_tier": review_tier,
        }
        review_id = self.db.create_task(
            action=f"Review 工部任务 #{parent_id} 的代码改动：检查 git diff、跑测试（如有）、确认无逻辑错误",
            reason=f"工部任务 #{parent_id} 已完成，需刑部验收（{review_tier}）",
            priority="medium",
            spec=review_spec,
            source="auto",
            parent_task_id=parent_id,
        )
        self.db.write_log(f"工部任务 #{parent_id} 完成 → 派刑部验收任务 #{review_id}", "INFO", "governor")
        log.info(f"ReviewManager: dispatched quality review #{review_id} for engineering task #{parent_id}")

        # 跳过门下省审查（验收本身就是审查），直接执行
        self.db.update_task(review_id, scrutiny_note="免审：工部→刑部验收链自动派单")
        if self.on_execute:
            self.on_execute(review_id)

    def dispatch_rework(self, review_task_id: int, review_task: dict,
                        task_cwd: str, project_name: str, review_output: str,
                        eval_result=None):
        """刑部验收失败，打回工部重做。追溯原始工部任务，携带结构化反馈。"""
        parent_id = review_task.get("parent_task_id")
        if not parent_id:
            log.warning(f"ReviewManager: review #{review_task_id} has no parent_task_id, skip rework")
            return

        original = self.db.get_task(parent_id)
        if not original:
            return
        original_spec = original.get("spec", {})
        rework_count = original_spec.get("rework_count", 0)
        if rework_count >= self.MAX_REWORK:
            # ── 达到上限，人类介入 ──
            self.db.write_log(
                f"EVAL 循环上限：任务 #{parent_id} 已返工 {rework_count} 次，仍有 "
                f"CRITICAL={eval_result.critical_count if eval_result else '?'} "
                f"HIGH={eval_result.high_count if eval_result else '?'} 问题。需要人类介入。",
                "WARNING", "governor")
            log.warning(f"ReviewManager: task #{parent_id} hit max rework ({rework_count}), escalating to human")
            self.db.create_task(
                action=f"人工介入：任务 #{parent_id} 经过 {rework_count} 轮返工仍未通过刑部验收",
                reason=f"EVAL 循环达上限，CRITICAL={eval_result.critical_count if eval_result else '?'}",
                priority="critical",
                spec={"department": "engineering", "project": project_name, "cwd": task_cwd,
                      "parent_task_id": parent_id, "escalation": True},
                source="user_intent",
                parent_task_id=parent_id,
            )
            return

        # ── 结构化反馈：优先用 EVAL 解析结果 ──
        if eval_result:
            feedback = format_eval_for_rework(eval_result, rework_count + 1)
        else:
            issue_lines = [
                l for l in review_output.splitlines()
                if l.strip().startswith(('\U0001f534', '\U0001f7e1', '[CRITICAL]', '[BUG]', '[WARN]'))
            ]
            if issue_lines:
                feedback = "\n".join(issue_lines[:10])
            else:
                feedback_lines = []
                for line in review_output.splitlines():
                    if line.startswith("VERDICT:"):
                        break
                    feedback_lines.append(line)
                feedback = "\n".join(feedback_lines[-10:])

        rework_spec = {
            "department": "engineering",
            "intent": "code_fix",
            "project": project_name,
            "cwd": task_cwd,
            "problem": f"刑部验收任务 #{review_task_id} 驳回了工部任务 #{parent_id}，需要返工修复",
            "observation": f"刑部反馈：\n{feedback}",
            "expected": original_spec.get("expected", "修复刑部指出的问题"),
            "summary": f"返工：{original.get('action', '')[:30]}（刑部驳回）",
            "rework_count": rework_count + 1,
        }
        rework_id = self.db.create_task(
            action=f"根据刑部反馈修复任务 #{parent_id} 的问题：{feedback[:100]}",
            reason=f"刑部验收 #{review_task_id} FAIL，需返工",
            priority="high",
            spec=rework_spec,
            source="auto",
            parent_task_id=review_task_id,
        )
        self.db.write_log(
            f"刑部验收 #{review_task_id} FAIL → 打回工部，创建返工任务 #{rework_id}（第 {rework_count + 1} 次）",
            "WARNING", "governor")
        log.info(f"ReviewManager: dispatched rework #{rework_id} for failed review #{review_task_id}")

        # 返工任务通过 on_execute 回调走完整管线（Governor 会处理审查+执行）
        if self.on_execute:
            self.on_execute(rework_id)
