from core.dialog_state_machine import DialogStateMachine
from core.interaction_state import (
    PendingChatFollowup,
    PendingConfirmTool,
    make_pending_chat_followup,
    make_pending_confirm_inferred_command,
    make_pending_confirm_tool,
    make_pending_video_followup,
)
from core.session_state import SessionState


class PendingResultStub:
    def __init__(self, *, set_pending=None, clear_pending=False):
        self.set_pending = set_pending
        self.clear_pending = clear_pending


def test_session_state_pending_helpers():
    session = SessionState()

    assert session.has_pending_action() is False
    pending = PendingConfirmTool(name="fs_apply", arguments={"confirmed": False})
    session.set_pending_action(pending)

    assert session.has_pending_action() is True
    assert session.pending_action == pending

    session.clear_pending_action()
    assert session.has_pending_action() is False


def test_dialog_state_machine_applies_set_pending():
    session = SessionState()
    dialog = DialogStateMachine(session)
    pending = PendingConfirmTool(name="fs_apply", arguments={"confirmed": False})

    dialog.apply_pending_result(PendingResultStub(set_pending=pending))

    snapshot = dialog.snapshot()
    assert snapshot.pending_action == pending
    assert snapshot.pending_kind == "confirm_tool"
    assert snapshot.phase == "awaiting_confirmation"


def test_dialog_state_machine_applies_clear_pending():
    session = SessionState()
    dialog = DialogStateMachine(session)
    dialog.set_pending(PendingConfirmTool(name="fs_apply", arguments={"confirmed": False}))

    dialog.apply_pending_result(PendingResultStub(clear_pending=True))

    snapshot = dialog.snapshot()
    assert snapshot.pending_action is None
    assert snapshot.pending_kind == ""
    assert snapshot.phase == "idle"


def test_interaction_state_factories_normalize_values():
    video = make_pending_video_followup(source="bilibili", sort="relevance", last_url=123)
    inferred = make_pending_confirm_inferred_command("system_control", {"target": "volume"})
    tool = make_pending_confirm_tool("fs_apply", None)
    chat = make_pending_chat_followup(topic="reply", asked=123)

    assert video.last_url == "123"
    assert inferred.arguments == {"target": "volume"}
    assert tool.arguments == {}
    assert chat.asked == "123"


def test_dialog_state_machine_uses_followup_phase_for_chat():
    session = SessionState()
    dialog = DialogStateMachine(session)
    dialog.set_pending(PendingChatFollowup(topic="reply", asked="你想怎么回？"))

    snapshot = dialog.snapshot()
    assert snapshot.pending_kind == "chat_followup"
    assert snapshot.phase == "awaiting_followup"
