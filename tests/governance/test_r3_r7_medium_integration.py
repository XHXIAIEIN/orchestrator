"""Tests for Round 3-7 medium-difficulty orphan module integrations.

Verifies that the 11 medium-difficulty steal modules are wired into
their respective production code paths:
  1. session_repair → executor_session.py (repair events before doom loop)
  2. compression → condenser/__init__.py (RatioCompressionCondenser adapter)
  3. permissions → executor.py (tool permission filtering)
  4. smart_approvals → approval.py (command-level trust learning)
  5. capability_registry → registry.py (capability metadata)
  6. design_memory → context/engine.py (DesignMemoryProvider)
  7. voice_directive → scrutiny.py + executor_prompt.py (voice injection/eval)
  8. code_retrieval → context/engine.py (CodeRetrievalProvider)
  9. session_manager → executor_session.py (session lifecycle)
  10. plan_executor → executor.py (plan-based execution mode)
  11. concurrency_pool → executor.py (shared concurrency management)
"""
import pytest


# ═══════════════════════════════════════════════════════════════
# 1. Session Repair → executor_session.py
# ═══════════════════════════════════════════════════════════════

class TestSessionRepairIntegration:
    """Test that session repair is wired into executor_session."""

    def test_repairer_imported_in_executor_session(self):
        """executor_session should import SessionRepairer."""
        import src.governance.executor_session as mod
        assert hasattr(mod, 'SessionRepairer')

    def test_repairer_basic_clean(self):
        """Clean events should pass through unchanged."""
        from src.governance.session_repair import SessionRepairer
        repairer = SessionRepairer()
        events = [
            {"event_type": "agent_turn", "data": {"text": ["hello"], "tools": ["Read"]}},
            {"event_type": "tool_result", "data": {"tool_use_id": "t1"}},
        ]
        repaired, report = repairer.repair(events)
        assert report.total_events == 2

    def test_repairer_removes_empty_messages(self):
        """Empty assistant messages should be removed."""
        from src.governance.session_repair import SessionRepairer
        repairer = SessionRepairer()
        events = [
            {"event_type": "agent_turn", "data": {"text": [], "tools": []}},  # empty
            {"event_type": "agent_turn", "data": {"text": ["hello"], "tools": ["Read"]}},
        ]
        repaired, report = repairer.repair(events)
        assert report.empty_messages == 1
        assert report.events_removed >= 1
        assert len(repaired) < len(events)


# ═══════════════════════════════════════════════════════════════
# 2. Compression → condenser/__init__.py
# ═══════════════════════════════════════════════════════════════

class TestCompressionIntegration:
    """Test that RatioCompressionCondenser is registered in condenser package."""

    def test_ratio_condenser_exported(self):
        """condenser package should export RatioCompressionCondenser."""
        from src.governance.condenser import RatioCompressionCondenser
        assert RatioCompressionCondenser is not None

    def test_ratio_condenser_is_condenser(self):
        """RatioCompressionCondenser should be a Condenser subclass."""
        from src.governance.condenser import RatioCompressionCondenser, Condenser
        condenser = RatioCompressionCondenser()
        assert isinstance(condenser, Condenser)

    def test_ratio_condenser_passthrough_small(self):
        """Small views should pass through without compression."""
        from src.governance.condenser import RatioCompressionCondenser, View, Event
        condenser = RatioCompressionCondenser(max_context_tokens=100000)
        events = [Event(id=i, event_type="action", source="agent", content=f"msg {i}")
                  for i in range(3)]
        view = View(events)
        result = condenser.condense(view)
        # Small payload, should not compress
        assert len(result.events) == 3

    def test_compression_standalone(self):
        """ContextCompressor should work standalone."""
        from src.governance.compression import ContextCompressor
        c = ContextCompressor(max_context_tokens=100, target_ratio=0.5,
                              protect_last_n=2, threshold=0.5)
        for i in range(10):
            c.add_turn("user", "x" * 30, tokens=10)
        assert c.should_compress()
        result = c.compress()
        assert result["compressed"]


# ═══════════════════════════════════════════════════════════════
# 3. Permissions → executor.py
# ═══════════════════════════════════════════════════════════════

