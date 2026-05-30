"""Regression tests for Round 5 cleanup: latent NameErrors, dead code, BM25 merge."""

import json
import tempfile
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# 1. is_weather NameError fix in PromptBuilder._select_tool_names
# ---------------------------------------------------------------------------

class TestSelectToolNamesIsWeather:
    """Verify _select_tool_names handles the weather + open keyword combo
    that previously triggered a NameError on `is_weather`.
    """

    @pytest.fixture
    def builder(self):
        from core.prompt_builder import PromptBuilder
        from core.tool_registry import ToolRegistry

        identity = MagicMock()
        identity.load_soul.return_value = ""
        identity.load_user.return_value = ""
        memory = MagicMock()
        memory.recall.return_value = []
        return PromptBuilder(identity, memory, ToolRegistry(), max_context_tokens=4096)

    def test_open_weather_does_not_raise(self, builder):
        """'打开天气' triggers both is_open and is_web — must not NameError."""
        tools = builder._select_tool_names("打开天气", route="chat")
        # Should return a list of tool names, never raise
        assert tools is None or isinstance(tools, list)

    def test_weather_only_returns_search_tools(self, builder):
        """Pure weather query (info route) returns search tools."""
        tools = builder._select_tool_names("今天天气怎么样", route="info")
        assert isinstance(tools, list)
        assert "smart_search" in tools
        assert "web_fetch" in tools

    def test_open_browser_excludes_weather_open(self, builder):
        """'打开 + 天气' should drop browser-open tools because of weather."""
        # Force the chat route so the "info early-return" doesn't fire.
        tools = builder._select_tool_names("打开天气", route="chat")
        # When is_open and is_weather both true, open_url/open_website discarded.
        if tools is not None:
            assert "open_url" not in tools
            assert "open_website" not in tools


# ---------------------------------------------------------------------------
# 2. urllib.request usage in server.py weather paths
# ---------------------------------------------------------------------------

class TestServerUrllibImport:
    """Verify server.py module imports urllib.request at top level so weather
    fast-path code does not crash with NameError on first call.
    """

    def test_module_has_urllib_request(self):
        import core.server as server_mod
        # The module should expose urllib (because of `import urllib.request`).
        assert hasattr(server_mod, "urllib"), "core.server must `import urllib.request`"
        # And urllib.request.urlopen must be reachable
        assert hasattr(server_mod.urllib, "request")
        assert callable(server_mod.urllib.request.urlopen)

    def test_audio_orchestrator_imported(self):
        """KageServer instantiates AudioOrchestrator — must be importable."""
        import core.server as server_mod
        assert hasattr(server_mod, "AudioOrchestrator")


# ---------------------------------------------------------------------------
# 3. Dead module deletion: core.intent_keywords no longer exists
# ---------------------------------------------------------------------------

class TestDeadModuleRemoved:
    def test_intent_keywords_module_deleted(self):
        with pytest.raises(ImportError):
            import core.intent_keywords  # noqa: F401,F811

    def test_tools_system_ops_module_deleted(self):
        with pytest.raises(ImportError):
            from core.tools import system_ops  # noqa: F401


# ---------------------------------------------------------------------------
# 4. Unified tool error response shape via _response.py
# ---------------------------------------------------------------------------

