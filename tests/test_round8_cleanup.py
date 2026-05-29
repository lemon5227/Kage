"""Round 8 regression tests: dead code, portability fix, _exec_one extraction."""

import asyncio
import os

import pytest


# ---------------------------------------------------------------------------
# tool_registry.get_tool_descriptions removed (no callers, dead since round 4)
# ---------------------------------------------------------------------------

class TestDeadToolRegistryMethod:
    def test_get_tool_descriptions_removed(self):
        from core.tool_registry import ToolRegistry
        registry = ToolRegistry()
        assert not hasattr(registry, "get_tool_descriptions")

    def test_descriptions_cache_field_removed(self):
        from core.tool_registry import ToolRegistry
        registry = ToolRegistry()
        assert not hasattr(registry, "_descriptions_cache")

    def test_get_all_schemas_still_cached(self):
        """Removing _descriptions_cache must not break the schemas cache."""
        from core.tool_registry import ToolRegistry, ToolDefinition
        registry = ToolRegistry()
        registry.register(ToolDefinition(
            name="t1", description="d", parameters={"type": "object", "properties": {}},
            handler=lambda: "x", safety_level="SAFE",
        ))
        s1 = registry.get_all_schemas()
        s2 = registry.get_all_schemas()
        assert s1 is s2  # same cached list object


# ---------------------------------------------------------------------------
# Portability: MCP default config path is module-relative, not user-pinned.
# ---------------------------------------------------------------------------

class TestMcpConfigPathPortability:
    def test_default_path_is_module_relative(self, monkeypatch):
        """Without env var or explicit arg, the default path should resolve
        relative to the repo (config/mcp.json next to core/), not be a
        string literal embedding a developer's home directory.
        """
        from core.tool_registry import _register_mcp_dynamic_aliases, ToolRegistry
        import core.tool_registry as tr_mod
        from io import StringIO

        captured_paths: list[str] = []

        def _spy_open(path, *args, **kwargs):
            captured_paths.append(str(path))
            return StringIO("{}")

        monkeypatch.setattr("builtins.open", _spy_open)
        monkeypatch.delenv("KAGE_MCP_CFG", raising=False)

        registry = ToolRegistry()
        _register_mcp_dynamic_aliases(registry, mcp_cfg_path=None)

        assert captured_paths, "_register_mcp_dynamic_aliases should attempt to open the config"
        path = captured_paths[0]
        # Path should end in config/mcp.json and live next to the tool_registry module
        assert path.endswith(os.path.join("config", "mcp.json"))
        # It must be derived from the module file (so siblings of core/ contain config/)
        module_dir = os.path.dirname(os.path.abspath(tr_mod.__file__))
        repo_root = os.path.dirname(module_dir)
        expected = os.path.join(repo_root, "config", "mcp.json")
        assert path == expected, f"expected module-relative {expected}, got {path}"

    def test_no_hardcoded_user_path_in_source(self):
        """Static check: source must not contain a literal '/Users/<name>/...'
        path used as a default. This prevents a regression where someone
        re-introduces a hardcoded path."""
        import core.tool_registry as tr_mod
        with open(tr_mod.__file__) as f:
            src = f.read()
        # No string literal starting with /Users/<word>/Kage in source
        # (path strings only — comments are allowed to mention them)
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert '"/Users/' not in stripped, \
                f"hardcoded user path found in tool_registry: {line!r}"


# ---------------------------------------------------------------------------
# AgenticLoop._exec_one — extracted from a closure inside run()
# ---------------------------------------------------------------------------

class _StubExec:
    """Mimics ToolExecutor.execute() returning a result-with-attrs object."""

    def __init__(self):
        self.calls: list[tuple] = []

    async def execute(self, name, args):
        self.calls.append((name, args))

        class R:
            success = True
            result = f"ok:{name}"
            error_type = None
            error_message = None
            elapsed_ms = 1.5
        return R()


class _ExplodingExec:
    async def execute(self, name, args):
        raise RuntimeError("boom")


class TestExecOneExtracted:
    """The async _exec_one helper is now a method on AgenticLoop, not a
    closure in `run()`. Tests verify its contract independently."""

    def _make_loop(self, executor):
        from core.agentic_loop import AgenticLoop
        loop = object.__new__(AgenticLoop)
        loop.tools = executor
        return loop

    def test_exec_one_is_method_on_class(self):
        from core.agentic_loop import AgenticLoop
        assert hasattr(AgenticLoop, "_exec_one")
        assert asyncio.iscoroutinefunction(AgenticLoop._exec_one)

    def test_exec_one_success_shape(self):
        loop = self._make_loop(_StubExec())
        out = asyncio.run(loop._exec_one({"name": "smart_search", "arguments": {"query": "kage"}}))
        assert out["name"] == "smart_search"
        assert out["arguments"] == {"query": "kage"}
        assert out["success"] is True
        assert out["result"] == "ok:smart_search"
        assert out["error_type"] is None
        assert out["elapsed_ms"] == pytest.approx(1.5)

    def test_exec_one_handles_executor_exception(self):
        loop = self._make_loop(_ExplodingExec())
        out = asyncio.run(loop._exec_one({"name": "x", "arguments": {}}))
        assert out["success"] is False
        assert out["error_type"] == "RuntimeError"
        assert out["error_message"] == "boom"
        assert out["elapsed_ms"] == 0.0

    def test_exec_one_normalizes_missing_arguments(self):
        loop = self._make_loop(_StubExec())
        out = asyncio.run(loop._exec_one({"name": "t"}))  # no arguments
        assert out["arguments"] == {}

    def test_exec_one_works_in_gather(self):
        """Sanity: multiple _exec_one calls overlap via asyncio.gather."""
        loop = self._make_loop(_StubExec())
        async def _drive():
            return await asyncio.gather(
                loop._exec_one({"name": "a", "arguments": {}}),
                loop._exec_one({"name": "b", "arguments": {}}),
            )
        rows = asyncio.run(_drive())
        names = sorted(r["name"] for r in rows)
        assert names == ["a", "b"]


# ---------------------------------------------------------------------------
# _SKILL_LIFECYCLE_TOOLS hoisted to module level
# ---------------------------------------------------------------------------

class TestSkillLifecycleToolsHoisted:
    def test_hoisted_frozenset_exists(self):
        from core.agentic_loop import _SKILL_LIFECYCLE_TOOLS
        assert isinstance(_SKILL_LIFECYCLE_TOOLS, frozenset)

    def test_contains_expected_skill_tools(self):
        from core.agentic_loop import _SKILL_LIFECYCLE_TOOLS
        assert _SKILL_LIFECYCLE_TOOLS == frozenset({
            "skills_find_remote", "web_fetch", "skills_install", "skills_read"
        })
