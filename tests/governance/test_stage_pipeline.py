"""Tests for stage pipeline."""
from src.governance.pipeline.stage_pipeline import (
    has_stage, get_pipeline, DEFAULT_PIPELINES, should_skip_stage, Stage,
)


def test_engineering_has_verify_gates():
    assert has_stage("engineering", "verify_gates")


def test_engineering_has_deslop():
    assert has_stage("engineering", "deslop")


def test_engineering_has_quality_review():
    assert has_stage("engineering", "quality_review")


def test_protocol_no_verify_gates():
    assert not has_stage("protocol", "verify_gates")


def test_protocol_no_quality_review():
    assert not has_stage("protocol", "quality_review")


def test_all_departments_have_execute():
    for dept in DEFAULT_PIPELINES:
        assert has_stage(dept, "execute"), f"{dept} missing execute stage"


def test_get_pipeline_returns_pipeline():
    p = get_pipeline("engineering")
    assert p.department == "engineering"
    assert len(p.stages) > 0


def test_should_skip_scout_task():
    stage = Stage("quality_review", "builtin", skip_if="scout_task")
    assert should_skip_stage(stage, {"is_scout": True})
    assert not should_skip_stage(stage, {"is_scout": False})


def test_should_skip_rework():
    stage = Stage("novelty_check", "builtin", skip_if="rework_task")
    assert should_skip_stage(stage, {"rework_count": 2})
    assert not should_skip_stage(stage, {"rework_count": 0})
