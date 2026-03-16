"""
Unit tests for core.session_manager.SessionManager

Tests cover:
- Initialization creates sessions directory
- add_turn writes to memory and file
- get_history returns last 20 turns
- load_from_file restores session
- archive_if_idle archives after 30 min idle
- get_last_user_time returns correct timestamp
- Corrupted file handling (rename to .bak)
- Invalid roles and empty content are rejected
"""

import json
import os
import time
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from core.session_manager import (
    IDLE_TIMEOUT_SEC,
    MAX_HISTORY,
    SessionManager,
)


@pytest.fixture
def workspace(tmp_path):
    """Create a temporary workspace directory."""
    return str(tmp_path / "kage_test")


@pytest.fixture
def manager(workspace):
    """Create a SessionManager with a temporary workspace."""
    return SessionManager(workspace_dir=workspace)


# ── Initialization ────────────────────────────────────────


class TestInit:
    def test_creates_sessions_dir(self, workspace):
        assert not os.path.exists(workspace)
        SessionManager(workspace_dir=workspace)
        sessions_dir = os.path.join(workspace, "sessions")
        assert os.path.isdir(sessions_dir)

    def test_existing_dir_is_fine(self, workspace):
        os.makedirs(os.path.join(workspace, "sessions"), exist_ok=True)
        mgr = SessionManager(workspace_dir=workspace)
        assert os.path.isdir(mgr.sessions_dir)

    def test_empty_history_on_init(self, manager):
        assert manager.get_history() == []


# ── add_turn ──────────────────────────────────────────────


