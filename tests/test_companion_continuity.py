"""Companion-assistant continuity tests.

These tests exercise behaviors that a "personal companion 二次元 assistant"
must hold across turns, not just per-call:

  1. User-stated preferences are recallable later.
  2. User profile (food / city / habits / relationships) is injected into
     the system prompt verbatim, so persona stays personalised.
  3. Profile changes persist across MemoryProfile reload (companion remembers
     across restarts).
  4. polish_chat_response NEVER returns an empty reply (an empty bubble would
     break the avatar UX).
  5. Persona-preserving polish: allowed emoji + Chinese stay, disallowed
     emoji / English-only filler get stripped, but result still has content.
  6. Bubble fit: every polished chat response is short enough for the
     Live2D avatar bubble (≤ 40 chars).
  7. Route-aware prompt sizing: info / command routes return a minimal
     tool set so latency stays under SLO.

All tests run without LLM calls (no model required).
"""

from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _bm25_only_memory(workspace_dir: str | None = None):
    """Build a MemorySystem that uses BM25 only (no SentenceTransformer)
    so tests stay deterministic and offline."""
    from core.memory import MemorySystem
    mem = MemorySystem(workspace_dir=workspace_dir or tempfile.mkdtemp())
    mem._model = None
    mem._embeddings = None
    return mem


def _make_prompt_builder(memory=None, profile=None, registry=None):
    from core.prompt_builder import PromptBuilder
    from core.tool_registry import ToolRegistry

    identity = MagicMock()
    identity.load_soul.return_value = "我是 Kage，傲娇但靠谱的终端精灵。"
    identity.load_user.return_value = "用户: Master"

    if memory is None:
        memory = MagicMock()
        memory.recall.return_value = []

    builder = PromptBuilder(
        identity_store=identity,
        memory_system=memory,
        tool_registry=registry or ToolRegistry(),
        max_context_tokens=4096,
        memory_profile=profile,
    )
    return builder


# ---------------------------------------------------------------------------
# 1. Multi-turn preference recall
# ---------------------------------------------------------------------------

class TestMultiTurnPreferenceRecall:
    """A companion must remember things the user told it many turns ago."""

    def test_food_preference_stated_in_turn1_is_recallable_in_turn5(self):
        mem = _bm25_only_memory()

        # Turn 1: user states a clear food preference
        mem.add_fact(
            content="用户喜欢喝黑咖啡",
            category="preference",
            importance=4,
            emotion="happy",
        )

        # Turns 2-4: unrelated chatter (but stored as low-importance noise)
        mem.add_memory("天气真好啊", importance=1)
        mem.add_memory("今天周末了", importance=1)
        mem.add_memory("好困啊", importance=1)

        # Turn 5: a query that should re-surface the coffee preference
        results = mem.recall("早上喝什么", n_results=3)

        contents = " | ".join(r["content"] for r in results)
        assert "咖啡" in contents, (
            f"User said they like 黑咖啡 in turn 1 — turn 5 query about morning "
            f"drinks should retrieve it. Got: {contents}"
        )

    def test_correction_keeps_both_versions_in_recall(self):
        """User said one thing then corrected. Both entries must remain
        recallable so the LLM can see the contradiction and prefer the
        corrected (newer / higher-importance) one."""
        mem = _bm25_only_memory()
        mem.add_fact(content="用户讨厌咖啡", category="preference", importance=2)
        mem.add_fact(content="用户其实超爱咖啡", category="preference", importance=4)

        results = mem.recall("咖啡偏好", n_results=5)
        contents = [r["content"] for r in results]
        # Both must be present so the LLM can reason about the contradiction.
        assert any("讨厌" in c for c in contents), \
            f"original preference must remain recallable, got {contents}"
        assert any("超爱" in c for c in contents), \
            f"corrected preference must be recallable, got {contents}"

        # The corrected (importance=4) version must rank in the top 2 when both
        # entries match the query equally well — otherwise an LLM with limited
        # n_results (e.g. 3) would only see the wrong version.
        top2 = results[:2]
        assert any("超爱" in r["content"] for r in top2), (
            f"user's correction (importance=4) must rank in top 2, got top: "
            f"{[r['content'] for r in top2]}"
        )


# ---------------------------------------------------------------------------
# 2. Profile injection into system prompt
# ---------------------------------------------------------------------------

