import asyncio

from core.background_lane import BackgroundLane
from core.background_worker import BackgroundWorker


def test_background_worker_processes_completed_job():
    lane = BackgroundLane()
    events = []

    async def processor(job):
        return {"echo": job["input_text"]}

    async def on_event(event, job):
        events.append((event, job["status"]))

    lane.submit(task_type="search", input_text="找资料")
    worker = BackgroundWorker(lane=lane, processor=processor, on_event=on_event)

    processed = asyncio.run(worker.process_next())
    jobs = lane.list()

    assert processed is True
    assert jobs[0]["status"] == "completed"
    assert jobs[0]["result"] == {"echo": "找资料"}
    assert events == [("started", "running"), ("completed", "completed")]


def test_background_worker_processes_failed_job():
    lane = BackgroundLane()
    events = []

    async def processor(job):
        raise RuntimeError("boom")

    async def on_event(event, job):
        events.append((event, job["status"], job.get("error")))

    lane.submit(task_type="cleanup", input_text="整理桌面")
    worker = BackgroundWorker(lane=lane, processor=processor, on_event=on_event)

    processed = asyncio.run(worker.process_next())
    jobs = lane.list()

    assert processed is True
    assert jobs[0]["status"] == "failed"
    assert jobs[0]["error"] == "boom"
    assert events == [("started", "running", None), ("failed", "failed", "boom")]
