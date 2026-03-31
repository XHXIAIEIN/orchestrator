"""End-to-end test: context flows from writer → DB → ctx_read."""
import subprocess
import sys
import pytest
from src.storage.events_db import EventsDB
from src.governance.context.writer import ContextWriter
from src.governance.context.tiers import classify_task_tier, TIERS

_WIN_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _run_ctx_read(db_path: str, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "scripts/ctx_read.py", "--db", db_path, *args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL, text=True, cwd=".",
        creationflags=_WIN_FLAGS,
    )


@pytest.fixture
def db(tmp_path):
    return EventsDB(str(tmp_path / "test.db"))


class TestContextParityE2E:
    def test_writer_to_ctx_read_flow(self, db, tmp_path):
        """ContextWriter writes → ctx_read reads back correctly."""
        db_path = str(tmp_path / "test.db")
        session = "e2e-test-1"
        writer = ContextWriter(db, session)

        # Writer populates context
        writer.write_layer1(conversation_summary="User wants to run Clawvard practice")
        writer.write_chain_output(99, '{"hash": "abc123", "nextBatch": [{"id": "q1"}]}')
        writer.write_layer0({"action": "test", "spec": {}}, "engineering")

        # ctx_read should see all keys
        result = _run_ctx_read(db_path, "--session", session, "--list")
        assert "session:conversation_summary" in result.stdout
        assert "chain:99" in result.stdout

        # ctx_read should read chain output
        result = _run_ctx_read(db_path, "--session", session, "--key", "chain:99")
        assert "abc123" in result.stdout
        assert "nextBatch" in result.stdout

    def test_tier_classification_affects_budget(self, db):
        """Heavy tier gets 128K budget, light gets 4K."""
        heavy = classify_task_tier("Clawvard practice: understanding", {})
        light = classify_task_tier("check docker status", {})
        assert heavy.context_budget == 128_000
        assert light.context_budget == 4_000

    def test_chain_context_survives_compression(self, db):
        """Chain output stored in DB is not subject to output_compress truncation."""
        session = "e2e-chain"
        writer = ContextWriter(db, session)
        # Simulate a large API response with nextBatch
        large_output = '{"results": [], "hash": "x", "nextBatch": ' + '[' + ','.join(
            [f'{{"id": "q{i}", "prompt": "' + 'x' * 500 + '"}}' for i in range(10)]
        ) + ']}'
        writer.write_chain_output(100, large_output)
        row = db.get_context(session, "chain:100")
        # Full content preserved, no truncation
        assert len(row["content"]) == len(large_output)
        assert "nextBatch" in row["content"]