class TestProfileInjectionIntoSystemPrompt:
    """A personalised companion needs the user's profile (food / city / habits)
    in the LLM's system prompt every turn."""

    def _make_profile_with_preferences(self):
        from core.memory_profile import MemoryProfile
        tmp = tempfile.mkdtemp()
        prof = MemoryProfile(profile_path=os.path.join(tmp, "profile.json"))
        prof.update_preference("food", "food_preference", "川菜")
        prof.update_preference("location", "city", "上海")
        prof.add_habit("sleep", "23:00-07:00")
        prof.add_relationship("小明", "朋友", "大学同学")
        return prof

    def test_food_preference_appears_in_system_prompt(self):
        profile = self._make_profile_with_preferences()
        builder = _make_prompt_builder(profile=profile)
        msgs, _ = builder.build("帮我推荐个吃的", history=[])
        system = msgs[0]["content"]
        assert "川菜" in system, "user's food preference must appear in system prompt"

    def test_city_appears_in_system_prompt(self):
        profile = self._make_profile_with_preferences()
        builder = _make_prompt_builder(profile=profile)
        msgs, _ = builder.build("今天去哪好", history=[])
        system = msgs[0]["content"]
        assert "上海" in system

    def test_sleep_habit_appears_in_system_prompt(self):
        profile = self._make_profile_with_preferences()
        builder = _make_prompt_builder(profile=profile)
        msgs, _ = builder.build("我累了", history=[])
        system = msgs[0]["content"]
        assert "23:00" in system or "07:00" in system

    def test_relationship_appears_in_system_prompt(self):
        profile = self._make_profile_with_preferences()
        builder = _make_prompt_builder(profile=profile)
        msgs, _ = builder.build("小明发消息了", history=[])
        system = msgs[0]["content"]
        assert "小明" in system


# ---------------------------------------------------------------------------
# 3. Profile durability across reload
# ---------------------------------------------------------------------------

class TestProfileDurabilityAcrossReload:
    """Companion must remember user across process restarts."""

    def test_food_preference_survives_reload(self):
        from core.memory_profile import MemoryProfile

        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "profile.json")

        # Session 1: user tells Kage they love spicy food
        prof1 = MemoryProfile(profile_path=path)
        prof1.update_preference("food", "food_preference", "重辣")

        # Process restart — fresh MemoryProfile reading the same file
        prof2 = MemoryProfile(profile_path=path)
        summary = prof2.get_profile_summary()
        assert "重辣" in summary, (
            "user's food preference should survive process restart but did not"
        )

    def test_relationship_survives_reload(self):
        from core.memory_profile import MemoryProfile

        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "profile.json")

        prof1 = MemoryProfile(profile_path=path)
        prof1.add_relationship("阿强", "同事", "产品经理")

        prof2 = MemoryProfile(profile_path=path)
        summary = prof2.get_profile_summary()
        assert "阿强" in summary


# ---------------------------------------------------------------------------
# 4. Empty-reply guarantee (a chat avatar with empty bubble would feel broken)
# ---------------------------------------------------------------------------

class TestNeverEmptyChatReply:
    """polish_chat_response must always return non-empty text **for non-empty
    input**. The avatar UI shows the result in a chat bubble — empty would
    look like Kage is frozen.

    Empty/None input is a separate contract: callers use it as a "no reply
    needed" signal, so polish passes it through.
    """

    @pytest.mark.parametrize("raw", [
        # Whitespace gets recovered to "嗯"
        "   ",
        "\n\n",
        # Pure blocked content — every char gets stripped
        "neutral happy sad",
        "<system-reminder>SECRET</system-reminder>",
        # Reasoning artifact only
        "<think>internal monologue</think>",
        # User/assistant echo only
        "用户: 你好 助手:",
        # Pure capability brag
        "我能做3项事:",
        # Disallowed emoji only (no allowed emoji)
        "🎵🎵🎵",
    ])
    def test_polish_recovers_to_non_empty_for_non_empty_input(self, raw):
        from core.chat_polisher import polish_chat_response
        out = polish_chat_response(raw)
        assert out, (
            f"polish_chat_response returned empty for non-empty input "
            f"{raw!r}; the avatar bubble would show nothing"
        )
        assert out.strip(), f"polish returned whitespace-only for: {raw!r}"

    def test_polish_passes_empty_through(self):
        """Truly empty input is a 'no reply' signal — polish leaves it
        as-is so the caller can short-circuit."""
        from core.chat_polisher import polish_chat_response
        assert polish_chat_response("") == ""
        assert polish_chat_response(None) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 5. Persona-preserving polish — allowed glyphs survive
# ---------------------------------------------------------------------------

class TestPersonaGlyphPreservation:
    """Kage's persona uses ✨😤💖 emoji and Chinese chars. polish must keep
    those even while stripping disallowed glyphs."""

    def test_allowed_emoji_survive(self):
        from core.chat_polisher import polish_chat_response
        out = polish_chat_response("好啦💖马上帮你✨")
        # At least one persona emoji should survive
        assert any(e in out for e in ("💖", "✨", "😤")), \
            f"persona emoji stripped: {out!r}"

    def test_chinese_punctuation_preserved(self):
        from core.chat_polisher import polish_chat_response
        out = polish_chat_response("好啦，马上！")
        # Chinese punctuation `，` and `！` are in _ALLOWED_PUNCT
        assert "，" in out or "！" in out

    def test_disallowed_emoji_stripped(self):
        from core.chat_polisher import polish_chat_response
        # 🎵 is NOT in _ALLOWED_EMOJI
        out = polish_chat_response("听音乐🎵的时候")
        assert "🎵" not in out, f"disallowed emoji 🎵 should be stripped: {out!r}"