class TestAddTurn:
    def test_adds_user_turn(self, manager):
        manager.add_turn("user", "你好")
        history = manager.get_history()
        assert len(history) == 1
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "你好"

    def test_adds_assistant_turn(self, manager):
        manager.add_turn("assistant", "你好呀")
        history = manager.get_history()
        assert len(history) == 1
        assert history[0]["role"] == "assistant"

    def test_rejects_invalid_role(self, manager):
        manager.add_turn("system", "test")
        assert manager.get_history() == []

    def test_rejects_empty_content(self, manager):
        manager.add_turn("user", "")
        manager.add_turn("user", "   ")
        assert manager.get_history() == []

    def test_rejects_none_content(self, manager):
        manager.add_turn("user", None)
        assert manager.get_history() == []

    def test_strips_whitespace(self, manager):
        manager.add_turn("user", "  hello  ")
        assert manager.get_history()[0]["content"] == "hello"

    def test_writes_to_file(self, manager):
        manager.add_turn("user", "测试")
        assert os.path.isfile(manager.current_file)
        with open(manager.current_file, "r", encoding="utf-8") as f:
            line = f.readline().strip()
        turn = json.loads(line)
        assert turn["role"] == "user"
        assert turn["content"] == "测试"
        assert "timestamp" in turn

    def test_appends_multiple_turns(self, manager):
        manager.add_turn("user", "问题1")
        manager.add_turn("assistant", "回答1")
        manager.add_turn("user", "问题2")
        with open(manager.current_file, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
        assert len(lines) == 3


# ── get_history ───────────────────────────────────────────


class TestGetHistory:
    def test_returns_last_20_turns(self, manager):
        for i in range(25):
            manager.add_turn("user", f"消息{i}")
        history = manager.get_history()
        assert len(history) == MAX_HISTORY
        # Should contain the last 20 messages (5-24)
        assert history[0]["content"] == "消息5"
        assert history[-1]["content"] == "消息24"

    def test_returns_only_role_and_content(self, manager):
        manager.add_turn("user", "test")
        history = manager.get_history()
        assert set(history[0].keys()) == {"role", "content"}


# ── load_from_file ────────────────────────────────────────


class TestLoadFromFile:
    def test_restores_session(self, workspace):
        # Write some turns, then create a new manager and load
        mgr1 = SessionManager(workspace_dir=workspace)
        mgr1.add_turn("user", "你好")
        mgr1.add_turn("assistant", "你好呀")

        mgr2 = SessionManager(workspace_dir=workspace)
        mgr2.load_from_file()
        history = mgr2.get_history()
        assert len(history) == 2
        assert history[0]["content"] == "你好"
        assert history[1]["content"] == "你好呀"

    def test_loads_last_20_from_large_file(self, workspace):
        mgr1 = SessionManager(workspace_dir=workspace)
        for i in range(30):
            mgr1.add_turn("user", f"消息{i}")

        mgr2 = SessionManager(workspace_dir=workspace)
        mgr2.load_from_file()
        # All 30 turns are loaded into _history, get_history returns last 20
        history = mgr2.get_history()
        assert len(history) == MAX_HISTORY

    def test_no_file_does_nothing(self, manager):
        manager.load_from_file()
        assert manager.get_history() == []

    def test_skips_corrupted_lines(self, workspace):
        mgr = SessionManager(workspace_dir=workspace)
        # Write a mix of valid and invalid lines
        with open(mgr.current_file, "w", encoding="utf-8") as f:
            f.write(json.dumps({"role": "user", "content": "好的", "timestamp": "2025-01-15T10:00:00"}) + "\n")
            f.write("this is not json\n")
            f.write(json.dumps({"role": "assistant", "content": "收到", "timestamp": "2025-01-15T10:00:01"}) + "\n")

        mgr.load_from_file()
        history = mgr.get_history()
        assert len(history) == 2
        assert history[0]["content"] == "好的"
        assert history[1]["content"] == "收到"

    def test_empty_file_loads_nothing(self, workspace):
        mgr = SessionManager(workspace_dir=workspace)
        with open(mgr.current_file, "w", encoding="utf-8") as f:
            f.write("")
        mgr.load_from_file()
        assert mgr.get_history() == []


# ── Corrupted file handling ───────────────────────────────


class TestCorruptedFile:
    def test_fully_corrupted_file_renamed_to_bak(self, workspace):
        mgr = SessionManager(workspace_dir=workspace)
        # Write a completely corrupted file
        with open(mgr.current_file, "w", encoding="utf-8") as f:
            f.write("not json at all\n")
            f.write("also broken\n")

        mgr.load_from_file()

        # Original should be replaced with empty file
        bak_path = mgr.current_file + ".bak"
        assert os.path.isfile(bak_path)
        # .bak contains the original corrupted content
        with open(bak_path, "r", encoding="utf-8") as f:
            bak_content = f.read()
        assert "not json at all" in bak_content

        # History should be empty
        assert mgr.get_history() == []

    def test_partially_corrupted_file_keeps_valid_lines(self, workspace):
        mgr = SessionManager(workspace_dir=workspace)
        with open(mgr.current_file, "w", encoding="utf-8") as f:
            f.write("broken line\n")
            f.write(json.dumps({"role": "user", "content": "有效", "timestamp": "2025-01-15T10:00:00"}) + "\n")

        mgr.load_from_file()
        history = mgr.get_history()
        # Has at least one valid line, so no .bak rename
        assert len(history) == 1
        assert history[0]["content"] == "有效"

    def test_missing_fields_line_skipped(self, workspace):
        mgr = SessionManager(workspace_dir=workspace)
        with open(mgr.current_file, "w", encoding="utf-8") as f:
            f.write(json.dumps({"role": "user"}) + "\n")  # missing content
            f.write(json.dumps({"role": "user", "content": "ok", "timestamp": "2025-01-15T10:00:00"}) + "\n")

        mgr.load_from_file()
        history = mgr.get_history()
        assert len(history) == 1
        assert history[0]["content"] == "ok"


# ── archive_if_idle ───────────────────────────────────────


class TestArchiveIfIdle:
    def test_no_history_returns_false(self, manager):
        assert manager.archive_if_idle() is False

    def test_recent_activity_returns_false(self, manager):
        manager.add_turn("user", "刚说的话")
        assert manager.archive_if_idle() is False

    def test_archives_after_idle_timeout(self, workspace):
        mgr = SessionManager(workspace_dir=workspace)
        mgr.add_turn("user", "旧消息")

        # Patch the last user timestamp to be 31 minutes ago
        old_time = time.time() - IDLE_TIMEOUT_SEC - 60
        old_ts = datetime.fromtimestamp(old_time, tz=timezone.utc).isoformat()
        mgr._history[0]["timestamp"] = old_ts

        result = mgr.archive_if_idle()
        assert result is True

        # current.jsonl should be empty/new
        assert mgr.get_history() == []

        # An archive file should exist
        archive_files = [
            f for f in os.listdir(mgr.sessions_dir)
            if f.endswith(".jsonl") and f != "current.jsonl"
        ]
        assert len(archive_files) == 1
        # Archive filename should match YYYY-MM-DD-HH-MM.jsonl pattern
        name = archive_files[0]
        assert len(name) == len("2025-01-15-10-30.jsonl")

    def test_archive_contains_original_content(self, workspace):
        mgr = SessionManager(workspace_dir=workspace)
        mgr.add_turn("user", "归档内容")

        old_time = time.time() - IDLE_TIMEOUT_SEC - 60
        old_ts = datetime.fromtimestamp(old_time, tz=timezone.utc).isoformat()
        mgr._history[0]["timestamp"] = old_ts

        mgr.archive_if_idle()

        archive_files = [
            f for f in os.listdir(mgr.sessions_dir)
            if f.endswith(".jsonl") and f != "current.jsonl"
        ]
        archive_path = os.path.join(mgr.sessions_dir, archive_files[0])
        with open(archive_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "归档内容" in content

    def test_not_idle_enough(self, workspace):
        mgr = SessionManager(workspace_dir=workspace)
        mgr.add_turn("user", "最近的消息")

        # Set timestamp to 29 minutes ago (just under threshold)
        recent_time = time.time() - IDLE_TIMEOUT_SEC + 60
        recent_ts = datetime.fromtimestamp(recent_time, tz=timezone.utc).isoformat()
        mgr._history[0]["timestamp"] = recent_ts

        assert mgr.archive_if_idle() is False


# ── get_last_user_time ────────────────────────────────────


class TestGetLastUserTime:
    def test_no_history_returns_none(self, manager):
        assert manager.get_last_user_time() is None

    def test_only_assistant_returns_none(self, manager):
        manager.add_turn("assistant", "你好")
        assert manager.get_last_user_time() is None

    def test_returns_last_user_timestamp(self, manager):
        manager.add_turn("user", "第一条")
        manager.add_turn("assistant", "回复")
        manager.add_turn("user", "第二条")

        last_time = manager.get_last_user_time()
        assert last_time is not None
        # Should be very recent (within last few seconds)
        assert abs(time.time() - last_time) < 5

    def test_ignores_assistant_turns(self, manager):
        manager.add_turn("user", "用户消息")
        user_time = manager.get_last_user_time()

        manager.add_turn("assistant", "助手回复")
        # Last user time should still be the same
        assert manager.get_last_user_time() == user_time
