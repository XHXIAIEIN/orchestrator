# tests/governance/test_condenser_integration.py
"""Tests for condenser context compression integration.

Covers:
- condense_context() passthrough when under threshold
- condense_context() compression when over threshold
- Pipeline chaining (AmortizedForgetting → LLMSummarizing)
- Configuration via dict (manifest.yaml proxy)
- Disabled condenser
- Error resilience (bad config, exceptions)
- Prompt section splitting and reassembly
"""
import pytest

from src.governance.condenser.context_condenser import (
    condense_context,
    _prompt_to_view,
    _view_to_prompt,
    _build_pipeline,
    DEFAULT_MAX_TOKENS,
    DEFAULT_HIGH_WATER,
)
from src.governance.condenser.base import Event, View
from src.governance.condenser.water_level import WaterLevelCondenser
from src.governance.condenser.amortized_forgetting import AmortizedForgettingCondenser
from src.governance.condenser.llm_summarizing import (
    LLMSummarizingCondenser,
    SUMMARY_PREFIX,
    ITERATIVE_UPDATE_PROMPT,
    _compute_summary_budget,
)
from src.governance.condenser.tool_output_pruner import (
    ToolOutputPruner,
    PruneConfig,
    _detect_tool_type,
    _collapse_search,
    _collapse_command,
)
from src.governance.condenser.upload_stripper import UploadStripper
from src.governance.condenser.pipeline import CondenserPipeline


# ── Helpers ──

def _make_long_prompt(num_sections: int = 200, chars_per_section: int = 2000) -> str:
    """Generate a prompt with many H2 sections to exceed water level."""
    sections = []
    for i in range(num_sections):
        sections.append(f"## Section {i}\n{'x' * chars_per_section}")
    return "\n\n".join(sections)


def _make_short_prompt() -> str:
    """A prompt well under the default water level."""
    return "## Task\nDo something simple.\n\n## Context\nSome context here."


# ── Tests: prompt <-> view conversion ──

class TestPromptViewConversion:
    def test_split_by_h2_headers(self):
        prompt = "## First\nContent 1\n\n## Second\nContent 2\n\n## Third\nContent 3"
        view = _prompt_to_view(prompt)
        assert len(view) == 3
        assert "First" in view.events[0].content
        assert "Second" in view.events[1].content
        assert "Third" in view.events[2].content

    def test_no_headers_single_event(self):
        prompt = "Just a plain text prompt with no headers."
        view = _prompt_to_view(prompt)
        assert len(view) == 1
        assert view.events[0].content == prompt

    def test_empty_prompt(self):
        view = _prompt_to_view("")
        assert len(view) == 0

    def test_roundtrip_preserves_content(self):
        prompt = "## A\nStuff\n\n## B\nMore stuff"
        view = _prompt_to_view(prompt)
        result = _view_to_prompt(view)
        # Content should be preserved (whitespace may differ slightly)
        assert "Stuff" in result
        assert "More stuff" in result

    def test_view_to_prompt_joins_with_double_newline(self):
        events = [
            Event(id=0, event_type="context", source="test", content="Part A"),
            Event(id=1, event_type="context", source="test", content="Part B"),
        ]
        view = View(events)
        result = _view_to_prompt(view)
        assert result == "Part A\n\nPart B"


# ── Tests: condense_context() passthrough ──

class TestCondenserPassthrough:
    def test_short_prompt_unchanged(self):
        prompt = _make_short_prompt()
        result = condense_context(prompt, dept_key="engineering")
        assert result == prompt

    def test_disabled_returns_original(self):
        prompt = _make_long_prompt()
        result = condense_context(prompt, config={"enabled": False})
        assert result == prompt

    def test_empty_prompt_returns_empty(self):
        result = condense_context("", dept_key="test")
        # Empty view → empty result, should not crash
        assert result == ""

    def test_default_config_is_enabled(self):
        """With no config, condenser is enabled but won't compress short prompts."""
        prompt = _make_short_prompt()
        result = condense_context(prompt)
        assert result == prompt


# ── Tests: condense_context() compression ──

