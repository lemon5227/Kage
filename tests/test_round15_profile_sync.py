"""
Round 15 Unit Tests - TASK-3: Dual Profile Sync (MemoryProfile <-> IdentityStore)
Verifies bidirectional synchronization between profile.json and USER.md,
unified user context generation, and PromptBuilder consistency.
"""

import os
import json
import pytest
from core.identity_store import IdentityStore
from core.memory_profile import MemoryProfile, UserProfile


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "kage_workspace"
    ws.mkdir()
    return str(ws)


class TestProfileIdentitySync:
    def test_memory_profile_syncs_to_user_md(self, workspace):
        ident = IdentityStore(workspace_dir=workspace)
        ident.ensure_files_exist()

        prof_path = os.path.join(workspace, "memory", "profile.json")
        prof = MemoryProfile(profile_path=prof_path, identity_store=ident)

        # Update profile fields and save
        prof.profile.name = "Alice"
        prof.profile.city = "Nice"
        prof.profile.music_preference = "Synthwave"
        prof.profile.sleep_schedule = "23:00-07:00"
        prof.save()

        # Check USER.md content
        user_md = ident.load_user()
        assert "姓名：Alice" in user_md
        assert "所在城市：Nice" in user_md
        assert "音乐偏好：Synthwave" in user_md
        assert "作息：23:00-07:00" in user_md

    def test_user_md_update_reflects_to_memory_profile(self, workspace):
        ident = IdentityStore(workspace_dir=workspace)
        ident.ensure_files_exist()

        prof_path = os.path.join(workspace, "memory", "profile.json")
        prof = MemoryProfile(profile_path=prof_path, identity_store=ident)
        ident.set_memory_profile(prof)

        # Update USER.md
        ident.update_user("姓名", "Bob")
        ident.update_user("音乐偏好", "Jazz")

        # Verify reflected in MemoryProfile
        assert prof.profile.name == "Bob"
        assert prof.profile.music_preference == "Jazz"

        # Verify persisted to profile.json
        with open(prof_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["name"] == "Bob"
        assert data["music_preference"] == "Jazz"

    def test_get_unified_user_context(self, workspace):
        ident = IdentityStore(workspace_dir=workspace)
        ident.ensure_files_exist()

        prof_path = os.path.join(workspace, "memory", "profile.json")
        prof = MemoryProfile(profile_path=prof_path)
        prof.profile.name = "Charlie"
        prof.profile.city = "Shanghai"
        prof.profile.occupation = "Engineer"

        context = ident.get_unified_user_context(prof)
        assert "姓名：Charlie" in context
        assert "所在城市：Shanghai" in context
        assert "职业：Engineer" in context

    def test_prompt_builder_renders_unified_context(self, workspace):
        from core.prompt_builder import PromptBuilder
        from core.tool_registry import ToolRegistry

        ident = IdentityStore(workspace_dir=workspace)
        ident.ensure_files_exist()

        prof_path = os.path.join(workspace, "memory", "profile.json")
        prof = MemoryProfile(profile_path=prof_path, identity_store=ident)
        ident.set_memory_profile(prof)

        prof.profile.name = "Diana"
        prof.profile.city = "Tokyo"
        prof.save()

        pb = PromptBuilder(
            identity_store=ident,
            memory_system=None,
            tool_registry=ToolRegistry(),
            memory_profile=prof,
        )

        messages, _ = pb.build("你好", history=[])
        sys_content = messages[0]["content"]
        assert "Diana" in sys_content
        assert "Tokyo" in sys_content
