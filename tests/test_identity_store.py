"""
Unit tests for core.identity_store.IdentityStore

Tests cover:
- File creation on first run
- Loading SOUL.md and USER.md
- Updating user fields
- Appending soul adjustments
- Corrupted/empty file recovery from persona.json
- USER.md template contains required fields
"""

import json
import os
import tempfile

import pytest

from core.identity_store import (
    IdentityStore,
    SOUL_TEMPLATE,
    USER_TEMPLATE,
    _generate_soul_from_persona,
    _is_file_valid,
)


@pytest.fixture
def workspace(tmp_path):
    """Create a temporary workspace directory."""
    return str(tmp_path / "kage_test")


@pytest.fixture
def persona_json(tmp_path):
    """Create a temporary persona.json and patch the lookup."""
    persona = {
        "name": "Kage",
        "description": "二次元机娘",
        "system_prompt": (
            "你是 Kage，一个傲娇但靠谱的终端精灵。你很在乎用户，但不会尬聊。\n\n"
            "【说话风格】\n"
            "1. 主要用自然中文，尽量像真人。\n"
            "2. 表情符号尽量少用；不要输出多余 emoji。\n"
            "3. 语气词（哒/捏/哇）可用但不要强制，每段最多一次。\n"
            "4. 回复要简短（优先 1-2 句，最多 60 字），不重复、不废话。\n"
            "5. 先回应用户情绪/意图，再给建议或追问 1 个问题。\n"
            "6. 除非被问到，否则不要自我介绍或说明你能做什么。\n"
        ),
        "voice_setting": "cute_female",
    }
    path = tmp_path / "persona.json"
    path.write_text(json.dumps(persona, ensure_ascii=False), encoding="utf-8")
    return str(path)


@pytest.fixture
def store_with_persona(workspace, persona_json, monkeypatch):
    """Create an IdentityStore with persona.json patched."""
    import core.identity_store as mod

    monkeypatch.setattr(mod, "_find_persona_json", lambda: persona_json)
    return IdentityStore(workspace_dir=workspace)


@pytest.fixture
def store_no_persona(workspace, monkeypatch):
    """Create an IdentityStore without persona.json available."""
    import core.identity_store as mod

    monkeypatch.setattr(mod, "_find_persona_json", lambda: None)
    return IdentityStore(workspace_dir=workspace)


# ── Directory creation ────────────────────────────────────


class TestInit:
    def test_creates_workspace_dir(self, workspace):
        assert not os.path.exists(workspace)
        IdentityStore(workspace_dir=workspace)
        assert os.path.isdir(workspace)

    def test_existing_dir_is_fine(self, workspace):
        os.makedirs(workspace, exist_ok=True)
        store = IdentityStore(workspace_dir=workspace)
        assert os.path.isdir(store.workspace_dir)


# ── ensure_files_exist ────────────────────────────────────


class TestEnsureFilesExist:
    def test_creates_all_three_files(self, store_with_persona):
        store = store_with_persona
        store.ensure_files_exist()
        assert os.path.isfile(store.soul_path)
        assert os.path.isfile(store.user_path)
        assert os.path.isfile(store.tools_path)

    def test_soul_generated_from_persona(self, store_with_persona):
        store = store_with_persona
        store.ensure_files_exist()
        content = store.load_soul()
        assert "Kage" in content
        assert "灵魂" in content
        assert "调整记录" in content

    def test_soul_uses_template_when_no_persona(self, store_no_persona):
        store = store_no_persona
        store.ensure_files_exist()
        content = store.load_soul()
        assert content == SOUL_TEMPLATE

    def test_user_template_has_required_fields(self, store_with_persona):
        store = store_with_persona
        store.ensure_files_exist()
        content = store.load_user()
        for field in ("姓名", "时区", "常用语言", "默认浏览器", "常用应用", "音乐偏好"):
            assert field in content, f"USER.md 缺少字段: {field}"

    def test_does_not_overwrite_existing_valid_files(self, store_with_persona):
        store = store_with_persona
        # Write custom content first
        os.makedirs(store.workspace_dir, exist_ok=True)
        custom = "# My custom soul\nI am unique."
        with open(store.soul_path, "w", encoding="utf-8") as f:
            f.write(custom)
        store.ensure_files_exist()
        assert store.load_soul() == custom


# ── load_soul / load_user ─────────────────────────────────


class TestLoad:
    def test_load_soul_creates_if_missing(self, store_with_persona):
        content = store_with_persona.load_soul()
        assert "Kage" in content

    def test_load_user_creates_if_missing(self, store_with_persona):
        content = store_with_persona.load_user()
        assert "用户信息" in content

    def test_load_tools_notes_returns_empty_if_missing(self, store_with_persona):
        assert store_with_persona.load_tools_notes() == ""


