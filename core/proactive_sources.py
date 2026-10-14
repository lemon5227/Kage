"""Proactive trigger sources: things worth bringing up without being asked.

A source exposes ``async collect(now: datetime) -> list[dict]`` returning
notifications built with :func:`core.proactive.make_notification`. A notification
may set ``dedup_seconds``: Heartbeat then skips it when the same ``source`` was
already delivered within that window, so a source can be polled every cycle.
"""

from __future__ import annotations

import datetime
import json
import re
from typing import Any, Callable

from core.proactive import make_notification

_FULL_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_YEARLY_DATE = re.compile(r"^\d{2}-\d{2}$")
TWO_DAYS = 2 * 24 * 3600


def _occurrence(date_spec: str, today: datetime.date) -> datetime.date | None:
    """Next occurrence (today or later) of a stored date; None when unparseable or past."""
    spec = str(date_spec or "").strip()
    try:
        if _FULL_DATE.match(spec):
            day = datetime.date.fromisoformat(spec)
            return day if day >= today else None
        if _YEARLY_DATE.match(spec):
            month, dom = (int(x) for x in spec.split("-"))
            for year in (today.year, today.year + 1):
                try:
                    day = datetime.date(year, month, dom)
                except ValueError:
                    continue  # e.g. 02-29 in a non-leap year
                if day >= today:
                    return day
    except ValueError:
        return None
    return None


class ImportantDateSource:
    """Reminds about MemoryProfile.important_dates due today or tomorrow.

    Each occurrence produces at most two reminders (the day before and the day
    itself), deduplicated through the delivered-notification log.
    """

    def __init__(self, profile_getter: Callable[[], Any]) -> None:
        self.profile_getter = profile_getter

    async def collect(self, now: datetime.datetime) -> list[dict]:
        profile = self.profile_getter()
        entries = getattr(getattr(profile, "profile", None), "important_dates", None) or []
        today = now.date()
        notes: list[dict] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            event = str(entry.get("event") or "").strip()
            day = _occurrence(entry.get("date", ""), today)
            if not event or day is None:
                continue
            delta = (day - today).days
            if delta not in (0, 1):
                continue
            when = "today" if delta == 0 else "tomorrow"
            content = str(entry.get("reminder") or "").strip() or (
                f"今天是{event}。" if delta == 0 else f"明天是{event}，提前跟你说一声。"
            )
            note = make_notification(f"date:{event}:{day.isoformat()}:{when}", content,
                                     type_="important_date", now=now)
            note["dedup_seconds"] = TWO_DAYS
            notes.append(note)
        return notes


def make_remember_date_handler(profile: Any) -> Callable[..., str]:
    """Tool handler so the model can store a date the user wants to be reminded of."""

    def remember_date(date: str, event: str, reminder: str = "", repeat_yearly: bool = False) -> str:
        spec = str(date or "").strip()
        name = str(event or "").strip()
        if not name:
            return json.dumps({"success": False, "error": "InvalidArgument", "message": "event 不能为空"},
                              ensure_ascii=False)
        if not _FULL_DATE.match(spec) and not _YEARLY_DATE.match(spec):
            return json.dumps({"success": False, "error": "InvalidArgument",
                               "message": "date 需为 YYYY-MM-DD 或每年重复的 MM-DD"}, ensure_ascii=False)
        try:
            if _FULL_DATE.match(spec):
                datetime.date.fromisoformat(spec)
                if repeat_yearly:
                    spec = spec[5:]
            else:
                month, dom = (int(x) for x in spec.split("-"))
                datetime.date(2024, month, dom)  # leap year accepts 02-29
        except ValueError:
            return json.dumps({"success": False, "error": "InvalidArgument", "message": f"无效日期: {date}"},
                              ensure_ascii=False)
        profile.add_important_date(spec, name, str(reminder or "").strip())
        return json.dumps({"success": True, "date": spec, "event": name}, ensure_ascii=False)

    return remember_date


TEACH_REPEAT_SECONDS = 24 * 3600
TEACHABLE_STATUSES = ("failed", "unknown")


def teach_request_for_job(job: dict, family_of: Callable[[str], str | None],
                          teaching_tasks: set[str] | frozenset[str]) -> dict | None:
    """Turn a finished browser task that failed (or could not be checked) into a
    proactive request for a human demonstration of the same task family.

    Returns None when the job is not a terminal failed/unknown browser experiment
    or when no teaching task exists for its family (nothing actionable to offer).
    """
    if str(job.get("task_type") or "") != "browser_experiment":
        return None
    status = str(job.get("status") or "")
    if status not in TEACHABLE_STATUSES:
        return None
    task_id = str(job.get("task_id") or "")
    family = family_of(task_id) if task_id else None
    teaching_task = f"demo_{family}" if family else ""
    if teaching_task not in teaching_tasks:
        return None
    outcome = "没完成" if status == "failed" else "没法确认有没有完成"
    note = make_notification(
        f"teach:{task_id}",
        f"刚才的“{task_id}”任务我{outcome}。你愿意示范一次给我看吗？我会记下来，下次自己试。",
        type_="teach_request",
        action={"type": "start_teaching", "task_id": teaching_task,
                "from_run": str(job.get("run_id") or job.get("job_id") or "")},
    )
    note["dedup_seconds"] = TEACH_REPEAT_SECONDS
    return note