class TestCondenserCompression:
    def test_long_prompt_gets_compressed(self):
        """A prompt exceeding default water level should be compressed."""
        # 200 sections × 2000 chars each = ~400K chars = ~114K tokens
        # Default threshold = 128K × 0.85 = ~108K tokens → triggers
        prompt = _make_long_prompt(num_sections=200, chars_per_section=2000)
        result = condense_context(prompt)
        # Result should be shorter (fewer sections or smaller)
        assert len(result) < len(prompt)

    def test_custom_low_threshold_triggers(self):
        """A lower water threshold should trigger on smaller prompts."""
        prompt = _make_long_prompt(num_sections=50, chars_per_section=500)
        config = {
            "max_tokens": 1000,  # Very low ceiling
            "high_water": 0.5,
            "amortized_max_events": 10,
            "amortized_keep_head": 2,
            "amortized_keep_tail": 3,
        }
        result = condense_context(prompt, config=config)
        assert len(result) < len(prompt)

    def test_compression_preserves_head_and_tail(self):
        """AmortizedForgetting should keep first and last sections."""
        sections = [f"## Section {i}\nContent for section {i}" for i in range(30)]
        prompt = "\n\n".join(sections)
        config = {
            "max_tokens": 100,  # Force trigger
            "high_water": 0.1,
            "amortized_max_events": 10,
            "amortized_keep_head": 3,
            "amortized_keep_tail": 3,
        }
        result = condense_context(prompt, config=config)
        # First and last sections should survive
        assert "Section 0" in result
        assert "Section 1" in result
        assert "Section 29" in result


# ── Tests: pipeline building ──

class TestBuildPipeline:
    def test_default_config_builds_pipeline(self):
        pipeline = _build_pipeline({})
        assert isinstance(pipeline, WaterLevelCondenser)
        assert isinstance(pipeline.inner, CondenserPipeline)
        assert len(pipeline.inner.condensers) == 4
        assert isinstance(pipeline.inner.condensers[0], UploadStripper)
        assert isinstance(pipeline.inner.condensers[1], ToolOutputPruner)
        assert isinstance(pipeline.inner.condensers[2], AmortizedForgettingCondenser)
        assert isinstance(pipeline.inner.condensers[3], LLMSummarizingCondenser)

    def test_custom_config_propagates(self):
        config = {
            "max_tokens": 64_000,
            "high_water": 0.7,
            "amortized_max_events": 50,
            "amortized_keep_head": 5,
            "amortized_keep_tail": 15,
            "llm_threshold": 30,
        }
        pipeline = _build_pipeline(config)
        assert pipeline.max_tokens == 64_000
        assert pipeline.high_water == 0.7
        inner_condensers = pipeline.inner.condensers
        # [0]=UploadStripper, [1]=ToolOutputPruner, [2]=AmortizedForgetting, [3]=LLMSummarizing
        assert inner_condensers[2].max_events == 50
        assert inner_condensers[2].keep_head == 5
        assert inner_condensers[3].threshold == 30

    def test_llm_fn_passed_through(self):
        mock_fn = lambda prompt: "summary"
        pipeline = _build_pipeline({"llm_fn": mock_fn})
        # [0]=UploadStripper, [1]=ToolOutputPruner, [2]=AmortizedForgetting, [3]=LLMSummarizing
        llm_condenser = pipeline.inner.condensers[3]
        assert llm_condenser.llm_fn is mock_fn


# ── Tests: error resilience ──

class TestCondenserResilience:
    def test_exception_in_pipeline_returns_original(self):
        """If condenser crashes, original prompt is returned unchanged."""
        prompt = _make_short_prompt()
        # Pass a config that would cause issues in the pipeline
        # but condense_context should catch and return original
        config = {
            "max_tokens": "not_a_number",  # Will cause TypeError
            "high_water": 0.01,  # Force trigger so we reach the bad max_tokens
        }
        result = condense_context(prompt, config=config)
        # Should return original on error
        assert result == prompt

    def test_none_config_uses_defaults(self):
        prompt = _make_short_prompt()
        result = condense_context(prompt, config=None)
        assert result == prompt


# ── Tests: manifest config extraction ──

class TestManifestConfig:
    def test_get_condenser_config_from_dept(self):
        """Verify _get_condenser_config extracts from dept dict."""
        from src.governance.executor_prompt import _get_condenser_config
        dept = {
            "prompt_prefix": "test",
            "condenser": {
                "enabled": True,
                "max_tokens": 64000,
                "high_water": 0.7,
            },
        }
        config = _get_condenser_config(dept, blueprint=None)
        assert config["max_tokens"] == 64000
        assert config["high_water"] == 0.7

    def test_get_condenser_config_empty_dept(self):
        from src.governance.executor_prompt import _get_condenser_config
        config = _get_condenser_config({}, blueprint=None)
        assert config == {}

    def test_get_condenser_config_non_dict_condenser(self):
        from src.governance.executor_prompt import _get_condenser_config
        dept = {"condenser": "invalid"}
        config = _get_condenser_config(dept, blueprint=None)
        assert config == {}


# ── Tests: WaterLevel gate behavior ──

