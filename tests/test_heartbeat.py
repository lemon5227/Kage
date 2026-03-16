"""Tests for Heartbeat — proactive behavior system."""

import asyncio
import os
import time
from unittest.mock import MagicMock, patch

import pytest

from core.heartbeat import Heartbeat, clamp_interval, MIN_INTERVAL_MIN, MAX_INTERVAL_MIN


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def workspace(tmp_path):
    return str(tmp_path)


@pytest.fixture
def session():
    sm = MagicMock()
    sm.get_last_user_time.return_value = None
    return sm


@pytest.fixture
def tool_executor():
    return MagicMock()


@pytest.fixture
def hb(tool_executor, session, workspace):
    return Heartbeat(tool_executor, session, workspace_dir=workspace)


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Interval clamping
# ---------------------------------------------------------------------------

class TestClampInterval:
    def test_normal_value(self):
        assert clamp_interval(30) == 30

    def test_below_minimum(self):
        assert clamp_interval(1) == MIN_INTERVAL_MIN
        assert clamp_interval(0) == MIN_INTERVAL_MIN
        assert clamp_interval(-10) == MIN_INTERVAL_MIN

    def test_above_maximum(self):
        assert clamp_interval(200) == MAX_INTERVAL_MIN
        assert clamp_interval(999) == MAX_INTERVAL_MIN

    def test_boundary_values(self):
        assert clamp_interval(5) == 5
        assert clamp_interval(120) == 120

    def test_float_input(self):
        assert clamp_interval(30.7) == 30


# ---------------------------------------------------------------------------
# HEARTBEAT.md parsing
# ---------------------------------------------------------------------------

class TestLoadCheckItems:
    def test_parses_heartbeat_md(self, hb, workspace):
        content = """# 心跳检查项

## 天气提醒
- enabled: true
- 描述：检查天气变化

## 日历提醒
- enabled: false
- 描述：检查今日日程

## 系统状态
- enabled: true
- 描述：检查磁盘空间
"""
        with open(os.path.join(workspace, "HEARTBEAT.md"), "w") as f:
            f.write(content)

        items = hb.load_check_items()
        assert len(items) == 3
        assert items[0]["name"] == "天气提醒"
        assert items[0]["enabled"] is True
        assert items[1]["enabled"] is False
        assert items[2]["description"] == "检查磁盘空间"

    def test_missing_file_returns_empty(self, hb):
        items = hb.load_check_items()
        assert items == []

    def test_empty_file(self, hb, workspace):
        with open(os.path.join(workspace, "HEARTBEAT.md"), "w") as f:
            f.write("")
        items = hb.load_check_items()
        assert items == []


# ---------------------------------------------------------------------------
# User activity detection
# ---------------------------------------------------------------------------

class TestIsUserActive:
    def test_no_history(self, hb, session):
        session.get_last_user_time.return_value = None
        assert hb.is_user_active() is False

    def test_recent_activity(self, hb, session):
        session.get_last_user_time.return_value = time.time() - 30  # 30 sec ago
        assert hb.is_user_active() is True

    def test_old_activity(self, hb, session):
        session.get_last_user_time.return_value = time.time() - 300  # 5 min ago
        assert hb.is_user_active() is False

    def test_exactly_at_threshold(self, hb, session):
        session.get_last_user_time.return_value = time.time() - 120
        # At exactly 120 seconds, not active (< not <=)
        assert hb.is_user_active() is False


# ---------------------------------------------------------------------------
# Tick — notification behavior
# ---------------------------------------------------------------------------

class TestTick:
    def test_tick_returns_notifications_when_idle(self, hb, session, workspace):
        session.get_last_user_time.return_value = None  # not active
        content = """# 心跳检查项

## 天气提醒
- enabled: true
- 描述：检查天气
"""
        with open(os.path.join(workspace, "HEARTBEAT.md"), "w") as f:
            f.write(content)

        notifications = run(hb.tick())
        assert len(notifications) == 1
        assert notifications[0]["type"] == "天气提醒"

    def test_tick_queues_when_active(self, hb, session, workspace):
        session.get_last_user_time.return_value = time.time() - 10  # active
        content = """# 心跳检查项

## 天气提醒
- enabled: true
- 描述：检查天气
"""
        with open(os.path.join(workspace, "HEARTBEAT.md"), "w") as f:
            f.write(content)

        notifications = run(hb.tick())
        assert notifications == []
        assert len(hb._notification_queue) == 1

    def test_queued_notifications_flushed_when_idle(self, hb, session, workspace):
        # First tick: user active → queue
        session.get_last_user_time.return_value = time.time() - 10
        content = """# 心跳检查项

## 天气提醒
- enabled: true
- 描述：检查天气
"""
        with open(os.path.join(workspace, "HEARTBEAT.md"), "w") as f:
            f.write(content)

        run(hb.tick())
        assert len(hb._notification_queue) == 1

        # Second tick: user idle → flush queue
        session.get_last_user_time.return_value = None
        notifications = run(hb.tick())
        assert len(notifications) == 2  # queued + new
        assert len(hb._notification_queue) == 0

    def test_disabled_items_skipped(self, hb, session, workspace):
        session.get_last_user_time.return_value = None
        content = """# 心跳检查项

## 日历提醒
- enabled: false
- 描述：检查日程
"""
        with open(os.path.join(workspace, "HEARTBEAT.md"), "w") as f:
            f.write(content)

        notifications = run(hb.tick())
        assert notifications == []

    def test_no_heartbeat_file(self, hb, session):
        session.get_last_user_time.return_value = None
        notifications = run(hb.tick())
        assert notifications == []


# ---------------------------------------------------------------------------
# Notification queue
# ---------------------------------------------------------------------------

class TestNotificationQueue:
    def test_get_queued_clears(self, hb):
        hb._notification_queue = [{"type": "test", "content": "hi"}]
        queued = hb.get_queued_notifications()
        assert len(queued) == 1
        assert len(hb._notification_queue) == 0


# ---------------------------------------------------------------------------
# Error logging
# ---------------------------------------------------------------------------

class TestErrorLogging:
    def test_logs_error(self, hb, workspace):
        hb._log_error("天气提醒", RuntimeError("API timeout"))
        error_log = os.path.join(workspace, "heartbeat_error.log")
        assert os.path.exists(error_log)
        with open(error_log, "r") as f:
            content = f.read()
        assert "天气提醒" in content
        assert "RuntimeError" in content
        assert "API timeout" in content
