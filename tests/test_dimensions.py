# tests/test_dimensions.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.governance.audit.dimensions import score_dimension, score_all, format_radar, DimensionScore

def test_score_execution_b_range():
    """75% success rate → B range."""
    runs = [
        *[{"status": "done", "duration_s": 60, "department": "engineering"}] * 9,
        *[{"status": "failed", "duration_s": 10, "department": "engineering"}] * 3,
    ]
    score = score_dimension("execution", runs)
    assert isinstance(score, DimensionScore)
    assert score.dimension == "execution"
    assert 70 <= score.score <= 79
    assert score.grade in ("B+", "B")

def test_score_execution_perfect():
    runs = [{"status": "done", "duration_s": 50, "department": "engineering"}] * 20
    score = score_dimension("execution", runs)
    assert score.score >= 90
    assert score.grade in ("S", "A+", "A")

def test_score_with_no_data():
    score = score_dimension("execution", [])
    assert score.score == 0
    assert score.grade == "N/A"
    assert "insufficient" in score.note.lower()

def test_score_with_duration_degradation():
    """Duration increasing > 100% should apply 15-point penalty."""
    runs = [
        *[{"status": "done", "duration_s": 30, "department": "engineering"}] * 5,
        *[{"status": "done", "duration_s": 200, "department": "engineering"}] * 5,
    ]
    score = score_dimension("execution", runs)
    # 100% success = 100, minus 15 penalty = 85
    assert score.score == 85.0
    assert score.grade == "A"

def test_score_all_returns_six():
    runs = [{"status": "done", "duration_s": 50, "department": "engineering"}] * 5
    scores = score_all(runs)
    assert len(scores) == 6
    # Only engineering has data
    eng = [s for s in scores if s.dimension == "execution"][0]
    assert eng.grade != "N/A"
    # Others should be N/A
    others = [s for s in scores if s.dimension != "execution"]
    assert all(s.grade == "N/A" for s in others)

def test_format_radar_output():
    runs = [{"status": "done", "duration_s": 50, "department": "engineering"}] * 10
    scores = score_all(runs)
    output = format_radar(scores)
    assert "六维度成绩单" in output
    assert "执行力" in output
    assert "综合" in output
