"""Companion-assistant: persona injection scenarios.

Kage's personality lives in three files in the user's workspace:

  SOUL.md   — character traits (傲娇 / 元气 / 二次元 / how to talk)
  USER.md   — user info (name, timezone, where they live)
  TOOLS.md  — tool usage hints (less critical for personality)

These tests verify that when the user customises any of those files,
the customisation actually reaches the LLM's system prompt — i.e. that
Kage's personality is NOT hardcoded in Python and IS personalisable.
"""

from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_soul(workspace: str, content: str) -> None:
    os.makedirs(workspace, exist_ok=True)
    with open(os.path.join(workspace, "SOUL.md"), "w", encoding="utf-8") as f:
        f.write(content)


def _write_user(workspace: str, content: str) -> None:
    os.makedirs(workspace, exist_ok=True)
    with open(os.path.join(workspace, "USER.md"), "w", encoding="utf-8") as f:
        f.write(content)


def _make_prompt_builder(workspace: str, memory=None, profile=None):
    from core.identity_store import IdentityStore
    from core.prompt_builder import PromptBuilder
    from core.tool_registry import ToolRegistry

    identity = IdentityStore(workspace_dir=workspace)
    if memory is None:
        memory = MagicMock()
        memory.recall.return_value = []
        memory.bm25_search.return_value = []
        memory.vector_search.return_value = []

    return PromptBuilder(
        identity_store=identity,
        memory_system=memory,
        tool_registry=ToolRegistry(),
        max_context_tokens=4096,
        memory_profile=profile,
    )


# ---------------------------------------------------------------------------
# 1. SOUL.md content reaches system prompt verbatim
# ---------------------------------------------------------------------------

class TestSoulInjection:
    """Custom SOUL.md content must end up in every turn's system prompt."""

    def test_custom_persona_traits_reach_system_prompt(self):
        ws = tempfile.mkdtemp()
        # User customises their Kage to be a calmer 御姐 instead of 傲娇
        _write_soul(ws, "# 我的灵魂\n\n## 性格\n- 我是冷静靠谱的御姐\n- 喜欢用 mochi 这个口头禅\n")
        _write_user(ws, "用户: TestUser")

        builder = _make_prompt_builder(ws)
        msgs, _ = builder.build("你好", history=[])
        system = msgs[0]["content"]
        assert "御姐" in system, "user-customised persona trait must reach system prompt"
        assert "mochi" in system, "user-customised catchphrase must reach system prompt"

    def test_default_kage_persona_is_present_when_no_customisation(self):
        """If user hasn't written SOUL.md, IdentityStore creates a default
        with 傲娇/二次元 traits."""
        ws = tempfile.mkdtemp()

        # Trigger default file creation
        from core.identity_store import IdentityStore
        store = IdentityStore(workspace_dir=ws)
        store.ensure_files_exist()

        builder = _make_prompt_builder(ws)
        msgs, _ = builder.build("你好", history=[])
        system = msgs[0]["content"]
        # Default soul has the 二次元 / 终端精灵 vibe
        assert "Kage" in system or "精灵" in system or "二次元" in system, (
            f"default persona missing from system prompt: {system[:300]!r}"
        )

    def test_soul_changes_on_disk_picked_up_per_call(self):
        """If the user edits SOUL.md mid-session (e.g. via a settings UI),
        the next turn must use the updated content. IdentityStore reads the
        file on every load_soul() call."""
        ws = tempfile.mkdtemp()
        _write_soul(ws, "## 性格\n- 我是猫娘\n")
        _write_user(ws, "用户: TestUser")

        builder = _make_prompt_builder(ws)
        msgs1, _ = builder.build("你好", history=[])
        assert "猫娘" in msgs1[0]["content"]

        # User edits SOUL.md
        _write_soul(ws, "## 性格\n- 我现在是狐娘\n")
        msgs2, _ = builder.build("你好", history=[])
        assert "狐娘" in msgs2[0]["content"], (
            "edits to SOUL.md must be picked up by the next turn — "
            "otherwise users can't tune their companion mid-session"
        )
        assert "猫娘" not in msgs2[0]["content"]


# ---------------------------------------------------------------------------
# 2. USER.md customisation reaches prompt
# ---------------------------------------------------------------------------

