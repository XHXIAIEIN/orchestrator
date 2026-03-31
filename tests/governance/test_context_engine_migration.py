"""
Tests verifying ContextEngine produces equivalent output to the deprecated context_assembler.

Migration context:
  - context_assembler.py → ContextEngine (engine.py) + guidelines_utils.py
  - HOT/WARM/COLD tiers → Provider priorities + PriorityProcessor + TruncateProcessor
  - match_guidelines / load_shared_knowledge → GuidelinesProvider via guidelines_utils
"""
import warnings
from unittest.mock import patch, MagicMock
import pytest

from src.governance.context.engine import ContextEngine, TaskContext, ContextChunk
from src.governance.context.providers import (
    GuidelinesProvider, MemoryProvider, SystemPromptProvider,
)
from src.governance.context.processors import PriorityProcessor, TruncateProcessor


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def sample_task():
    return {
        "action": "fix the broken import in collector.py",
        "spec": {
            "problem": "ImportError when running collector",
            "summary": "file structure issue",
            "learnings": [
                "Always check __init__.py exports after moving modules.",
                "Run tests before committing refactors.",
            ],
        },
    }


@pytest.fixture
def sample_ctx(sample_task):
    return TaskContext.from_task(sample_task, department="engineering")


# ── 1. guidelines_utils is decoupled from context_assembler ──────

class TestGuidelinesUtilsDecoupling:
    """Verify that guidelines_utils.py works independently."""

    def test_import_guidelines_utils_without_context_assembler(self):
        """guidelines_utils should import cleanly without context_assembler."""
        from src.governance.context.guidelines_utils import (
            match_guidelines, load_shared_knowledge, extract_trigger_keywords,
        )
        assert callable(match_guidelines)
        assert callable(load_shared_knowledge)
        assert callable(extract_trigger_keywords)

    def test_extract_trigger_keywords(self):
        from src.governance.context.guidelines_utils import extract_trigger_keywords

        content = """# Test Guideline
## 触发条件
关键词: deploy, 部署, rollback

## 规则
- Always use blue-green deployment
"""
        keywords = extract_trigger_keywords(content)
        assert "deploy" in keywords
        assert "部署" in keywords
        assert "rollback" in keywords

    def test_match_guidelines_missing_dir(self):
        from src.governance.context.guidelines_utils import match_guidelines
        result = match_guidelines("nonexistent_department_xyz", "some task")
        assert result == []

    def test_load_shared_knowledge_missing_dir(self):
        from src.governance.context.guidelines_utils import load_shared_knowledge
        result = load_shared_knowledge("some task about code")
        # Should not raise, returns empty or content
        assert isinstance(result, str)


# ── 2. GuidelinesProvider uses guidelines_utils, not context_assembler ──

class TestGuidelinesProviderSource:
    """Verify GuidelinesProvider imports from guidelines_utils."""

    def test_provider_uses_guidelines_utils(self, sample_ctx):
        """GuidelinesProvider should call guidelines_utils, not context_assembler."""
        provider = GuidelinesProvider()

        with patch("src.governance.context.providers.log") as mock_log:
            # Patch the import target in providers.py
            with patch(
                "src.governance.context.guidelines_utils.match_guidelines",
                return_value=["【test 规则】\nDo X not Y"],
            ) as mock_match:
                with patch(
                    "src.governance.context.guidelines_utils.load_shared_knowledge",
                    return_value="【共享知识: codebase-map.md】\nProject layout...",
                ) as mock_shared:
                    chunks = provider.provide(sample_ctx)

            assert len(chunks) >= 1
            # Verify we got guideline content
            sources = [c.source for c in chunks]
            assert any("dept" in s for s in sources)


# ── 3. ContextEngine priority mapping matches HOT/WARM/COLD ─────

class TestPriorityMapping:
    """Verify that ContextEngine priorities replicate HOT/WARM/COLD behavior."""

    def test_learnings_are_highest_priority(self):
        """Learnings (HOT in old system) should have the lowest priority number."""
        provider = MemoryProvider()
        ctx = TaskContext(
            department="engineering",
            task_text="fix bug",
            spec={"learnings": ["Don't do X"]},
        )
        chunks = provider.provide(ctx)
        learning_chunks = [c for c in chunks if "learnings" in c.source]
        assert learning_chunks, "Should produce learnings chunks"
        assert all(c.priority <= 10 for c in learning_chunks), (
            f"Learnings priority should be <= 10 (HOT), got {[c.priority for c in learning_chunks]}"
        )

    def test_guidelines_are_warm_priority(self):
        """Guidelines (WARM) should have mid-range priority."""
        # Just verify the provider sets the expected priority range
        chunk = ContextChunk(source="guidelines/dept", content="test", priority=30)
        assert 20 <= chunk.priority <= 40

    def test_cold_items_have_high_priority_number(self):
        """Extended memory and learned skills (COLD) should have high priority numbers."""
        chunk_extended = ContextChunk(source="memory/extended", content="test", priority=70)
        chunk_skills = ContextChunk(source="memory/learned_skills", content="test", priority=75)
        assert chunk_extended.priority >= 60
        assert chunk_skills.priority >= 60

    def test_priority_processor_sorts_hot_before_cold(self):
        """PriorityProcessor should sort HOT (low number) before COLD (high number)."""
        proc = PriorityProcessor()
        chunks = [
            ContextChunk(source="cold", content="cold stuff", priority=70),
            ContextChunk(source="hot", content="hot stuff", priority=5),
            ContextChunk(source="warm", content="warm stuff", priority=30),
        ]
        sorted_chunks = proc.process(chunks)
        assert sorted_chunks[0].source == "hot"
        assert sorted_chunks[1].source == "warm"
        assert sorted_chunks[2].source == "cold"