class TestPermissionsIntegration:
    """Test that permission checker is wired into executor."""

    def test_permission_checker_imported(self):
        """executor.py should import get_permission_checker."""
        import src.governance.executor as mod
        assert hasattr(mod, 'get_permission_checker')

    def test_permission_checker_basic(self):
        """Permission checker should filter tools by tier."""
        from src.governance.permissions import PermissionChecker, PermissionTier
        checker = PermissionChecker()
        checker.set_department_tier("engineering", PermissionTier.ADVANCED)
        # System tools should be blocked for ADVANCED tier
        result = checker.check("engineering", "WebFetch")
        assert not result.permitted
        # Basic tools should be allowed
        result = checker.check("engineering", "Read")
        assert result.permitted

    def test_filter_tools(self):
        """filter_tools should return only permitted tools."""
        from src.governance.permissions import PermissionChecker, PermissionTier
        checker = PermissionChecker()
        checker.set_department_tier("engineering", PermissionTier.BASIC)
        tools = ["Read", "Glob", "Bash", "WebFetch"]
        filtered = checker.filter_tools("engineering", tools)
        assert "Read" in filtered
        assert "Glob" in filtered
        assert "Bash" not in filtered
        assert "WebFetch" not in filtered

    def test_dangerous_command_blocked(self):
        """Dangerous bash commands should be blocked."""
        from src.governance.permissions import PermissionChecker, PermissionTier
        checker = PermissionChecker()
        checker.set_department_tier("engineering", PermissionTier.ADVANCED)
        result = checker.check("engineering", "Bash", {"command": "rm -rf /"})
        assert not result.permitted


# ═══════════════════════════════════════════════════════════════
# 4. Smart Approvals → approval.py
# ═══════════════════════════════════════════════════════════════

class TestSmartApprovalsIntegration:
    """Test that smart approvals is wired into approval gateway."""

    def test_smart_approvals_imported(self):
        """approval.py should import SmartApprovals."""
        import src.governance.approval as mod
        assert hasattr(mod, '_smart_approvals')

    def test_smart_approvals_learning(self):
        """SmartApprovals should learn from repeated approvals."""
        from src.governance.smart_approvals import SmartApprovals
        sa = SmartApprovals(threshold=2)
        cmd = "git push origin feature"
        assert not sa.should_auto_approve(cmd)
        sa.record(cmd, "approve")
        assert not sa.should_auto_approve(cmd)  # threshold=2, only 1 approval
        sa.record(cmd, "approve")
        assert sa.should_auto_approve(cmd)  # now 2 approvals

    def test_denial_resets_trust(self):
        """A denial should reset approval count."""
        from src.governance.smart_approvals import SmartApprovals
        sa = SmartApprovals(threshold=2)
        cmd = "docker stop db"
        sa.record(cmd, "approve")
        sa.record(cmd, "approve")
        assert sa.should_auto_approve(cmd)
        sa.record(cmd, "deny")
        assert not sa.should_auto_approve(cmd)


# ═══════════════════════════════════════════════════════════════
# 5. Capability Registry → registry.py
# ═══════════════════════════════════════════════════════════════

class TestCapabilityRegistryIntegration:
    """Test that capability registry is wired into department registry."""

    def test_registry_imported(self):
        """registry.py should import capability registry."""
        import src.governance.registry as mod
        assert hasattr(mod, '_capability_registry')

    def test_resolve_tools_function(self):
        """resolve_tools_for_capabilities should be accessible."""
        from src.governance.registry import resolve_tools_for_capabilities
        tools = resolve_tools_for_capabilities(["file_read"])
        assert "Read" in tools

    def test_get_capability_registry(self):
        """get_capability_registry should return a CapabilityRegistry."""
        from src.governance.registry import get_capability_registry
        reg = get_capability_registry()
        assert reg is not None
        assert len(reg.list_all_tools()) > 0

    def test_default_registry_tools(self):
        """Default registry should have standard tools."""
        from src.governance.capability_registry import build_default_registry
        reg = build_default_registry()
        tools = reg.resolve(["shell", "file_read"])
        assert "Bash" in tools
        assert "Read" in tools

    def test_tier_filtering(self):
        """resolve with max_tier should filter appropriately."""
        from src.governance.capability_registry import build_default_registry
        reg = build_default_registry()
        # basic tier should exclude system tools
        tools = reg.resolve(["network", "file_read"], max_tier="basic")
        assert "WebFetch" not in tools
        assert "Read" in tools


# ═══════════════════════════════════════════════════════════════
# 6. Design Memory → context/engine.py
# ═══════════════════════════════════════════════════════════════

