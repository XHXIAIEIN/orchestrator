"""Tests for R64 Hindsight three-phase transaction executor."""
import pytest
from src.governance.transaction.three_phase import (
    Phase,
    PhaseSpec,
    TransactionPlan,
    ThreePhaseExecutor,
    three_phase_write,
)


@pytest.mark.asyncio
async def test_three_phases_run_in_order():
    order = []

    async def prep(ctx, acc): order.append("p"); return {"pv": 1}
    async def commit(ctx, acc): order.append("c"); return {"cv": acc["pv"] + 1}
    async def supp(ctx, acc): order.append("s"); return {"sv": acc["cv"] + 1}

    results = await three_phase_write(prep, commit, supp, context={})
    assert order == ["p", "c", "s"]
    assert [r.phase for r in results] == [Phase.PREPARE, Phase.COMMIT, Phase.SUPPLEMENT]
    assert all(r.success for r in results)


@pytest.mark.asyncio
async def test_prepare_failure_aborts_plan():
    calls = []

    async def prep(ctx, acc): calls.append("p"); raise RuntimeError("boom")
    async def commit(ctx, acc): calls.append("c"); return {}

    results = await three_phase_write(prep, commit, context={})
    assert calls == ["p"]
    assert len(results) == 1
    assert results[0].success is False
    assert "boom" in (results[0].error or "")


@pytest.mark.asyncio
async def test_supplement_failure_is_best_effort():
    async def prep(ctx, acc): return {}
    async def commit(ctx, acc): return {"ok": True}
    async def supp(ctx, acc): raise RuntimeError("supp fail")

    results = await three_phase_write(prep, commit, supp, context={})
    assert results[1].success is True  # commit still ok
    assert results[2].success is False
    assert "supp fail" in (results[2].error or "")