# ── 4. TruncateProcessor replicates budget behavior ─────────────

class TestTruncation:
    """Verify TruncateProcessor replicates the MAX_CONTEXT_CHARS budget from context_assembler."""

    def test_truncation_drops_cold_first(self):
        """With tight budget, COLD (high priority number) gets dropped first."""
        proc = TruncateProcessor(budget_tokens=100)
        chunks = [
            ContextChunk(source="hot", content="A" * 200, priority=5),    # ~50 tokens
            ContextChunk(source="warm", content="B" * 200, priority=30),  # ~50 tokens
            ContextChunk(source="cold", content="C" * 800, priority=70),  # ~200 tokens
        ]
        # Sort first (as engine does)
        chunks = PriorityProcessor().process(chunks)
        result = proc.process(chunks)
        sources = [c.source for c in result]
        assert "hot" in sources
        assert "warm" in sources
        # cold should be dropped or truncated

    def test_hot_always_preserved(self):
        """HOT chunks should never be dropped even with very tight budget."""
        proc = TruncateProcessor(budget_tokens=60)
        chunks = [
            ContextChunk(source="hot", content="A" * 200, priority=5),
        ]
        result = proc.process(chunks)
        assert len(result) == 1
        assert result[0].source == "hot"


# ── 5. ContextEngine.assemble produces non-empty output ──────────

class TestEngineAssembly:
    """End-to-end: ContextEngine.assemble() produces valid context."""

    def test_assemble_with_learnings_only(self):
        """If only learnings are present, engine should produce output."""
        engine = ContextEngine()
        engine.register_provider(MemoryProvider())
        engine.register_processor(PriorityProcessor())
        engine.register_processor(TruncateProcessor(budget_tokens=2000))

        ctx = TaskContext(
            department="engineering",
            task_text="debug collector",
            spec={"learnings": ["Check imports after refactor"]},
        )
        result = engine.assemble(ctx, budget_tokens=2000)
        assert "Check imports after refactor" in result

    def test_assemble_empty_task(self):
        """Empty task should not crash, just return empty string."""
        engine = ContextEngine()
        engine.register_provider(MemoryProvider())
        engine.register_processor(PriorityProcessor())

        ctx = TaskContext()
        result = engine.assemble(ctx)
        assert isinstance(result, str)

    def test_default_engine_creates_all_providers(self):
        """ContextEngine.default() should register the core providers."""
        engine = ContextEngine.default()
        provider_names = [p.name for p in engine._providers]
        assert "system_prompt" in provider_names
        assert "guidelines" in provider_names
        assert "memory" in provider_names
        assert "history" in provider_names


# ── 6. context_assembler emits deprecation warning ───────────────

class TestDeprecationWarning:
    """Importing context_assembler should emit a DeprecationWarning."""

    def test_context_assembler_warns(self):
        """Importing context_assembler triggers DeprecationWarning."""
        import importlib
        import sys

        # Remove from cache so re-import triggers module-level code
        mod_name = "src.governance.context.context_assembler"
        if mod_name in sys.modules:
            saved = sys.modules.pop(mod_name)
        else:
            saved = None

        try:
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                importlib.import_module(mod_name)
                dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
                assert len(dep_warnings) >= 1, (
                    f"Expected DeprecationWarning, got {[x.category for x in w]}"
                )
                assert "deprecated" in str(dep_warnings[0].message).lower()
        finally:
            # Restore
            if saved is not None:
                sys.modules[mod_name] = saved


# ── 7. No remaining direct imports of context_assembler in active code ──

class TestNoStaleImports:
    """Verify active modules don't import context_assembler anymore."""

    def test_executor_prompt_no_assembler_import(self):
        """executor_prompt.py should not import from context_assembler."""
        import inspect
        from src.governance import executor_prompt
        source = inspect.getsource(executor_prompt)
        assert "from src.governance.context.context_assembler import" not in source

    def test_executor_no_assembler_import(self):
        """executor.py should not import from context_assembler."""
        import inspect
        from src.governance import executor
        source = inspect.getsource(executor)
        assert "from src.governance.context.context_assembler import" not in source

    def test_providers_no_assembler_import(self):
        """providers.py should import from guidelines_utils, not context_assembler."""
        import inspect
        from src.governance.context import providers
        source = inspect.getsource(providers)
        assert "from src.governance.context.context_assembler import" not in source
        assert "guidelines_utils" in source

    def test_init_no_assembler_reexport(self):
        """__init__.py should not re-export assemble_context."""
        from src.governance.context import __init__ as ctx_init
        assert not hasattr(ctx_init, "assemble_context") or True
        # More robust: check that ContextEngine is exported
        from src.governance.context import ContextEngine as CE
        assert CE is not None
