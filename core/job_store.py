from __future__ import annotations

import threading
from typing import Any, Callable


class InMemoryJobStore:
    """Thread-safe in-memory job registry.

    Keep the API intentionally small so runtime jobs and future background
    jobs can share the same storage semantics.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}

    def create(self, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        record = dict(payload)
        record["job_id"] = str(job_id)
        with self._lock:
            self._jobs[str(job_id)] = record
        return dict(record)

    def update(self, job_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            current = self._jobs.get(str(job_id))
            if current is None:
                return None
            current.update(dict(patch))
            return dict(current)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            current = self._jobs.get(str(job_id))
            return dict(current) if current is not None else None

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(record) for record in self._jobs.values()]

    def find_first(self, predicate: Callable[[dict[str, Any]], bool]) -> dict[str, Any] | None:
        with self._lock:
            for record in self._jobs.values():
                try:
                    if predicate(record):
                        return dict(record)
                except Exception:
                    continue
        return None
