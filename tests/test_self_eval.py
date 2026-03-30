"""验证 self_eval 管线：考试数据 → learnings → promoter → boot.md"""
import tempfile
import shutil
from pathlib import Path

from src.governance.audit.self_eval import ExamResult, ingest_all_exams

ERRORS_TEMPLATE = """# Errors

Classified execution errors from tool calls, API failures, and task timeouts.
Format: `ERR-YYYYMMDD-NNN` with Pattern-Key for recurring pattern detection.

<!-- entries below this line are auto-managed -->
"""

LEARNINGS_TEMPLATE = """# Learnings

Hard-won knowledge updates and best practices, auto-captured from run history.
Format: `LRN-YYYYMMDD-NNN` with Pattern-Key for dedup and promotion tracking.

<!-- entries below this line are auto-managed -->
"""

BOOT_TEMPLATE = """# SOUL Boot Image

## Learnings

- existing learning entry
"""


def test_three_exams_promote_execution():
    """执行力连续 3 次 80 分 → 达到阈值 → 自动写进 boot.md"""
    with tempfile.TemporaryDirectory() as tmpdir:
        learnings_dir = Path(tmpdir) / "learnings"
        learnings_dir.mkdir()
        (learnings_dir / "ERRORS.md").write_text(ERRORS_TEMPLATE, encoding="utf-8")
        (learnings_dir / "LEARNINGS.md").write_text(LEARNINGS_TEMPLATE, encoding="utf-8")

        boot_path = Path(tmpdir) / "boot.md"
        boot_path.write_text(BOOT_TEMPLATE, encoding="utf-8")

        exams = [
            ExamResult("exam-1", {"execution": 80, "reflection": 100, "retrieval": 95}, "A+", 98),
            ExamResult("exam-2", {"execution": 80, "reflection": 90, "retrieval": 95}, "A+", 91),
            ExamResult("exam-3", {"execution": 80, "reflection": 65, "retrieval": 95}, "A", 81),
        ]

        outcome = ingest_all_exams(exams, str(learnings_dir), str(boot_path))

        # 执行力出现 3 次，应该被晋升
        assert any("agent-exec-ceiling" in p for p in outcome.promoted), \
            f"execution pattern should be promoted, got: {outcome.promoted}"

        # boot.md 应该包含执行力矫正规则
        boot_text = boot_path.read_text(encoding="utf-8")
        assert "edge-case" in boot_text.lower() or "boundary" in boot_text.lower(), \
            "boot.md should contain execution fix rule"

        # 反思力也出现了 2 次低于阈值 (90 < 85? no, 90 >= 85)
        # 实际上: exam-2 reflection=90 >= 85 不触发, exam-3 reflection=65 < 85 触发
        # 所以反思力只有 1 次，不晋升
        errors_text = (learnings_dir / "ERRORS.md").read_text(encoding="utf-8")
        assert "agent-performative-reflection" in errors_text

        print("PASS: execution promoted after 3 exams")
        print(f"Promoted: {outcome.promoted}")
        print(f"Errors recorded: {outcome.errors_recorded}")


def test_reflection_decline_triggers():
    """反思力连续下降也触发记录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        learnings_dir = Path(tmpdir) / "learnings"
        learnings_dir.mkdir()
        (learnings_dir / "ERRORS.md").write_text(ERRORS_TEMPLATE, encoding="utf-8")
        (learnings_dir / "LEARNINGS.md").write_text(LEARNINGS_TEMPLATE, encoding="utf-8")

        boot_path = Path(tmpdir) / "boot.md"
        boot_path.write_text(BOOT_TEMPLATE, encoding="utf-8")

        # 3 次都低于 85 阈值
        exams = [
            ExamResult("exam-1", {"reflection": 80}, "A", 90),
            ExamResult("exam-2", {"reflection": 70}, "A", 85),
            ExamResult("exam-3", {"reflection": 65}, "A", 81),
        ]

        outcome = ingest_all_exams(exams, str(learnings_dir), str(boot_path))

        # 反思力 3 次低于阈值 → 晋升
        assert any("performative-reflection" in p for p in outcome.promoted), \
            f"reflection pattern should be promoted, got: {outcome.promoted}"

        boot_text = boot_path.read_text(encoding="utf-8")
        assert "widen" in boot_text.lower() or "interval" in boot_text.lower(), \
            "boot.md should contain reflection fix rule"

        print("PASS: reflection promoted after 3 low scores")
        print(f"Boot learnings section now includes: {[l for l in boot_text.split(chr(10)) if 'auto-promoted' in l]}")


if __name__ == "__main__":
    test_three_exams_promote_execution()
    test_reflection_decline_triggers()
    print("\nAll self_eval tests passed.")