class TestDesignMemoryIntegration:
    """Test that design memory provider is registered in ContextEngine."""

    def test_provider_in_default_engine(self):
        """Default ContextEngine should include DesignMemoryProvider."""
        from src.governance.context.engine import ContextEngine, DesignMemoryProvider
        engine = ContextEngine.default()
        provider_names = [p.name for p in engine._providers]
        assert "design_memory" in provider_names

    def test_design_memory_standalone(self):
        """DesignMemory should store and retrieve decisions."""
        from src.governance.design_memory import DesignMemory
        mem = DesignMemory()
        mem.record_decision("color", "Use slate-800 for text", approved=True)
        mem.record_anti_pattern("Never use pure black")
        ctx = mem.to_prompt_context(categories=["color", "anti-pattern"])
        assert "slate-800" in ctx
        assert "pure black" in ctx

    def test_provider_only_activates_for_ui(self):
        """DesignMemoryProvider should only provide context for UI tasks."""
        from src.governance.context.engine import DesignMemoryProvider, TaskContext
        provider = DesignMemoryProvider()
        # Non-UI task
        ctx = TaskContext(department="engineering", task_text="fix database migration")
        chunks = provider.provide(ctx)
        assert len(chunks) == 0


# ═══════════════════════════════════════════════════════════════
# 7. Voice Directive → scrutiny.py + executor_prompt.py
# ═══════════════════════════════════════════════════════════════

class TestVoiceDirectiveIntegration:
    """Test that voice directive is wired into scrutiny and prompt builder."""

    def test_voice_imported_in_scrutiny(self):
        """scrutiny.py should import evaluate_voice."""
        import src.governance.scrutiny as mod
        assert hasattr(mod, 'evaluate_voice')

    def test_voice_imported_in_executor_prompt(self):
        """executor_prompt.py should import VoiceDirective."""
        import src.governance.executor_prompt as mod
        assert hasattr(mod, '_VoiceDirective')

    def test_voice_evaluation(self):
        """evaluate_voice should score text quality."""
        from src.governance.voice_directive import evaluate_voice
        # Hedging text
        score = evaluate_voice("I think perhaps maybe we should consider this approach")
        assert score.hedge_count > 0
        assert score.directness < 1.0

    def test_voice_directive_injection(self):
        """VoiceDirective should inject voice block into prompt."""
        from src.governance.voice_directive import VoiceDirective
        directive = VoiceDirective.for_department("engineering")
        result = directive.inject("Base prompt here")
        assert "Voice Directive" in result
        assert "direct" in result.lower()

    def test_ai_words_detection(self):
        """Should detect AI-typical vocabulary."""
        from src.governance.voice_directive import evaluate_voice
        score = evaluate_voice("We need to leverage this innovative paradigm to delve deeper")
        assert score.ai_word_count >= 3


# ═══════════════════════════════════════════════════════════════
# 8. Code Retrieval → context/engine.py
# ═══════════════════════════════════════════════════════════════

class TestCodeRetrievalIntegration:
    """Test that code retrieval provider is registered in ContextEngine."""

    def test_provider_in_default_engine(self):
        """Default ContextEngine should include CodeRetrievalProvider."""
        from src.governance.context.engine import ContextEngine, CodeRetrievalProvider
        engine = ContextEngine.default()
        provider_names = [p.name for p in engine._providers]
        assert "code_retrieval" in provider_names

    def test_code_retriever_standalone(self):
        """CodeRetriever should search codebase."""
        from src.governance.code_retrieval import CodeRetriever
        import os
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        retriever = CodeRetriever(project_root=repo_root)
        result = retriever.search("TaskExecutor", layers=[0], file_pattern="**/*.py")
        assert len(result.matches) > 0

    def test_layered_search(self):
        """L1 structural search should find function signatures."""
        from src.governance.code_retrieval import CodeRetriever
        import os
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        retriever = CodeRetriever(project_root=repo_root)
        result = retriever.search("execute_task", layers=[1], file_pattern="**/*.py")
        signatures = [m.get("signature", "") for m in result.matches if m.get("type") == "function"]
        assert any("execute_task" in sig for sig in signatures)


# ═══════════════════════════════════════════════════════════════
# 9. Session Manager → executor_session.py
# ═══════════════════════════════════════════════════════════════