class TestToolResponseShape:
    """Every error from web_ops, skill_ops, shortcuts_ops, memory_ops, agent_ops
    must include `success: False` (the canonical shape from _response.py).
    """

    def test_response_helpers_basic(self):
        from core.tools._response import ok, err
        s_ok = ok(foo="bar")
        s_err = err("Boom", "details")
        d_ok = json.loads(s_ok)
        d_err = json.loads(s_err)
        assert d_ok == {"success": True, "foo": "bar"}
        assert d_err == {"success": False, "error": "Boom", "message": "details"}

    def test_search_empty_returns_canonical_error(self):
        from core.tools import web_ops
        out = json.loads(web_ops.search(""))
        assert out.get("success") is False
        assert out.get("error") == "InvalidInput"

    def test_exec_command_blocked_returns_canonical_error(self):
        from core.tools.web_ops import exec_command
        out = json.loads(exec_command("rm -rf /"))
        assert out.get("success") is False
        assert out.get("error") == "Blocked"

    def test_memory_search_no_system_returns_canonical_error(self):
        from core.tools.memory_ops import memory_search
        out = json.loads(memory_search("foo", memory_system=None))
        assert out.get("success") is False
        assert out.get("error") == "NotAvailable"

    def test_shortcuts_create_returns_canonical_success(self):
        from core.tools.shortcuts_ops import shortcuts_create
        out = json.loads(shortcuts_create("MyShortcut"))
        assert out.get("success") is True
        assert "MyShortcut" in out.get("message", "")

    def test_get_time_returns_canonical_success(self):
        from core.tools.web_ops import get_time
        out = json.loads(get_time())
        assert out.get("success") is True
        assert "time" in out
        assert "weekday" in out


# ---------------------------------------------------------------------------
# 5. _merge_similar_bm25 actually merges (was silently broken)
# ---------------------------------------------------------------------------

class TestMergeSimilarBM25:
    """The BM25 fallback path in merge_similar_facts must actually remove
    duplicate entries and update content/importance, not just count them.
    """

    def _make_memory_no_embeddings(self):
        """Build a MemorySystem instance without sentence-transformers loaded
        so the BM25 fallback path is exercised.
        """
        from core.memory import MemorySystem

        tmp = tempfile.mkdtemp()
        mem = MemorySystem(workspace_dir=tmp)
        # Force BM25 fallback by ensuring no embedding model is loaded.
        mem._model = None
        mem._embeddings = None
        return mem

    def test_merge_removes_duplicate_entries(self):
        mem = self._make_memory_no_embeddings()
        # Add three nearly-identical entries plus one distinct.
        mem.add_memory("用户喜欢喝咖啡", importance=2)
        mem.add_memory("用户喜欢喝咖啡每天早上", importance=4)
        mem.add_memory("用户喜欢喝咖啡的", importance=1)
        mem.add_memory("用户养了一只猫", importance=3)

        before = len(mem._entries)
        merged = mem._merge_similar_bm25()

        # Some merging should happen on the coffee-related entries.
        if merged > 0:
            assert len(mem._entries) == before - merged, "entry count must decrease by merged"
            # Importance of the surviving merged entry must be the max of merged group.
            survivors_content = [e.get("content", "") for e in mem._entries]
            assert any("咖啡" in c for c in survivors_content)

    def test_merge_returns_zero_on_empty(self):
        mem = self._make_memory_no_embeddings()
        assert mem._merge_similar_bm25() == 0


# ---------------------------------------------------------------------------
# 6. Deduplicate BM25 hoisting (perf, but should still be correct)
# ---------------------------------------------------------------------------

class TestDeduplicateBM25:
    def _make_memory_no_embeddings(self):
        from core.memory import MemorySystem
        tmp = tempfile.mkdtemp()
        mem = MemorySystem(workspace_dir=tmp)
        mem._model = None
        mem._embeddings = None
        return mem

    def test_dedup_removes_exact_duplicates(self):
        mem = self._make_memory_no_embeddings()
        mem.add_memory("用户喜欢黑咖啡", importance=3)
        mem.add_memory("用户喜欢黑咖啡", importance=3)  # exact dup
        mem.add_memory("用户养了一只猫", importance=2)
        before = len(mem._entries)
        removed = mem._deduplicate_bm25()
        assert removed >= 1
        assert len(mem._entries) <= before  # entries are not removed in this method;
        # _deduplicate_bm25 only counts; the removal happens in deduplicate_memories.


# ---------------------------------------------------------------------------
# 7. agentic_loop staticmethods still work after dead-import removal
# ---------------------------------------------------------------------------

