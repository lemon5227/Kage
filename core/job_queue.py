from __future__ import annotations

from collections import deque


class JobQueue:
    """Simple FIFO queue for job ids.

    Keep this intentionally minimal until we introduce workers and retry
    policies. The queue only owns ordering; metadata lives in the job store.
    """

    def __init__(self):
        self._queue: deque[str] = deque()

    def enqueue(self, job_id: str) -> None:
        self._queue.append(str(job_id))

    def dequeue(self) -> str | None:
        if not self._queue:
            return None
        return self._queue.popleft()

    def remove(self, job_id: str) -> bool:
        target = str(job_id)
        try:
            self._queue.remove(target)
            return True
        except ValueError:
            return False

    def __len__(self) -> int:
        return len(self._queue)
