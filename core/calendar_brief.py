"""D2: the daily schedule brief (calendar + reminders), read-only.

Reading goes through ~/.kage/bin/KageCalendar.app (tools/kage-calendar), a tiny app bundle with its own
permission text: a Python process has no usage description and macOS denies it silently, and AppleScript does
not expand recurring events. The helper is started with `open` so macOS attributes the permission to it.

`DailyBriefSource` is a heartbeat source: once per day, at the configured time (default 12:30, user choice
10-25) or the first heartbeat after it, it sends today's events and open reminders. "今天/明天有什么日程" is
answered directly from the same reader (server fast path), not by the model.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid

HELPER = Path('~/.kage/bin/KageCalendar.app').expanduser()
WEEKDAYS = '一二三四五六日'
ASK = re.compile(r'(今天|明天|今日|明日)(的)?(都)?(有)?(什么|哪些|啥)?(的)?(日程|安排|会议|会|行程)')


def run_helper(*args: str, timeout: float = 30) -> dict:
    if not HELPER.exists():
        raise RuntimeError('calendar helper is not built (tools/kage-calendar/build.sh)')
    out = Path(tempfile.gettempdir()) / f'kage-calendar-{uuid.uuid4().hex}.json'
    try:
        for attempt in range(3):
            subprocess.run(['open', '-W', '-n', '--stdout', str(out), '--stderr', '/dev/null', str(HELPER),
                            '--args', *args], capture_output=True, timeout=timeout)
            end = time.monotonic() + 5            # `open -W` can return before stdout is flushed
            while time.monotonic() < end:
                text = out.read_text().strip() if out.exists() else ''
                if text:
                    result = json.loads(text.splitlines()[-1])
                    if not result.get('ok'):
                        raise RuntimeError(result.get('error') or 'calendar helper failed')
                    return result
                time.sleep(.1)
        raise RuntimeError('calendar helper produced no output')
    finally:
        out.unlink(missing_ok=True)


def _local(iso: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(iso.replace('Z', '+00:00')).astimezone()


def day_bounds(day: datetime.date) -> tuple[str, str]:
    start = datetime.datetime.combine(day, datetime.time()).astimezone()
    end = datetime.datetime.combine(day + datetime.timedelta(days=1), datetime.time()).astimezone()
    return start.isoformat(timespec='seconds'), end.isoformat(timespec='seconds')


def events_on(day: datetime.date) -> list[dict]:
    return run_helper('events', *day_bounds(day))['events']


def open_reminders() -> list[dict]:
    return run_helper('reminders')['reminders']


def render(day: datetime.date, events: list[dict], reminders: list[dict] | None, now: datetime.datetime,
           *, greeting: str = '') -> str:
    label = '今天' if day == now.date() else ('明天' if day == now.date() + datetime.timedelta(days=1) else f'{day:%m月%d日}')
    head = f"{greeting}{label}（{day.month}月{day.day}日 周{WEEKDAYS[day.weekday()]}）"
    if not events:
        lines = [f'{head}没有日程。']
    else:
        lines = [f'{head}的日程：']
        upcoming, seen = None, set()
        for e in sorted(events, key=lambda e: (not e['all_day'], e['start'])):
            key = (e['title'], e['start'], e['end'])
            if key in seen:                       # the same holiday from two subscribed calendars
                continue
            seen.add(key)
            start, end = _local(e['start']), _local(e['end'])
            if e['all_day']:
                when = '全天'
            else:
                tail = end.strftime('%H:%M') if end.date() <= day else f"次日{end:%H:%M}"
                when = f"{start:%H:%M}–{tail}" if start.date() == day else f"（前一天开始）–{tail}"
            notes = []
            if e.get('location'):
                notes.append(f"@{e['location']}")
            if e.get('recurring'):
                notes.append('重复')
            if e.get('alarms_min'):
                notes.append(f"提前{e['alarms_min'][0]}分钟提醒")
            passed = not e['all_day'] and day == now.date() and end <= now
            lines.append(f"· {when} {e['title']}" + (f"（{'，'.join(notes)}）" if notes else '') + ('（已过）' if passed else ''))
            if upcoming is None and not e['all_day'] and day == now.date() and start > now:
                upcoming = (start, e['title'])
        if upcoming:
            minutes = int((upcoming[0] - now).total_seconds() // 60)
            lines.append(f"下一个：{upcoming[0]:%H:%M} {upcoming[1]}（还有 {minutes // 60} 小时 {minutes % 60} 分）"
                         if minutes >= 60 else f"下一个：{upcoming[0]:%H:%M} {upcoming[1]}（还有 {minutes} 分钟）")
    if reminders:
        lines.append(f'待办提醒 {len(reminders)} 条：' + '；'.join(r['title'] for r in reminders[:8])
                     + ('……' if len(reminders) > 8 else ''))
    return '\n'.join(lines)


def answer(text: str, now: datetime.datetime | None = None) -> str | None:
    """Reply to "今天/明天有什么日程" (None: not such a question)."""
    match = ASK.search(str(text or ''))
    if not match:
        return None
    now = now or datetime.datetime.now().astimezone()
    day = now.date() + datetime.timedelta(days=1 if match.group(1) in ('明天', '明日') else 0)
    try:
        return render(day, events_on(day), open_reminders() if day == now.date() else None, now)
    except Exception as exc:
        return f'没能读取日历：{exc}'


def _mail_line() -> str:
    """D3: unread mail in the daily brief (count + newest three subjects); empty if Mail cannot be read."""
    try:
        from core import mail_reader
        total = mail_reader.unread_count()
        if not total:
            return '\n没有未读邮件。'
        rows = mail_reader.unread(3)
        return (f'\n未读邮件 {total} 封，最新：' +
                '；'.join(f"{mail_reader.sender_name(r['sender'])}「{r['subject'][:30]}」" for r in rows)
                + '（说“看看新邮件”查看）')
    except Exception:
        return ''


class DailyBriefSource:
    """Heartbeat source: one brief per day at `daily_brief.time` (config; default 12:30)."""

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self.enabled = bool(cfg.get('enabled', True))
        hour, minute = (int(x) for x in str(cfg.get('time', '12:30')).split(':'))
        self.at = datetime.time(hour, minute)

    async def collect(self, now: datetime.datetime) -> list[dict]:
        from core.proactive import make_notification
        if not self.enabled or now.time() < self.at:
            return []
        local = now.astimezone() if now.tzinfo else now.astimezone()
        import asyncio
        try:
            events = await asyncio.to_thread(events_on, local.date())
            reminders = await asyncio.to_thread(open_reminders)
            content = render(local.date(), events, reminders, local, greeting='中午好！' if 11 <= self.at.hour < 14 else '')
            content += await asyncio.to_thread(_mail_line)
        except Exception as exc:
            content = f'今天的日程提醒没能读取日历：{exc}'
        note = make_notification(f'daily_brief:{local.date().isoformat()}', content, type_='daily_brief', now=now)
        note['dedup_seconds'] = 20 * 3600         # once per day
        return [note]