class TestWaterLevelGate:
    def test_under_threshold_no_compression(self):
        """WaterLevel should pass through when tokens are under threshold."""
        events = [Event(id=i, event_type="ctx", source="t", content=f"Short {i}") for i in range(5)]
        view = View(events)

        inner = CondenserPipeline([AmortizedForgettingCondenser(max_events=3)])
        gate = WaterLevelCondenser(inner=inner, max_tokens=100000, high_water=0.85)

        result = gate.condense(view)
        # Under threshold → inner pipeline NOT called → same number of events
        assert len(result) == len(view)
        assert gate.compress_count == 0

    def test_over_threshold_triggers_inner(self):
        """WaterLevel should trigger inner pipeline when over threshold."""
        # Create enough content to exceed a low threshold
        events = [
            Event(id=i, event_type="ctx", source="t", content="x" * 500)
            for i in range(20)
        ]
        view = View(events)

        inner = AmortizedForgettingCondenser(max_events=10, keep_head=2, keep_tail=3)
        gate = WaterLevelCondenser(inner=inner, max_tokens=500, high_water=0.1)

        result = gate.condense(view)
        assert len(result) < len(view)
        assert gate.compress_count == 1


# ── Tests: R77 State Serialization (LLMSummarizingCondenser) ──

class TestStateSerialization:
    """Tests for R77 structured state serialization features."""

    def _make_condenser(self, llm_fn=None, threshold=60, keep_head=5, keep_tail=5):
        return LLMSummarizingCondenser(
            llm_fn=llm_fn, threshold=threshold,
            keep_head=keep_head, keep_tail=keep_tail,
        )

    def _make_events(self, n=70):
        return [Event(id=i, event_type="ctx", source="t", content=f"event {i} " + "x" * 80) for i in range(n)]

    def test_summary_has_prefix(self):
        """Summary event content starts with SUMMARY_PREFIX."""
        c = self._make_condenser()
        result = c.condense(View(self._make_events()))
        summary = [e for e in result.events if e.source == "condenser:llm"]
        assert len(summary) == 1
        assert "REFERENCE ONLY" in summary[0].content

    def test_summary_strategy_metadata(self):
        """Summary metadata has strategy='llm_state_serialization'."""
        c = self._make_condenser()
        result = c.condense(View(self._make_events()))
        summary = [e for e in result.events if e.source == "condenser:llm"][0]
        assert summary.metadata["strategy"] == "llm_state_serialization"

    def test_dynamic_budget_floor(self):
        """_compute_summary_budget(100) == 2000 (floor)."""
        assert _compute_summary_budget(100) == 2000

    def test_dynamic_budget_ceiling(self):
        """_compute_summary_budget(100000) == 12000 (ceiling)."""
        assert _compute_summary_budget(100000) == 12000

    def test_dynamic_budget_scaled(self):
        """_compute_summary_budget(30000) == 6000 (20%)."""
        assert _compute_summary_budget(30000) == 6000

    def test_iterative_detects_previous_summary(self):
        """When head contains a condenser:llm event, iterative=True in metadata."""
        # Create events with an old summary in head position
        old_summary = Event(
            id=-1, event_type="system", source="condenser:llm",
            content=f"{SUMMARY_PREFIX}\n## Goal\nDo stuff\n## Remaining Work\nMore stuff",
            metadata={"strategy": "llm_state_serialization", "condensed_count": 10},
            condensed=True,
        )
        events = [old_summary] + [
            Event(id=i, event_type="ctx", source="t", content=f"new event {i} " + "y" * 80)
            for i in range(1, 80)
        ]
        c = self._make_condenser(threshold=60, keep_head=5, keep_tail=5)
        result = c.condense(View(events))
        summary = [e for e in result.events if e.source == "condenser:llm"]
        assert len(summary) == 1
        assert summary[0].metadata["iterative"] is True

    def test_iterative_removes_old_summary(self):
        """Iterative update removes old summary event from head (no stacking)."""
        old_summary = Event(
            id=-1, event_type="system", source="condenser:llm",
            content=f"{SUMMARY_PREFIX}\n## Goal\nOld goal",
            metadata={"strategy": "llm_state_serialization", "condensed_count": 5},
            condensed=True,
        )
        events = [old_summary] + [
            Event(id=i, event_type="ctx", source="t", content=f"event {i} " + "z" * 80)
            for i in range(1, 80)
        ]
        c = self._make_condenser(threshold=60, keep_head=5, keep_tail=5)
        result = c.condense(View(events))
        # Should have exactly 1 summary event (the new one), not 2
        summaries = [e for e in result.events if e.source == "condenser:llm"]
        assert len(summaries) == 1
        # Old summary should not be in the result
        assert "Old goal" not in summaries[0].content or "机械压缩" in summaries[0].content

    def test_is_llm_summary_backward_compat(self):
        """_is_llm_summary matches both old and new strategy names."""
        old = Event(id=0, event_type="system", source="condenser:llm",
                    content="old", metadata={"strategy": "llm_summarizing"}, condensed=True)
        new = Event(id=1, event_type="system", source="condenser:llm",
                    content="new", metadata={"strategy": "llm_state_serialization"}, condensed=True)
        not_summary = Event(id=2, event_type="ctx", source="t",
                           content="x", metadata={}, condensed=False)
        assert LLMSummarizingCondenser._is_llm_summary(old) is True
        assert LLMSummarizingCondenser._is_llm_summary(new) is True
        assert LLMSummarizingCondenser._is_llm_summary(not_summary) is False

    def test_mechanical_fallback_unchanged(self):
        """Mechanical fallback format unchanged when LLM unavailable."""
        c = self._make_condenser(llm_fn=None)
        result = c.condense(View(self._make_events()))
        summary = [e for e in result.events if e.source == "condenser:llm"][0]
        assert "机械压缩" in summary.content


