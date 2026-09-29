from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from core.background_lane import BackgroundLane


JobProcessor = Callable[[dict[str, Any]], Awaitable[Any]]
JobEventSink = Callable[[str, dict[str, Any]], Awaitable[None]]


class BackgroundWorker:
    """Single-worker consumer for BackgroundLane."""

    def __init__(
        self,
        *,
        lane: BackgroundLane,
        processor: JobProcessor,
        on_event: JobEventSink | None = None,
        idle_sleep_sec: float = 0.2,
        context_factory: Callable[[], Any] | None = None,
    ):
        self._lane = lane
        self._processor = processor
        self._on_event = on_event
        self._idle_sleep_sec = max(0.01, float(idle_sleep_sec))
        self._context_factory = context_factory
        self._task: asyncio.Task | None = None
        self._running = False

    def ensure_started(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        self._running = False
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass

    async def run(self) -> None:
        while self._running:
            processed = await self.process_next()
            if not processed:
                await asyncio.sleep(self._idle_sleep_sec)

    async def process_next(self) -> bool:
        job = self._lane.claim_next()
        if job is None:
            return False
        await self._emit("started", job)
        job_id = str(job.get("job_id") or "")
        try:
            if self._context_factory is not None:
                ctx = self._context_factory()
                try:
                    result = await self._processor(job, context=ctx)
                except TypeError:
                    result = await self._processor(job)
            else:
                result = await self._processor(job)
        except Exception as exc:
            failed = self._lane.fail(job_id, str(exc))
            if failed is not None:
                await self._emit("failed", failed)
            return True

        completed = self._lane.complete(job_id, result)
        if completed is not None:
            await self._emit("completed", completed)
        return True

    async def _emit(self, event: str, job: dict[str, Any]) -> None:
        if self._on_event is None:
            return
        await self._on_event(event, job)
