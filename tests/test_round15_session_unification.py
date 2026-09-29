"""
Round 15 Unit Tests - TASK-2: Session State Unification (SSOT)
Verifies SessionManager and SessionState unification, pending action lifecycle,
deque compatibility, DialogStateMachine interoperability, and no turn duplication.
"""

from collections import deque
import pytest
from core.session_manager import SessionManager
from core.session_state import SessionState
from core.dialog_state_machine import DialogStateMachine
from core.pending_handlers import PendingHandlerResult
from core.interaction_state import make_pending_confirm_tool


class TestSessionManagerUnification:
    def test_session_manager_pending_action_lifecycle(self, tmp_path):
        mgr = SessionManager(workspace_dir=str(tmp_path))
        assert not mgr.has_pending_action()
        assert mgr.pending_action is None

        pending = make_pending_confirm_tool("system_volume", {"value": 50})
        res = mgr.set_pending_action(pending)
        assert res is pending
        assert mgr.has_pending_action()
        assert mgr.pending_action == pending

        mgr.clear_pending_action()
        assert not mgr.has_pending_action()
        assert mgr.pending_action is None

    def test_session_manager_last_action(self, tmp_path):
        mgr = SessionManager(workspace_dir=str(tmp_path))
        assert mgr.last_action is None
        mgr.last_action = {"type": "weather", "city": "Nice"}
        assert mgr.last_action == {"type": "weather", "city": "Nice"}

    def test_session_manager_history_and_as_history_list(self, tmp_path):
        mgr = SessionManager(workspace_dir=str(tmp_path))
        mgr.add_turn("user", "Hello")
        mgr.add_turn("assistant", "Hi there")

        hist_list = mgr.as_history_list()
        assert len(hist_list) == 2
        assert hist_list[0] == {"role": "user", "content": "Hello"}
        assert hist_list[1] == {"role": "assistant", "content": "Hi there"}

        assert isinstance(mgr.history, deque)
        assert len(mgr.history) == 2
        assert mgr.history[0] == {"role": "user", "content": "Hello"}

    def test_session_manager_history_deque_append_syncs(self, tmp_path):
        mgr = SessionManager(workspace_dir=str(tmp_path))
        mgr.history.append({"role": "user", "content": "Proxied message"})
        assert len(mgr.get_history()) == 1
        assert mgr.get_history()[0]["content"] == "Proxied message"


class TestSessionStateCompatibility:
    def test_session_state_default_in_memory(self):
        state = SessionState()
        assert state.persist is False
        state.add_turn("user", "test state")
        state.add_turn("assistant", "ok")

        assert len(state.as_history_list()) == 2
        assert state.as_history_list()[0]["content"] == "test state"
        assert state.pending_action is None

    def test_session_state_with_dialog_state_machine(self):
        state = SessionState()
        dsm = DialogStateMachine(state)
        assert dsm.snapshot().phase == "idle"

        pending = make_pending_confirm_tool("fs_trash", {"path": "/tmp/a"})
        dsm.set_pending(pending)
        assert dsm.snapshot().phase == "awaiting_confirmation"
        assert state.has_pending_action()

        dsm.apply_pending_result(PendingHandlerResult(handled=True, clear_pending=True))
        assert not state.has_pending_action()
        assert dsm.snapshot().phase == "idle"


class TestServerSessionUnification:
    def test_record_turn_completed_single_source_of_truth(self, tmp_path):
        from core.server import KageServer

        s = object.__new__(KageServer)
        unified_session = SessionManager(workspace_dir=str(tmp_path))
        s.session = unified_session
        s.session_manager = unified_session

        s._record_turn_completed("今天天气如何", "今天天气晴朗")

        # Must record exactly 2 turns (1 user, 1 assistant), NOT 4 turns
        turns = s.session.as_history_list()
        assert len(turns) == 2
        assert turns[0] == {"role": "user", "content": "今天天气如何"}
        assert turns[1] == {"role": "assistant", "content": "今天天气晴朗"}