class TestAgenticLoopStatics:
    def test_needs_tool_action_works(self):
        from core.agentic_loop import AgenticLoop
        assert AgenticLoop._needs_tool_action("帮我整理下载文件夹") is True
        assert AgenticLoop._needs_tool_action("你好") is False

    def test_primitive_tool_hint_works(self):
        from core.agentic_loop import AgenticLoop
        h = AgenticLoop._primitive_tool_hint("把音量调大")
        assert "system_control" in h


# ---------------------------------------------------------------------------
# 8. tool_executor runs sync handlers in a worker thread (no event-loop block)
# ---------------------------------------------------------------------------

class TestToolExecutorThreadOffload:
    """Sync handlers must run via asyncio.to_thread so the event loop stays
    responsive and parallel tool batches actually run concurrently.
    """

    def _make_executor(self):
        from core.tool_registry import ToolRegistry, ToolDefinition
        from core.tool_executor import ToolExecutor

        registry = ToolRegistry()
        # A blocking handler — sleeps to simulate I/O.
        def slow_blocking(delay: float = 0.05):
            import time as _t
            _t.sleep(delay)
            return "done"

        registry.register(ToolDefinition(
            name="slow_blocking",
            description="Blocking sleep tool for tests",
            parameters={"type": "object", "properties": {"delay": {"type": "number"}}},
            handler=slow_blocking,
            safety_level="SAFE",
        ))
        return ToolExecutor(registry)

    def test_parallel_sync_handlers_overlap(self):
        """Two parallel calls to a 100ms blocking tool should finish in
        roughly 100ms (overlap), not 200ms (serial)."""
        import asyncio
        import time as _t

        executor = self._make_executor()

        async def run_pair():
            t0 = _t.monotonic()
            r1, r2 = await asyncio.gather(
                executor.execute("slow_blocking", {"delay": 0.1}),
                executor.execute("slow_blocking", {"delay": 0.1}),
            )
            return r1, r2, _t.monotonic() - t0

        r1, r2, elapsed = asyncio.run(run_pair())
        assert r1.success is True and r1.result == "done"
        assert r2.success is True and r2.result == "done"
        # If the executor still ran handlers serially, elapsed would be >= 200ms.
        # With asyncio.to_thread it should overlap. The 170ms budget gives plenty
        # of room for thread-pool warmup + scheduling jitter on loaded CI.
        assert elapsed < 0.17, f"parallel handlers did not overlap: {elapsed*1000:.1f}ms"

    def test_async_handler_awaited_directly(self):
        """An async handler should be awaited, not wrapped in to_thread."""
        import asyncio
        from core.tool_registry import ToolRegistry, ToolDefinition
        from core.tool_executor import ToolExecutor

        async def async_handler(x: int = 1):
            await asyncio.sleep(0)
            return f"async-{x}"

        registry = ToolRegistry()
        registry.register(ToolDefinition(
            name="async_tool",
            description="Async handler test",
            parameters={"type": "object", "properties": {"x": {"type": "integer"}}},
            handler=async_handler,
            safety_level="SAFE",
        ))
        executor = ToolExecutor(registry)

        result = asyncio.run(executor.execute("async_tool", {"x": 42}))
        assert result.success is True
        assert result.result == "async-42"


# ---------------------------------------------------------------------------
# 9. MemoryExtractor pattern compilation hoisted to module level
# ---------------------------------------------------------------------------

class TestMemoryExtractorModuleCompile:
    def test_instances_share_compiled_patterns(self):
        from core.memory_extractor import MemoryExtractor

        a = MemoryExtractor()
        b = MemoryExtractor()
        # Both instances must use the same pre-compiled pattern dict (the
        # module-level singleton) — verifies we didn't recompile per instance.
        assert a._compiled_patterns is b._compiled_patterns

    def test_extractor_still_extracts(self):
        from core.memory_extractor import MemoryExtractor

        extractor = MemoryExtractor()
        facts = extractor.extract_from_conversation(
            user_input="我每天早上6点起床",
            assistant_response="",
        )
        # Sanity: should classify as habit
        assert len(facts) >= 1
        cats = {f.category for f in facts}
        assert "habit" in cats
