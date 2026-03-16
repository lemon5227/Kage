from __future__ import annotations

from typing import Any
from uuid import uuid4
import time

from core.job_queue import JobQueue
from core.job_store import InMemoryJobStore
from core.job_types import (
    JOB_STATUS_CANCELLED,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    make_background_job_record,
)


class BackgroundLane:
    """Facade for background job lifecycle.

    This is the minimal backbone for future asynchronous task execution:
    submit -> queue -> claim -> update status -> complete/fail/cancel.
    """

    def __init__(self, *, store: InMemoryJobStore | None = None, queue: JobQueue | None = None):
        self._store = store or InMemoryJobStore()
        self._queue = queue or JobQueue()

    def submit(
        self,
        *,
        task_type: str,
        input_text: str,
        priority: int = 100,
        notify_on_finish: bool = True,
    ) -> dict[str, Any]:
        record = make_background_job_record(
            job_id=uuid4().hex,
            task_type=task_type,
            input_text=input_text,
            priority=priority,
            notify_on_finish=notify_on_finish,
        )
        payload = self._store.create(record.job_id, record.to_dict())
        self._queue.enqueue(record.job_id)
        return payload

    def claim_next(self) -> dict[str, Any] | None:
        job_id = self._queue.dequeue()
        if job_id is None:
            return None
        return self._store.update(
            job_id,
            {
                "status": JOB_STATUS_RUNNING,
                "updated_at": time.time(),
            },
        )

    def complete(self, job_id: str, result: Any) -> dict[str, Any] | None:
        return self._store.update(
            job_id,
            {
                "status": JOB_STATUS_COMPLETED,
                "result": result,
                "error": None,
                "updated_at": time.time(),
            },
        )

    def fail(self, job_id: str, error: str) -> dict[str, Any] | None:
        return self._store.update(
            job_id,
            {
                "status": JOB_STATUS_FAILED,
                "error": str(error or ""),
                "updated_at": time.time(),
            },
        )

    def cancel(self, job_id: str) -> dict[str, Any] | None:
        self._queue.remove(job_id)
        return self._store.update(
            job_id,
            {
                "status": JOB_STATUS_CANCELLED,
                "updated_at": time.time(),
            },
        )

    def get(self, job_id: str) -> dict[str, Any] | None:
        return self._store.get(job_id)

    def list(self) -> list[dict[str, Any]]:
        return self._store.list()
