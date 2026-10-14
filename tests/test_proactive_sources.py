"""T06: important dates become proactive reminders (and the model can store them)."""

import asyncio
import datetime
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.heartbeat import Heartbeat
from core.proactive_sources import ImportantDateSource, make_remember_date_handler


def _profile(dates):
    profile = SimpleNamespace(profile=SimpleNamespace(important_dates=list(dates)))

    def add_important_date(date, event, reminder=""):
        profile.profile.important_dates.append({"date": date, "event": event, "reminder": reminder})

    profile.add_important_date = add_important_date
    return profile


def _collect(dates, now):
    return asyncio.run(ImportantDateSource(lambda: _profile(dates)).collect(now))


def test_yearly_and_one_off_dates_due_today_or_tomorrow():
    now = datetime.datetime(2026, 10, 14, 9)
    notes = _collect([
        {"date": "10-15", "event": "妈妈生日", "reminder": ""},
        {"date": "2026-10-14", "event": "交报告", "reminder": "今天要交报告哦"},
        {"date": "10-20", "event": "太远", "reminder": ""},
        {"date": "2025-10-14", "event": "去年", "reminder": ""},
    ], now)
    by_event = {n["source"].split(":")[1]: n for n in notes}
    assert set(by_event) == {"妈妈生日", "交报告"}
    assert by_event["妈妈生日"]["content"].startswith("明天是妈妈生日")
    assert by_event["交报告"]["content"] == "今天要交报告哦"
    assert all(n["dedup_seconds"] > 0 for n in notes)


def test_year_boundary_and_invalid_entries_are_ignored():
    now = datetime.datetime(2026, 12, 31, 9)
    notes = _collect([
        {"date": "01-01", "event": "新年", "reminder": ""},
        {"date": "13-45", "event": "坏日期", "reminder": ""},
        {"date": "whenever", "event": "坏格式", "reminder": ""},
        "not a dict",
        {"date": "02-29", "event": "闰日", "reminder": ""},
    ], now)
    assert [n["source"] for n in notes] == ["date:新年:2027-01-01:tomorrow"]


def test_heartbeat_does_not_repeat_a_delivered_date(tmp_path):
    session = MagicMock()
    session.get_last_user_time.return_value = None
    delivered = []

    async def deliver(notes):
        delivered.extend(notes)

    today = datetime.date.today().isoformat()
    source = ImportantDateSource(lambda: _profile([{"date": today, "event": "测试日", "reminder": ""}]))
    hb = Heartbeat(MagicMock(), session, workspace_dir=str(tmp_path), on_notifications=deliver, sources=[source])
    asyncio.run(hb._run_once())
    asyncio.run(hb._run_once())
    assert len(delivered) == 1


def test_broken_source_is_logged_not_fatal(tmp_path):
    class Broken:
        async def collect(self, now):
            raise RuntimeError("profile unreadable")

    session = MagicMock()
    session.get_last_user_time.return_value = None
    hb = Heartbeat(MagicMock(), session, workspace_dir=str(tmp_path), sources=[Broken()])
    assert asyncio.run(hb.tick()) == []
    assert "profile unreadable" in open(hb.error_log_file, encoding="utf-8").read()


def test_remember_date_tool_validates_and_stores():
    profile = _profile([])
    remember = make_remember_date_handler(profile)
    assert json.loads(remember("2026-11-02", "体检"))["success"] is True
    assert json.loads(remember("1990-05-20", "我的生日", repeat_yearly=True))["date"] == "05-20"
    assert json.loads(remember("02-29", "闰日"))["success"] is True
    assert json.loads(remember("2026-02-30", "坏"))["success"] is False
    assert json.loads(remember("明天", "坏"))["success"] is False
    assert json.loads(remember("2026-11-02", ""))["success"] is False
    assert [d["event"] for d in profile.profile.important_dates] == ["体检", "我的生日", "闰日"]


def test_remember_date_visible_on_reminder_intent():
    from core.tool_visibility import select
    assert "remember_date" in select("下周三是我妈生日，记得提醒我", "chat").names
    assert "remember_date" not in select("今天天气怎么样", "info").names


# ---------------------------------------------------------------------------
# T07: failed / unknown browser tasks lead to a teaching request
# ---------------------------------------------------------------------------

from core.proactive_sources import teach_request_for_job  # noqa: E402

FAMILIES = {"preferences_dev": "preferences", "invoice_dev": "invoice"}
TEACHING = frozenset({"demo_preferences", "demo_profile"})


def _job(status, task_id="preferences_dev", task_type="browser_experiment"):
    return {"task_type": task_type, "status": status, "task_id": task_id, "run_id": "r1"}


def test_teach_request_only_for_failed_or_unknown_with_teaching_task():
    for status in ("failed", "unknown"):
        note = teach_request_for_job(_job(status), FAMILIES.get, TEACHING)
        assert note["source"] == "teach:preferences_dev"
        assert note["action"] == {"type": "start_teaching", "task_id": "demo_preferences", "from_run": "r1"}
    assert teach_request_for_job(_job("completed"), FAMILIES.get, TEACHING) is None
    assert teach_request_for_job(_job("stopped"), FAMILIES.get, TEACHING) is None
    assert teach_request_for_job(_job("failed", "invoice_dev"), FAMILIES.get, TEACHING) is None
    assert teach_request_for_job(_job("failed", task_type="browser_demonstration"), FAMILIES.get, TEACHING) is None


def _server_with_heartbeat(tmp_path):
    from core.server import KageServer

    delivered = []
    session = MagicMock()
    session.get_last_user_time.return_value = None

    async def deliver(notes):
        delivered.extend(notes)

    server = object.__new__(KageServer)
    server.heartbeat = Heartbeat(MagicMock(), session, workspace_dir=str(tmp_path), on_notifications=deliver)
    server._log_server_event = lambda *a, **k: None
    return server, delivered


def test_server_requests_teaching_once_per_day(tmp_path):
    server, delivered = _server_with_heartbeat(tmp_path)
    job = _job("failed")
    asyncio.run(server._maybe_request_teaching(job))
    asyncio.run(server._maybe_request_teaching(job))
    assert [n["source"] for n in delivered] == ["teach:preferences_dev"]


def test_server_completed_task_does_not_request_teaching(tmp_path):
    server, delivered = _server_with_heartbeat(tmp_path)
    asyncio.run(server._maybe_request_teaching(_job("completed")))
    assert delivered == []


def test_accepting_teaching_request_starts_human_demonstration(tmp_path, monkeypatch):
    from core.routes import browser_demonstrations

    submitted = []

    class Service:
        async def submit(self, payload):
            submitted.append(payload)
            return {"run_id": "d1", "status": "starting"}

    monkeypatch.setattr(browser_demonstrations, "_get_service", lambda: Service())
    server, delivered = _server_with_heartbeat(tmp_path)
    sent = []

    async def send_message(type_, data):
        sent.append((type_, data))

    server.send_message = send_message
    server._proactive_action_handlers = {"start_teaching": server._start_teaching}
    asyncio.run(server._maybe_request_teaching(_job("unknown")))
    note = delivered[0]
    asyncio.run(server.handle_proactive_feedback({"id": note["id"], "action": "accept"}))
    assert submitted == [{"task_id": "demo_preferences", "source_kind": "human_declared"}]
    assert sent == [("proactive", {"event": "teaching_started", "job": {"run_id": "d1", "status": "starting"}})]
