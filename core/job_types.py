from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import time


JOB_STATUS_QUEUED = "queued"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_WAITING_USER = "waiting_user"
JOB_STATUS_COMPLETED = "completed"
JOB_STATUS_FAILED = "failed"
JOB_STATUS_CANCELLED = "cancelled"


TERMINAL_JOB_STATUSES = {
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JOB_STATUS_CANCELLED,
}


@dataclass(frozen=True)
class BackgroundJobRecord:
    job_id: str
    task_type: str
    input_text: str
    status: str = JOB_STATUS_QUEUED
    priority: int = 100
    notify_on_finish: bool = True
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    result: Any = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "task_type": self.task_type,
            "input_text": self.input_text,
            "status": self.status,
            "priority": self.priority,
            "notify_on_finish": self.notify_on_finish,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "result": self.result,
            "error": self.error,
        }


def make_background_job_record(
    *,
    job_id: str,
    task_type: str,
    input_text: str,
    priority: int = 100,
    notify_on_finish: bool = True,
) -> BackgroundJobRecord:
    now = time.time()
    return BackgroundJobRecord(
        job_id=str(job_id),
        task_type=str(task_type or "background_task"),
        input_text=str(input_text or ""),
        priority=int(priority),
        notify_on_finish=bool(notify_on_finish),
        created_at=now,
        updated_at=now,
    )