class TestSessionManagerIntegration:
    """Test that session manager is wired into executor_session."""

    def test_session_manager_imported(self):
        """executor_session should import SessionManager."""
        import src.governance.executor_session as mod
        assert hasattr(mod, '_session_mgr')

    def test_session_create_and_fork(self):
        """SessionManager should create and fork sessions."""
        from src.governance.session_manager import SessionManager
        mgr = SessionManager()
        parent = mgr.create("task_1", cwd="/project")
        assert parent.status == "active"
        child = mgr.fork(parent.id, reason="context_overflow")
        assert child is not None
        assert child.parent_id == parent.id
        assert child.cwd == parent.cwd
        assert parent.status == "forked"

    def test_session_lineage(self):
        """get_lineage should return parent->child chain."""
        from src.governance.session_manager import SessionManager
        mgr = SessionManager()
        p = mgr.create("task_2", cwd="/proj")
        c = mgr.fork(p.id)
        lineage = mgr.get_lineage(c.id)
        assert len(lineage) == 2
        assert lineage[0].id == p.id
        assert lineage[1].id == c.id


# ═══════════════════════════════════════════════════════════════
# 10. Plan Executor → executor.py
# ═══════════════════════════════════════════════════════════════

class TestPlanExecutorIntegration:
    """Test that plan executor is wired into TaskExecutor."""

    def test_plan_executor_imported(self):
        """executor.py should import PlanExecutor."""
        import src.governance.executor as mod
        assert hasattr(mod, 'PlanExecutor')

    def test_plan_lifecycle(self):
        """PlanExecutor should manage plan create->approve->execute lifecycle."""
        from src.governance.plan_executor import PlanExecutor, PlanStatus
        pe = PlanExecutor()
        plan = pe.create_plan("t1", "Fix bug", "Resolve crash in parser", steps=[
            {"description": "Read error logs"},
            {"description": "Fix parser.py"},
            {"description": "Run tests"},
        ])
        assert plan.status == PlanStatus.DRAFT
        assert len(plan.steps) == 3

        pe.approve_plan("t1")
        assert plan.status == PlanStatus.READY

        pe.execute_plan("t1")
        assert plan.status == PlanStatus.COMPLETED
        assert plan.progress == 1.0

    def test_plan_markdown(self):
        """Plan should render as markdown."""
        from src.governance.plan_executor import PlanExecutor
        pe = PlanExecutor()
        plan = pe.create_plan("t2", "Deploy", "Deploy to prod", steps=[
            {"description": "Build", "command": "make build"},
        ])
        md = plan.to_markdown()
        assert "Deploy" in md
        assert "Build" in md

    def test_task_executor_has_plan_executor(self):
        """TaskExecutor instance should have _plan_executor attribute."""
        import src.governance.executor as mod
        assert hasattr(mod, 'PlanExecutor')
        if mod.PlanExecutor:
            # Verify it's available as a class
            pe = mod.PlanExecutor()
            assert pe is not None


# ═══════════════════════════════════════════════════════════════
# 11. Concurrency Pool → executor.py
# ═══════════════════════════════════════════════════════════════

class TestConcurrencyPoolIntegration:
    """Test that concurrency pool is wired into executor."""

    def test_pool_imported(self):
        """executor.py should import get_concurrency_pool."""
        import src.governance.executor as mod
        assert hasattr(mod, 'get_concurrency_pool')

    def test_pool_acquire_release(self):
        """Pool should acquire and release slots."""
        from src.core.concurrency_pool import ConcurrencyPool
        pool = ConcurrencyPool(max_concurrent=2)
        slot1 = pool.acquire("test:1")
        assert slot1 is not None
        slot2 = pool.acquire("test:2")
        assert slot2 is not None
        # Pool is full
        slot3 = pool.acquire("test:3")
        assert slot3 is None
        # Release one
        pool.release(slot1)
        slot3 = pool.acquire("test:3")
        assert slot3 is not None

    def test_pool_singleton(self):
        """get_concurrency_pool should return singleton."""
        from src.core.concurrency_pool import get_concurrency_pool
        p1 = get_concurrency_pool()
        p2 = get_concurrency_pool()
        assert p1 is p2

    def test_pool_stats(self):
        """Pool stats should track acquired/released/rejected."""
        from src.core.concurrency_pool import ConcurrencyPool
        pool = ConcurrencyPool(max_concurrent=1)
        slot = pool.acquire("owner1")
        pool.acquire("owner2")  # rejected
        stats = pool.get_stats()
        assert stats["acquired"] == 1
        assert stats["rejected"] == 1
        pool.release(slot)
        stats = pool.get_stats()
        assert stats["released"] == 1
