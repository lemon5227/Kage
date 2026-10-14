"""T04: proactive notifications carry id/source and user feedback is recorded."""

import asyncio
from unittest.mock import MagicMock

import pytest

from core.heartbeat import Heartbeat
from core.proactive import ProactiveFeedbackStore, make_notification
from core.server import KageServer


def test_make_notification_has_identity_fields():
    n = make_notification("date:生日", "明天是生日", action={"type": "noop"})
    assert len(n["id"]) == 12
    assert n["source"] == "date:生日"
    assert n["type"] == "date:生日"
    assert n["action"] == {"type": "noop"}


def test_feedback_store_mute_and_snooze_persist(tmp_path):
    clock = [1000.0]
    path = str(tmp_path / "fb.jsonl")
    store = ProactiveFeedbackStore(path, snooze_minutes=10, now_fn=lambda: clock[0])
    store.record("a", "src:a", "mute")
    store.record("b", "src:b", "snooze")
    reopened = ProactiveFeedbackStore(path, snooze_minutes=10, now_fn=lambda: clock[0])
    assert reopened.is_muted("src:a") and not reopened.is_muted("src:b")
    assert reopened.snoozed_until("src:b") == 1000.0 + 600


def test_feedback_store_rejects_unknown_action(tmp_path):
    store = ProactiveFeedbackStore(str(tmp_path / "fb.jsonl"))
    with pytest.raises(ValueError):
        store.record("a", "s", "delete_everything")


def test_feedback_store_ignores_torn_lines(tmp_path):
    path = tmp_path / "fb.jsonl"
    path.write_text('{"source": "s", "action": "mute"}\n{"broken', encoding="utf-8")
    assert ProactiveFeedbackStore(str(path)).is_muted("s")


def _heartbeat(tmp_path, delivered):
    session = MagicMock()
    session.get_last_user_time.return_value = None

    async def deliver(notes):
        delivered.extend(notes)

    return Heartbeat(MagicMock(), session, workspace_dir=str(tmp_path), on_notifications=deliver)


def test_heartbeat_notifications_have_source_and_feedback_roundtrip(tmp_path):
    (tmp_path / "HEARTBEAT.md").write_text("## 喝水\n- enabled: true\n- 描述：该喝水了\n", encoding="utf-8")
    delivered = []
    hb = _heartbeat(tmp_path, delivered)
    asyncio.run(hb._run_once())
    note = delivered[0]
    assert note["source"] == "heartbeat:喝水" and note["type"] == "喝水"
    assert hb.record_feedback(note["id"], "mute") is note
    assert hb.feedback.is_muted("heartbeat:喝水")
    assert hb.record_feedback("unknown-id", "mute") is None


def _server_with(hb):
    server = object.__new__(KageServer)
    server.heartbeat = hb
    server._proactive_action_handlers = {}
    server._log_server_event = lambda *a, **k: None
    return server


def test_server_accept_runs_registered_action_handler(tmp_path):
    delivered = []
    hb = _heartbeat(tmp_path, delivered)
    note = make_notification("teach:t1", "要示范吗？", action={"type": "open_teaching", "task_id": "t1"})
    asyncio.run(hb._deliver([note]))
    server = _server_with(hb)
    seen = []

    async def handler(action):
        seen.append(action)

    server._proactive_action_handlers["open_teaching"] = handler
    asyncio.run(server.handle_proactive_feedback({"type": "proactive_feedback", "id": note["id"], "action": "accept"}))
    assert seen == [{"type": "open_teaching", "task_id": "t1"}]


def test_server_snooze_does_not_run_action_and_bad_action_is_ignored(tmp_path):
    delivered = []
    hb = _heartbeat(tmp_path, delivered)
    note = make_notification("teach:t1", "要示范吗？", action={"type": "open_teaching"})
    asyncio.run(hb._deliver([note]))
    server = _server_with(hb)
    seen = []

    async def handler(action):
        seen.append(action)

    server._proactive_action_handlers["open_teaching"] = handler
    assert asyncio.run(server.handle_proactive_feedback({"id": note["id"], "action": "snooze"})) is note
    assert asyncio.run(server.handle_proactive_feedback({"id": note["id"], "action": "rm -rf"})) is None
    assert seen == []
