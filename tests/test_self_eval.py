"""验证 self_eval 管线：考试数据 → fitness rules → learnings DB → promoter → boot.md"""
from pathlib import Path

from src.storage.events_db import EventsDB
from src.governance.audit.self_eval import ExamResult, ingest_all_exams, ingest_exam
from src.governance.audit.fitness import Gate, Tier

BOOT_TEMPLATE = """# SOUL Boot Image

## Learnings

- existing learning entry
"""


def _setup(tmp_path):
    """Create DB, boot.md, and fitness dir with test rules."""
    db = EventsDB(str(tmp_path / "test.db"))
    boot_path = tmp_path / "boot.md"
    boot_path.write_text(BOOT_TEMPLATE, encoding="utf-8")

    # Create fitness rules matching the project's docs/fitness/
    fitness_dir = tmp_path / "fitness"
    fitness_dir.mkdir()

    (fitness_dir / "execution.md").write_text(
        "---\n"
        "dimension: execution\n"
        "pattern_key: agent-exec-ceiling\n"
        "gate: hard\n"
        "tier: normal\n"
        "weight: 35\n"
        "threshold_pass: 85\n"
        "threshold_warn: 70\n"
        "error_summary: Agent execution score capped at 80 — code output lacks edge-case coverage and tests\n"
        "learning_summary: After writing code, STOP and add boundary tests before submitting — do not rely on momentum\n"
        "---\n\nExecution detail.\n",
        encoding="utf-8",
    )
    (fitness_dir / "reflection.md").write_text(
        "---\n"
        "dimension: reflection\n"
        "pattern_key: agent-performative-reflection\n"
        "gate: hard\n"
        "tier: normal\n"
        "weight: 30\n"
        "threshold_pass: 85\n"
        "threshold_warn: 65\n"
        "error_summary: Agent reflection declining — acknowledges problems but does not modify behavior\n"
        "learning_summary: When expressing uncertainty, WIDEN the interval and COMMIT to the wider range\n"
        "---\n\nReflection detail.\n",
        encoding="utf-8",
    )
    (fitness_dir / "retrieval.md").write_text(
        "---\n"
        "dimension: retrieval\n"
        "pattern_key: agent-retrieval-stable\n"
        "gate: advisory\n"
        "tier: fast\n"
        "weight: 10\n"
        "threshold_pass: 90\n"
        "threshold_warn: 80\n"
        "---\n\nAdvisory only.\n",
        encoding="utf-8",
    )

    return db, str(boot_path), str(fitness_dir)


def test_three_exams_promote_execution(tmp_path):
    """执行力连续 3 次 80 分 → 达到阈值 → 自动写进 boot.md"""
    db, boot_path, fitness_dir = _setup(tmp_path)

    exams = [
        ExamResult("exam-1", {"execution": 80, "reflection": 100, "retrieval": 95}, "A+", 98),
        ExamResult("exam-2", {"execution": 80, "reflection": 90, "retrieval": 95}, "A+", 91),
        ExamResult("exam-3", {"execution": 80, "reflection": 65, "retrieval": 95}, "A", 81),
    ]

    outcome = ingest_all_exams(exams, db=db, boot_path=boot_path, fitness_dir=fitness_dir)

    assert any("agent-exec-ceiling" in p for p in outcome.promoted), \
        f"execution pattern should be promoted, got: {outcome.promoted}"

    boot_text = Path(boot_path).read_text(encoding="utf-8")
    assert "edge-case" in boot_text.lower() or "boundary" in boot_text.lower(), \
        "boot.md should contain execution fix rule"


def test_reflection_decline_triggers(tmp_path):
    """反思力连续下降也触发记录"""
    db, boot_path, fitness_dir = _setup(tmp_path)

    exams = [
        ExamResult("exam-1", {"reflection": 80}, "A", 90),
        ExamResult("exam-2", {"reflection": 70}, "A", 85),
        ExamResult("exam-3", {"reflection": 65}, "A", 81),
    ]

    outcome = ingest_all_exams(exams, db=db, boot_path=boot_path, fitness_dir=fitness_dir)

    assert any("performative-reflection" in p for p in outcome.promoted), \
        f"reflection pattern should be promoted, got: {outcome.promoted}"

    boot_text = Path(boot_path).read_text(encoding="utf-8")
    assert "widen" in boot_text.lower() or "interval" in boot_text.lower(), \
        "boot.md should contain reflection fix rule"


def test_advisory_dimension_no_db_writes(tmp_path):
    """Advisory 维度（如 retrieval）低分不写 DB，只记日志"""
    db, boot_path, fitness_dir = _setup(tmp_path)

    result = ExamResult("exam-adv", {"retrieval": 50}, "B", 60)
    outcome = ingest_exam(result, db=db, boot_path=boot_path, fitness_dir=fitness_dir)

    assert len(outcome.errors_recorded) == 0
    assert len(outcome.learnings_recorded) == 0


def test_verdict_attached_to_outcome(tmp_path):
    """Outcome should carry FitnessVerdict."""
    db, boot_path, fitness_dir = _setup(tmp_path)

    result = ExamResult("exam-v", {"execution": 90, "reflection": 90}, "A+", 99)
    outcome = ingest_exam(result, db=db, boot_path=boot_path, fitness_dir=fitness_dir)

    assert outcome.verdict is not None
    assert outcome.verdict.passed
    assert outcome.verdict.weighted_score > 0


def test_evidence_gap_recorded(tmp_path):
    """Evidence gap should be recorded as error."""
    db, boot_path, fitness_dir = _setup(tmp_path)

    result = ExamResult("exam-eg", {"execution": 90}, "A+", 99)
    outcome = ingest_exam(
        result, db=db, boot_path=boot_path, fitness_dir=fitness_dir,
        changed_files=["src/governance/audit/self_eval.py"],
        test_files_changed=[],
    )

    assert outcome.verdict is not None
    assert len(outcome.verdict.evidence_gaps) > 0


if __name__ == "__main__":
    import tempfile
    tests = [
        test_three_exams_promote_execution,
        test_reflection_decline_triggers,
        test_advisory_dimension_no_db_writes,
        test_verdict_attached_to_outcome,
        test_evidence_gap_recorded,
    ]
    for t in tests:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            t(Path(tmpdir))
        print(f"  PASS: {t.__name__}")
    print(f"\nAll {len(tests)} self_eval tests passed.")
