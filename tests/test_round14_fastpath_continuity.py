"""Tests for Round 14 ISSUE-1: Fastpath Multi-turn Session Continuity.

Verifies that fastpath branches (commands, weather, video, undo, etc.)
correctly record turns into both SessionState and SessionManager so subsequent
agentic turns do not lose conversational context.
"""

from __future__ import annotations

import tempfile
from unittest.mock import MagicMock
import pytest

from core.server import KageServer
from core.session_state import SessionState
from core.session_manager import SessionManager


class _MockTools:
    def __init__(self):
        self.calls = []

    def system_control(self, target, action, value=None):
        self.calls.append(("system_control", target, action, value))
        return f"{target} {action} ok"


@pytest.fixture
def mock_server(tmp_path):
    s = object.__new__(KageServer)
    s.tools = _MockTools()
    s.session = SessionState()
    s.session_manager = SessionManager(workspace_dir=str(tmp_path))
    s._fast_cache = {}
    return s


class TestFastpathSessionContinuity:
    def test_record_turn_completed_updates_both_session_and_manager(self, mock_server):
        user_msg = "音量调大"
        reply = "音量已为您调大啦"
        
        mock_server._record_turn_completed(user_msg, reply)
        
        # Verify SessionState (in-memory)
        session_hist = mock_server.session.as_history_list()
        assert len(session_hist) == 2
        assert session_hist[0] == {"role": "user", "content": user_msg}
        assert session_hist[1] == {"role": "assistant", "content": reply}
        
        # Verify SessionManager (persisted)
        manager_hist = mock_server.session_manager.get_history()
        assert len(manager_hist) == 2
        assert manager_hist[0]["role"] == "user"
        assert manager_hist[0]["content"] == user_msg
        assert manager_hist[1]["role"] == "assistant"
        assert manager_hist[1]["content"] == reply

    def test_record_turn_completed_handles_empty_safely(self, mock_server):
        mock_server._record_turn_completed("", "")
        assert len(mock_server.session.as_history_list()) == 0
        assert len(mock_server.session_manager.get_history()) == 0
        
        mock_server._record_turn_completed("  ", "ok")
        assert len(mock_server.session.as_history_list()) == 0

        mock_server._record_turn_completed("hello", "")
        assert len(mock_server.session.as_history_list()) == 0

    def test_record_turn_completed_tolerates_exceptions(self, mock_server):
        mock_server.session = MagicMock()
        mock_server.session.add_turn.side_effect = RuntimeError("session broken")
        
        # Should not raise exception
        mock_server._record_turn_completed("test", "test")
        # SessionManager should still be called
        manager_hist = mock_server.session_manager.get_history()
        assert len(manager_hist) == 2

    def test_consecutive_fastpaths_accumulate_history(self, mock_server):
        turns = [
            ("音量调大", "音量已调大"),
            ("静音", "已静音"),
            ("取消静音", "已恢复音量"),
        ]
        for u, a in turns:
            mock_server._record_turn_completed(u, a)
            
        hist = mock_server.session.as_history_list()
        assert len(hist) == 6
        assert hist[0]["content"] == "音量调大"
        assert hist[2]["content"] == "静音"
        assert hist[4]["content"] == "取消静音"