# ── Tests: R77 Semantic Collapse (ToolOutputPruner) ──

class TestSemanticCollapse:
    """Tests for R77 tool-type-aware semantic collapse + hash dedup."""

    def test_detect_tool_type_search(self):
        assert _detect_tool_type("grep -r pattern .") == "search"
        assert _detect_tool_type("50 matches found") == "search"

    def test_detect_tool_type_command(self):
        assert _detect_tool_type("$ ls -la") == "command"
        assert _detect_tool_type("exit code 1") == "command"

    def test_detect_tool_type_git(self):
        assert _detect_tool_type("diff --git a/foo b/foo") == "git"
        assert _detect_tool_type("On branch main") == "git"

    def test_detect_tool_type_read(self):
        assert _detect_tool_type("Read file: test.py") == "read"
        assert _detect_tool_type("Content of /etc/hosts") == "read"

    def test_detect_tool_type_unknown(self):
        assert _detect_tool_type("hello world nothing special") == "unknown"

    def test_semantic_collapse_search_preserves_count(self):
        """Search collapse keeps match count and first/last matches."""
        search_output = "grep -r foo .\n50 matches found\n" + "\n".join(
            f"file{i}.py:10: match line {i}" for i in range(50)
        )
        collapsed = _collapse_search(search_output, 2000)
        assert len(collapsed) < len(search_output)
        # Should have first matches and "more matches omitted"
        assert "file0.py" in collapsed
        assert "omitted" in collapsed or "file49.py" in collapsed

    def test_semantic_collapse_command_preserves_errors(self):
        """Command collapse keeps error lines and exit code."""
        cmd_output = "$ python test.py\n" + "\n".join(
            f"output line {i}" for i in range(50)
        ) + "\nError: something broke\nTraceback: line 42\nexit code 1"
        collapsed = _collapse_command(cmd_output, 2000)
        assert "Error: something broke" in collapsed
        assert "exit code 1" in collapsed

    def test_hash_dedup_removes_earlier_duplicates(self):
        """Identical tool outputs: only latest kept."""
        dup = "x" * 500
        events = [
            Event(id=0, event_type="obs", source="tool", content=dup),
            Event(id=1, event_type="obs", source="tool", content="unique " * 50),
            Event(id=2, event_type="obs", source="tool", content=dup),
        ]
        p = ToolOutputPruner()
        result = p._dedup_by_hash(events)
        # id=0 removed (dup, not last), id=1 kept (unique), id=2 kept (last dup)
        assert len(result) == 2
        assert result[0].id == 1
        assert result[1].id == 2

    def test_hash_dedup_skips_short_content(self):
        """Content < 200 chars not deduped."""
        short = "x" * 100
        events = [
            Event(id=0, event_type="obs", source="tool", content=short),
            Event(id=1, event_type="obs", source="tool", content=short),
        ]
        p = ToolOutputPruner()
        result = p._dedup_by_hash(events)
        assert len(result) == 2  # Both kept (too short for dedup)

    def test_hash_dedup_skips_non_tool_sources(self):
        """User/system events not deduped even if identical."""
        dup = "x" * 500
        events = [
            Event(id=0, event_type="msg", source="user", content=dup),
            Event(id=1, event_type="msg", source="user", content=dup),
        ]
        p = ToolOutputPruner()
        result = p._dedup_by_hash(events)
        assert len(result) == 2  # Both kept (non-tool source)

    def test_positional_fallback_for_unknown_type(self):
        """Unknown tool type uses R39 head+tail positional prune."""
        p = ToolOutputPruner()
        long_text = "x" * 2000
        result = p.prune_text(long_text, tool_type="unknown")
        assert "pruned by ToolOutputPruner" in result
        assert len(result) < len(long_text)

    def test_semantic_collapse_disabled_config(self):
        """PruneConfig(semantic_collapse=False) forces positional for all types."""
        p = ToolOutputPruner(PruneConfig(semantic_collapse=False))
        search_text = "grep result\n" + "file.py:1: match\n" * 200
        result = p.prune_text(search_text, tool_type="search")
        assert "pruned by ToolOutputPruner" in result
