"""Round 7 regression tests: dead-function removal + hot-path constant hoisting."""


# ---------------------------------------------------------------------------
# Dead functions removed from route_classifier and chat_polisher
# ---------------------------------------------------------------------------

class TestDeadFunctionsRemoved:
    def test_extract_location_from_text_removed(self):
        from core import route_classifier
        assert not hasattr(route_classifier, "extract_location_from_text")

    def test_location_filler_constant_removed(self):
        from core import route_classifier
        assert not hasattr(route_classifier, "_LOCATION_FILLER")

    def test_is_bad_chat_response_removed(self):
        from core import chat_polisher
        assert not hasattr(chat_polisher, "is_bad_chat_response")

    def test_fallback_chat_response_removed(self):
        from core import chat_polisher
        assert not hasattr(chat_polisher, "fallback_chat_response")

    def test_short_care_phrase_removed(self):
        from core import chat_polisher
        assert not hasattr(chat_polisher, "short_care_phrase")

    def test_chat_polisher_random_import_removed(self):
        """random was only used by short_care_phrase; should be gone now."""
        from core import chat_polisher
        # We can check the module's source does not reference random
        src = open(chat_polisher.__file__).read()
        # Allow only as part of an unrelated word, but module should not import random
        for line in src.splitlines():
            stripped = line.strip()
            assert not stripped.startswith("import random"), \
                "random should no longer be imported in chat_polisher"

    def test_dead_constants_removed_from_chat_polisher(self):
        from core import chat_polisher
        for c in ("_BAD_RESPONSE_PHRASES", "_GENERIC_ACKNOWLEDGEMENTS",
                  "_SHORT_OK_RESPONSES", "_RE_HAS_LATIN", "_CARE_PHRASES"):
            assert not hasattr(chat_polisher, c), f"{c} should have been removed"


# ---------------------------------------------------------------------------
# Hot-path constant hoisting (perf)
# ---------------------------------------------------------------------------

class TestModuleLevelConstants:
    def test_read_only_tools_hoisted(self):
        from core.agentic_loop import _READ_ONLY_TOOLS
        assert isinstance(_READ_ONLY_TOOLS, frozenset)
        # Sanity: contains the read-only set previously built per call
        assert "smart_search" in _READ_ONLY_TOOLS
        assert "web_fetch" in _READ_ONLY_TOOLS
        assert "fs_search" in _READ_ONLY_TOOLS
        # And NOT a writing tool
        assert "fs_apply" not in _READ_ONLY_TOOLS

    def test_can_parallelize_uses_hoisted_set(self):
        from core.agentic_loop import AgenticLoop
        # Two read-only tools — parallelizable
        assert AgenticLoop._can_parallelize_tool_calls([
            {"name": "smart_search"},
            {"name": "web_fetch"},
        ]) is True
        # One writing tool — not parallelizable
        assert AgenticLoop._can_parallelize_tool_calls([
            {"name": "smart_search"},
            {"name": "fs_apply"},
        ]) is False

    def test_prompt_builder_tool_subsets_hoisted(self):
        from core.prompt_builder import (
            _TOOLS_INFO_DEFAULT, _TOOLS_INFO_WEATHER,
            _TOOLS_WEB, _TOOLS_OPEN, _TOOLS_FILE, _TOOLS_SYSTEM,
        )
        # Pre-sorted lists for early-return paths
        assert _TOOLS_INFO_DEFAULT == sorted(_TOOLS_INFO_DEFAULT)
        assert _TOOLS_INFO_WEATHER == sorted(_TOOLS_INFO_WEATHER)
        # Frozensets for set-union operations
        assert isinstance(_TOOLS_WEB, frozenset)
        assert isinstance(_TOOLS_OPEN, frozenset)
        assert isinstance(_TOOLS_FILE, frozenset)
        assert isinstance(_TOOLS_SYSTEM, frozenset)
        # Sanity: set membership preserved
        assert "smart_search" in _TOOLS_WEB
        assert "open_url" in _TOOLS_OPEN
        assert "fs_apply" in _TOOLS_FILE
        assert "system_control" in _TOOLS_SYSTEM

    def test_tool_executor_helpers_hoisted(self):
        from core.tool_executor import _first_value, _FS_APPLY_KIND_MAP
        # _first_value is now a module function (not a closure inside _normalize_arguments)
        assert callable(_first_value)
        assert _first_value({"a": 1, "b": 2}, ("a", "b")) == 1
        assert _first_value({"a": "", "b": 2}, ("a", "b")) == 2  # empty string skipped
        assert _first_value({"a": None, "b": 2}, ("a", "b")) == 2  # None skipped
        assert _first_value({"x": 1}, ("a", "b")) is None
        # FS apply kind map covers known synonyms
        assert _FS_APPLY_KIND_MAP["mv"] == "move"
        assert _FS_APPLY_KIND_MAP["delete"] == "trash"
        assert _FS_APPLY_KIND_MAP["save"] == "write"

    def test_file_ops_home_tmp_resolved_at_import(self):
        from core.tools import file_ops
        import os
        import tempfile

        assert hasattr(file_ops, "_HOME_REAL")
        assert hasattr(file_ops, "_TMP_REAL")
        # Resolved at import — must equal the realpath of home / tmp
        assert file_ops._HOME_REAL == os.path.realpath(os.path.expanduser("~"))
        assert file_ops._TMP_REAL == os.path.realpath(tempfile.gettempdir())


