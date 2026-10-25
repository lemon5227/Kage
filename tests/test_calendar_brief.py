"""D2: brief rendering (no calendar access needed)."""
import datetime

from core import calendar_brief as cb

TZ = datetime.timezone(datetime.timedelta(hours=1))
NOW = datetime.datetime(2026, 10, 25, 12, 30, tzinfo=TZ)


def ev(title, start, end, **kw):
    return {'title': title, 'start': start, 'end': end, 'all_day': kw.get('all_day', False),
            'location': kw.get('location', ''), 'recurring': kw.get('recurring', False), 'alarms_min': kw.get('alarms', [])}


def test_today_brief_orders_marks_passed_next_and_dedupes(monkeypatch):
    monkeypatch.setattr(cb, '_local', lambda iso: datetime.datetime.fromisoformat(iso).astimezone(TZ))
    events = [ev('组会', '2026-10-25T14:00:00+01:00', '2026-10-25T15:00:00+01:00', location='会议室A'),
              ev('站会', '2026-10-25T09:00:00+01:00', '2026-10-25T09:15:00+01:00', recurring=True),
              ev('论文日', '2026-10-25T00:00:00+01:00', '2026-10-26T00:00:00+01:00', all_day=True),
              ev('论文日', '2026-10-25T00:00:00+01:00', '2026-10-26T00:00:00+01:00', all_day=True),
              ev('部署', '2026-10-25T22:00:00+01:00', '2026-10-26T01:00:00+01:00')]
    text = cb.render(NOW.date(), events, [{'title': '买面包'}], NOW, greeting='中午好！')
    assert text.startswith('中午好！今天（10月25日 周日）的日程：')
    assert text.count('论文日') == 1 and '· 全天 论文日' in text
    assert '09:00–09:15 站会（重复）（已过）' in text and '@会议室A' in text
    assert '22:00–次日01:00 部署' in text and '下一个：14:00 组会（还有 1 小时 30 分）' in text
    assert '待办提醒 1 条：买面包' in text
    tomorrow = cb.render(NOW.date() + datetime.timedelta(days=1), [events[-1]], None, NOW)
    assert '（前一天开始）–01:00 部署' in tomorrow


def test_questions_and_daily_source_timing():
    assert cb.ASK.search('今天有什么日程') and cb.ASK.search('明天的安排') and not cb.ASK.search('打开日历')
    import asyncio
    source = cb.DailyBriefSource({'time': '12:30'})
    assert asyncio.run(source.collect(datetime.datetime(2026, 10, 25, 12, 0))) == []      # before the time
