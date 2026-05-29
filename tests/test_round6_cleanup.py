"""Round 6 regression tests: dead-method removal + memory perf + token budget."""

import pytest
import tempfile


# ---------------------------------------------------------------------------
# Dead methods removed from KageServer
# ---------------------------------------------------------------------------

class TestServerDeadMethodsRemoved:
    """These methods had no callers across core/, tests/ or scripts/.
    They should no longer exist on KageServer."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from core.server import KageServer
        self.cls = KageServer

    def test_think_report_removed(self):
        assert not hasattr(self.cls, "_think_report")

    def test_quick_chat_plan_removed(self):
        assert not hasattr(self.cls, "_quick_chat_plan")

    def test_repair_chat_response_removed(self):
        assert not hasattr(self.cls, "_repair_chat_response")

    def test_should_try_tools_wrapper_removed(self):
        # Only the unused `self._should_try_tools` wrapper was removed; the
        # imported `should_try_tools` from `route_classifier` is still callable.
        from core.route_classifier import should_try_tools
        assert callable(should_try_tools)
        assert not hasattr(self.cls, "_should_try_tools")

    def test_strip_cmd_output_removed(self):
        assert not hasattr(self.cls, "_strip_cmd_output")

    def test_send_random_motion_wrapper_removed(self):
        # The thin async delegator on KageServer is gone; the underlying
        # speech_engine module-level function is still available.
        from core.speech_engine import _send_random_motion
        assert callable(_send_random_motion)
        assert not hasattr(self.cls, "_send_random_motion")

    def test_sanitize_for_speech_test_api_kept(self):
        """`_sanitize_for_speech` is kept as a test-friendly API."""
        assert hasattr(self.cls, "_sanitize_for_speech")


# ---------------------------------------------------------------------------
# Memory: importance cache + argpartition correctness
# ---------------------------------------------------------------------------

class TestImportanceCache:
    def _make_memory(self):
        from core.memory import MemorySystem
        tmp = tempfile.mkdtemp()
        mem = MemorySystem(workspace_dir=tmp)
        # Force BM25-only path so the test does not pull in the embedding model.
        mem._model = None
        mem._embeddings = None
        return mem

    def test_cache_initially_none(self):
        mem = self._make_memory()
        assert mem._importance_cache is None

    def test_cache_built_on_first_recall(self):
        mem = self._make_memory()
        for i in range(5):
            mem.add_memory(f"entry {i}", importance=i + 1)
        # Trigger recall (which calls _get_importance_array internally)
        mem.recall("entry", n_results=3)
        assert mem._importance_cache is not None
        assert len(mem._importance_cache) == 5
        # importance values 1..5
        assert list(mem._importance_cache) == [1.0, 2.0, 3.0, 4.0, 5.0]

    def test_cache_appends_on_add(self):
        mem = self._make_memory()
        for i in range(3):
            mem.add_memory(f"entry {i}", importance=i + 1)
        mem.recall("entry", n_results=2)  # build cache
        assert mem._importance_cache is not None
        # Add one more
        mem.add_memory("entry new", importance=7)
        assert mem._importance_cache is not None
        assert len(mem._importance_cache) == 4
        assert mem._importance_cache[-1] == 7.0

    def test_cache_invalidated_on_eviction(self):
        from core.memory import MemorySystem
        tmp = tempfile.mkdtemp()
        # Tiny capacity to force eviction quickly.
        mem = MemorySystem(workspace_dir=tmp, max_entries=10)
        mem._model = None
        mem._embeddings = None
        for i in range(15):
            mem.add_memory(f"entry {i}", importance=(i % 5) + 1)
        # Eviction happened. Importance cache (if rebuilt) must match entries length.
        mem.recall("entry", n_results=3)
        assert len(mem._importance_cache) == len(mem._entries)


class TestRecallTopKArgpartition:
    """`recall` should return the top-N entries by final score in descending order."""

    def _make_memory(self):
        from core.memory import MemorySystem
        tmp = tempfile.mkdtemp()
        mem = MemorySystem(workspace_dir=tmp)
        mem._model = None
        mem._embeddings = None
        return mem

    def test_recall_returns_at_most_n_results(self):
        mem = self._make_memory()
        for i in range(20):
            mem.add_memory(f"topic apple banana {i}", importance=(i % 5) + 1)
        results = mem.recall("apple", n_results=5)
        assert len(results) <= 5

    def test_recall_when_n_exceeds_entries(self):
        mem = self._make_memory()
        mem.add_memory("apple", importance=3)
        mem.add_memory("banana", importance=2)
        # ask for more than we have — should fall back to argsort, not crash.
        results = mem.recall("apple banana", n_results=10)
        assert 0 < len(results) <= 2

    def test_recall_zero_results_on_empty(self):
        mem = self._make_memory()
        assert mem.recall("anything", n_results=5) == []

    def test_recall_results_ordered_by_score(self):
        """Higher-importance, more-relevant entries should come first."""
        mem = self._make_memory()
        # Same content, different importance — relevance ties broken by importance
        mem.add_memory("apple banana cherry", importance=1)
        mem.add_memory("apple banana cherry", importance=5)
        mem.add_memory("apple banana cherry", importance=3)
        results = mem.recall("apple banana", n_results=3)
        importances = [r["importance"] for r in results]
        assert importances == sorted(importances, reverse=True)


# ---------------------------------------------------------------------------
# chat_polisher.collapse_repeats — regex implementation correctness
# ---------------------------------------------------------------------------

class TestCollapseRepeats:
    def test_empty(self):
        from core.chat_polisher import collapse_repeats
        assert collapse_repeats("") == ""

    def test_no_runs(self):
        from core.chat_polisher import collapse_repeats
        assert collapse_repeats("abcdef") == "abcdef"

    def test_two_repeats_kept(self):
        from core.chat_polisher import collapse_repeats
        # Two consecutive same chars are allowed.
        assert collapse_repeats("aabb") == "aabb"

    def test_three_or_more_collapsed_to_two(self):
        from core.chat_polisher import collapse_repeats
        assert collapse_repeats("aaa") == "aa"
        assert collapse_repeats("aaaa") == "aa"
        assert collapse_repeats("aaaaaaaa") == "aa"

    def test_mixed(self):
        from core.chat_polisher import collapse_repeats
        # `aaab` → `aab`, mid-word run also collapsed
        assert collapse_repeats("aaab") == "aab"
        assert collapse_repeats("好哒哒哒哒") == "好哒哒"

    def test_full_pipeline_collapse_runs(self):
        """End-to-end through polish_chat_response — the truncated 40-char
        avatar reply should not contain runs of 3+ identical chars."""
        from core.chat_polisher import polish_chat_response
        out = polish_chat_response("你好哒哒哒哒哒哒哒哒哒")
        # No 3-char runs
        for i in range(len(out) - 2):
            assert not (out[i] == out[i + 1] == out[i + 2]), f"unexpected run in {out!r}"


# ---------------------------------------------------------------------------
# prompt_builder._enforce_budget — incremental subtraction correctness
# ---------------------------------------------------------------------------

class TestEnforceBudget:
    def _make_builder(self):
        from unittest.mock import MagicMock
        from core.prompt_builder import PromptBuilder
        from core.tool_registry import ToolRegistry
        identity = MagicMock()
        identity.load_soul.return_value = ""
        identity.load_user.return_value = ""
        memory = MagicMock()
        memory.recall.return_value = []
        return PromptBuilder(identity, memory, ToolRegistry(), max_context_tokens=4096)

    def test_under_budget_returns_unchanged(self):
        builder = self._make_builder()
        msgs = [
            {"role": "system", "content": "x"},
            {"role": "user", "content": "y"},
        ]
        out = builder._enforce_budget(list(msgs), budget=10000)
        assert out == msgs

    def test_protects_minimum_messages(self):
        builder = self._make_builder()
        # 3 messages: budget too small but can't be trimmed below 5 → returns as-is.
        msgs = [
            {"role": "system", "content": "x" * 10000},
            {"role": "user", "content": "y" * 10000},
            {"role": "user", "content": "z"},
        ]
        out = builder._enforce_budget(list(msgs), budget=1)
        assert len(out) == 3

    def test_trims_oldest_history(self):
        builder = self._make_builder()
        # 8 messages: system, 6 history, user. Should trim oldest history first.
        msgs = [{"role": "system", "content": "S"}]
        for i in range(6):
            msgs.append({"role": "user" if i % 2 == 0 else "assistant",
                         "content": f"H{i}-" + "x" * 200})
        msgs.append({"role": "user", "content": "current"})
        out = builder._enforce_budget(list(msgs), budget=50)
        # System + last 3 history + user should remain (5 messages)
        assert len(out) == 5
        # System and current user are preserved
        assert out[0]["content"] == "S"
        assert out[-1]["content"] == "current"