# ---------------------------------------------------------------------------
# 6. Bubble fit — avatar bubble can only show a short reply
# ---------------------------------------------------------------------------

class TestPolishBubbleFit:
    """Live2D bubble has a fixed character budget (`_MAX_CHAT_RESPONSE_LEN`)."""

    def test_long_reply_fits_in_bubble(self):
        from core.chat_polisher import polish_chat_response, _MAX_CHAT_RESPONSE_LEN
        long_input = "这是一段很长的回复" * 30  # ~270 chars
        out = polish_chat_response(long_input)
        assert len(out) <= _MAX_CHAT_RESPONSE_LEN, (
            f"polished reply ({len(out)} chars) exceeds bubble budget "
            f"({_MAX_CHAT_RESPONSE_LEN}): {out!r}"
        )

    def test_short_reply_unchanged_length(self):
        from core.chat_polisher import polish_chat_response, _MAX_CHAT_RESPONSE_LEN
        out = polish_chat_response("好哒💖")
        assert len(out) <= _MAX_CHAT_RESPONSE_LEN


# ---------------------------------------------------------------------------
# 7. Route-aware prompt sizing
# ---------------------------------------------------------------------------

class TestRouteAwarePromptSizing:
    """For latency: info / command routes get pruned tool sets and skip
    memory recall (which would otherwise take ~5ms with embeddings)."""

    def test_info_route_skips_memory_recall_by_default(self):
        """For info queries (天气, 新闻), recall is disabled to keep p95 < 6s."""
        mem = MagicMock()
        mem.recall.return_value = [{"content": "old fact", "importance": 3,
                                    "emotion_data": {"emotion": "neutral"},
                                    "timestamp": "", "type": "chat"}]
        mem.bm25_search.return_value = []
        mem.vector_search.return_value = []

        builder = _make_prompt_builder(memory=mem)
        # The default config has recall_web_enabled = False for info
        msgs, _ = builder.build("查一下今天天气", history=[])

        # System prompt should not contain the old fact (recall was skipped)
        system = msgs[0]["content"]
        assert "old fact" not in system, (
            "info-route turn should not pull in unrelated memories; "
            "found 'old fact' in system prompt"
        )

    def test_command_route_skips_memory_recall(self):
        """For command (打开/截屏/调音量), recall is hard-disabled."""
        mem = MagicMock()
        mem.recall.return_value = [{"content": "user's bff is 小明", "importance": 4,
                                    "emotion_data": {"emotion": "neutral"},
                                    "timestamp": "", "type": "chat"}]
        mem.bm25_search.return_value = []
        mem.vector_search.return_value = []

        builder = _make_prompt_builder(memory=mem)
        msgs, _ = builder.build("帮我打开 Safari", history=[])
        system = msgs[0]["content"]
        assert "user's bff is" not in system, (
            "command-route turn should never recall friendship facts"
        )

    @pytest.mark.xfail(
        reason="Classifier matches '截屏' as substring but '截个屏' does not contain it. "
        "Colloquial phrasings of system commands fall through to chat route — "
        "documented gap; fix would require token-aware matching.",
        strict=True,
    )
    def test_classifier_recognises_colloquial_screenshot(self):
        """User naturally says '截个屏' not '截屏'. Today this falls through
        to chat route. This xfail documents the gap so we notice if the
        classifier improves."""
        builder = _make_prompt_builder()
        assert builder.classify_route("帮我截个屏") == "command"

    def test_info_route_returns_minimal_tool_set(self):
        from core.prompt_builder import _TOOLS_INFO_DEFAULT
        builder = _make_prompt_builder()
        tools = builder._select_tool_names("查一下汇率", route="info")
        # Only the search/get_time tools, no fs_*, system_control, etc.
        for forbidden in ("fs_apply", "fs_move", "system_control", "open_url"):
            assert forbidden not in tools, (
                f"info route leaked unrelated tool {forbidden}: {tools}"
            )
        for required in _TOOLS_INFO_DEFAULT:
            assert required in tools

    def test_command_route_excludes_search_tools(self):
        builder = _make_prompt_builder()
        tools = builder._select_tool_names("打开 Safari", route="command")
        # Command route is for actions; search tools would just add noise
        assert "smart_search" not in tools, (
            f"command route should not include smart_search: {tools}"
        )
