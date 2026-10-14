"""T05: quiet hours, rate limit, snooze and mute decide when proactive messages go out."""

import asyncio
import datetime
from unittest.mock import MagicMock

from core.heartbeat import Heartbeat
from core.proactive import ProactiveFeedbackStore, ProactivePolicy, make_notification


def _ts(hour, minute=0):
    return datetime.datetime(2026, 10, 14, hour, minute).timestamp()


def _policy(tmp_path, clock, **kwargs):
    fb = ProactiveFeedbackStore(str(tmp_path / "fb.jsonl"), snooze_minutes=30, now_fn=lambda: clock[0])
    return ProactivePolicy(fb, str(tmp_path / "sent.jsonl"), now_fn=lambda: clock[0], **kwargs), fb


def test_quiet_hours_cross_midnight(tmp_path):
    clock = [_ts(23, 30)]
    policy, _ = _policy(tmp_path, clock, quiet_hours="23:00-08:00")
    note = make_notification("s", "x")
    assert policy.verdict(note) == ("hold", "quiet_hours")
    clock[0] = _ts(7, 59)
    assert policy.verdict(note)[0] == "hold"
    clock[0] = _ts(8, 0)
    assert policy.verdict(note) == ("deliver", "")


def test_quiet_hours_same_day_window_and_invalid_spec(tmp_path):
    clock = [_ts(13, 0)]
    policy, _ = _policy(tmp_path, clock, quiet_hours="12:00-14:00")
    assert policy.verdict(make_notification("s", "x"))[1] == "quiet_hours"
    policy, _ = _policy(tmp_path, clock, quiet_hours="nonsense")
    assert policy.verdict(make_notification("s", "x"))[0] == "deliver"


def test_rate_limit_counts_last_hour(tmp_path):
    clock = [_ts(10)]
    policy, _ = _policy(tmp_path, clock, max_per_hour=2)
    for i in range(2):
        note = make_notification(f"s{i}", "x")
        assert policy.verdict(note)[0] == "deliver"
        policy.mark_sent(note)
    assert policy.verdict(make_notification("s9", "x")) == ("hold", "rate_limited")
    clock[0] += 3601
    assert policy.verdict(make_notification("s9", "x"))[0] == "deliver"


def test_snooze_expires_and_mute_is_permanent(tmp_path):
    clock = [_ts(10)]
    policy, fb = _policy(tmp_path, clock)
    fb.record("a", "snoozed", "snooze")
    fb.record("b", "muted", "mute")
    assert policy.verdict(make_notification("snoozed", "x")) == ("hold", "snoozed")
    assert policy.verdict(make_notification("muted", "x")) == ("drop", "muted")
    clock[0] += 31 * 60
    assert policy.verdict(make_notification("snoozed", "x"))[0] == "deliver"
    assert policy.verdict(make_notification("muted", "x"))[0] == "drop"


def test_was_sent_window(tmp_path):
    clock = [_ts(10)]
    policy, _ = _policy(tmp_path, clock)
    policy.mark_sent(make_notification("teach:t1", "x"))
    assert policy.was_sent("teach:t1", 60)
    clock[0] += 120
    assert not policy.was_sent("teach:t1", 60)


def _heartbeat(tmp_path, delivered, **cfg):
    session = MagicMock()
    session.get_last_user_time.return_value = None

    async def deliver(notes):
        delivered.extend(notes)

    return Heartbeat(MagicMock(), session, workspace_dir=str(tmp_path),
                     on_notifications=deliver, proactive_config=cfg)


def test_heartbeat_holds_rate_limited_and_drops_muted(tmp_path):
    delivered = []
    hb = _heartbeat(tmp_path, delivered, max_per_hour=1)
    first, second = make_notification("a", "1"), make_notification("b", "2")
    asyncio.run(hb._deliver([first, second]))
    assert delivered == [first]
    assert hb._notification_queue == [second]

    hb.feedback.record("x", "muted", "mute")
    asyncio.run(hb._deliver([make_notification("muted", "3")]))
    assert all(n["source"] != "muted" for n in delivered + hb._notification_queue)


def test_held_queue_keeps_latest_per_source(tmp_path):
    delivered = []
    hb = _heartbeat(tmp_path, delivered, max_per_hour=1)
    asyncio.run(hb._deliver([make_notification("used", "0")]))
    asyncio.run(hb._deliver([make_notification("a", "old"), make_notification("a", "new")]))
    assert [n["content"] for n in hb._notification_queue] == ["new"]


def test_deliver_now_holds_while_user_active(tmp_path):
    delivered = []
    hb = _heartbeat(tmp_path, delivered)
    import time
    hb.session.get_last_user_time.return_value = time.time()
    asyncio.run(hb.deliver_now([make_notification("ev", "x")]))
    assert delivered == [] and len(hb._notification_queue) == 1
