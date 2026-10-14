"""Proactive interaction primitives shared by Heartbeat, the server and triggers.

A proactive notification is a plain dict::

    {"id": "3f2a9c1b7d4e", "source": "heartbeat:天气检查", "type": "天气检查",
     "content": "要带伞", "timestamp": "...", "action": {...optional...}}

``source`` is the stable identity used for mute/snooze/dedup; ``id`` identifies one
delivery so the user's feedback can be tied back to it.
"""

from __future__ import annotations

import datetime
import json
import os
import time
import uuid
from typing import Any, Callable

FEEDBACK_ACTIONS = ("accept", "snooze", "mute")


def make_notification(source: str, content: str, *, type_: str = "", action: dict | None = None,
                      now: datetime.datetime | None = None) -> dict[str, Any]:
    notification: dict[str, Any] = {
        "id": uuid.uuid4().hex[:12],
        "source": str(source),
        "type": str(type_ or source),
        "content": str(content or ""),
        "timestamp": (now or datetime.datetime.now()).isoformat(),
    }
    if action:
        notification["action"] = dict(action)
    return notification


def _append_jsonl(path: str, row: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _read_jsonl(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue  # a torn last line must not disable proactive behaviour
            if isinstance(row, dict):
                rows.append(row)
    return rows


class ProactiveFeedbackStore:
    """Append-only record of the user's reactions to proactive notifications.

    ``mute`` silences a source permanently, ``snooze`` silences it for
    ``snooze_minutes``; both survive restarts because they are re-read from disk.
    """

    def __init__(self, path: str, *, snooze_minutes: int = 60,
                 now_fn: Callable[[], float] = time.time) -> None:
        self.path = path
        self.snooze_seconds = max(0, int(snooze_minutes)) * 60
        self.now_fn = now_fn

    def record(self, notification_id: str, source: str, action: str) -> dict:
        if action not in FEEDBACK_ACTIONS:
            raise ValueError(f"unknown feedback action: {action!r}")
        row = {"ts": self.now_fn(), "id": str(notification_id), "source": str(source), "action": action}
        _append_jsonl(self.path, row)
        return row

    def rows(self) -> list[dict]:
        return _read_jsonl(self.path)

    def is_muted(self, source: str) -> bool:
        return any(r.get("source") == source and r.get("action") == "mute" for r in self.rows())

    def snoozed_until(self, source: str) -> float:
        until = 0.0
        for r in self.rows():
            if r.get("source") == source and r.get("action") == "snooze":
                until = max(until, float(r.get("ts") or 0) + self.snooze_seconds)
        return until
