"""ReviewManager — post-execution finalization, quality review dispatch, rework loop."""
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from src.storage.events_db import EventsDB
from src.governance.scrutiny import classify_cognitive_mode
from src.governance.policy.blueprint import load_blueprint
from src.governance.pipeline.eval_loop import parse_eval_output, format_eval_for_rework, MAX_EVAL_ITERATIONS
from src.governance.output_validator import validate_output
from src.governance.review_dispatch import ReviewDispatcher, _extract_artifact
from src.governance.task_handoff import TaskHandoff

# Optional imports
try:
    from src.governance.pipeline.scratchpad import write_scratchpad, build_handoff_prompt
except ImportError:
    write_scratchpad = None
    build_handoff_prompt = None

try:
    from src.governance.audit.run_logger import append_run_log
except ImportError:
    append_run_log = None

try:
    from src.governance.audit.outcome_tracker import record_outcome
except ImportError:
    record_outcome = None

try:
    from src.governance.pipeline.fan_out import get_fan_out
except ImportError:
    get_fan_out = None

try:
    from src.governance.policy.tiered_review import determine_review_tier, get_review_config
except ImportError:
    determine_review_tier = None
    get_review_config = None

try:
    from src.governance.policy.policy_advisor import observe_task_execution
except ImportError:
    observe_task_execution = None

try:
    from src.governance.learning.deslop import scan_for_slop, format_slop_report
except ImportError:
    scan_for_slop = None
    format_slop_report = None

try:
    from src.governance.learning.learn_from_edit import analyze_human_edits, save_lessons
except ImportError:
    analyze_human_edits = None
    save_lessons = None

try:
    from src.governance.learning.evolution_cycle import should_trigger, run_evolution_cycle
except ImportError:
    should_trigger = None
    run_evolution_cycle = None

try:
    from src.governance.learning.fact_extractor import extract_facts, save_extracted_facts
except ImportError:
    extract_facts = None
    save_extracted_facts = None

try:
    from src.governance.quality.fix_first import classify_eval_result
except ImportError:
    classify_eval_result = None

try:
    from src.governance.pipeline.stage_pipeline import has_stage
except ImportError:
    has_stage = None

try:
    from src.governance.context.intent_manifest import build_manifest
except ImportError:
    build_manifest = None

try:
    from src.governance.budget.token_budget import TokenAccountant
except ImportError:
    TokenAccountant = None

try:
    from src.governance.safety.verify_gate import run_gates, save_gate_record
except ImportError:
    run_gates = None
    save_gate_record = None

try:
    from src.governance.audit.file_ratchet import FileRatchet, DEFAULT_RATCHET
except ImportError:
    FileRatchet = None
    DEFAULT_RATCHET = None

try:
    from src.core.llm_router import get_router
except ImportError:
    get_router = None

# Production → Test Corpus (stolen from Braintrust, Round 38)
try:
    from src.governance.eval.corpus import capture_for_corpus, CAPTURABLE_STATUSES
except ImportError:
    capture_for_corpus = None
    CAPTURABLE_STATUSES = set()

# Cross-Model Review (stolen from gstack, Round 3-7)
try:
    from src.governance.cross_review import CrossModelReviewer
except ImportError:
    CrossModelReviewer = None

# Elder Council (stolen from karpathy/llm-council, Round 19)
try:
    from src.governance.council import ElderCouncil
except ImportError:
    ElderCouncil = None

log = logging.getLogger(__name__)

# Departments considered high blast-radius for cross-review
_HIGH_BLAST_DEPARTMENTS = {"security", "operations"}


