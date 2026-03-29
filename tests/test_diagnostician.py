import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.governance.audit.diagnostician import diagnose, format_diagnosis

def test_diagnose_finds_weakest():
    """Diagnose should identify the weakest dimension and suggest improvement."""
    runs = [
        # Engineering: 10 runs, 9 success = 90%
        *[{"department": "engineering", "status": "done", "duration_s": 50}] * 9,
        {"department": "engineering", "status": "failed", "duration_s": 10},
        # Security: 10 runs, 5 success = 50%
        *[{"department": "security", "status": "done", "duration_s": 30}] * 5,
        *[{"department": "security", "status": "failed", "duration_s": 5}] * 5,
    ]
    result = diagnose(runs)
    assert result.weakest.dimension == "security"
    assert result.weakest.score < 60
    assert len(result.prescriptions) > 0
    assert any("security" in p.lower() or "兵部" in p for p in result.prescriptions)

def test_diagnose_empty_data():
    result = diagnose([])
    assert result.weakest is None
    assert "insufficient" in result.summary.lower()

def test_diagnose_summary_format():
    runs = [
        *[{"department": "engineering", "status": "done", "duration_s": 50}] * 10,
        *[{"department": "quality", "status": "done", "duration_s": 30}] * 8,
        *[{"department": "quality", "status": "failed", "duration_s": 5}] * 2,
    ]
    result = diagnose(runs)
    assert "综合" in result.summary
    assert "最强" in result.summary
    assert "最弱" in result.summary

def test_format_diagnosis_output():
    runs = [
        *[{"department": "engineering", "status": "done", "duration_s": 50}] * 10,
        *[{"department": "security", "status": "failed", "duration_s": 5}] * 5,
        *[{"department": "security", "status": "done", "duration_s": 30}] * 5,
    ]
    result = diagnose(runs)
    output = format_diagnosis(result)
    assert "六维度成绩单" in output
    assert "诊断" in output
    assert "处方" in output

def test_format_diagnosis_empty():
    result = diagnose([])
    output = format_diagnosis(result)
    assert "数据不足" in output