# ---------------------------------------------------------------------------
# Behavior preserved for changed callers
# ---------------------------------------------------------------------------

class TestBehaviorPreserved:
    def test_select_tool_names_pure_info_returns_sorted_list(self):
        """Pure info queries previously returned `sorted(core)`. Must still
        return a sorted list (order matters for cache keys / log readability)."""
        from unittest.mock import MagicMock
        from core.prompt_builder import PromptBuilder
        from core.tool_registry import ToolRegistry
        identity = MagicMock()
        identity.load_soul.return_value = ""
        identity.load_user.return_value = ""
        memory = MagicMock()
        memory.recall.return_value = []
        builder = PromptBuilder(identity, memory, ToolRegistry(), max_context_tokens=4096)

        out = builder._select_tool_names("查一下今天的天气", route="chat")
        assert out is not None
        assert out == sorted(out), f"_select_tool_names result must be sorted, got {out}"

    def test_normalize_arguments_still_works_for_all_tools(self):
        from core.tool_executor import ToolExecutor
        from core.tool_registry import ToolRegistry, ToolDefinition

        registry = ToolRegistry()
        # Stub all relevant tools
        for n in ("exec", "open_url", "skills_find_remote", "skills_install",
                  "fs_move", "fs_rename", "fs_write", "fs_trash", "fs_apply"):
            registry.register(ToolDefinition(
                name=n, description="x", parameters={"type": "object", "properties": {}},
                handler=lambda **_: "ok", safety_level="SAFE",
            ))
        executor = ToolExecutor(registry)

        # exec — alias `cmd` should map to `command`
        out = executor._normalize_arguments("exec", {"cmd": "ls", "time": 5})
        assert out["command"] == "ls"
        assert out["timeout"] == 5

        # open_url — alias `link` should map to `url` (and only `url` is kept)
        out = executor._normalize_arguments("open_url", {"link": "https://example.com"})
        assert out == {"url": "https://example.com"}

        # fs_move — `source` → `src`, `to` → `dest_dir`
        out = executor._normalize_arguments("fs_move", {"source": "a.txt", "to": "/tmp"})
        assert out["src"] == "a.txt"
        assert out["dest_dir"] == "/tmp"

        # fs_apply — kind synonyms
        out = executor._normalize_arguments("fs_apply", {
            "ops": [
                {"op": "mv", "source": "a", "to": "/tmp"},
                {"op": "delete", "path": "/tmp/x"},
                {"op": "save", "file": "/tmp/y", "data": "hi"},
            ]
        })
        kinds = [op["op"] for op in out["ops"]]
        assert kinds == ["move", "trash", "write"]