# ── update_user ───────────────────────────────────────────


class TestUpdateUser:
    def test_update_existing_field(self, store_with_persona):
        store = store_with_persona
        store.ensure_files_exist()
        store.update_user("姓名", "小明")
        content = store.load_user()
        assert "小明" in content

    def test_update_preserves_other_fields(self, store_with_persona):
        store = store_with_persona
        store.ensure_files_exist()
        store.update_user("姓名", "小明")
        store.update_user("时区", "Asia/Shanghai")
        content = store.load_user()
        assert "小明" in content
        assert "Asia/Shanghai" in content

    def test_update_nonexistent_field_logs_warning(self, store_with_persona, caplog):
        store = store_with_persona
        store.ensure_files_exist()
        import logging

        with caplog.at_level(logging.WARNING):
            store.update_user("不存在的字段", "value")
        assert "未找到字段" in caplog.text

    def test_update_replaces_value_not_appends(self, store_with_persona):
        store = store_with_persona
        store.ensure_files_exist()
        store.update_user("姓名", "Alice")
        store.update_user("姓名", "Bob")
        content = store.load_user()
        assert "Bob" in content
        assert "Alice" not in content


# ── append_soul_adjustment ────────────────────────────────


class TestAppendSoulAdjustment:
    def test_append_feedback(self, store_with_persona):
        store = store_with_persona
        store.ensure_files_exist()
        store.append_soul_adjustment("说话太正式了，请更随意一些")
        content = store.load_soul()
        assert "说话太正式了，请更随意一些" in content

    def test_multiple_appends(self, store_with_persona):
        store = store_with_persona
        store.ensure_files_exist()
        store.append_soul_adjustment("反馈1")
        store.append_soul_adjustment("反馈2")
        content = store.load_soul()
        assert "反馈1" in content
        assert "反馈2" in content

    def test_feedback_in_adjustment_section(self, store_with_persona):
        store = store_with_persona
        store.ensure_files_exist()
        store.append_soul_adjustment("测试反馈")
        content = store.load_soul()
        # Feedback should appear after the adjustment section header
        adj_idx = content.index("调整记录")
        fb_idx = content.index("测试反馈")
        assert fb_idx > adj_idx


# ── Corrupted / empty file recovery ──────────────────────


class TestCorruptedFileRecovery:
    def test_empty_soul_regenerated(self, store_with_persona):
        store = store_with_persona
        # Create an empty SOUL.md
        os.makedirs(store.workspace_dir, exist_ok=True)
        with open(store.soul_path, "w") as f:
            f.write("")
        store.ensure_files_exist()
        content = store.load_soul()
        assert len(content.strip()) > 0
        assert "Kage" in content

    def test_empty_user_regenerated(self, store_with_persona):
        store = store_with_persona
        os.makedirs(store.workspace_dir, exist_ok=True)
        with open(store.user_path, "w") as f:
            f.write("")
        store.ensure_files_exist()
        content = store.load_user()
        assert "用户信息" in content

    def test_whitespace_only_soul_regenerated(self, store_with_persona):
        store = store_with_persona
        os.makedirs(store.workspace_dir, exist_ok=True)
        with open(store.soul_path, "w") as f:
            f.write("   \n\n  \t  ")
        store.ensure_files_exist()
        content = store.load_soul()
        assert "Kage" in content

    def test_empty_soul_without_persona_uses_template(self, store_no_persona):
        store = store_no_persona
        os.makedirs(store.workspace_dir, exist_ok=True)
        with open(store.soul_path, "w") as f:
            f.write("")
        store.ensure_files_exist()
        content = store.load_soul()
        assert content == SOUL_TEMPLATE


# ── Helper functions ──────────────────────────────────────


class TestHelpers:
    def test_is_file_valid_nonexistent(self, tmp_path):
        assert not _is_file_valid(str(tmp_path / "nope.md"))

    def test_is_file_valid_empty(self, tmp_path):
        p = tmp_path / "empty.md"
        p.write_text("")
        assert not _is_file_valid(str(p))

    def test_is_file_valid_whitespace(self, tmp_path):
        p = tmp_path / "ws.md"
        p.write_text("   \n  ")
        assert not _is_file_valid(str(p))

    def test_is_file_valid_ok(self, tmp_path):
        p = tmp_path / "ok.md"
        p.write_text("hello")
        assert _is_file_valid(str(p))

    def test_generate_soul_from_persona_contains_name(self):
        persona = {"name": "TestBot", "system_prompt": "你是 TestBot"}
        result = _generate_soul_from_persona(persona)
        assert "TestBot" in result
        assert "灵魂" in result
        assert "调整记录" in result
