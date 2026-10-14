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
