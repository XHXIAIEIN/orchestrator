import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from src.governance.audit.evolution_chain import (
    EvolutionPhase,
    record_signal, record_hypothesis, record_attempt, record_outcome,
    load_chain, get_department_history,
)


def test_full_four_stage_chain(tmp_path):
    chain_path = str(tmp_path / "evolution_events.jsonl")
    evo_id = record_signal("engineering", ["success_rate dropped to 0.6", "3 timeouts in last 10 runs"], chain_path)
    assert evo_id.startswith("evo-")
    record_hypothesis(evo_id, "Timeout threshold too low for large codebases", "Increase timeout_s from 300 to 600", chain_path)
    record_attempt(evo_id, ["departments/engineering/manifest.yaml"], "timeout_s: 300 → 600", chain_path)
    record_outcome(evo_id, True, {"success_rate": 0.6}, {"success_rate": 0.85}, chain_path)
    events = load_chain(chain_path)
    evo_events = [e for e in events if e["evo_id"] == evo_id]
    assert len(evo_events) == 4
    phases = [e["phase"] for e in evo_events]
    assert phases == ["signal", "hypothesis", "attempt", "outcome"]


def test_incomplete_chain_detected(tmp_path):
    chain_path = str(tmp_path / "evolution_events.jsonl")
    evo_id = record_signal("quality", ["review findings dropped"], chain_path)
    events = load_chain(chain_path)
    evo_events = [e for e in events if e["evo_id"] == evo_id]
    assert len(evo_events) == 1
    assert evo_events[0]["phase"] == "signal"


def test_get_department_history(tmp_path):
    chain_path = str(tmp_path / "evolution_events.jsonl")
    evo1 = record_signal("engineering", ["signal A"], chain_path)
    record_outcome(evo1, True, {}, {}, chain_path)
    evo2 = record_signal("quality", ["signal B"], chain_path)
    record_outcome(evo2, False, {}, {}, chain_path)
    eng_history = get_department_history(chain_path, "engineering")
    assert len(eng_history) == 1
    assert eng_history[0]["evo_id"] == evo1
    qual_history = get_department_history(chain_path, "quality")
    assert len(qual_history) == 1
    assert qual_history[0]["evo_id"] == evo2


def test_chain_is_append_only(tmp_path):
    chain_path = str(tmp_path / "evolution_events.jsonl")
    record_signal("engineering", ["test"], chain_path)
    record_signal("operations", ["test2"], chain_path)
    lines = Path(chain_path).read_text().strip().split("\n")
    assert len(lines) == 2
    for line in lines:
        event = json.loads(line)
        assert "ts" in event
        assert "evo_id" in event
        assert "phase" in event