class ReviewManager:
    """Post-execution: finalization, quality review dispatch, rework loop."""

    MAX_REWORK = MAX_EVAL_ITERATIONS - 1

    def __init__(self, db: EventsDB, on_execute: Callable[[int], None] | None = None):
        self.db = db
        self.on_execute = on_execute
        self.accountant = TokenAccountant(db=self.db) if TokenAccountant else None
        self._dispatcher = ReviewDispatcher(db=self.db, on_execute=on_execute)

    def finalize_task(self, task_id: int, task: dict, dept_key: str,
                      status: str, output: str, task_cwd: str, project_name: str, now: str):
        """Post-execution: visual verify, scratchpad, update status, write run log, dispatch collaboration."""
        spec = task.get("spec", {})

        # ── Scratchpad: 长输出写文件，DB 只存摘要 ──
        scratchpad_path = None
        if len(output) > 500 and write_scratchpad:
            try:
                sp_path = write_scratchpad(task_id, dept_key, output, metadata={
                    "project": project_name, "status": status,
                })
                scratchpad_path = str(sp_path)
                spec["scratchpad"] = scratchpad_path
                self.db.update_task(task_id, spec=json.dumps(spec, ensure_ascii=False, default=str))
            except Exception as e:
                log.warning(f"ReviewManager: scratchpad write failed for task #{task_id}: {e}")

        # ── Pipeline-aware stage checks ──
        _has = lambda stage: has_stage(dept_key, stage) if has_stage else False

        # ── Output Schema Validation: Constraint Paradox ──
        try:
            validation = validate_output(dept_key, output)
            if not validation["valid"]:
                log.warning(
                    f"review: output schema validation failed for {dept_key} task#{task_id}: "
                    f"missing {validation['missing_fields']}"
                )
                self.db.add_agent_event(task_id, "output_validation", {
                    "valid": False,
                    "missing_fields": validation["missing_fields"],
                    "score": validation["score"],
                })
            else:
                log.info(
                    f"review: output schema valid for {dept_key} task#{task_id} "
                    f"(score={validation['score']})"
                )
        except Exception as e:
            log.debug(f"ReviewManager: output schema validation error for task #{task_id}: {e}")

        # ── Verify Gates: non-negotiable 质量门控 ──
        if status == "done" and _has("verify_gates") and run_gates:
            try:
                gate_record = run_gates(dept_key, task_id, task_cwd)
                save_gate_record(gate_record, db=self.db)
                if not gate_record.all_passed:
                    failed_gates = [g for g in gate_record.gates if not g.passed]
                    gate_msg = "; ".join(f"{g.gate_id}: {g.message}" for g in failed_gates)
                    status = "gate_failed"
                    output += f"\n\n[GATE FAILED] {gate_msg}"
                    log.warning(f"ReviewManager: task #{task_id} failed verify gates: {gate_msg}")
            except Exception as e:
                log.warning(f"ReviewManager: verify gate error for task #{task_id}: {e}")

        # ── Elder Council / Cross-Model Review (Round 19: karpathy/llm-council) ──
        # HIGH blast-radius → full council (5 elders + ranking + chairman)
        # MEDIUM with critical flag → light council (skip ranking stage)
        # Fallback → legacy CrossModelReviewer
        _needs_review = (
            status == "done"
            and (dept_key in _HIGH_BLAST_DEPARTMENTS
                 or spec.get("requires_approval")
                 or spec.get("priority") == "critical")
        )
        if _needs_review and ElderCouncil:
            try:
                is_high = dept_key in _HIGH_BLAST_DEPARTMENTS or spec.get("requires_approval")
                council = ElderCouncil(skip_ranking=not is_high)
                # Round 22 (Review Swarm): build intent packet for focused deliberation
                _intent = {
                    "should_change": task.get("action", ""),
                    "should_not_change": spec.get("constraints", []),
                    "constraints": spec.get("expected", ""),
                }
                if build_manifest:
                    try:
                        manifest = build_manifest(task)
                        speculative = [i.description for i in manifest.intents
                                       if i.type == "speculative"]
                        if speculative:
                            _intent["speculative_changes"] = speculative
                    except Exception:
                        pass
                verdict = council.deliberate(
                    question=f"Review this {dept_key} task output for safety and correctness",
                    context=output[:2000],
                    intent=_intent,
                )
                self.db.add_agent_event(task_id, "council_verdict", verdict.to_event_dict())
                if verdict.decision == "reject":
                    output += f"\n\n[COUNCIL: REJECT] {verdict.synthesis[:300]}"
                    log.warning(
                        f"ReviewManager: council rejected task #{task_id} "
                        f"(confidence={verdict.confidence:.0%}, dissent={verdict.dissent_count}/5)"
                    )
                elif verdict.decision == "defer":
                    output += f"\n\n[COUNCIL: DEFER] {verdict.synthesis[:300]}"
                    log.warning(f"ReviewManager: council deferred task #{task_id}")
                else:
                    log.info(
                        f"ReviewManager: council approved task #{task_id} "
                        f"(confidence={verdict.confidence:.0%}, dissent={verdict.dissent_count}/5)"
                    )
            except Exception as e:
                log.debug(f"ReviewManager: council failed for task #{task_id}: {e}")
                # Fallback to legacy cross-review
                if CrossModelReviewer:
                    try:
                        reviewer = CrossModelReviewer()
                        report = reviewer.review(
                            question=f"Review this {dept_key} task output for safety and correctness",
                            context=output[:2000],
                        )
                        self.db.add_agent_event(task_id, "cross_review", {
                            "consensus": report.consensus,
                            "confidence": report.confidence,
                            "recommendation": report.recommendation[:500],
                            "latency_ms": report.latency_ms,
                        })
                        if report.consensus == "disagree":
                            output += f"\n\n[CROSS-REVIEW: DISAGREE] {report.recommendation[:300]}"
                    except Exception as e2:
                        log.debug(f"ReviewManager: cross-review fallback also failed: {e2}")
        elif _needs_review and CrossModelReviewer:
            try:
                reviewer = CrossModelReviewer()
                report = reviewer.review(
                    question=f"Review this {dept_key} task output for safety and correctness",
                    context=output[:2000],
                )
                self.db.add_agent_event(task_id, "cross_review", {
                    "consensus": report.consensus,
                    "confidence": report.confidence,
                    "recommendation": report.recommendation[:500],
                    "latency_ms": report.latency_ms,
                })
                if report.consensus == "disagree":
                    output += f"\n\n[CROSS-REVIEW: DISAGREE] {report.recommendation[:300]}"
            except Exception as e:
                log.debug(f"ReviewManager: cross-review failed for task #{task_id}: {e}")

        # ── Deslop: 扫描工部产出的 AI 臭味 ──
        if status == "done" and _has("deslop") and scan_for_slop:
            try:
                import subprocess
                diff = subprocess.run(
                    ["git", "diff", "--name-only"], cwd=task_cwd,
                    capture_output=True, text=True, timeout=10,
                ).stdout.strip()
                all_findings = []
                for fpath in diff.splitlines()[:10]:  # 最多扫 10 个文件
                    if fpath.endswith(".py"):
                        full = Path(task_cwd) / fpath
                        if full.exists():
                            content = full.read_text(encoding="utf-8", errors="ignore")
                            all_findings.extend(scan_for_slop(str(fpath), content))
                if all_findings:
                    slop_report = format_slop_report(all_findings)
                    output += f"\n\n{slop_report}"
                    log.info(f"ReviewManager: deslop found {len(all_findings)} issues in task #{task_id}")
            except Exception as e:
                log.debug(f"ReviewManager: deslop scan failed for task #{task_id}: {e}")

        # ── File Ratchet: check for code bloat after execution ──
        if status == "done" and FileRatchet and DEFAULT_RATCHET:
            try:
                ratchet = FileRatchet(DEFAULT_RATCHET, repo_root=task_cwd)
                ratchet_results = ratchet.check_all()
                ratchet_failures = [r for r in ratchet_results if not r.passed]
                if ratchet_failures:
                    ratchet_lines = []
                    for r in ratchet_failures[:5]:  # Report top 5
                        rel_path = ratchet._to_relative(r.path)
                        ratchet_lines.append(
                            f"  {rel_path}: {r.baseline_lines} -> {r.current_lines} (+{r.delta})"
                        )
                    ratchet_msg = "\n".join(ratchet_lines)
                    output += f"\n\n[RATCHET WARNING] {len(ratchet_failures)} file(s) grew past threshold:\n{ratchet_msg}"
                    log.warning(
                        f"ReviewManager: file ratchet flagged {len(ratchet_failures)} files in task #{task_id}"
                    )
                    self.db.add_agent_event(task_id, "file_ratchet", {
                        "failures": len(ratchet_failures),
                        "details": [
                            {"path": ratchet._to_relative(r.path), "baseline": r.baseline_lines,
                             "current": r.current_lines, "delta": r.delta}
                            for r in ratchet_failures[:10]
                        ],
                    })
            except Exception as e:
                log.debug(f"ReviewManager: file ratchet check failed for task #{task_id}: {e}")

        # 视觉验证
        if status == "done":
            verification = self._visual_verify(task_id, task_cwd, spec)
            if verification:
                output = f"{output}\n\n[visual_verify] {verification}"

        finished = datetime.now(timezone.utc).isoformat()
        try:
            self.db.update_task(task_id, status=status, output=output, finished_at=finished)
        except Exception as e:
            log.error(f"ReviewManager: failed to update task #{task_id} status: {e}")
        self.db.write_log(f"任务 #{task_id}（{project_name}）{status}：{output[:80]}", "INFO" if status == "done" else "ERROR", "governor")
        log.info(f"ReviewManager: task #{task_id} {status}")

        # ── Production → Test Corpus (R38: Braintrust feedback loop) ──
        # Capture interesting failures as eval corpus entries for Clawvard
        if capture_for_corpus and status in CAPTURABLE_STATUSES:
            try:
                trajectory_summary = {}
                # Try to get trajectory from execution snapshot
                try:
                    from src.governance.audit.execution_snapshot import SnapshotStore
                    store = SnapshotStore()
                    snapshot = store.load_snapshot(task_id)
                    trajectory_summary = snapshot.get_summary()
                except Exception:
                    pass
                corpus_path = capture_for_corpus(
                    task_id=task_id,
                    task=task,
                    output=output,
                    status=status,
                    trajectory_summary=trajectory_summary,
                )
                if corpus_path:
                    self.db.add_agent_event(task_id, "corpus_captured", {
                        "corpus_file": str(corpus_path.name),
                        "status": status,
                    })
            except Exception as e:
                log.debug(f"ReviewManager: corpus capture failed for task #{task_id}: {e}")

        # ── Dependency Chain: unblock downstream tasks (stolen from Cline Kanban) ──
        if status == "done":
            try:
                unblocked = self.db.unblock_ready_dependents(task_id)
                if unblocked:
                    ids_str = ", ".join(f"#{uid}" for uid in unblocked)
                    self.db.write_log(
                        f"依赖链触发: 任务 #{task_id} 完成 → 解锁 {ids_str}",
                        "INFO", "governor",
                    )
                    log.info(f"ReviewManager: dependency chain unblocked {ids_str} after task #{task_id}")
                    # Auto-execute unblocked tasks
                    if self.on_execute:
                        for uid in unblocked:
                            self.on_execute(uid)
            except Exception as e:
                log.warning(f"ReviewManager: dependency chain trigger failed for task #{task_id}: {e}")

        # 部门执行记忆
        commit_hash = ""
        if append_run_log:
            try:
                duration_s = 0
                try:
                    started_dt = datetime.fromisoformat(task.get("started_at") or now)
                    finished_dt = datetime.fromisoformat(finished)
                    duration_s = int((finished_dt - started_dt).total_seconds())
                except (ValueError, TypeError):
                    pass
                commit_hash = ""
                commit_match = re.search(r'\b([0-9a-f]{7,40})\b', output) if "commit" in output.lower() else None
                if commit_match:
                    commit_hash = commit_match.group(1)
                append_run_log(
                    department=dept_key,
                    task_id=task_id,
                    mode=task.get("source", "auto"),
                    summary=task.get("action", "")[:200],
                    commit=commit_hash,
                    status=status,
                    duration_s=duration_s,
                    notes=output[:200] if status == "failed" else "",
                )
            except Exception as e:
                log.warning(f"ReviewManager: failed to write run-log for task #{task_id}: {e}")

        # ── Learn-from-edit: 检测人工修正，提取教训 ──
        if status == "done" and analyze_human_edits and commit_hash:
            try:
                edit_lessons = analyze_human_edits(commit_hash, dept_key, cwd=task_cwd)
                if edit_lessons and save_lessons:
                    save_lessons(dept_key, edit_lessons)
            except Exception as e:
                log.debug(f"ReviewManager: learn_from_edit failed for task #{task_id}: {e}")

        # ── Fact Extraction: 从任务输出中提取可复用事实 ──
        if status == "done" and extract_facts and output:
            try:
                facts = extract_facts(output, task_spec=spec, department=dept_key)
                if facts and save_extracted_facts:
                    saved = save_extracted_facts(
                        self.db, facts, department=dept_key, task_id=task_id,
                    )
                    if saved:
                        log.info(f"ReviewManager: extracted {saved} facts from task #{task_id}")
            except Exception as e:
                log.debug(f"ReviewManager: fact extraction failed for task #{task_id}: {e}")

        # ── Evolution Cycle: 检查是否应触发自我改善 ──
        if should_trigger and should_trigger(dept_key):
            try:
                evo_result = run_evolution_cycle(dept_key)
                if evo_result.get("patch_applied"):
                    log.info(
                        f"ReviewManager: evolution cycle applied patch for {dept_key} "
                        f"({evo_result.get('pattern_findings', 0)} patterns)"
                    )
                elif evo_result.get("triggered"):
                    log.info(f"ReviewManager: evolution cycle ran for {dept_key}: {evo_result.get('reason')}")
            except Exception as e:
                log.debug(f"ReviewManager: evolution cycle failed for {dept_key}: {e}")

        # ── TokenAccountant: 记录成本 ──
        if self.accountant:
            try:
                agent_events = self.db.get_agent_events(task_id, limit=10)
                for evt in reversed(agent_events):
                    data = json.loads(evt["data"]) if isinstance(evt.get("data"), str) else evt.get("data", {})
                    if data.get("cost_usd"):
                        self.accountant.record_usage(task_id, dept_key, "agent_sdk", data["cost_usd"])
                        break
            except Exception:
                pass

        # ── Policy Advisor: observe execution for denial patterns ──
        if observe_task_execution:
            try:
                blueprint = load_blueprint(dept_key)
                if blueprint:
                    agent_events = self.db.get_agent_events(task_id, limit=50)
                    observe_task_execution(
                        department=dept_key, task_id=task_id,
                        agent_events=agent_events, task_output=output,
                        task_status=status, blueprint=blueprint,
                    )
            except Exception as e:
                log.warning(f"ReviewManager: policy advisor observation failed for task #{task_id}: {e}")

        # ── Outcome Tracker: planned vs actual ──
        if record_outcome:
            try:
                record_outcome(task, output, dept_key)
            except Exception as e:
                log.debug(f"ReviewManager: outcome tracking failed ({e})")

        # ── Fan-out: 多路输出 ──
        if get_fan_out:
            try:
                fan = get_fan_out()
                fan.emit(f"task.{status}", {
                    "task_id": task_id, "department": dept_key,
                    "status": status, "project": project_name,
                    "summary": task.get("action", "")[:100],
                }, department=dept_key)
            except Exception:
                pass

        # 部门协作 — PLAN→ACT→EVAL 闭环 (pipeline-driven)
        if status == "done":
            if _has("quality_review"):
                task["output"] = output
                handoff = TaskHandoff(
                    from_dept=dept_key,
                    to_dept="quality",
                    handoff_type="quality_review",
                    task_id=task_id,
                    output=output,
                    artifact=_extract_artifact(task),
                    reason=f"{dept_key} task #{task_id} completed, dispatching quality review",
                )
                self.db.add_agent_event(task_id, "task_handoff", handoff.to_dict())
                self._dispatch_quality_review(task_id, task, task_cwd, project_name, handoff=handoff)
            elif dept_key == "quality":
                eval_result = parse_eval_output(output)
                log.info(f"ReviewManager: EVAL task #{task_id}: passed={eval_result.passed} "
                         f"critical={eval_result.critical_count} high={eval_result.high_count}")

                # ── Fix-First: classify findings as AUTO_FIX / ASK / SKIP ──
                if classify_eval_result and eval_result.issues:
                    try:
                        fix_report = classify_eval_result(eval_result, task_id=task_id)
                        self.db.add_agent_event(task_id, "fix_first_report", {
                            "auto_fix": len(fix_report.auto_fixable),
                            "ask": len(fix_report.needs_human),
                            "skip": len(fix_report.skippable),
                            "can_auto_resolve": fix_report.can_auto_resolve,
                        })
                        log.info(
                            f"ReviewManager: FixFirst task #{task_id} — "
                            f"{len(fix_report.auto_fixable)} auto-fix, "
                            f"{len(fix_report.needs_human)} ask, "
                            f"{len(fix_report.skippable)} skip"
                        )
                    except Exception as e:
                        log.debug(f"ReviewManager: fix_first classification failed for task #{task_id}: {e}")

                if eval_result.should_rework:
                    handoff = TaskHandoff(
                        from_dept="quality",
                        to_dept="engineering",
                        handoff_type="rework",
                        task_id=task_id,
                        output=output,
                        reason=f"Quality review #{task_id} failed, rework needed",
                        rework_count=spec.get("rework_count", 0),
                    )
                    self.db.add_agent_event(task_id, "task_handoff", handoff.to_dict())
                    self._dispatch_rework(task_id, task, task_cwd, project_name, output,
                                          eval_result=eval_result, handoff=handoff)

    def _visual_verify(self, task_id: int, task_cwd: str, spec: dict) -> str:
        """可选视觉验证：检查约定路径是否有截图，有则用 vision 模型验证。"""
        verify_dir = Path(task_cwd) / ".governor-verify"
        if not verify_dir.exists():
            return ""

        images = list(verify_dir.glob("*.png")) + list(verify_dir.glob("*.jpg"))
        if not images:
            return ""

        image_paths = [str(p) for p in images[:3]]
        expected = spec.get("expected", "任务完成")

        if not get_router:
            return ""

        try:
            result = get_router().generate(
                f"这是任务执行后的截图。预期结果是：{expected}\n\n"
                f"请判断截图是否符合预期，用一句话回答。",
                task_type="vision",
                images=image_paths,
            )
            if result:
                log.info(f"ReviewManager: visual verify task #{task_id}: {result[:80]}")
                for p in images:
                    p.unlink(missing_ok=True)
                verify_dir.rmdir()
            return result
        except Exception as e:
            log.warning(f"ReviewManager: visual verify failed: {e}")
            return ""

    def _dispatch_quality_review(self, parent_id: int, parent_task: dict, task_cwd: str, project_name: str, handoff=None):
        """Delegate to ReviewDispatcher."""
        self._dispatcher.dispatch_quality_review(parent_id, parent_task, task_cwd, project_name, handoff=handoff)

    def _dispatch_rework(self, review_task_id: int, review_task: dict,
                         task_cwd: str, project_name: str, review_output: str,
                         eval_result=None, handoff=None):
        """Delegate to ReviewDispatcher."""
        self._dispatcher.dispatch_rework(review_task_id, review_task, task_cwd, project_name,
                                         review_output, eval_result=eval_result, handoff=handoff)