class TestUserMdInjection:
    def test_user_name_in_prompt(self):
        ws = tempfile.mkdtemp()
        _write_soul(ws, "## 性格\n- 一个 AI\n")
        _write_user(ws, "# 用户\n\n- 称呼：小明同学\n- 时区：Asia/Shanghai\n")

        builder = _make_prompt_builder(ws)
        msgs, _ = builder.build("你好", history=[])
        system = msgs[0]["content"]
        assert "小明同学" in system

    def test_user_timezone_in_prompt(self):
        ws = tempfile.mkdtemp()
        _write_soul(ws, "## 性格\n- 一个 AI\n")
        _write_user(ws, "- 称呼: User\n- 时区: Europe/Paris\n")

        builder = _make_prompt_builder(ws)
        msgs, _ = builder.build("现在几点", history=[])
        system = msgs[0]["content"]
        assert "Europe/Paris" in system


# ---------------------------------------------------------------------------
# 3. Profile-vs-USER.md: profile preferences come AFTER soul/user info
# ---------------------------------------------------------------------------

class TestPromptOrdering:
    """Ordering matters for LLM prompt-following: persona first, then
    user info, then time, then memory/profile, then tools, then history.
    """

    def test_soul_appears_before_profile_summary(self):
        """If both exist, the persona instruction should come BEFORE the
        profile summary so the LLM frames its style first, then personalises."""
        from core.memory_profile import MemoryProfile

        ws = tempfile.mkdtemp()
        _write_soul(ws, "## 性格\n- UNIQUE_SOUL_MARKER 元气满满\n")
        _write_user(ws, "用户: u")

        prof = MemoryProfile(profile_path=os.path.join(ws, "profile.json"))
        prof.update_preference("food", "food_preference", "UNIQUE_PROFILE_MARKER 麻辣")

        builder = _make_prompt_builder(ws, profile=prof)
        msgs, _ = builder.build("帮我推荐", history=[])
        system = msgs[0]["content"]

        soul_idx = system.find("UNIQUE_SOUL_MARKER")
        prof_idx = system.find("UNIQUE_PROFILE_MARKER")
        assert soul_idx >= 0 and prof_idx >= 0, "both markers must be present"
        assert soul_idx < prof_idx, (
            f"SOUL must precede profile summary; got soul@{soul_idx}, profile@{prof_idx}"
        )

    def test_current_time_in_prompt(self):
        ws = tempfile.mkdtemp()
        _write_soul(ws, "## 性格\n- a\n")
        _write_user(ws, "用户: u")

        builder = _make_prompt_builder(ws)
        msgs, _ = builder.build("hi", history=[])
        system = msgs[0]["content"]
        # A YYYY-MM-DD pattern should be present (current_time line).
        import datetime
        today = datetime.date.today().isoformat()
        assert today in system


# ---------------------------------------------------------------------------
# 4. Persona stays even when system context is large
# ---------------------------------------------------------------------------

class TestPersonaSurvivesTokenBudget:
    """When history grows large, _enforce_budget trims old user/assistant
    turns — but the SYSTEM prompt (which holds the persona) MUST survive."""

    def test_persona_survives_long_history(self):
        ws = tempfile.mkdtemp()
        _write_soul(ws, "## 性格\n- PERSONA_TAG 我是 Kage\n")
        _write_user(ws, "用户: u")

        builder = _make_prompt_builder(ws)
        # Massive history that should force budget trimming
        history = [
            {"role": "user" if i % 2 == 0 else "assistant",
             "content": "x" * 800}
            for i in range(50)
        ]
        msgs, _ = builder.build("最新的问题", history=history)
        # System prompt must still be the first message
        assert msgs[0]["role"] == "system"
        # And the persona tag must survive untrimmed
        assert "PERSONA_TAG" in msgs[0]["content"], (
            "persona must NOT be trimmed even under budget pressure — "
            "Kage would lose its character"
        )

    def test_current_user_input_always_last(self):
        """The just-spoken user input is the most important message — it
        must not be trimmed by budget enforcement."""
        ws = tempfile.mkdtemp()
        _write_soul(ws, "## 性格\n- a\n")
        _write_user(ws, "用户: u")

        builder = _make_prompt_builder(ws)
        history = [{"role": "user", "content": "x" * 5000}] * 10
        msgs, _ = builder.build("UNIQUE_LAST_USER_QUESTION", history=history)
        assert msgs[-1]["role"] == "user"
        assert msgs[-1]["content"] == "UNIQUE_LAST_USER_QUESTION"
